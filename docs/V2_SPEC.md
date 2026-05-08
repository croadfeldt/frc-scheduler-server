# V2 day_config — canonical specification

**Status:** active. This is the authoritative model. V1 is a deprecated
legacy format being retired (see [V1_RETIREMENT.md](V1_RETIREMENT.md)).

V2 represents an event day as a **tree of typed time blocks**. Every
schedulable concept (matches, breaks, ceremonies, alliance selection,
awards, playoffs) is a block; the tree's shape carries the user's
intent about which blocks contain which others.

---

## 1. Why V2 exists

V1 modeled a day as `(start, end, breaks[], cycleChanges[])` —
essentially a single match-window with breaks punched into it. It
couldn't represent:

- Multiple match blocks per day (e.g. a practice block followed by a
  qual block on the same day, each with its own cycle time)
- Ceremonies, alliance selection, awards as first-class events with
  type-aware rendering, distinct from generic breaks
- Per-block cycle times (V1 had one cycleTime per day with global
  after-match changes)
- Playoff windows with deferred match generation
- The hierarchical relationship between e.g. an awards ceremony nested
  inside a playoff bracket vs sitting at the day level
- Day-level metadata like a user-typed label override

V2 captures all of these and persists them losslessly.

---

## 2. Top-level structure

```jsonc
{
  "dayConfigVersion": 2,
  "cycleTime": 9,          // event default ct (minutes), used when a block omits its own
  "breakBuffer": 5,         // minutes before a break that the scheduler stops trying to fit a match
  "days": [ /* Day */ ]
}
```

The `dayConfigVersion: 2` marker is **required**. Any object lacking it
is V1 data and is run through the legacy migrator (during the
transition period only — see retirement plan).

---

## 3. Day

```jsonc
{
  "label": "Day 1",            // free-form, defaults to "Day N"
  "labelOverride": null,        // user-typed override, supersedes the auto-classified label
  "date": "2026-04-04",         // ISO yyyy-mm-dd; "" or null when unset
  "blocks": [ /* Block */ ]
}
```

`labelOverride` semantics: if non-empty, this is what the user typed
in the day card's label field. Renderers prefer it over the auto-
classifier ("Practice / Qual / Playoff" depending on block contents).

A day with zero blocks is legal but useless — renderers may skip it.

---

## 4. Block tier system

Every block has an immutable `tier` derived from its `type`. The tier
governs nesting: **a child must have a strictly higher tier number than
its parent.** That's the entire rule.

| Tier | Members                                                   | Can contain      |
|------|-----------------------------------------------------------|------------------|
| 1    | Day (implicit — not a Block, but the container of blocks) | Tier 2 + Tier 3  |
| 2    | `practice`, `qualification`, `playoff`                    | Tier 3           |
| 3    | `break`, `awards`, `alliance_selection`, `ceremony`       | nothing          |

Practical consequence: you can put an awards ceremony inside a playoff
window (tier 2 parent, tier 3 child), but you can't put a qualification
block inside a playoff (both tier 2). Tier-3 blocks are leaves.

Children live in the parent's `breaks: []` array regardless of their
own type. The name is historical (V1 only had breaks). The array is
heterogeneous in V2 — it can hold any tier-3 block. **Do not filter
this array by `type === 'break'`** — that loses awards/ceremony/
alliance entries. (This filter mistake has been the source of multiple
recent bugs; see V1_RETIREMENT.md item R-12.)

---

## 5. Block types

### 5.1 `qualification` (tier 2)

```jsonc
{
  "type": "qualification",
  "start": "09:00", "end": "17:00",     // canonical 24h HH:MM, see §6
  "cycleTime": 9,                        // minutes; this block's start-of-block ct
  "changes": [                           // mid-block cycle changes (block-local indices)
    { "afterMatch": 5,  "cycleTime": 10 },
    { "afterMatch": 20, "cycleTime": 8  }
  ],
  "breaks": [ /* tier-3 children */ ]   // nested ceremonies / awards / breaks / alliance
}
```

`changes[].afterMatch` is **block-local** — "after the 5th match of
this qual block." The materializer translates to a global match index
when emitting matches; consumers of the V2 model don't need to.

### 5.2 `practice` (tier 2)

Same as `qualification` plus two practice-specific fields:

```jsonc
{
  "type": "practice",
  // ...all qualification fields...
  "guaranteed": 3,    // matches per team that must fit (planner uses this to size the block)
  "maxFiller":  99    // additional matches per team allowed if time remains
}
```

### 5.3 `playoff` (tier 2)

A time-window with reserved fields for future match generation:

```jsonc
{
  "type": "playoff",
  "start": "17:30", "end": "20:30",
  "playoffFormat":   "double_elim",    // double_elim | round_robin | other-from-V2_PLAYOFF_FORMATS
  "playoffAlliances": 8,               // 2..16
  "cycleTime":       11,                // playoff match cadence (typically slower than quals)
  "changes":         [],                // mid-block cycle changes; same shape as qual

  // Reserved for the playoff scheduling workstream. Empty arrays today;
  // populated when playoff match generation lands. Keeping them in the
  // model now means we never need a v3 bump just to add playoffs.
  "alliances": [],                      // alliance roster from alliance_selection
  "matches":   [],                      // generated playoff matches with bracket position

  "breaks": [ /* tier-3 children: awards, breaks, ceremonies */ ]
}
```

Field semantics:

- **`cycleTime`** — start-of-block cadence for playoff matches. A
  separate field from qual cycle time because playoff matches are
  typically slower-paced (longer between-match resets). Required
  even pre-match-generation; used by the time-budget calculator
  to estimate whether the playoff window is sized appropriately.
- **`changes[]`** — same shape as `qualification.changes[]`; same
  per-block-local `afterMatch` semantics described in §7.
- **`alliances[]`** *(reserved)* — populated by alliance selection.
  Each entry: `{ number, captain, picks: [team, team, …] }`. Alliance
  number is 1-indexed (1 = top seed).
- **`matches[]`** *(reserved)* — populated by playoff scheduler. Each
  entry includes `matchNum`, bracket label (e.g. `"QF1"`, `"SF2"`,
  `"F1"`), participating alliance numbers, projected start time, and
  the conditional dependency that determined the alliances (e.g.
  "winner of QF1 vs winner of QF2"). Exact shape will be settled
  when the playoff scheduling workstream begins; the field is
  reserved now to avoid a wire format break.
- **`breaks[]`** — tier-3 children that share the playoff window.
  Awards ceremonies between rounds, lunch within a long playoff
  block, etc. Same heterogeneous-array semantics as elsewhere.

The legacy field name `playoffTeams` is read-tolerated for old saved
data and translated to `playoffAlliances` on first load. Writers emit
`playoffAlliances` only.

**Today's behavior:** playoff match generation is deferred. The
materializer reserves the time window but emits no match entries.
`alliances[]` and `matches[]` stay empty. The agenda renderer shows
the window with format + alliance count.

**Forward path:** when alliance selection is materialized (the
`alliance_selection` block produces alliance picks), those flow into
`playoff.alliances[]`. Then the playoff scheduler walks the chosen
format and emits `playoff.matches[]`. The renderer transitions from
showing a generic playoff window to showing individual playoff
matches with bracket labels.

### 5.4 `break` (tier 3)

Generic time reservation:

```jsonc
{
  "type": "break",
  "start": "12:00", "end": "13:00",
  "label": "Lunch",                    // optional; auto-derived from breakKind when empty
  "breakKind": "lunch"                  // "lunch" | "break" | "other"
}
```

`breakKind: "other"` is the user-typed-name escape hatch. The label is
required to be non-empty when kind is "other"; the editor enforces.

### 5.5 `ceremony` (tier 3)

Opening or closing ceremony:

```jsonc
{
  "type": "ceremony",
  "start": "08:30", "end": "09:00",
  "label": "Opening ceremony",         // optional; defaults from ceremonyKind
  "ceremonyKind": "opening"             // "opening" | "closing"
}
```

By convention, the first ceremony of a day defaults to opening; any
subsequent one defaults to closing. The user can override.

### 5.6 `alliance_selection` (tier 3)

```jsonc
{
  "type": "alliance_selection",
  "start": "17:00", "end": "17:30",
  "label": "Alliance selection"        // optional; defaults to type label
}
```

Time-only. No body content beyond the label.

### 5.7 `awards` (tier 3)

```jsonc
{
  "type": "awards",
  "start": "20:30", "end": "21:00",
  "label": "Awards ceremony"
}
```

Same shape as alliance_selection.

---

## 6. Time semantics

- **Canonical wire format:** 24-hour `HH:MM` strings, zero-padded
  (`"09:00"`, `"17:30"`). All persisted day_config objects use this.
- **Display:** the editor and viewer respect a per-user 12h/24h
  preference (localStorage `frcUse24h`). Display formatters convert
  on the fly; the canonical 24h value is always retained in
  `data-value-24h` attributes on the inputs.
- **Date format:** ISO `yyyy-mm-dd` for `Day.date`, or `""`/`null`
  when unset.
- **Validation:** `end > start` (strict). End times that wrap past
  midnight are not yet supported.

---

## 7. Cycle changes

`cycleTime` exists at two levels:

1. `dayConfig.cycleTime` — the event default. Used when a block
   omits its own.
2. `block.cycleTime` — the **start-of-block** cycle time for that
   particular schedulable block. Distinct per-block, so a practice
   block at 11 min/cycle and a qual block at 9 min/cycle live happily
   on the same day.

`block.changes[]` defines mid-block cycle changes:

```jsonc
{ "afterMatch": 4, "cycleTime": 8 }
```

`afterMatch` is **1-based and local to this block**.

### Semantic: the change applies to the interval *after* match N

A change `{ afterMatch: 4, cycleTime: 8 }` means: **the gap from
match 4's start to match 5's start is 8 minutes** (and so on for
matches 5, 6, … until the next change).

Worked example with `block.cycleTime = 9` and `changes: [{ afterMatch: 4, cycleTime: 8 }]`:

| Match | Starts at         | Cycle time used for *next* gap |
|-------|-------------------|---------------------------------|
| 1     | block.start       | 9 min                           |
| 2     | start + 9 min     | 9 min                           |
| 3     | start + 18 min    | 9 min                           |
| 4     | start + 27 min    | **8 min** ← change applies here |
| 5     | start + 35 min    | 8 min                           |
| 6     | start + 43 min    | 8 min                           |

Equivalent restatement: the cycle time governs the **departure
interval** for matches *strictly after* match N. Match N itself starts
at whatever time the prior cycle time put it at; only the gap leading
to N+1 (and beyond, until the next change) uses the new value.

This matches operator intuition — "after match 4 we're going faster"
naturally means match 5 comes up sooner than match 4 + 9 min would
have predicted.

### Global offset translation

When materializing to global match indices for the scheduler, the
materializer adds the running global match offset to each block's
local `afterMatch`. A block-local "after match 4" on day 2 (with 60
day-1 matches preceding) becomes global "after match 64."

---

## 8. Validation rules

Enforced by the editor (`_v2validateAll()` and friends):

- All times present and well-formed `HH:MM`.
- Each block: `end > start`.
- Each block contained in its day's effective window — no times
  outside `min(blocks.start) .. max(blocks.end)` (the day window is
  derived, not specified separately).
- Tier rule: children's tier > parent's tier.
- Each `changes[].afterMatch >= 1`.
- Each `changes[].cycleTime > 0`.
- Playoff: `playoffAlliances` in `[2, 16]`.
- Practice: `guaranteed >= 1`.
- Ceremony: `ceremonyKind` in `["opening", "closing"]`.
- Break: `breakKind` in `["lunch", "break", "other"]`; if "other", `label` non-empty.

Invalid blocks render with a red border and prevent generation.

---

## 9. Persistence

### 9.1 In the database

`day_config` is stored as a JSON column (PostgreSQL `JSON` type) on
three tables (see [DB_V2_MIGRATION.md](DB_V2_MIGRATION.md)):

- `abstract_schedules.day_config`
- `assigned_schedules.day_config`
- `assigned_schedule_history.day_config`

Post-migration, all three columns hold native V2 shape. Pre-migration
rows go through the legacy migrator on read.

### 9.2 In the URL

V2 carries the day_config tree in URL parameters. Two formats are
supported, both lossless, both selectable per emit:

#### 9.2.1 Human-readable (default)

A flat namespace of typed params, one per logical leaf. The day
ordinal is in the param name (`d1`, `d2`, …) and block ordinal
inside that day (`b1`, `b2`, …). Children of a block use `c1`, `c2`.

```
?dcv=2
&n=12&mpt=23&cd=3&ct=8&bb=5
&d1=2026-04-04|Day%201
&d1b1=qual|09:00|17:00|9
&d1b1cc=4:8;15:10
&d1b1c1=ceremony|08:30|09:00|Opening%20ceremony|opening
&d1b1c2=break|12:00|13:00|Lunch|lunch
&d1b2=playoff|17:30|20:30|double_elim|8|11
&d1b2c1=awards|20:30|21:00|Awards
```

Field separators within a value: `|` (pipe). Sub-list separators:
`,` (top level), `;` (within a list value). Names containing pipes
or commas get URL-encoded but the structural separator chars stay
literal in the param so the URL is scannable by eye.

Per-param shapes:

| Param           | Shape                                                      |
|-----------------|------------------------------------------------------------|
| `dcv`           | `2` — wire version, always present in V2 URLs              |
| `dN`            | `<date>\|<label>` (date or label may be empty)              |
| `dNbM`          | type-specific, see below                                   |
| `dNbMcc`        | `afterMatch:cycleTime;afterMatch:cycleTime;…`              |
| `dNbMcK`        | child K of block M, type-specific                          |

Block param shapes by type:

| Type                 | `dNbM=` shape                                          |
|----------------------|--------------------------------------------------------|
| `qualification`      | `qual\|<start>\|<end>\|<cycleTime>`                      |
| `practice`           | `practice\|<start>\|<end>\|<cycleTime>\|<guaranteed>\|<maxFiller>` |
| `playoff`            | `playoff\|<start>\|<end>\|<format>\|<alliances>\|<cycleTime>` |
| `break`              | `break\|<start>\|<end>\|<label>\|<breakKind>`            |
| `ceremony`           | `ceremony\|<start>\|<end>\|<label>\|<ceremonyKind>`      |
| `awards`             | `awards\|<start>\|<end>\|<label>`                       |
| `alliance_selection` | `alliance\|<start>\|<end>\|<label>` *(short form so it fits)* |

Children (`dNbMcK`) use the same per-type shapes but only the
tier-3 types appear there.

#### 9.2.2 Compact (optional)

When the human-readable URL would exceed 2000 characters (e.g. a
multi-day event with many blocks), the emitter falls back to a single
encoded param:

```
?dcv=2&dc=eyJkYXlDb25maWdWZXJzaW9uIjoyLC...
```

`dc=` carries `base64(JSON.stringify(day_config))`. The parser
preference order: `dc=` first (if present, ignore the human-readable
params); otherwise reconstruct from `dN`/`dNbM`/etc.

The user can force compact mode by appending `&dcc=1` to a share URL
(useful for length-sensitive contexts like SMS); the editor's share
button picks human-readable by default.

#### 9.2.3 Legacy (V1) parameters

The V1 wire format (`d1=HH:MM-HH:MM`, `d1b=…`, `cc=…`, `pday=`, …) is
still parsed for backward compatibility with shared links produced
before the V2 URL switch. The parser checks for `dcv=` first; if
absent and any V1-only params are present, it runs the legacy
path through the migrator.

**Retention:** the V1 parser stays indefinitely while the back-compat
load is small (essentially zero — only one V1 URL has been published
publicly). It can be deleted in phase 5 without notice.

### 9.3 In memory (the editor)

V2 lives in:

- The DOM under `#v2DaysContainer` (rendered by `renderDayConfigV2`).
- Reconstructed on demand via `collectDayConfigV2()`.
- Side-channel state on `window._frcPreservedDayDates` (date
  round-tripping) and similar single-purpose holders.

There is no persistent in-memory V2 object; the DOM is the truth.

---

## 10. Schedule materialization

The scheduler converts V2 day_config into:

- A flat `entries[]` array per day, where each entry is one of:
  - `{ type: 'match', num, red[], blue[], startMin, endMin }`
  - `{ type: 'break', name, start, end, subtype, breakKind, ceremonyKind }`
  - `{ type: 'cycle-change', start, time }`
- A `playoffBlocks[]` side-channel (windows only — no matches yet).

Materialization rules:

1. Each day's `blocks[]` is walked in chronological order.
2. Schedulable blocks (`practice`, `qualification`) own a slice of
   the `matches[]` queue. Cursor walks through the block applying
   `cycleTime` and `changes[]` (with global offset translation),
   inserting nested-children's blocks at their times.
3. Tier-3 top-level blocks emit single `break` entries with the
   block's subtype/kind preserved.
4. Playoff windows emit no entries; they go on `playoffBlocks[]` for
   the agenda renderer.

The materializer is the only place that needs to understand tier
hierarchy. Downstream (the renderers, the URL builder, the save path)
sees a flat per-day entry list plus the playoff side-channel.

---

## 11. Adding a new block type

1. Add an entry to `V2_BLOCK_TYPES` in `static/index.html` with its
   tier number and rendering metadata.
2. Add a default-seed factory case in `_v2defaultNestedChild` (or
   the top-level equivalent, `openV2BlockPicker`).
3. Add a read branch in `_v2readBlockFromDom` for any type-specific
   fields beyond `start/end/label`.
4. Add a render branch in `buildV2Block` for the body section.
5. Add a render branch in the agenda renderers
   (`renderAgendaBlocks` and `renderScheduleBars`) for the segment
   color and width-tiered label.
6. Add a materialization branch in the scheduler if the block emits
   anything other than a single `break` entry.

The tier system handles nesting permissions automatically.

---

## 12. Versioning

`dayConfigVersion` is an integer, currently `2`. If we ever need to
break the V2 wire format (e.g. add midnight-wrapping times, change
cycle-change semantics, etc.), bump to `3` and add a migrator. V2 →
V3 should be lossless; V1 → V2 is **not** lossless (V1 can't represent
type info).
