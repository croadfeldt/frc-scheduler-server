"""Adapter for Idle Loop's MatchMaker (Tom & Cathy Saxton).

MatchMaker is a Linux command-line tool that generates FRC-style
schedules. It writes its schedule to stdout; we capture and parse it.

Locating the binary — the adapter tries these in order:
  1. The `binary=` argument to the adapter constructor (set by the
     runner's `--matchmaker-binary` flag).
  2. The MATCHMAKER_BINARY environment variable.
  3. A `matchmaker` executable on $PATH (resolved via shutil.which).

Any of the three is sufficient. A typical setup is to drop the
binary somewhere on $PATH (e.g. /usr/local/bin/matchmaker) and let
the default resolution handle it; no flag or env var needed. If
the binary lives elsewhere, set MATCHMAKER_BINARY=/path/to/matchmaker
in your shell, or pass --matchmaker-binary to the runner per-run.

Verify the install works with `matchmaker --help` (or whatever the
binary's actual name resolves to).

CLI flags from the 1.6.1 release notes:
  -t N      number of teams
  -r N      number of rounds (matches per team)
  -a N      teams per alliance (default 3)
  -u N      surrogate round (1-indexed)
  -k spec   breaks
  -D        print team repeat counts (informational)
  -M        mirrored station balance for 2017 Steamworks (probably not needed)

The exact flag names may differ — the release notes don't enumerate
every flag. The adapter has a `--help` probe mode that runs
`matchmaker --help` on first instantiation and logs the available
flags for verification. Adjust the flag names below if reality differs
from this guess.

Output format guess: plain text, line-per-match, columns for blue/red
team slots. Real format will be confirmed when MatchMaker is run on
Stark; if it differs from this guess, _parse_output() needs to change
but the adapter shape stays the same.

Determinism: the 1.0.3 release notes say "new method for seeding the
match generation should reduce clumping" but no `-s seed` flag is
documented. The adapter assumes MatchMaker is non-deterministic and
expects `trial` to produce different schedules on subsequent calls.
This will be verified on first run; if it turns out to be deterministic
the harness simply gets identical Schedule objects and the comparison
collapses to N=1, which is fine.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .base import Adapter
from ..harness_types import Fixture, Match, Schedule


DEFAULT_BINARY = os.environ.get("MATCHMAKER_BINARY", "matchmaker")
# A safety cap on subprocess wallclock time. MatchMaker is fast; if it
# hasn't returned in 5 minutes something is wrong.
DEFAULT_TIMEOUT_SECONDS = 300.0


def _resolve_binary(binary: str | Path) -> str | None:
    """Resolve `binary` to an absolute path that exists, or None.

    Tries, in order:
      1. If `binary` is an absolute or relative path that exists as a
         regular file, return it.
      2. Otherwise treat it as a name to look up on $PATH via shutil.which.

    Returns the resolved absolute path on success, None on failure.
    """
    p = Path(binary)
    if p.is_file():
        return str(p.resolve())
    found = shutil.which(str(binary))
    return found  # may be None


class MatchMakerAdapter(Adapter):
    """Wraps Idle Loop's MatchMaker behind the standard adapter interface."""

    name = "matchmaker"

    def __init__(self, binary: str | Path | None = None,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 extra_args: list[str] | None = None):
        """`extra_args` is appended verbatim to every invocation —
        useful for global tuning without modifying the adapter.

        Binary resolution priority:
          1. explicit `binary=` argument (set by --matchmaker-binary)
          2. MATCHMAKER_BINARY env var (read at module load)
          3. 'matchmaker' on $PATH (resolved via shutil.which)

        On failure, raises FileNotFoundError with detailed diagnostics
        about every candidate considered and why each was rejected.
        """
        # Start with the requested name, then resolve to an absolute
        # path. Storing the absolute path means the subprocess call
        # doesn't depend on PATH being inherited correctly into worker
        # processes (relevant for multiprocessing.spawn on macOS, and
        # cheap insurance on Linux too).
        requested = str(binary) if binary else DEFAULT_BINARY
        resolved = _resolve_binary(requested)
        if resolved is None:
            # Build a detailed error showing what was considered and why.
            # This is far more useful than "binary not found: 'matchmaker'"
            # when the caller is sure they have it installed.
            env_var = os.environ.get("MATCHMAKER_BINARY")
            path_env = os.environ.get("PATH", "")
            path_dirs = path_env.split(os.pathsep) if path_env else []
            diag_lines = [
                f"MatchMaker binary not found.",
                f"  Requested:           {requested!r}",
                f"  Constructor binary:  {binary!r}",
                f"  MATCHMAKER_BINARY:   {env_var!r}" if env_var else
                f"  MATCHMAKER_BINARY:   <unset>",
                f"  PATH directories ({len(path_dirs)}):",
            ]
            for d in path_dirs[:20]:
                diag_lines.append(f"    {d}")
            if len(path_dirs) > 20:
                diag_lines.append(f"    ... and {len(path_dirs) - 20} more")
            diag_lines.extend([
                "",
                "Resolution attempts:",
                f"  - Path('{requested}').is_file() -> "
                f"{Path(requested).is_file()}",
                f"  - shutil.which('{requested}') -> "
                f"{shutil.which(str(requested))!r}",
                "",
                "Fixes:",
                "  - Verify with: which matchmaker",
                "  - If installed elsewhere: export MATCHMAKER_BINARY=/full/path/to/matchmaker",
                "  - Or pass --matchmaker-binary /full/path/to/matchmaker to the runner",
                "  - If multiprocessing isn't inheriting PATH, prefer the absolute path forms",
            ])
            raise FileNotFoundError("\n".join(diag_lines))
        self.binary = resolved
        self.timeout_seconds = timeout_seconds
        self.extra_args = list(extra_args) if extra_args else []

    def generate(self, fixture: Fixture, *, seed: int | None = None,
                 trial: int = 0) -> Schedule:
        cmd = self._build_command(fixture)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout_seconds, check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"MatchMaker exceeded {self.timeout_seconds}s timeout for "
                f"{fixture.fixture_id}; cmd: {' '.join(cmd)}"
            )
        elapsed = time.monotonic() - t0

        if proc.returncode != 0:
            raise RuntimeError(
                f"MatchMaker exited {proc.returncode} for {fixture.fixture_id}.\n"
                f"cmd:    {' '.join(cmd)}\n"
                f"stderr: {proc.stderr.strip()[:500]}"
            )

        matches = self._parse_output(proc.stdout, fixture)

        return Schedule(
            fixture_id=fixture.fixture_id,
            adapter_name=self.name,
            matches=matches,
            generation_seconds=elapsed,
            seed=seed,
            adapter_diagnostics={
                "command":         " ".join(cmd),
                "exit_code":       proc.returncode,
                "stdout_bytes":    len(proc.stdout),
                "stderr_excerpt":  proc.stderr.strip()[:500] if proc.stderr else "",
                "trial":           trial,
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def _build_command(self, fixture: Fixture) -> list[str]:
        cmd = [self.binary,
               "-t", str(fixture.num_teams),
               "-r", str(fixture.matches_per_team),
               "-a", str(fixture.teams_per_alliance)]
        if fixture.surrogate_round is not None:
            cmd.extend(["-u", str(fixture.surrogate_round)])
        cmd.extend(self.extra_args)
        return cmd

    def _parse_output(self, stdout: str, fixture: Fixture) -> list[Match]:
        """Parse MatchMaker's stdout into Match objects.

        Format varies by MatchMaker version. The 1.6.1 binary's output
        is presumed to be one match per line, with columns. Until we
        run MatchMaker on Stark and capture a real sample, this parser
        handles the most-common shape:

            Match  Red1  Red2  Red3  Blue1  Blue2  Blue3  [* if surrogate]

        Or a similar columnar layout. The parser is liberal about
        whitespace — splits on runs of spaces. Lines that don't parse
        as match rows are ignored (header lines, statistics, blank
        lines).

        IMPORTANT: this parser is a best-guess until validated on real
        MatchMaker output. When you run the adapter for the first time
        and it produces a parse error or wrong-looking matches, capture
        a sample of stdout and update _parse_output to match.

        The returned matches have team-number entries mapped through
        the fixture's team list — MatchMaker outputs schedule positions
        (1..N) which we translate to actual team numbers.
        """
        matches: list[Match] = []
        # Pattern: integer match number followed by 6 (or 2*teams_per_alliance)
        # integers, optionally with '*' marking surrogates.
        team_count_per_match = 2 * fixture.teams_per_alliance
        slot_pattern = r"(\d+)(\*)?"
        line_re = re.compile(
            r"^\s*(\d+)\s+" + r"\s+".join([slot_pattern] * team_count_per_match)
            + r"\s*$"
        )

        for raw_line in stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            m = line_re.match(line)
            if not m:
                continue
            groups = m.groups()
            match_num = int(groups[0])
            # groups[1:] alternate: (slot_str, surrogate_marker)
            slot_pairs = [
                (int(groups[1 + 2*i]), groups[2 + 2*i] == "*")
                for i in range(team_count_per_match)
            ]
            # Convention: MatchMaker outputs RED first, then BLUE.
            # If your version outputs BLUE first, swap these halves.
            half = fixture.teams_per_alliance
            red_slots, blue_slots = slot_pairs[:half], slot_pairs[half:]
            red_teams       = [self._slot_to_team(s, fixture) for s, _ in red_slots]
            red_surrogates  = [is_surr for _, is_surr in red_slots]
            blue_teams      = [self._slot_to_team(s, fixture) for s, _ in blue_slots]
            blue_surrogates = [is_surr for _, is_surr in blue_slots]
            matches.append(Match(
                match_num=match_num,
                blue=blue_teams, red=red_teams,
                blue_surrogate=blue_surrogates,
                red_surrogate=red_surrogates,
            ))

        if not matches:
            raise ValueError(
                "MatchMaker output produced 0 matches — parser may be "
                "wrong for this MatchMaker version. Sample of output:\n"
                + stdout[:1000]
            )
        if len(matches) != fixture.total_matches:
            raise ValueError(
                f"MatchMaker output has {len(matches)} matches; fixture "
                f"expects {fixture.total_matches}. Parser may be missing "
                f"rows or fixture parameters are wrong."
            )
        return matches

    @staticmethod
    def _slot_to_team(slot: int, fixture: Fixture) -> int:
        """MatchMaker outputs slot indices 1..N; translate to team numbers."""
        if not 1 <= slot <= fixture.num_teams:
            raise ValueError(
                f"MatchMaker output references slot {slot}, outside "
                f"valid range 1..{fixture.num_teams}"
            )
        return fixture.teams[slot - 1]

    def probe_help(self) -> str:
        """Run `matchmaker --help` and return its output.

        Useful for first-time setup verification — confirms the binary
        runs and surfaces the actual flag names so we can fix the
        adapter if our guesses are wrong.
        """
        try:
            proc = subprocess.run(
                [self.binary, "--help"], capture_output=True,
                text=True, timeout=10, check=False,
            )
            return (proc.stdout or "") + (proc.stderr or "")
        except Exception as e:
            return f"(probe failed: {e})"
