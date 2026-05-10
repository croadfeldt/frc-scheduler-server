// Regression test for cycle-time-change application semantics.
//
// V2_SPEC §7 specifies: a change with afterMatch=N means "the gap
// from match N's start to match N+1's start uses the new cycleTime."
// Equivalently: match N's own slot is the first to use the new ct.
//
// This was off-by-one in five sites in static/index.html and one in
// static/view.html — the new ct was being applied starting at gap
// (N+1)→(N+2) instead of N→(N+1). All six sites now use >= comparisons
// (or, in the capacity-counter case in calcMaxMatches, the equivalent
// <= matchCount + 1 idiom).
//
// Run via: node tests/test_cycle_change_walker.js
//
// Two-pronged check, matching the pattern of test_field_three_up.js:
//   1. Substring guards on the production HTML/JS source — the new
//      ct must be applied at >= boundaries, not >.
//   2. A faithful re-implementation of the walker that produces the
//      exact match-start times from V2_SPEC §7's worked example.

'use strict';

const fs   = require('fs');
const path = require('path');

const indexHtml = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'index.html'),
  'utf8'
);
const viewHtml = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'view.html'),
  'utf8'
);

let failures = 0;
function check(label, ok, detail) {
  if (ok) {
    console.log('  ✓ ' + label);
  } else {
    console.log('  ✗ ' + label + (detail ? ': ' + detail : ''));
    failures += 1;
  }
}

// ── 1. Substring guards on production source ──────────────────────────
//
// Each guard pins the >= comparison at one of the six application
// sites. If any of these fail, someone reverted the off-by-one fix
// and the cycle-change semantic regressed.

console.log('Source guards — V2_SPEC §7 cycle-change semantic:');

// view.html — display walker (the user-visible regression site).
check(
  'view.html display walker uses (matchIdx + 1) >= c.afterMatch',
  /\(matchIdx \+ 1\)\s*>=\s*c\.afterMatch/.test(viewHtml),
  'expected `(matchIdx + 1) >= c.afterMatch`'
);

// index.html — practice walker.
check(
  'index.html practice walker uses idx + 1 >= cc.afterMatch',
  /idx \+ 1\s*>=\s*cc\.afterMatch/.test(indexHtml),
  'expected `idx + 1 >= cc.afterMatch` in _pracEffectiveCt'
);

// index.html — qual-day walker (dayCt computation).
const dayCtMatches = (indexHtml.match(/matchIdx \+ 1\s*>=\s*cc\.afterMatch/g) || []).length;
check(
  'index.html qual walker uses matchIdx + 1 >= cc.afterMatch (dayCt + nextDayCt)',
  dayCtMatches >= 2,
  `expected ≥2 occurrences of \`matchIdx + 1 >= cc.afterMatch\` (dayCt + nextDayCt branches), got ${dayCtMatches}`
);

// index.html — prevDayCt branch (different shape: matchIdx is post-
// increment, so it's already 1-based).
check(
  'index.html prevDayCt uses matchIdx >= cc.afterMatch',
  /matchIdx\s*>=\s*cc\.afterMatch/.test(indexHtml),
  'expected `matchIdx >= cc.afterMatch` in prevDayCt branch'
);

// index.html — calcMaxMatches capacity counter.
check(
  'calcMaxMatches uses afterMatch <= matchCount + 1',
  /changesAhead\[0\]\.afterMatch\s*<=\s*matchCount\s*\+\s*1/.test(indexHtml),
  'expected `changesAhead[0].afterMatch <= matchCount + 1`'
);

// Negative guards — make sure none of the off-by-one comparisons
// crept back in. Comments referencing "was >" and "Was <=" are
// allowed (they document the bug for future readers); we only
// reject live code patterns.
function stripBlockComments(src) {
  // Strip /* ... */ block comments. Crude but adequate — the cycle-
  // change explanatory comments are block-style so they get stripped
  // and won't false-positive against the negative guards. Inline
  // // comments are left in place; they don't contain the patterns
  // we're guarding against.
  return src.replace(/\/\*[\s\S]*?\*\//g, '');
}
const indexCode = stripBlockComments(indexHtml);
const viewCode  = stripBlockComments(viewHtml);

check(
  'no live `> cc.afterMatch` in index.html (off-by-one regression check)',
  !/[^=]>\s*cc\.afterMatch/.test(indexCode),
  'a `> cc.afterMatch` slipped back in'
);
check(
  'no live `> c.afterMatch` in view.html',
  !/[^=]>\s*c\.afterMatch/.test(viewCode),
  'a `> c.afterMatch` slipped back in'
);
check(
  'no live `afterMatch <= matchCount` (without + 1) in index.html',
  !/afterMatch\s*<=\s*matchCount\s*[)\s]/.test(indexCode.replace(/matchCount\s*\+\s*1/g, 'matchCountPlus1')),
  'a `afterMatch <= matchCount` (off-by-one) is still in calcMaxMatches'
);

// ── 2. Faithful walker re-implementation against V2_SPEC §7 ───────────
//
// Spec example (from docs/V2_SPEC.md §7):
//   block.cycleTime = 9, changes = [{afterMatch: 4, cycleTime: 8}]
//   Match 1 → start + 0 min, slot uses 9
//   Match 2 → start + 9 min, slot uses 9
//   Match 3 → start + 18 min, slot uses 9
//   Match 4 → start + 27 min, slot uses 8 ← change applies here
//   Match 5 → start + 35 min, slot uses 8
//   Match 6 → start + 43 min, slot uses 8
//
// This re-implementation is identical in shape to the production walker
// (post-fix). If it produces the spec's expected times, the
// production walker's logic is correct.

function walk(startMin, blockCycleTime, changes, count) {
  // Mirrors the post-fix view.html walker (no breaks, no buffer — we're
  // testing cycle-change application in isolation).
  const out = [];
  let cursor = startMin;
  for (let matchIdx = 0; matchIdx < count; matchIdx++) {
    let ct = blockCycleTime;
    changes.forEach(c => {
      if (c.isStart && c.cycleTime) ct = c.cycleTime;
      else if (!c.isStart && c.afterMatch != null && (matchIdx + 1) >= c.afterMatch && c.cycleTime) {
        ct = c.cycleTime;
      }
    });
    out.push({ matchNum: matchIdx + 1, startMin: cursor, ctUsed: ct });
    cursor += ct;
  }
  return out;
}

console.log('\nWalker semantics — V2_SPEC §7 worked example:');

// The spec example in offset form (start at 0).
const spec = walk(
  0,
  9,
  [{ isStart: false, afterMatch: 4, cycleTime: 8 }],
  6,
);

const expected = [
  { matchNum: 1, startMin:  0, ctUsed: 9 },
  { matchNum: 2, startMin:  9, ctUsed: 9 },
  { matchNum: 3, startMin: 18, ctUsed: 9 },
  { matchNum: 4, startMin: 27, ctUsed: 8 }, // ← change applies HERE
  { matchNum: 5, startMin: 35, ctUsed: 8 },
  { matchNum: 6, startMin: 43, ctUsed: 8 },
];

for (let i = 0; i < expected.length; i++) {
  const e = expected[i], g = spec[i];
  check(
    `match ${e.matchNum}: start=${e.startMin}, ct=${e.ctUsed}`,
    g.startMin === e.startMin && g.ctUsed === e.ctUsed,
    `got start=${g.startMin}, ct=${g.ctUsed}`
  );
}

// Off-by-one anti-test: with the OLD buggy comparison, match 4's slot
// would still use ct=9, pushing match 5 to start at 36 instead of 35.
// We re-implement the buggy walker here to confirm we're really
// distinguishing the two semantics — not just both producing the
// right answer.

function walkBuggy(startMin, blockCycleTime, changes, count) {
  const out = [];
  let cursor = startMin;
  for (let matchIdx = 0; matchIdx < count; matchIdx++) {
    let ct = blockCycleTime;
    changes.forEach(c => {
      if (c.isStart && c.cycleTime) ct = c.cycleTime;
      else if (!c.isStart && c.afterMatch != null && (matchIdx + 1) > c.afterMatch && c.cycleTime) {
        ct = c.cycleTime;  // BUGGY: > instead of >=
      }
    });
    out.push({ matchNum: matchIdx + 1, startMin: cursor, ctUsed: ct });
    cursor += ct;
  }
  return out;
}

const buggy = walkBuggy(
  0,
  9,
  [{ isStart: false, afterMatch: 4, cycleTime: 8 }],
  6,
);
check(
  'buggy walker (>) produces match 4 with ct=9 (off-by-one)',
  buggy[3].ctUsed === 9 && buggy[3].startMin === 27 && buggy[4].startMin === 36,
  `expected the buggy walker to put match 5 at 36; got match 4 ct=${buggy[3].ctUsed}, match 5 start=${buggy[4].startMin}`
);
check(
  'fix actually changes behavior vs buggy — match 5 starts 1 min earlier',
  buggy[4].startMin - spec[4].startMin === 1,
  `spec walker puts match 5 at ${spec[4].startMin}, buggy at ${buggy[4].startMin}, diff should be 1`
);

// ── 3. Capacity-counter semantics ────────────────────────────────────
//
// calcMaxMatches's loop is a budget consumer, not a placer. With the
// spec example and a 60-minute budget the post-fix walker should fit
// exactly the same matches that walk() produces inside that budget.

function capacityCount(totalMinutes, blockCycleTime, changes) {
  // Mirrors the post-fix calcMaxMatches loop.
  let remaining = totalMinutes;
  let curCt     = blockCycleTime;
  const ahead   = changes.slice().sort((a, b) => (a.afterMatch || 0) - (b.afterMatch || 0));
  let matchCount = 0;
  while (remaining >= curCt) {
    remaining  -= curCt;
    matchCount += 1;
    while (ahead.length && ahead[0].afterMatch <= matchCount + 1) {
      curCt = ahead.shift().cycleTime || curCt;
    }
  }
  return matchCount;
}

console.log('\nCapacity counter — same scenario, 60-min budget:');

// Spec scenario in 60 min: m1..m3 at 9 min each = 27 min consumed,
// then m4..m7 at 8 min each = 32 min, total 59 min. Match 8 would
// need another 8 min and we only have 1 left. So 7 matches fit.
const fits = capacityCount(60, 9, [{ afterMatch: 4, cycleTime: 8 }]);
check(
  'capacity = 7 matches in 60-min budget with afterMatch=4 ct→8',
  fits === 7,
  `expected 7, got ${fits}`
);

// Flat 9-min cycle: 60 / 9 = 6.67, so 6 matches fit (6×9=54 used,
// remaining 6 < 9 so no 7th).
const baseline = capacityCount(60, 9, []);
check(
  'capacity = 6 matches in 60-min budget at flat 9-min cycle',
  baseline === 6,
  `expected 6, got ${baseline}`
);

// Anti-test: with the OLD buggy `<= matchCount` comparison, in the
// afterMatch=4 scenario the change would fire one iter later, so the
// pattern would be m1..m4 at 9 (36 min consumed), then m5..m7 at 8
// (24 min), total 60. mc=7. Same as the fixed version in this
// particular case — the off-by-one nets out at the budget boundary.
// So this counter case can't distinguish the two in capacity totals.
// The walker tests above are the meaningful semantic guard; this
// section just pins the post-fix counter doesn't drift.

// ── Done ──────────────────────────────────────────────────────────────

console.log('');
if (failures > 0) {
  console.log(failures + ' failure(s).');
  process.exit(1);
}
console.log('All cycle-change walker tests passed.');
