# FRC Match Scheduler — Team Placement Priorities

## Overview: Two-Stage Scheduling

- **Stage 1** produces an abstract slot-based schedule (slot indices 1..N, no real
  team numbers). Deterministic given a seed — same seed always produces same structure.
- **Stage 2** assigns real team numbers to those slots by trying many random permutations
  and picking the one that best satisfies the placement criteria.

The scheduler's defaults are aligned with the official FIRST/MatchMaker
algorithm (Saxton/Idle Loop, used by FMS). Where we go beyond FIRST, it's
additive — better diversity, more flexibility — never contradictory. See
the **FIRST Alignment** section below for the line-by-line comparison.

---

## Stage 1: Abstract Schedule Generation

### Step 1 — Match Count (pure math, no criteria)

```
totalMatches    = ceil(N × MPT / 6)
matchesPerRound = ceil(N / 6)          ← Phase 1 size; cosmetic marker after
totalSurSlots   = totalMatches × 6 − N × MPT
phase1Surplus   = matchesPerRound × 6 − N
fairSurCap      = max(1, ceil(totalSurSlots / N))
```

The match count is a mathematical fact. No placement criteria affect it.

`fairSurCap` is the strict ceiling on how many surrogate appearances any
single team can have. Previously this was `ceil(slots/N) + 1` — the +1
buffer was dropped to match FIRST's stricter "no team gets more than one
surrogate match in normal cases."

### Step 2 — Team Placement

#### Phase 1 — Round 1 (matchesPerRound matches)

- Every slot plays exactly once before any slot plays twice.
- Last match fills `phase1Surplus` extra slots with early second-plays (NOT surrogates).
- Alliance assignment enumerates all C(6,3)=20 splits; last match penalises
  unequal second-play distribution across alliances (−500 per imbalance unit).
- No slot in Phase 1 is ever flagged as a surrogate.

#### Phase 2 — Open Scheduling (remaining matches)

```
underQuota = slots with mc[s] < MPT
atQuota    = slots with mc[s] == MPT  (drafted only when surNeeded > 0)
surNeeded  = max(0, 6 − len(underQuota))
```

60 random candidate sets per match; highest-scoring chosen.
A slot is flagged surrogate only when mc[s] >= MPT at selection time.

> **Known divergence from FIRST:** the FRC manual (§10.5.2 / §11.6.2) says
> a surrogate's extra match is always *that team's* third qualification
> match. We currently let surrogate appearances fall where they need to
> based on quota math (typically end-of-schedule). Implementing the
> "always 3rd appearance" rule requires reworking Phase 2's quota model
> to pre-pick the K surrogate teams and target MPT+1 for them with the
> 3rd appearance flagged. Tracked as future work.

---

### Placement Priorities

| #   | Priority             | Type     | Weight (default)  | Description |
|-----|----------------------|----------|-------------------|-------------|
| P1  | Match composition    | **Hard** | —                 | Exactly 6 teams/match, 3 red / 3 blue |
| P2  | Play quota           | **Hard** | —                 | Each slot plays exactly MPT times. Surrogates fill structural surplus. Cap: `fairSurCap` |
| P3  | Round 1 guarantee    | **Hard** | —                 | All slots play once before any plays twice |
| P4  | Cooldown             | **Hard** | −1000 × deficit   | Slot cannot replay within cooldown matches of last appearance |
| P5  | Match equity         | Soft     | W_COUNT = 5       | Prefer slots with fewer appearances |
| P6  | Alliance balance     | Soft     | W_BALANCE = 30    | Minimise per-team red/blue imbalance |
| P7  | Gap maximisation     | Soft     | W_GAP = 10        | Reward slots that have waited longer |
| P8  | Opponent diversity   | Soft     | W_OPPONENT = 60   | Penalise repeat cross-alliance opponents (**quadratic**) |
| P9  | Partner diversity    | Soft     | W_PARTNER = 80    | Penalise repeat same-alliance partners (**quadratic**, weighted higher than opponents per FIRST: only 2 partners but 3 opponents per match) |
| P10 | Station balance      | Soft     | W_STATION = 30    | Penalise uneven distribution across the 6 stations (R1, R2, R3, B1, B2, B3) per team |
| P11 | Surrogate fairness   | Soft     | W_SUR_RPT = 200   | Spread surrogates evenly. Hard cap: `fairSurCap` |

**Quadratic penalty for repeats** (P8, P9): the cost of a pair encountering
each other for the (k+1)-th time is `(2k+1) × W` — derived from `(k+1)² − k²`.
This means:

- 1st encounter: cost = 1 × W
- 2nd encounter: cost = 4 × W (3× more than the 1st)
- 3rd encounter: cost = 9 × W (5× more than the 2nd)

This pushes the scheduler to spread repeats evenly across all pairs rather
than concentrate them on a few unlucky pairs. Why it matters: a team's
qualification rank should reflect their performance, not luck of partner
draw — broad partner distribution is what makes OPR/EPA work and what makes
playoff alliance selection reflect actual team strength.

### Configurability

All weights are runtime-configurable via the editor's "Placement Criteria
(FIRST-aligned)" panel. Each row shows the FIRST default value next to the
user's chosen value. Deviating from defaults:

- Highlights the row in amber
- Shows a notice banner: "⚠ Custom weights — generated schedule will not match official FIRST scheduling"
- Persists the weights with the schedule (DB column + URL params) for full reproducibility

A "⊕ Match FIRST defaults" button resets all weights to the canonical
values listed in the table above. The same defaults are exposed via
`GET /api/scheduler/defaults` for tooling.

---

### Post-Generation Sweeps (deterministic, after greedy scheduling)

| Rule | Constraint | Method |
|---|---|---|
| R1 | No surrogate in **last match** | Swap surrogate S in last match with non-surrogate R in same match, via earlier match M where S appears and R is absent. Flag moves to M. |
| R2 | No surrogate as **first appearance** | Guard inside R1: skip match M if M ≤ first_appearance[S]. |
| R3 | No surrogate as **last appearance** | Move flag from slot's last appearance to any earlier non-first appearance. No teams change matches. Up to 3 passes. |

### Iteration Scoring

```
score = −(B2B×1000 + maxAllianceImbalance×500 + surrogates×200 +
          Σ(opp_count²)×W_OPPONENT + Σ(par_count²)×W_PARTNER +
          Σ(stationSpread)×W_STATION)
```

The multi-worker iteration loop already explores the seed space. Each
worker produces several candidate schedules; the best score wins.

### Seeding

`generate_matches(num_teams, matches_per_team, ideal_gap, seed, weights)` —
hex string seed, optional weights dict.
Mulberry32 PRNG (JS) / `random.Random(seed)` (Python). Same seed → identical output.
Auto-generated per run, stored in DB and URL.

---

## Stage 2: Team Assignment

**Input:** abstract schedule + N real team numbers + `assign_seed`

**Method:** N iterations with seeded RNG. Each shuffles team numbers into slots,
scores against P5–P11 with real numbers, returns best `slot_map {slot: team_number}`.

Default iterations: 500.

---

## Diversity Report

After Stage 1 generation, the editor renders a Diversity Report panel
showing the actual placement quality:

- **Headline numbers:** average partner repeats per pair vs. theoretical floor, average opponent repeats per pair, count of pairs that never met, max station imbalance, surrogate distribution.
- **Histograms:** distribution of pair-encounters at each repeat count (0, 1, 2…) for both partners and opponents, with bars colored green (at floor), amber (over floor by 1), and red (over floor by 2+).
- **Issues callouts:** worst-case pairs that exceed the theoretical floor; slots with uneven station distribution; surrogate concentration. Or a green "clean" banner if everything is at floor.

This makes it visible whether the algorithm is doing its job. Different
seeds can be compared directly — "seed A produces 3 over-floor pairs,
seed B produces 0; use seed B."

API: `GET /api/abstract-schedules/{id}/diversity-report`.

---

## URL Reproducibility

After generating, the browser URL is updated with all parameters needed to exactly
reproduce the schedule. Opening the URL auto-runs Stage 1 and optionally Stage 2.

### URL Parameter Reference

| Parameter | Example | Description |
|-----------|---------|-------------|
| `n` | `51` | Number of teams |
| `mpt` | `11` | Matches per team |
| `cd` | `3` | Cooldown (matches between appearances) |
| `ct` | `8` | Default cycle time in minutes |
| `days` | `2` | Number of competition days |
| `seed` | `a1b2c3d4` | Stage 1 hex seed |
| `aseed` | `cafebabe` | Stage 2 assignment hex seed |
| `teams` | `254,1114,...` | Team numbers in slot order (slot 1 first) |
| `d1` | `08:00-17:00` | Day 1 start and end time (`HH:MM-HH:MM`) |
| `d1b` | `Lunch\|12:00\|13:00,...` | Day 1 breaks: `Name\|HH:MM\|HH:MM`, comma-separated |
| `wp` | `100` | W_PARTNER override (only emitted if differs from FIRST default of 80) |
| `wo` | `40` | W_OPPONENT override (default 60) |
| `ws` | `15` | W_STATION override (default 30) |
| `wb` | `50` | W_BALANCE override (default 30) |
| `wg` | `5` | W_GAP override (default 10) |
| `wsr` | `100` | W_SUR_RPT override (default 200) |
| `wc` | `2` | W_COUNT override (default 5) |

Up to 5 days supported (`d1`–`d5`, `d1b`–`d5b`). Weights are only emitted
when they differ from FIRST defaults — the common case keeps URLs short.

### Example URL

```
?n=51&mpt=11&cd=3&ct=8&days=2&seed=a1b2c3d4&aseed=cafebabe
  &d1=08:00-17:00&d1b=Lunch|12:00|13:00
  &d2=08:00-15:00
  &teams=254,1114,2052,...
```

**Without `teams`:** abstract schedule renders with S1/S2 slot labels.
**Without `aseed`:** Stage 2 skipped; abstract schedule shown only.
**Without `seed`:** params applied to UI but auto-run not triggered.

---

## FIRST Alignment

This scheduler's defaults match what FIRST's MatchMaker algorithm (used
by FMS at all official events) produces. Source documents:

- [Idle Loop / Saxton — MatchMaker Algorithm](https://idleloop.com/matchmaker/)
- FRC Game Manual §10.5.2 (or §11.6.2 in some years) — Match Assignment
- FMS Manual — Run Match Maker

### Criteria comparison

| FIRST Criterion | Status | Our Implementation |
|---|---|---|
| 1. Round uniformity | ✅ Match | P3 — every slot plays once before any plays twice |
| 2. Match separation | ✅ Match | P4 — cooldown enforces minimum gap (configurable; FIRST has fixed minimum based on team count) |
| 3. Pairing uniformity | ✅ Match + extend | P8/P9 with quadratic penalty, partners weighted higher than opponents (matches FIRST's stated rationale: 2 partners vs 3 opponents per match) |
| 4. Minimize surrogates | ✅ Match + extend | Strict cap `fairSurCap` (we dropped the +1 buffer) |
| 5. Red/Blue balancing | ✅ Match | P6 — W_BALANCE penalty per imbalance unit |
| 6. Station position balancing | ✅ Match | P10 — new in this revision; FIRST has done this since 2017 (Steamworks) |
| Surrogates = team's 3rd match | ⚠ Diverge | FIRST manual §10.5.2: "always their third Qualification MATCH" (since 2008). We currently let surrogates fall where quota math dictates. Tracked as future work — requires Phase 2 quota model rework. |

### Where we go beyond FIRST

- **Configurable cooldown** — FIRST uses a fixed minimum based on team count. We expose this as a parameter so events can prioritize separation more heavily if needed.
- **Configurable weights** — FIRST's MatchMaker is fixed; ours are tunable via the editor. Defaults match FIRST.
- **Multi-day events** with breaks, cycle-time changes, and day breaks.
- **Practice match scheduling** with separate constraints.
- **Diversity Report panel** — visible per-pair distribution, station balance, surrogate placement so users can see whether a generated schedule meets their expectations.
- **Quadratic penalty for repeats** — FIRST uses a doubling penalty per duplicate. Our quadratic version provides stronger pressure to spread repeats evenly. Still produces FIRST-compatible schedules at default weights; just optimizes harder.
- **Stage 2 separate from Stage 1** — FIRST's MatchMaker conflates them. Splitting lets us regenerate team-to-slot assignments without disrupting the underlying structure.

None of these contradict FIRST; they are all additive.

### "FIRST strict" preset

The editor's "⊕ Match FIRST defaults" button resets all weights to canonical
FIRST values:

```
W_BALANCE  = 30   W_GAP     = 10   W_COUNT   = 5
W_OPPONENT = 60   W_PARTNER = 80
W_STATION  = 30   W_SUR_RPT = 200
```

After clicking, the URL has no weight params (all at defaults), the deviation
notice disappears, and the generated schedule will follow FIRST's relative
priorities. The cooldown parameter is left untouched — that's a per-event
operational decision.

---

## Access Control

| Operation | Anonymous | Authenticated |
|---|---|---|
| View any schedule | ✓ read-only | ✓ |
| Generate abstract schedule | ✓ | ✓ (becomes owner) |
| Assign teams | ✓ | ✓ (becomes owner) |
| Delete schedule | ✗ | ✓ if created_by matches |
| Duplicate any schedule | ✓ (unowned copy) | ✓ (owned copy) |
| Share URL | ✓ always | ✓ |

`created_by` = OAuth subject (`google:<sub>` or `apple:<sub>`).
NULL `created_by` = anonymous schedule; readable by all, deletable by none.
