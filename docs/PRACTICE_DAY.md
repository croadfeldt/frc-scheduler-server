# Practice Day Feature

## Overview

The Practice Day feature adds a separate pre-qualification schedule that appears before the qualification days in the schedule output. Practice matches are displayed with a `P` prefix (P1, P2, P3…) and are excluded from qualification statistics.

## FRC Regional Context

At most FRC regionals, the practice day schedule looks like:
- **3 guaranteed matches per team** — every team is guaranteed exactly 3 practice matches
- **Filler matches** — remaining time is filled with additional matches up to a configurable limit
- **Slower cycle time** — practice typically runs at ~9 min/match vs ~8 min/match for quals

## PDF Auto-Detection

When an event agenda PDF is loaded, the scheduler automatically looks for `Practice Match` time blocks using the same parser variants as qualification matches:
- Standard format: `HH:MM AM – HH:MM AM  Practice Matches`
- Ontario two-column format
- NC Begin/Continue format
- Wisconsin fi-ligature repaired format
- Colorado numeric date format

If practice blocks are found, the Practice Day section is automatically enabled and the time window is filled in. A green `PDF ✓` badge appears in the panel header.

## UI Controls

The Practice Day panel appears above the Daily Schedule section and is collapsed by default. Check the **▶ Practice Day** box to expand it.

| Field | Default | Description |
|-------|---------|-------------|
| Start Time | 08:00 | Practice day start |
| End Time | 17:00 | Practice day end |
| Guaranteed Matches/Team | 3 | Minimum matches every team plays |
| Max Filler Matches/Team | 99 (unlimited) | Cap on additional time-fill matches |
| Minutes per Practice Match | 9 | Cycle time for practice matches |

The **status line** below the fields shows the estimated match count after calculation: e.g. `≈ 42 practice matches (21 guaranteed + 21 filler) · ≈5.4 per team · 378/540 min used`.

## URL Parameters

Practice day settings are fully serialized into the share URL:

| Param | Example | Description |
|-------|---------|-------------|
| `pday` | `1` | Practice day enabled |
| `pd` | `08:00-17:00` | Start–end time |
| `pmpt` | `3` | Guaranteed matches/team |
| `pfill` | `99` | Max filler matches/team |
| `pct` | `9` | Minutes per practice match |

## `day_config` JSON

Practice day config is persisted to the `day_config` JSON column alongside the qual day config:

```json
{
  "practiceDay": {
    "enabled": true,
    "start": "08:00",
    "end": "17:00",
    "guaranteed": 3,
    "filler": 99,
    "ct": 9
  }
}
```

## Schedule Output

- Practice day renders as a **"Practice"** day header with a green left border accent
- Match numbers appear as **P1, P2, P3…** instead of 1, 2, 3…
- Practice day is **day 0** internally (`dayNum: 0, isPracticeDay: true`)
- Qualification stats (Total Matches, Matches/Team, Days) **exclude** practice matches
- CSV export includes a `Type` column: `Practice` or `Qualification`

## Match Generation

Practice matches are generated using the same `generateMatches()` algorithm as qualification matches, with:
- A derived seed from the qual seed (`currentSeed + 'p'`) for determinism
- A cooldown of 3 (standard)
- Separate slot numbering (does not affect qual slot assignment)

Practice matches are generated fresh each time the schedule is regenerated — they are **not** persisted to the database as qual matches are (they are part of the `_frcScheduled` rendering data, not the stored abstract schedule).
