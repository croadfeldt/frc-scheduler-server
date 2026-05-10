# Schedule Comparison + Named History — Design Proposal

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Document type:** Specification / design proposal
**Status:** Proposal — paused. Two related capabilities surfaced during the auth/lifecycle work that aren't yet implemented. Captures decisions to make deliberately when work resumes after the live event.
**Companion docs:**
- `workstreams/schedule-lifecycle.md` — schedule states, history table, fork model
- `workstreams/rbac.md` — role-based access proposal

---

## What this is

Two related features:

1. **Schedule comparison** — show what's different between two schedules, or between a schedule and one of its history snapshots. "What changed since I last looked at this?"
2. **Named history snapshots** — let users tag history rows with human-readable labels ("pre-tournament backup", "after Alice's day-2 fixes") so they can find specific versions later.

Both are quality-of-life features that compound: comparison is more useful when you can pick two named snapshots to compare, and named history is more useful when you can quickly diff each snapshot against the current state.

## What this is not

- A real-time collaborative-editing diff viewer
- A merge tool for combining changes from two divergent schedules
- A continuous integration / pull-request workflow for schedules
- Support for binary fields (no PDF or image diffs)

---

## Why we need this

### Schedule comparison

The current "Saved Schedules" UI lists every schedule for an event. Without comparison, the only ways to understand differences are:

- **Mental diff.** Open one schedule, memorize the relevant fields, switch to another, compare from memory. Doesn't scale beyond 2-3 fields, doesn't catch subtle changes.
- **Side-by-side windows.** Open two browser tabs, eyeball them. Works for top-level differences but misses individual match changes.
- **Direct database query.** The slot_map JSON is queryable but requires SQL knowledge and no rendering.

For the use cases that come up:

- "I have last year's schedule and this year's. Are the qual rounds structured the same?"
- "I just restored from a history snapshot. What did I just change?"
- "Bob made changes overnight. What did he change?"
- "Which of my three saved versions has the lowest cooldown variance?"

…there's no good answer today. Users either trust the latest version or laboriously verify by hand.

### Named history snapshots

The history table records every mutation as a snapshot, but rows are identified only by timestamp + action type. After an editing session, a user might have:

```
2026-05-08 14:32  patch   alice@…
2026-05-08 14:35  patch   alice@…
2026-05-08 14:41  patch   alice@…
2026-05-08 14:55  patch   alice@…
2026-05-08 15:23  restore alice@…
2026-05-08 15:27  patch   alice@…
2026-05-08 15:34  mark-official alice@…
```

Six months later, "find the snapshot from before the morning of the regional" requires guessing from timestamps. A user-supplied label transforms this into:

```
2026-05-08 14:32  patch   alice@…  "Initial draft"
2026-05-08 14:55  patch   alice@…  "Pre-tournament backup"
2026-05-08 15:34  mark-official alice@…
```

Tags don't have to be on every row — just the ones the user wants to find later. Most rows stay anonymous.

---

## Design

### Part 1 — Schedule comparison

**Comparison scope.** Three useful modes:

- **A. Two schedules** (cross-schedule comparison). Pick schedule X and schedule Y; see what's different. Both can be drafts, both can be finalized; the comparison doesn't care about state.
- **B. Schedule vs history snapshot** (intra-schedule comparison). Pick schedule X and history row #3; see what's changed since that snapshot. Useful for "what did I just change?"
- **C. Two history snapshots** (timeline comparison). Pick history rows #2 and #5 within the same schedule; see the cumulative change between them.

All three reduce to "given two snapshots A and B, render a diff." The picker UX differs.

**What we diff.** A schedule has these comparable fields:

| Field | Type | Diff approach |
|---|---|---|
| `name` | string | Equality + textual diff if both present |
| `slot_map` | JSON of match assignments | Per-match diff (red/blue alliance changes) |
| `day_config` | JSON of days, blocks, cycle times | Structural diff (added/removed days, changed durations) |
| `practice_matches` | JSON | Per-match diff |
| `match_rows` | Table of resolved match assignments | Per-match diff (the "rendered" view of slot_map + assignments) |

Excluded from diff (operational, not content):
- `is_active`, `is_official`, `is_locked`
- `locked_at`, `locked_by_name`, `official_at`, `official_by_name`
- `created_at`, `updated_at`, `forked_from_id`
- Anything in `event` (handled at event level)

**Diff representation.**

For per-match changes, four categories:

- **Added** — match exists in B but not A (e.g., schedule was extended)
- **Removed** — match exists in A but not B
- **Changed** — match exists in both, but at least one alliance position differs
- **Unchanged** — match identical in both (typically the majority; collapsed in UI)

For day_config, a similar shape but on `(day_index, block_index)` keys.

**API endpoint.**

```
GET /api/schedules/{schedule_id}/diff?against=schedule:{other_id}
GET /api/schedules/{schedule_id}/diff?against=history:{history_id}
```

Returns a JSON document like:

```json
{
  "left":  { "schedule_id": 5,  "label": "Schedule 12:04 PM",       "snapshot_at": "2026-05-08T14:55:00Z" },
  "right": { "schedule_id": 5,  "label": "(history snapshot)",      "snapshot_at": "2026-05-08T14:32:00Z", "history_id": 17 },
  "summary": {
    "matches_added":     2,
    "matches_removed":   0,
    "matches_changed":   3,
    "matches_unchanged": 67,
    "day_config_changed": true,
    "name_changed":      false
  },
  "matches": [
    {
      "match_num": 12,
      "kind": "changed",
      "before": { "red": [2530, 1781, 4329], "blue": [3128, 2052, 2410] },
      "after":  { "red": [2530, 1781, 4329], "blue": [3128, 2410, 2052] },
      "alliance_positions_changed": ["blue2", "blue3"]
    },
    {
      "match_num": 73,
      "kind": "added",
      "after": { "red": [...], "blue": [...] }
    }
  ],
  "day_config": {
    "kind": "changed",
    "before_summary": "2 days, 14 blocks total",
    "after_summary":  "2 days, 16 blocks total",
    "details": [
      { "day": 1, "block": 5, "kind": "changed", "before": {"start": "13:00", "duration": 60}, "after": {"start": "13:00", "duration": 75} }
    ]
  }
}
```

The detail level lets the UI render either a high-level summary ("3 matches changed, day 1 block 5 duration extended") or a deep drill-in.

**Performance.**

A diff between two schedules with 70 matches each is `O(70)` per-match comparisons plus a structural day_config diff. Should run in under 50ms for typical sizes; cache on `(left_id, right_id, left_updated_at, right_updated_at)` if needed.

For history-snapshot diffs, the snapshot already lives in `assigned_schedule_history.slot_map` and `.day_config` — no additional joins needed.

**UI.**

A "Compare" button on each saved-schedule row, plus a "Compare to current" button on each history row. Clicking opens a comparison modal:

```
┌────────────────────────────────────────────────────────────────┐
│ Comparing                                                       │
│   Left:  Schedule 12:04 PM (current)                            │
│   Right: History snapshot from 14:32                            │
│                                                                  │
│ Summary                                                          │
│   3 matches changed • 2 added • 0 removed • 67 unchanged        │
│   Day config: changed (day 1 block 5 duration: 60 → 75 min)     │
│                                                                  │
│ Match-level changes (3)                                          │
│ ┌──────┬──────────────────┬──────────────────┐                  │
│ │ #12  │ Before           │ After            │                  │
│ │      │ R: 2530 1781 …   │ R: 2530 1781 …   │                  │
│ │      │ B: 3128 2052 …   │ B: 3128 2410 …   │ ← red text       │
│ ├──────┼──────────────────┼──────────────────┤                  │
│ │ ...  │ ...              │ ...              │                  │
│ └──────┴──────────────────┴──────────────────┘                  │
│                                                                  │
│ [Show unchanged matches (67)]                                    │
└────────────────────────────────────────────────────────────────┘
```

Color coding: red text for removed alliance positions, green for added, amber for moved within the match.

### Part 2 — Named history snapshots

**Data model.** One column added to `assigned_schedule_history`:

```sql
ALTER TABLE assigned_schedule_history
  ADD COLUMN label VARCHAR(128);

CREATE INDEX assigned_schedule_history_labeled_idx
  ON assigned_schedule_history(assigned_schedule_id, label)
  WHERE label IS NOT NULL;
```

The partial index supports fast "find labeled snapshots for this schedule" lookups. NULL on most rows; populated only when the user explicitly tags one.

**Naming flow.** Two paths to add a label:

1. **At save time.** When the user saves an edit, the modal offers an optional label field:

   ```
   ┌──────────────────────────────────────┐
   │ Save changes to "Schedule 12:04 PM"? │
   │                                       │
   │ Label this version (optional):       │
   │ [Pre-tournament backup_____________] │
   │                                       │
   │ [Cancel]                  [Save]     │
   └──────────────────────────────────────┘
   ```

   The label attaches to the *snapshot taken before* the edit. So "Pre-tournament backup" describes the pre-edit state, not the post-edit state. This matches the conventional reading.

2. **Retroactively from the history modal.** Clicking on any history row reveals a label edit affordance:

   ```
   2026-05-08 14:32  Edit  alice@…  "Initial draft"     [✎]
   2026-05-08 14:55  Edit  alice@…  (no label)         [+ label]
   2026-05-08 15:34  Mark Official  alice@…
   ```

   Clicking [+ label] or [✎] opens an inline editor.

**API endpoint.**

```
PATCH /api/assigned-schedules/{schedule_id}/history/{history_id}
Body: {label: "Pre-tournament backup"}
```

Returns the updated history row. Setting `label: null` clears the label.

Authorization: any authenticated user with edit access to the underlying schedule can label any history row. Labels are *annotations*, not authoritative claims — they don't change history.

**Constraints.**

- Max 128 characters
- Whitespace trimmed
- Empty string treated as NULL
- No uniqueness constraint — two snapshots can share a label
- Label is editable forever, regardless of schedule lock or official state (annotations are metadata, not content)

### Cross-cutting: history filtering and search

Once labels exist, the history modal benefits from filter/search. Three useful filters:

- **Show labeled only** — collapses the timeline to just the named milestones
- **Search by label substring** — finds "all snapshots with 'tournament' in the label"
- **Filter by action** — show only patches, only renames, etc. (already trivial; just a UI toggle)

For the comparison feature, the snapshot picker benefits even more. Without labels:

```
Pick a snapshot to compare to:
  • 2026-05-08 14:32 (patch by alice)
  • 2026-05-08 14:55 (patch by alice)
  • 2026-05-08 15:23 (restore by alice)
  ...
```

With labels:

```
Pick a snapshot to compare to:
  • Initial draft (May 8, 14:32)
  • Pre-tournament backup (May 8, 14:55)
  • [unlabeled snapshots…]
```

The labeled rows lift up; unlabeled stay collapsed but accessible.

---

## Implementation phases

### Phase D-1 — Compare API endpoint (no UI)

- Implement `GET /api/schedules/{id}/diff?against=...`
- Accepts both `schedule:N` and `history:N` against-targets
- Returns structured diff JSON per the schema above
- Tests against synthetic schedule pairs

Acceptance: API returns correct diff data for representative cases (identical schedules, all-changed schedules, partial changes, day_config changes).

### Phase D-2 — Compare UI

- "Compare to…" button on each saved-schedule row
- "Compare to current" button on each history row
- Comparison modal with summary + drill-in
- Color-coded match-level changes

Acceptance: a user can compare two schedules and identify all differences in under 30 seconds.

### Phase D-3 — Named history schema + API

- Migration adds `label` column + partial index
- PATCH endpoint for label updates
- Surface `label` field in the history list response

Acceptance: labels persist across requests and are visible in subsequent fetches.

### Phase D-4 — Named history UI

- Label field in save-edit modal (pre-edit snapshot is what gets labeled)
- Inline label editor in history modal
- Show labels in history list

Acceptance: user can save with a label, see it later, edit it later, clear it.

### Phase D-5 — Comparison + label integration

- Snapshot picker in compare modal surfaces labeled snapshots first
- History list filter "show labeled only"
- Search by label substring

Acceptance: a user with 50 history rows and 5 labeled rows can find a labeled comparison target in 2 clicks.

---

## Open design questions

**1. Should the diff include practice matches?** They're separate from qual matches but live in the same schedule. Including them adds detail; excluding them simplifies the common case (most users care about quals). Recommendation: include them in a separate section so the UI can collapse them by default.

**2. Should match-row-level changes (resolved alliance assignments) diff separately from slot_map?** They're computed from slot_map + the team list, so changes to slot_map will cascade. Recommendation: compute diff at the slot_map level; render as match assignments in the UI (the user thinks in matches, not slots).

**3. Is per-alliance-position diff useful?** "Match 12 blue 2 changed from team 2052 to team 2410" vs "Match 12 changed." Recommendation: yes — alliance-position granularity helps users spot which specific team moved, which is often the answer they want.

**4. Should labels support multi-label / tags?** "Pre-tournament" and "Backup" as separate tags vs one combined string. Recommendation: single string for v1; multi-tag is a v2 concern that may not earn its complexity.

**5. Should labels be visible to the public /view page?** No, by default. Internal annotations only. If event organizers ever want public release notes, that's a separate concept (event-level changelog, not schedule-level history labels).

**6. Should the diff show *who* changed each thing?** Currently the history table records the actor for the *whole* snapshot, not per-field. Saying "alice changed match 12 blue 2" requires per-field actor tracking, which is a separate workstream. Recommendation: don't try to resolve per-field actors; show the snapshot's actor as the responsible party for everything in that snapshot.

**7. Should comparisons be shareable via URL?** A `?diff=12,17` query param would let users link to a specific comparison. Worthwhile if the comparison feature gets heavy use; YAGNI otherwise. Recommendation: defer until requested.

---

## Decision points

Before implementation:

1. **Phase ordering: ship comparison API + UI before named history?** Or vice versa? Recommendation: comparison first. It's the larger benefit and works without labels (snapshots have timestamps and action types that are usable, just less ergonomic).

2. **Schema migration timing.** Adding `label` is cheap and idempotent — can ship in any phase. Recommendation: ship it in D-1 alongside the diff endpoint, even though the UI for it doesn't land until D-3.

3. **Coexistence with the lifecycle spec's structural-immutability rule.** Comparing a once-official schedule to a fork is the canonical use case. Recommendation: the diff endpoint is read-only and operates on any schedule pair regardless of official status.

4. **Backward compatibility for content_edit_count.** The fix shipped during the live-event work added `content_edit_count` to the listing endpoint. The frontend now uses it for the "edited" badge. Comparison and named history use the same history-table foundation; no further changes needed there.

5. **Do nothing during the change-freeze.** This whole document is a paused proposal. No code changes ship until the live event concludes and architectural direction is committed.

---

*Spec drafted alongside the auth/lifecycle work to capture features that surfaced during real use but aren't yet built. Implementation begins after the live-event change-freeze lifts. Comparison and named history are independent enough that either can ship first; the design here lets them compose cleanly when both are present.*
