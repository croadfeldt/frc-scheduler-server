# FRC Match Scheduler — Team Placement Priorities

## Overview: Two-Stage Scheduling

- **Stage 1** produces an abstract slot-based schedule (slot indices 1..N, no real
  team numbers). Deterministic given a seed — same seed always produces same structure.
- **Stage 2** assigns real team numbers to those slots by trying many random permutations
  and picking the one that best satisfies the placement criteria.

---

## Stage 1: Abstract Schedule Generation

### Step 1 — Match Count (pure math, no criteria)

```
totalMatches    = ceil(N × MPT / 6)
matchesPerRound = ceil(N / 6)          ← Phase 1 size; cosmetic marker after
totalSurSlots   = totalMatches × 6 − N × MPT
phase1Surplus   = matchesPerRound × 6 − N
fairSurCap      = ceil(totalSurSlots / N) + 1
```

The match count is a mathematical fact. No placement criteria affect it.

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

---

### Placement Priorities

| #   | Priority           | Type     | Weight          | Description |
|-----|--------------------|----------|-----------------|-------------|
| P1  | Match composition  | **Hard** | —               | Exactly 6 teams/match, 3 red / 3 blue |
| P2  | Play quota         | **Hard** | —               | Each slot plays exactly MPT times. Surrogates fill structural surplus. Cap: fairSurCap |
| P3  | Round 1 guarantee  | **Hard** | —               | All slots play once before any plays twice |
| P4  | Cooldown           | **Hard** | −1000 × deficit | Slot cannot replay within cooldown matches of last appearance |
| P5  | Match equity       | Soft     | W_COUNT = 5     | Prefer slots with fewer appearances |
| P6  | Alliance balance   | Soft     | W_BALANCE = 50  | Minimise |redCount − blueCount|. All C(6,3)=20 splits evaluated |
| P7  | Gap maximisation   | Soft     | W_GAP = 10      | Reward slots that have waited longer |
| P8  | Opponent diversity | Soft     | W_OPPONENT = 15 | Penalise repeat cross-alliance opponents |
| P9  | Partner diversity  | Soft     | W_PARTNER = 12  | Penalise repeat same-alliance partners |
| P10 | Surrogate fairness | Soft     | W_SUR_RPT = 200 | Spread surrogates evenly. Hard cap: fairSurCap |

---

### Post-Generation Sweeps (deterministic, after greedy scheduling)

| Rule | Constraint | Method |
|---|---|---|
| R1 | No surrogate in **last match** | Swap surrogate S in last match with non-surrogate R in same match, via earlier match M where S appears and R is absent. Flag moves to M. |
| R2 | No surrogate as **first appearance** | Guard inside R1: skip match M if M ≤ first_appearance[S]. |
| R3 | No surrogate as **last appearance** | Move flag from slot's last appearance to any earlier non-first appearance. No teams change matches. Up to 3 passes. |

---

### Iteration Scoring

```
score = −(B2B×1000 + maxAllianceImbalance×500 + surrogates×200 + repeatOpponents×15 + repeatPartners×12)
```

Stage 1 runs as a single deterministic pass (iterations=1).

### Seeding

`generateMatches(numTeams, matchesPerTeam, cooldown, seed)` — hex string seed.
Mulberry32 PRNG (JS) / `random.Random(seed)` (Python). Same seed → identical output.
Auto-generated per run, stored in DB and URL.

---

## Stage 2: Team Assignment

**Input:** abstract schedule + N real team numbers + `assign_seed`

**Method:** N iterations with seeded RNG. Each shuffles team numbers into slots,
scores against P5–P10 with real numbers, returns best `slot_map {slot: team_number}`.

Default iterations: 500.

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
| `d2` | `08:00-15:30` | Day 2 start and end time |
| `d1b` | `Lunch\|12:00\|13:00,...` | Day 1 breaks: `Name\|HH:MM\|HH:MM`, comma-separated |
| `d2b` | `Break\|14:30\|14:45` | Day 2 breaks |

Up to 5 days supported (`d1`–`d5`, `d1b`–`d5b`).

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

---

## Agenda Fit (from frc-schedule-builder)

Integrated from [github.com/phil-lopreiato/frc-schedule-builder](https://github.com/phil-lopreiato/frc-schedule-builder).

### What it does
When an event is activated, the scheduler automatically fetches the official FIRST agenda PDF and extracts the "Qualification Match" time blocks. It then computes a fit analysis:

| Metric | Formula |
|---|---|
| Total matches needed | `ceil(teams × mpt / 6)` |
| Surrogates | `totalMatches × 6 − teams × mpt` |
| Time needed | `totalMatches × cycleTime` |
| Time available | Sum of parsed qual block durations |
| Buffer / Overflow | `available − needed` |
| Capacity % | `needed / available × 100` |
| Max cycle to fit | `available / totalMatches` |
| Matches per hour | `60 / cycleTime` |

**Fit status:** Comfortable (≤85%), Tight (≤100%), Over Capacity (>100%)

### Agenda PDF URL pattern
```
https://info.firstinspires.org/hubfs/web/event/frc/{year}/{year}_{EVENTCODE}_Agenda.pdf
```
e.g. `2026_WASNO_Agenda.pdf` for event key `2026wasno`.

### Fallback
If the PDF is unavailable (not yet published, CORS blocked, or no "Qualification Match" blocks found), the panel shows a manual "total available minutes" input instead.

### UI behaviour
- Panel appears at the top of the results column when an event is loaded
- Collapsible (click header to toggle)
- Badge shows fit status: ✓ Comfortable / ⚠ Tight / ✗ Over Capacity
- Per-block timeline bars update in real time as numTeams, mpt, or cycleTime change
- Resets when event changes or full reset is triggered

## UI Features

### Day/Night Mode
Toggle between dark (default, Catppuccin Mocha) and light theme via 🌙/☀️ button in the header. Persisted in localStorage.

### Agenda Fit — Apply to Schedule
After FIRST agenda PDF is parsed, "↓ Apply to Day Configuration" auto-fills the day config from real qual time windows, including breaks between sessions.

### TBA Cross-Year Search
Typing in the event field falls back to TBA's global search index when year-specific results are sparse, enabling event discovery across all seasons.

