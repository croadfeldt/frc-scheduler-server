#!/usr/bin/env bash
# scripts/overnight_quality_run.sh
#
# Long-running batch of schedule-quality work suitable for leaving on
# overnight or while AFK. Runs 4 jobs in sequence; each writes a self-
# contained log and a brief summary line to a master log.
#
# Jobs (in order):
#   1. Standards eval on existing 5-fixture inventory (~30 min)
#      Validates the new adapter defaults + construction fix don't
#      regress the canonical-library shapes.
#
#   2. Matchmaker head-to-head on the three MN regional fixtures (~5 min)
#      Final validation that adapter fixes are still effective post-
#      everything; locks in the eval comparison data.
#
#   3. Canonical re-curation of existing 5 shapes (~2-4 hrs)
#      Rebuilds the canonical library at high SA budget + new
#      construction. Existing canonicals stay in place until success.
#      Writes new versions to a dated directory; promotion to
#      app/canonical_schedules/ is a manual step after review.
#
#   4. Build new canonicals for MSHSL odd-team-count shapes (~2-4 hrs)
#      51×7, 55×7, 55×8, 61×7, 61×8 — the shapes that motivated
#      this whole arc. Now that construction succeeds on them, they're
#      candidates for the canonical library so production users on
#      those events get cache hits.
#
# Usage:
#   ./scripts/overnight_quality_run.sh                 # all 4 jobs
#   ./scripts/overnight_quality_run.sh --skip-job 3,4  # just 1 and 2
#   ./scripts/overnight_quality_run.sh --dry-run       # print plan, exit
#
# Output:
#   reports/overnight_<timestamp>/
#     ├── overnight.log         (master log: timing + status per job)
#     ├── job1_standards.log    (full stdout/stderr from job 1)
#     ├── job2_matchmaker.log
#     ├── job3_recurate.log
#     ├── job4_new_canonicals.log
#     ├── standards/            (Phase D report)
#     ├── matchmaker/           (head-to-head report)
#     └── canonicals/           (newly built canonical JSON files)
#
# Resilience:
#   - Each job is independent; later jobs run even if earlier ones fail.
#   - Failures are logged with timing; the script exits non-zero overall
#     if any job failed, but only after all attempted.
#   - Uses `nohup`-safe redirection so you can disconnect mid-run.

set -uo pipefail

# Resolve repo root (so the script works from anywhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ── Configuration ────────────────────────────────────────────────────

# Read SA iterations from env to make it easy to dial up/down without
# editing the script. The defaults below are tuned for "leave it running
# all day on Stark's 36 cores".
SA_ITERATIONS_STANDARDS=${SA_ITERATIONS_STANDARDS:-500000}
SA_ITERATIONS_CANONICAL=${SA_ITERATIONS_CANONICAL:-2000000}
N_SEEDS_STANDARDS=${N_SEEDS_STANDARDS:-5}
N_SEEDS_CANONICAL=${N_SEEDS_CANONICAL:-20}
CPSAT_BUDGET_CANONICAL=${CPSAT_BUDGET_CANONICAL:-600}  # 10 min per canonical

# Existing canonical inventory (from standards_config.py)
EXISTING_FIXTURES=(
    "12x6_cd2"
    "20x8_cd2"
    "24x8_cd2"
    "36x7_cd2"
    "60x12_cd2"
)

# Existing canonical shape specs for re-curation
# Format: "n mpt tpa cooldown"
EXISTING_CANONICALS=(
    "12 6 3 2"
    "20 8 3 2"
    "24 8 3 2"
    "36 7 3 2"
    "60 12 3 2"
)

# New canonicals to build — MSHSL odd-team-count shapes
NEW_CANONICALS=(
    "51 7 3 2"
    "55 7 3 2"
    "55 8 3 2"
    "61 7 3 2"
    "61 8 3 2"
)

# MN regional fixtures for matchmaker comparison
MN_FIXTURES="2023mnmi,2024mndu,2025mnmi"

# ── Argument parsing ─────────────────────────────────────────────────

SKIP_JOBS=""
DRY_RUN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-job) SKIP_JOBS="$2"; shift 2 ;;
        --dry-run)  DRY_RUN=1; shift ;;
        -h|--help)
            sed -n '/^# Usage:/,/^# Resilience:/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

should_skip() {
    local jobnum=$1
    [[ ",$SKIP_JOBS," == *",$jobnum,"* ]]
}

# ── Setup ────────────────────────────────────────────────────────────

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTDIR="reports/overnight_${TIMESTAMP}"
mkdir -p "$OUTDIR" "$OUTDIR/canonicals" "$OUTDIR/standards" "$OUTDIR/matchmaker"

MASTER_LOG="$OUTDIR/overnight.log"

# Helper: log line goes to master log AND stdout
log() {
    local msg="[$(date +%H:%M:%S)] $*"
    echo "$msg" | tee -a "$MASTER_LOG"
}

# Helper: log line ONLY to master log (for separators, etc.)
log_quiet() {
    echo "[$(date +%H:%M:%S)] $*" >> "$MASTER_LOG"
}

# Helper: run a command, capturing wall time + exit code
# Args: <job_name> <log_file> <command...>
run_job() {
    local name="$1"
    local logfile="$2"
    shift 2
    log "─── START $name ───"
    log "  cmd: $*"
    log "  log: $logfile"
    local start=$SECONDS
    set +e
    "$@" > "$logfile" 2>&1
    local rc=$?
    set -e
    local elapsed=$((SECONDS - start))
    local mins=$((elapsed / 60))
    local secs=$((elapsed % 60))
    if [[ $rc -eq 0 ]]; then
        log "─── DONE  $name  rc=0  elapsed=${mins}m${secs}s ───"
    else
        log "─── FAIL  $name  rc=$rc  elapsed=${mins}m${secs}s ───"
        log "  Last 10 lines of log:"
        tail -10 "$logfile" | sed 's/^/    /' | tee -a "$MASTER_LOG"
    fi
    return $rc
}

# ── Sanity checks ────────────────────────────────────────────────────

log "Overnight quality run — $(date)"
log "Repo: $REPO_ROOT"
log "Output: $OUTDIR"
log "Python: $(which python3)  ($(python3 -V 2>&1))"
log "Config:"
log "  SA_ITERATIONS_STANDARDS = $SA_ITERATIONS_STANDARDS"
log "  SA_ITERATIONS_CANONICAL = $SA_ITERATIONS_CANONICAL"
log "  N_SEEDS_STANDARDS       = $N_SEEDS_STANDARDS"
log "  N_SEEDS_CANONICAL       = $N_SEEDS_CANONICAL"
log "  CPSAT_BUDGET_CANONICAL  = $CPSAT_BUDGET_CANONICAL s"

# Verify ortools is importable — degrading silently mid-run would waste hours
if ! python3 -c "from ortools.sat.python import cp_model" 2>/dev/null; then
    log "FATAL: ortools not importable. Activate venv or install ortools."
    log "       \`source .venv/bin/activate && pip install ortools\`"
    exit 3
fi
log "✓ ortools importable"

# Verify matchmaker binary if job 2 is going to run
if ! should_skip 2; then
    if ! command -v matchmaker &>/dev/null; then
        log "WARN: matchmaker binary not on PATH. Job 2 will fail. Skipping."
        SKIP_JOBS="${SKIP_JOBS:+$SKIP_JOBS,}2"
    else
        log "✓ matchmaker binary: $(which matchmaker)"
    fi
fi

if [[ $DRY_RUN -eq 1 ]]; then
    log ""
    log "DRY RUN — would execute these jobs:"
    for j in 1 2 3 4; do
        if should_skip $j; then
            log "  [skip] Job $j"
        else
            log "  [run]  Job $j"
        fi
    done
    exit 0
fi

# Track overall success
OVERALL_RC=0

# ── Job 1: Standards eval on existing inventory ──────────────────────

if should_skip 1; then
    log "Skipping Job 1 (standards eval)"
else
    JOB1_LOG="$OUTDIR/job1_standards.log"
    FIXTURES_CSV=$(IFS=,; echo "${EXISTING_FIXTURES[*]}")
    # standards.py writes its own timestamped report under
    # scripts/scheduler_eval/reports/. Capture which files it produced
    # (by stamping a marker before/after) and move them into our run dir.
    JOB1_PRE_STAMP="$(date +%s)"
    sleep 1   # ensure report mtime is strictly > marker
    run_job "Job 1: Standards eval (existing inventory)" "$JOB1_LOG" \
        python3 scripts/scheduler_eval/standards.py \
            --fixtures "$FIXTURES_CSV" \
            --seeds "$N_SEEDS_STANDARDS" \
            --sa-iterations "$SA_ITERATIONS_STANDARDS" \
        || OVERALL_RC=1
    # Move any standards_*.{json,md} files newer than the marker
    find scripts/scheduler_eval/reports -maxdepth 1 \
        -name 'standards_*' -newermt "@$JOB1_PRE_STAMP" \
        -exec mv {} "$OUTDIR/standards/" \; 2>/dev/null
    # Surface the verdict
    JOB1_REPORT="$(ls -t "$OUTDIR/standards"/standards_*.json 2>/dev/null | head -1)"
    if [[ -n "$JOB1_REPORT" && -f "$JOB1_REPORT" ]]; then
        log "  Standards report: $JOB1_REPORT"
        python3 -c "
import json
try:
    with open('$JOB1_REPORT') as f:
        r = json.load(f)
    v = r.get('overall_verdict', 'unknown')
    fc = len(r.get('fixtures', []) if isinstance(r.get('fixtures'), list) else r.get('fixtures', {}))
    print(f'  Verdict: {v}, fixtures evaluated: {fc}')
except Exception as e:
    print(f'  (could not parse report: {e})')
" 2>&1 | tee -a "$MASTER_LOG"
    fi
fi

# ── Job 2: Matchmaker head-to-head ───────────────────────────────────

if should_skip 2; then
    log "Skipping Job 2 (matchmaker comparison)"
else
    JOB2_LOG="$OUTDIR/job2_matchmaker.log"
    run_job "Job 2: Matchmaker head-to-head (MN regionals)" "$JOB2_LOG" \
        python3 scripts/scheduler_eval/runner.py \
            --fixtures "$MN_FIXTURES" \
            --adapters frc-scheduler-server,matchmaker \
            --trials 1 \
            --out-dir "$OUTDIR/matchmaker" \
        || OVERALL_RC=1
    # Surface the head-to-head summary if present
    LATEST_RUN=$(ls -td "$OUTDIR/matchmaker"/[0-9]* 2>/dev/null | head -1)
    if [[ -n "$LATEST_RUN" && -f "$LATEST_RUN/report.md" ]]; then
        log "  Head-to-head section from report.md:"
        sed -n '/^### Head-to-head/,/^##/p' "$LATEST_RUN/report.md" \
            | head -15 | sed 's/^/    /' | tee -a "$MASTER_LOG"
    fi
fi

# ── Job 3: Canonical re-curation (existing shapes) ───────────────────

if should_skip 3; then
    log "Skipping Job 3 (canonical re-curation)"
else
    JOB3_LOG="$OUTDIR/job3_recurate.log"
    log "─── START Job 3: Re-curate ${#EXISTING_CANONICALS[@]} existing canonicals ───"
    log "  Writing to: $OUTDIR/canonicals/ (NOT to app/canonical_schedules/)"
    log "  Promotion to app/ is a manual review step after this completes."
    JOB3_START=$SECONDS
    JOB3_FAILS=0
    # Save originals so we can restore them after the run
    cp -r app/canonical_schedules "$OUTDIR/canonicals/_originals_backup"
    for spec in "${EXISTING_CANONICALS[@]}"; do
        read -r n mpt tpa cd <<< "$spec"
        shape="${n}x${mpt}"
        canonical_log="$OUTDIR/canonicals/${shape}_cd${cd}.log"
        log "  Building canonical: ${n}×${mpt} cd=${cd} → ${canonical_log}"
        spec_start=$SECONDS
        set +e
        python3 scripts/scheduler_eval/build_canonical.py \
            --shape "$shape" --tpa "$tpa" --cooldown "$cd" \
            --method sa \
            --sa-iterations "$SA_ITERATIONS_CANONICAL" \
            --n-seeds "$N_SEEDS_CANONICAL" \
            --cpsat-post-pass-budget "$CPSAT_BUDGET_CANONICAL" \
            > "$canonical_log" 2>&1
        rc=$?
        set -e
        spec_elapsed=$((SECONDS - spec_start))
        if [[ $rc -eq 0 ]]; then
            # Move the just-built canonical into the run's output dir
            built="app/canonical_schedules/${n}x${mpt}x${tpa}_cd${cd}.json"
            if [[ -f "$built" ]]; then
                cp "$built" "$OUTDIR/canonicals/${shape}x${tpa}_cd${cd}.json"
                # Restore the original so production isn't disturbed mid-run
                if [[ -f "$OUTDIR/canonicals/_originals_backup/${n}x${mpt}x${tpa}_cd${cd}.json" ]]; then
                    cp "$OUTDIR/canonicals/_originals_backup/${n}x${mpt}x${tpa}_cd${cd}.json" "$built"
                fi
                log "  ✓ ${shape} cd=${cd}  elapsed=${spec_elapsed}s"
            else
                log "  ⚠ ${shape} cd=${cd}  rc=0 but expected file not found"
                JOB3_FAILS=$((JOB3_FAILS + 1))
            fi
        else
            log "  ✗ ${shape} cd=${cd}  rc=$rc  elapsed=${spec_elapsed}s"
            log "    last 5 lines:"
            tail -5 "$canonical_log" | sed 's/^/      /' | tee -a "$MASTER_LOG"
            JOB3_FAILS=$((JOB3_FAILS + 1))
        fi
        # Concat per-spec log into the job log
        echo "=== ${shape} cd=${cd} (rc=$rc) ===" >> "$JOB3_LOG"
        cat "$canonical_log" >> "$JOB3_LOG"
        echo >> "$JOB3_LOG"
    done
    JOB3_ELAPSED=$((SECONDS - JOB3_START))
    JOB3_MINS=$((JOB3_ELAPSED / 60))
    if [[ $JOB3_FAILS -eq 0 ]]; then
        log "─── DONE  Job 3  ${#EXISTING_CANONICALS[@]}/${#EXISTING_CANONICALS[@]} succeeded  elapsed=${JOB3_MINS}m ───"
    else
        log "─── PARTIAL Job 3  $((${#EXISTING_CANONICALS[@]} - JOB3_FAILS))/${#EXISTING_CANONICALS[@]} succeeded  elapsed=${JOB3_MINS}m ───"
        OVERALL_RC=1
    fi
fi

# ── Job 4: Build new canonicals for MSHSL odd-team-count shapes ──────

if should_skip 4; then
    log "Skipping Job 4 (new canonicals for odd-team-count shapes)"
else
    JOB4_LOG="$OUTDIR/job4_new_canonicals.log"
    log "─── START Job 4: Build ${#NEW_CANONICALS[@]} new canonicals (MSHSL shapes) ───"
    JOB4_START=$SECONDS
    JOB4_FAILS=0
    for spec in "${NEW_CANONICALS[@]}"; do
        read -r n mpt tpa cd <<< "$spec"
        shape="${n}x${mpt}"
        canonical_log="$OUTDIR/canonicals/new_${shape}_cd${cd}.log"
        log "  Building new canonical: ${n}×${mpt} cd=${cd} → ${canonical_log}"
        spec_start=$SECONDS
        set +e
        python3 scripts/scheduler_eval/build_canonical.py \
            --shape "$shape" --tpa "$tpa" --cooldown "$cd" \
            --method sa \
            --sa-iterations "$SA_ITERATIONS_CANONICAL" \
            --n-seeds "$N_SEEDS_CANONICAL" \
            --cpsat-post-pass-budget "$CPSAT_BUDGET_CANONICAL" \
            > "$canonical_log" 2>&1
        rc=$?
        set -e
        spec_elapsed=$((SECONDS - spec_start))
        if [[ $rc -eq 0 ]]; then
            built="app/canonical_schedules/${n}x${mpt}x${tpa}_cd${cd}.json"
            if [[ -f "$built" ]]; then
                # NEW shapes — capture but also remove from app/ since they
                # weren't there before and we want a clean review step
                cp "$built" "$OUTDIR/canonicals/new_${shape}x${tpa}_cd${cd}.json"
                rm "$built"
                log "  ✓ ${shape} cd=${cd}  elapsed=${spec_elapsed}s"
            else
                log "  ⚠ ${shape} cd=${cd}  rc=0 but expected file not found"
                JOB4_FAILS=$((JOB4_FAILS + 1))
            fi
        else
            log "  ✗ ${shape} cd=${cd}  rc=$rc  elapsed=${spec_elapsed}s"
            log "    last 5 lines:"
            tail -5 "$canonical_log" | sed 's/^/      /' | tee -a "$MASTER_LOG"
            JOB4_FAILS=$((JOB4_FAILS + 1))
        fi
        echo "=== new ${shape} cd=${cd} (rc=$rc) ===" >> "$JOB4_LOG"
        cat "$canonical_log" >> "$JOB4_LOG"
        echo >> "$JOB4_LOG"
    done
    JOB4_ELAPSED=$((SECONDS - JOB4_START))
    JOB4_MINS=$((JOB4_ELAPSED / 60))
    if [[ $JOB4_FAILS -eq 0 ]]; then
        log "─── DONE  Job 4  ${#NEW_CANONICALS[@]}/${#NEW_CANONICALS[@]} succeeded  elapsed=${JOB4_MINS}m ───"
    else
        log "─── PARTIAL Job 4  $((${#NEW_CANONICALS[@]} - JOB4_FAILS))/${#NEW_CANONICALS[@]} succeeded  elapsed=${JOB4_MINS}m ───"
        OVERALL_RC=1
    fi
fi

# ── Final summary ────────────────────────────────────────────────────

log ""
log "═══════════════════════════════════════════════════════════════"
log "Overnight run complete. Output dir: $OUTDIR"
log ""
log "Artifacts of interest:"
log "  Master log:   $MASTER_LOG"
log "  Standards:    $OUTDIR/standards/"
log "  MM compare:   $OUTDIR/matchmaker/"
log "  Canonicals:   $OUTDIR/canonicals/"
log ""
log "Review steps when you return:"
log "  1. cat $MASTER_LOG"
log "  2. Compare existing canonicals (Job 3 output) to current app/:"
log "       diff -q app/canonical_schedules/ $OUTDIR/canonicals/"
log "  3. Inspect new canonicals (Job 4 output):"
log "       ls -la $OUTDIR/canonicals/new_*.json"
log "  4. If new canonicals look good, copy them into app/ and commit."
log "═══════════════════════════════════════════════════════════════"
log "OVERALL: $([[ $OVERALL_RC -eq 0 ]] && echo SUCCESS || echo "PARTIAL ($OVERALL_RC)")"

exit $OVERALL_RC
