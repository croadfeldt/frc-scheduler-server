// Tests for _findFieldThreeUp's scheduled fallback — the pre-event
// state machine that decides whether to surface on-field / on-deck /
// queueing rows when no Nexus or TBA actuals are available.
//
// Run via: node tests/test_field_three_up.js
//
// State machine spec:
//   T-15 min before next session → field + deck only (no queueing)
//   T-5  min before next session → field + deck + queueing
//   In session (now in match window OR prev match ended < 5 min ago)
//                                → field + deck + queueing, walk by clock
//   Otherwise (>15 min out, or after last match) → null
//
// "Session" boundary = gap > 5 minutes between consecutive matches.
// Live data (Nexus / TBA) overrides every gate — those branches return
// before the scheduled fallback runs and aren't tested here.

'use strict';

const fs   = require('fs');
const path = require('path');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'view.html'),
  'utf8'
);

// Extract just the scheduled-fallback portion of _findFieldThreeUp.
// We can't easily run the whole function (depends on STATE,
// _resolveMatchTimestamp, etc.) so we re-implement the logic here
// in isolation and then verify the live function matches our
// expected behavior via a substring fingerprint check.
//
// The real logic lives in static/view.html — this test:
//   1. Guards against regression by string-checking key invariants
//   2. Exercises a faithful re-implementation against scenario data
// If the substring guards fail, the production logic has drifted.

// ── Substring guards on the production source ─────────────────────
const guards = [
  // 15-min and 5-min thresholds use named constants
  /WINDOW_15_MS\s*=\s*15\s*\*\s*60\s*\*\s*1000/,
  /WINDOW_5_MS\s*=\s*5\s*\*\s*60\s*\*\s*1000/,
  // Session-gap detection
  /SESSION_GAP_MS\s*=\s*5\s*\*\s*60\s*\*\s*1000/,
  // Active-day filter on the entry's date
  /e3\.date\s*&&\s*e3\.date\s*!==\s*todayStr/,
  // The three branches of the state machine
  /timeToStart\s*>\s*WINDOW_15_MS/,
  /timeToStart\s*>\s*WINDOW_5_MS/,
  // In-session detection covers both "now in window" and "prev-end-near"
  /nowMs\s*>=\s*onField\.startMs/,
  /onField\.startMs\s*-\s*prev\.endMs/,
];

let passed = 0, failed = 0;
function check(label, ok) {
  if (ok) { passed++; }
  else    { failed++; console.error('FAIL:', label); }
}

guards.forEach((re, i) => {
  check('source guard #' + (i + 1) + ': ' + re.source.slice(0, 60),
        re.test(html));
});

// ── Re-implementation for scenario testing ────────────────────────
function findThreeUpScheduled(matches, nowMs) {
  const WINDOW_15_MS   = 15 * 60 * 1000;
  const WINDOW_5_MS    =  5 * 60 * 1000;
  const SESSION_GAP_MS =  5 * 60 * 1000;
  if (!matches.length) return null;
  const sorted = matches.slice().sort((a, b) => a.startMs - b.startMs);

  // Find onFieldIdx
  let onFieldIdx = -1;
  for (let i = 0; i < sorted.length; i++) {
    const m = sorted[i];
    if (nowMs >= m.startMs && nowMs < m.endMs) { onFieldIdx = i; break; }
    if (nowMs < m.startMs)                     { onFieldIdx = i; break; }
  }
  if (onFieldIdx < 0) return null;

  const onField  = sorted[onFieldIdx];
  const deckEnt  = sorted[onFieldIdx + 1] || null;
  const queueEnt = sorted[onFieldIdx + 2] || null;

  let inSession = false;
  if (nowMs >= onField.startMs) inSession = true;
  else if (onFieldIdx > 0) {
    const prev = sorted[onFieldIdx - 1];
    if ((onField.startMs - prev.endMs) <= SESSION_GAP_MS) inSession = true;
  }

  if (inSession) {
    return { field: onField, deck: deckEnt, queueing: queueEnt };
  }
  const timeToStart = onField.startMs - nowMs;
  if (timeToStart > WINDOW_15_MS) return null;
  if (timeToStart > WINDOW_5_MS)  return { field: onField, deck: deckEnt, queueing: null };
  return { field: onField, deck: deckEnt, queueing: queueEnt };
}

// Synthesize a session: 5 matches starting at `t0`, each `cycleMin`
// minutes long with a `gapMin` gap between (gap = 0 → back-to-back).
function session(t0, cycleMin, gapMin, count) {
  const out = [];
  let cur = t0;
  for (let i = 0; i < count; i++) {
    const start = cur;
    const end   = start + cycleMin * 60 * 1000;
    out.push({ id: 'Q' + (i + 1), startMs: start, endMs: end });
    cur = end + gapMin * 60 * 1000;
  }
  return out;
}

const T0 = Date.parse('2026-04-04T10:00:00Z');  // session start anchor
const matches = session(T0, 9, 0, 10);  // Q1..Q10, 9-min cycles, no gap

// ── Scenario tests ────────────────────────────────────────────────
function expect(label, got, want) {
  const eq = (a, b) => (a == null && b == null) ||
                       (a && b && a.id === b.id);
  const ok = (got == null && want == null)
          || (got && want && eq(got.field, want.field)
                          && eq(got.deck, want.deck)
                          && eq(got.queueing, want.queueing));
  check(label, ok);
}

// 1. Way before event (8 days out) → null
expect('8 days out → null',
       findThreeUpScheduled(matches, T0 - 8 * 24 * 60 * 60 * 1000),
       null);

// 2. 30 min before Q1 → null (>15 min)
expect('30 min before Q1 → null',
       findThreeUpScheduled(matches, T0 - 30 * 60 * 1000),
       null);

// 3. 15 min before Q1 → field=Q1, deck=Q2, no queueing
expect('15 min before → field+deck only',
       findThreeUpScheduled(matches, T0 - 15 * 60 * 1000),
       { field: matches[0], deck: matches[1], queueing: null });

// 4. 10 min before Q1 → still field+deck only
expect('10 min before → field+deck only',
       findThreeUpScheduled(matches, T0 - 10 * 60 * 1000),
       { field: matches[0], deck: matches[1], queueing: null });

// 5. 5 min before Q1 → all 3
expect('5 min before → all 3',
       findThreeUpScheduled(matches, T0 - 5 * 60 * 1000),
       { field: matches[0], deck: matches[1], queueing: matches[2] });

// 6. 1 min before Q1 → all 3
expect('1 min before → all 3',
       findThreeUpScheduled(matches, T0 - 60 * 1000),
       { field: matches[0], deck: matches[1], queueing: matches[2] });

// 7. Q1 in progress → field=Q1, deck=Q2, queueing=Q3
expect('Q1 in progress → all 3',
       findThreeUpScheduled(matches, T0 + 5 * 60 * 1000),
       { field: matches[0], deck: matches[1], queueing: matches[2] });

// 8. Q1 just ended (Q2 starts now) → in-session, all 3
expect('Q2 starts now → all 3',
       findThreeUpScheduled(matches, T0 + 9 * 60 * 1000),
       { field: matches[1], deck: matches[2], queueing: matches[3] });

// 9. Q5 in progress → field=Q5, deck=Q6, queueing=Q7
expect('Q5 mid-window → all 3 from Q5',
       findThreeUpScheduled(matches, T0 + (4 * 9 + 4) * 60 * 1000),
       { field: matches[4], deck: matches[5], queueing: matches[6] });

// 10. Past last match → null
expect('past last match → null',
       findThreeUpScheduled(matches, T0 + (10 * 9 + 10) * 60 * 1000),
       null);

// 11. Mid-session 4-min gap (lunch-light) → still in-session
const gapped = session(T0, 9, 4, 5);
expect('4-min gap inside session → in-session',
       findThreeUpScheduled(gapped, gapped[0].endMs + 60 * 1000),
       { field: gapped[1], deck: gapped[2], queueing: gapped[3] });

// 12. Mid-day 6-min gap → SESSION BOUNDARY (gap > 5 min)
const splitDay = session(T0, 9, 6, 5);
// During the gap, between Q1 end (T0+9m) and Q2 start (T0+15m).
// "Now" = T0+11m, so 4 min before Q2 start. < 5 → all 3.
expect('6-min gap, 4 min before next → all 3',
       findThreeUpScheduled(splitDay, T0 + 11 * 60 * 1000),
       { field: splitDay[1], deck: splitDay[2], queueing: splitDay[3] });

// 13. Mid-day 6-min gap, 5.5 min before next → field+deck only
expect('6-min gap, 5.5 min before next → field+deck only',
       findThreeUpScheduled(splitDay,
         splitDay[1].startMs - 5.5 * 60 * 1000),
       { field: splitDay[1], deck: splitDay[2], queueing: null });

// 14. Lunch break (60-min gap) — 30 min before resume → null
const withLunch = session(T0, 9, 60, 5);
expect('60-min lunch, 30 min before resume → null',
       findThreeUpScheduled(withLunch,
         withLunch[1].startMs - 30 * 60 * 1000),
       null);

// 15. Lunch break — 12 min before resume → field+deck only
expect('60-min lunch, 12 min before resume → field+deck only',
       findThreeUpScheduled(withLunch,
         withLunch[1].startMs - 12 * 60 * 1000),
       { field: withLunch[1], deck: withLunch[2], queueing: null });

// ── Summary ───────────────────────────────────────────────────────
console.log(`${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
