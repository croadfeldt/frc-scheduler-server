# FRC Match Scheduler — Team Placement Priorities

## Overview: Two-Stage Scheduling

The scheduler separates **structure** from **assignment**:

- **Stage 1** produces an abstract slot-based schedule (slot indices 1..N, no real
  team numbers). Deterministic given a seed — same seed always produces same structure.
- **Stage 2** assigns real team numbers to those slots by trying many random permutations
  and picking the one that best satisfies the placement criteria.

---

## Stage 1: Abstract Schedule Generation

### Step 1 — Match Count (pure math, no criteria)

```
totalMatches    = ceil(N × MPT / 6)
matchesPerRound = ceil(N / 6)          ← Phase 1 size; cosmetic marker thereafter
totalSurSlots   = totalMatches × 6 − N × MPT
phase1Surplus   = matchesPerRound × 6 − N
fairSurCap      = ceil(totalSurSlots / N) + 1
```

The match count is a mathematical fact. No placement criteria affect it.
`totalSurSlots` is the structural surplus — cannot be reduced further.

### Step 2 — Team Placement

#### Phase 1 — Round 1 (matchesPerRound matches)

- Every slot plays exactly once before any slot plays twice.
- Last match fills `phase1Surplus` extra slots with early second-plays (NOT surrogates).
- Alliance assignment enumerates all C(6,3)=20 splits; last match additionally
  penalises unequal second-play distribution across alliances (−500 per imbalance unit).
- No slot in Phase 1 is ever flagged as a surrogate.

#### Phase 2 — Open Scheduling (remaining matches)

```
underQuota = slots with mc[s] < MPT     ← regular
atQuota    = slots with mc[s] == MPT    ← surrogate (only when surNeeded > 0)
surNeeded  = max(0, 6 − len(underQuota))
```

60 random candidate combinations tried per match; highest-scoring chosen.
A slot is flagged surrogate only when mc[s] >= MPT at time of selection.

---

### Placement Priorities

| #   | Priority           | Type     | Weight            | Description |
|-----|--------------------|----------|-------------------|-------------|
| P1  | Match composition  | **Hard** | —                 | Exactly 6 teams/match, 3 red / 3 blue |
| P2  | Play quota         | **Hard** | —                 | Each slot plays exactly MPT times. Surrogates fill structural surplus. Cap: fairSurCap |
| P3  | Round 1 guarantee  | **Hard** | —                 | All slots play once before any plays twice |
| P4  | Cooldown           | **Hard** | −1000 × deficit   | Slot cannot replay within cooldown matches of last appearance |
| P5  | Match equity       | Soft     | W_COUNT = 5       | Prefer slots with fewer appearances |
| P6  | Alliance balance   | Soft     | W_BALANCE = 50    | Minimise |redCount − blueCount|. All C(6,3)=20 splits evaluated |
| P7  | Gap maximisation   | Soft     | W_GAP = 10        | Reward slots that have waited longer |
| P8  | Opponent diversity | Soft     | W_OPPONENT = 15   | Penalise repeat cross-alliance opponents |
| P9  | Partner diversity  | Soft     | W_PARTNER = 12    | Penalise repeat same-alliance partners |
| P10 | Surrogate fairness | Soft     | W_SUR_RPT = 200   | Spread surrogate appearances evenly. Hard cap: fairSurCap |

---

### Post-Generation Sweeps (deterministic, applied after greedy scheduling)

| Rule | Constraint | Method |
|---|---|---|
| R1 | No surrogate in **last match** | Swap surrogate S in last match with non-surrogate R in same match, via an earlier match M where S appears and R is absent. Flag moves to M. |
| R2 | No surrogate as **first appearance** | Guard inside R1: skip match M if M ≤ first_appearance[S]. |
| R3 | No surrogate as **last appearance** | Flag reassignment: move the surrogate flag from a slot's last appearance to any earlier non-first appearance. No teams change matches. Up to 3 passes. |

---

### Iteration Scoring

```
score = −(B2B×1000 + maxAllianceImbalance×500 + surrogates×200 + repeatOpponents×15 + repeatPartners×12)
```

Stage 1 runs as a single deterministic pass (iterations=1).
Same formula used by Stage 2 to evaluate assignment permutations.

### Seeding

`generateMatches(numTeams, matchesPerTeam, cooldown, seed)` — hex string seed.
Internally: mulberry32 PRNG (JS) / `random.Random(seed)` (Python).
Same seed → identical output always. Auto-generated per run, stored in DB and URL.

---

## Stage 2: Team Assignment

**Input:** abstract schedule + N real team numbers + `assign_seed`

**Method:** N iterations with seeded RNG. Each shuffles team numbers into slot positions,
scores against P5–P10 with real numbers, returns best `slot_map {slot: team_number}`.

Default iterations: 500. The abstract match structure is fixed — only slot→team mapping varies.

---

## URL Reproducibility

```
?n=51&mpt=11&cd=3&seed=a1b2c3d4&aseed=cafebabe&teams=254,1114,2052,...
```

| Param  | Meaning |
|--------|---------|
| `n`    | Number of teams |
| `mpt`  | Matches per team |
| `cd`   | Cooldown |
| `seed` | Stage 1 hex seed |
| `aseed`| Stage 2 hex seed |
| `teams`| Comma-separated team numbers in slot order |

Opening the URL auto-runs Stage 1 (with seed), then Stage 2 (if teams + event loaded).
Without teams, abstract schedule shows with S1/S2 slot labels.

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

`created_by` = OAuth subject string (`google:<sub>` or `apple:<sub>`).
NULL created_by = anonymous; cannot be deleted.
