# Iteration Ceiling Investigation — 2026 Lex SA

**Status:** Practical ceiling chosen at 5,000,000. Strict ceiling (per
tight criterion) is **above 5M**, not found within the tested range.
Documented as known-open question for future revisit.

## Background

The lex SA's iteration count tunes wall-clock vs schedule quality. We
ran an iteration sweep on Stark (36 workers, 30 trials per level) on
the 2026mnst fixture (36 teams × 7 MPT) with all phases enabled
(Phase 0a lex score, 0b hard cooldown, 0c targeted moves, Phase 1 R/B
post-pass, Phase 2 Sykes station post-pass).

**Tight criterion:** K\* is the smallest iteration count where the mean
improvement at the next level is less than the standard deviation at K.
Past K\*, additional iterations buy randomness, not quality.

## Sweep results — tests/iteration_sweep/2026mnst_30trials.json

Run: 7.6 minutes wall-clock on Stark, 210 trials total. Bottleneck
identified as opp_quad (par_quad converges to floor 252 by SA=200K).

### Mean opp_quad and stdev across 30 trials per level

| Level | Mean | Stdev | Min (best of 30) | p50 |
|------:|-----:|------:|-----------------:|-----:|
| 10K | 485.2 | 33.8 | 454 | 469 |
| 50K | 511.1 | 14.7 | 482 | 509 |
| 200K | 474.5 | 8.4 | 460 | 475 |
| 500K | 448.9 | 8.1 | 432 | 450 |
| 1M | 433.8 | 8.1 | 420 | 434 |
| 2M | 416.5 | 6.5 | 404 | 418 |
| 5M | 401.4 | 5.4 | 386 | 401 |

### Tight criterion application

| Transition | Mean improvement | Stdev at K | Verdict |
|-----------|----------------:|-----------:|--------:|
| 10K → 50K | -25.9 (worse) | 33.8 | Degenerate (par_quad lockdown) |
| 50K → 200K | +36.6 | 14.7 | Still improving (2.5σ) |
| 200K → 500K | +25.7 | 8.4 | Still improving (3.1σ) |
| 500K → 1M | +15.1 | 8.1 | Still improving (1.9σ) |
| 1M → 2M | +17.3 | 8.1 | Still improving (2.1σ) |
| 2M → 5M | +15.1 | 6.5 | Still improving (2.3σ) |

**No level satisfies the tight criterion within the tested range.**
Each successive level continues to produce mean improvements that
exceed one standard deviation. The strict K\* lies above 5M.

## The 10K → 50K anomaly

Mean opp_quad got *worse* going 10K → 50K (485.2 → 511.1) while stdev
shrank dramatically (33.8 → 14.7). This is not noise.

At 10K, the SA hasn't fully converged on par_quad (some trials still
escape with par_quad > 252). When par_quad isn't locked at floor, the
SA can freely move teams in ways that happen to keep opp_quad lower.

At 50K, par_quad has locked at 252 (mean 252.2, stdev 1.1). Once
par_quad is at floor, lex paramount forbids any swap that would
worsen partner — that constraint funnels opp_quad into a basin
slightly higher than the unlocked-partner regime would allow.

This is correct FRC-paramount behavior. FRC #2 (partner) > FRC #3
(opponent), so we'd rather have opp_quad = 511 with par_quad = 252
than opp_quad = 485 with par_quad = 256. The data shows lex
semantics are working as designed.

## Practical ceiling decision

The diminishing-returns curve is steady but real:

| Transition | opp_quad Δ | Time Δ (per trial) | Improvement / second |
|-----------|-----------:|-------------------:|---------------------:|
| 200K → 500K | -28 | +11.7s | 2.4 units/s |
| 500K → 1M | -12 | +19.6s | 0.6 units/s |
| 1M → 2M | -16 | +36.5s | 0.4 units/s |
| 2M → 5M | -18 | +106s | 0.17 units/s |

Beyond 5M, single-trial wall-clock exceeds 3 minutes, becoming
impractical for users running interactive schedule generation.

**Decision (per user direction, 2026-05-09):** Cap "Best" preset at
5,000,000 iterations. K\* is documented as **above 5M, not found**.

**Documented as future work** — if compute budget or schedule-quality
expectations change, extend the sweep upward to find K\* properly.

## Future work — extending the sweep

To find K\* per tight criterion, run an extended sweep:

```bash
python3 scripts/iteration_sweep.py \\
    --fixture 2026mnst \\
    --trials 30 \\
    --levels 1000000,2000000,5000000,10000000,20000000,50000000 \\
    --workers 36 \\
    --out tests/iteration_sweep/2026mnst_extended.json
```

Estimated wall-clock on Stark: ~5 hours (50M trials are ~30 minutes
each; 30 trials × 50M = ~15 CPU-hours = ~25 wall-clock minutes for
that level alone, plus the lower levels).

K\* may turn out to be 10M, 20M, or higher. Even when found, the
"Best" user-facing preset stays at 5M unless we rework the UI to
allow long-running async generation with progress indicator.

## How this connects to the MatchMaker reference

On the user's actual state qual schedule (36 teams × 7 MPT):

- MatchMaker tuple: `(0, 252, 416, 0, 3, 65, 0, 0)`
- Best-of-30 at SA=2M: `(0, 252, 404, 0, 1, 39, 0, 0)`
- Best-of-30 at SA=5M: `(0, 252, 386, 0, 1, 44, 0, 0)`

All three tuples share the same cooldown (0), partner floor (252), and
surrogate count (0). They differ at opp_quad, rb_metric, and station_pen.
The lex tuples produced at SA=2M+ are in a comparable range to the
MatchMaker reference — that's the development bar this sweep was set up
to verify. MatchMaker (idleloop.com/matchmaker) remains the long-standing
community scheduler used by event organizers; comparing against it here
is sanity-check, not competition.

The extended sweep (future work) would tell us how the lex tuples move
at higher iteration budgets, not change the conclusion that we're in
the right neighborhood.

## Variance and best-of-N strategy

Stdev is ~5-8 across all levels above 200K. Best-of-30 effectively
samples the lower tail. To further improve:

- Best-of-100 at SA=2M: roughly equivalent to best-of-30 at SA=5M
  (both push the minimum further into the distribution's left tail)
- Stark with 36 workers can run best-of-30 at SA=2M in ~90 seconds
  parallel wall-clock, vs ~3 minutes for best-of-30 at SA=5M

For users who care about consistent best results, **higher trial
count is often more useful than higher iteration count** within
this regime.

## Recommended preset levels (locked in code)

| Preset | SA budget | Single-trial time | Use case |
|---|---|---|---|
| Fair | 50,000 | ~2s | Quick previews |
| Good | 500,000 | ~20s | Default for interactive editing |
| Best | 2,000,000 | ~75s | Production / state events |
| Maximum | 5,000,000 | ~180s | When compute budget allows |

These map to the `quality_preset` parameter on the schedule
generation endpoint and UI control.

## Provenance

- Sweep harness: `scripts/iteration_sweep.py`
- Run on Stark, 2026-05-09, 36 workers, 7.6 min wall-clock
- JSON output: `tests/iteration_sweep/2026mnst_30trials.json`
- Tight criterion analysis: `tests/iteration_sweep/2026mnst_30trials_analysis.txt`
  (the "Per-level stats" + "Tight criterion" tables shown above)
