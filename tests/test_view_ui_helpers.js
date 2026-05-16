// SPDX-License-Identifier: GPL-3.0-or-later
//
// Test for the three view.html UI changes:
//   1. _formatCountdownTilde - coarse "in ~N min" formatter for 3-up
//   2. _fmtMSS               - per-row cycle-time formatter ("M:SS")
//   3. per-match cycle map   - the inline pre-pass that drives the
//                              cycle badges on each completed match row
//
// Extracts each function from static/view.html via regex, evaluates
// it in this Node context, and asserts behavior.

'use strict';

const fs   = require('fs');
const path = require('path');

const VIEW = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'view.html'),
  'utf8'
);

// ── helpers ──────────────────────────────────────────────────────

function extractFunction(name) {
  // Match `function name(...) {` then collect balanced braces.
  const re = new RegExp('function\\s+' + name + '\\s*\\(', 'g');
  const m = re.exec(VIEW);
  if (!m) throw new Error('Could not find function ' + name);
  let i = m.index;
  // Find first { after the signature
  const open = VIEW.indexOf('{', i);
  if (open < 0) throw new Error('No body brace for ' + name);
  let depth = 0;
  for (let p = open; p < VIEW.length; p++) {
    const c = VIEW[p];
    if (c === '{') depth++;
    else if (c === '}') {
      depth--;
      if (depth === 0) {
        return VIEW.slice(m.index, p + 1);
      }
    }
  }
  throw new Error('Unbalanced braces for ' + name);
}

let _failures = 0;
function check(name, cond, detail) {
  if (cond) console.log('  ✓ ' + name);
  else {
    _failures++;
    console.log('  ✗ ' + name + (detail ? ': ' + detail : ''));
  }
}

// ── _formatCountdownTilde ───────────────────────────────────────

console.log('_formatCountdownTilde:');
{
  const src = extractFunction('_formatCountdownTilde');
  // Strict mode + eval doesn't expose function declarations, so wrap
  // the source so it returns the constructed function.
  // eslint-disable-next-line no-new-func
  const _formatCountdownTilde = new Function(src + '\nreturn _formatCountdownTilde;')();
  check('past target shows "now"',
        _formatCountdownTilde(-100) === 'now');
  check('zero shows "now"',
        _formatCountdownTilde(0) === 'now');
  check('30s shows "in <1 min"',
        _formatCountdownTilde(30 * 1000) === 'in <1 min');
  check('59s shows "in <1 min"',
        _formatCountdownTilde(59 * 1000) === 'in <1 min');
  check('1 min exact shows ~1 min',
        _formatCountdownTilde(60 * 1000) === 'in ~1 min');
  check('5 min shows ~5 min',
        _formatCountdownTilde(5 * 60 * 1000) === 'in ~5 min');
  check('59 min shows ~59 min',
        _formatCountdownTilde(59 * 60 * 1000) === 'in ~59 min');
  check('1h exact shows "in 1h 00m"',
        _formatCountdownTilde(60 * 60 * 1000) === 'in 1h 00m');
  check('2h 30m shows "in 2h 30m"',
        _formatCountdownTilde(150 * 60 * 1000) === 'in 2h 30m');
  // Rounding behavior — 4 min 31 sec should be 5, not 4
  check('4:31 rounds to ~5 min',
        _formatCountdownTilde(271 * 1000) === 'in ~5 min',
        'got: ' + _formatCountdownTilde(271 * 1000));
  check('4:29 rounds to ~4 min',
        _formatCountdownTilde(269 * 1000) === 'in ~4 min',
        'got: ' + _formatCountdownTilde(269 * 1000));
}

// ── _fmtMSS ─────────────────────────────────────────────────────
//
// _fmtMSS is defined inside renderTable as an inner function. We
// extract its body and rewrap so it's callable in isolation.

console.log('\n_fmtMSS:');
{
  // Match inner function declaration
  const m = /function\s+_fmtMSS\s*\(min\)\s*\{([\s\S]*?)\n\s\s\}/.exec(VIEW);
  if (!m) throw new Error('Could not find _fmtMSS body');
  // eslint-disable-next-line no-new-func
  const _fmtMSS = new Function('min', m[1]);

  check('null → empty', _fmtMSS(null) === '');
  check('undefined → empty', _fmtMSS(undefined) === '');
  check('Infinity → empty', _fmtMSS(Infinity) === '');
  check('NaN → empty', _fmtMSS(NaN) === '');
  check('0 → "0:00"', _fmtMSS(0) === '0:00');
  check('1 → "1:00"', _fmtMSS(1) === '1:00');
  check('7.5 → "7:30"', _fmtMSS(7.5) === '7:30',
        'got: ' + _fmtMSS(7.5));
  check('0.85 → "0:51"', _fmtMSS(0.85) === '0:51',
        'got: ' + _fmtMSS(0.85));
  check('rounding: 0.999 → "1:00" (s=60 carries to m)',
        _fmtMSS(0.999) === '1:00',
        'got: ' + _fmtMSS(0.999));
  check('negative: -1.5 → "-1:30"', _fmtMSS(-1.5) === '-1:30',
        'got: ' + _fmtMSS(-1.5));
  check('negative small: -0.85 → "-0:51"', _fmtMSS(-0.85) === '-0:51',
        'got: ' + _fmtMSS(-0.85));
  // Padding: 0:05 not 0:5
  check('seconds zero-pad: 7.0833... → "7:05"',
        _fmtMSS(7 + 5/60) === '7:05',
        'got: ' + _fmtMSS(7 + 5/60));
}

// ── Per-match cycle pre-pass ────────────────────────────────────
//
// We test the algorithm in isolation by constructing fake
// STATE.computed + STATE.liveByMatch shapes and running a
// mini-version of the pre-pass loop. The actual loop in the
// renderer is closed over STATE, computed, _resolveMatchTimestamp.
// To test it cleanly, re-implement the same logic here from spec
// and verify it matches the documented behavior.

console.log('\nPer-match cycle map (algorithm equivalence):');
{
  // Inline copy of the algorithm — kept in lockstep with renderTable's
  // _buildPerMatchCycles. If renderTable's pre-pass changes, update
  // this and the corresponding test assertions.
  function buildPerMatchCycles(computed, liveByMatch, resolveTs) {
    const _perMatchCycles = {};
    let lastActualSec = null, lastSchedSec = null;
    let inScopeSum = 0, inScopeCount = 0;
    for (let ci = 0; ci < computed.length; ci++) {
      const ce = computed[ci];
      if (ce.type !== 'match' || ce.isPractice) continue;
      const clive = liveByMatch[ce.matchNum];
      if (!clive || !clive.actual_time) continue;
      const schedTs = resolveTs(ce);
      const schedSec = schedTs != null ? schedTs / 1000 : null;
      if (lastActualSec == null) {
        lastActualSec = clive.actual_time;
        lastSchedSec  = schedSec;
        continue;
      }
      const cycleMin = (clive.actual_time - lastActualSec) / 60;
      const schedGapMin = (lastSchedSec != null && schedSec != null)
        ? (schedSec - lastSchedSec) / 60 : null;
      const info = { cycleMin };
      if (cycleMin <= 0) info.isReplay = true;
      else if (schedGapMin != null && schedGapMin > 15) info.isBreak = true;
      else {
        inScopeSum += cycleMin;
        inScopeCount++;
        const mean = inScopeSum / inScopeCount;
        info.runningMeanMin = mean;
        info.deltaVsMeanMin = cycleMin - mean;
      }
      _perMatchCycles[ce.matchNum] = info;
      lastActualSec = clive.actual_time;
      lastSchedSec  = schedSec;
    }
    return _perMatchCycles;
  }

  // Scenario 1: three consecutive matches, all in scope
  const t0 = 1700000000;  // arbitrary epoch
  const computed1 = [
    { type: 'match', matchNum: 1, isPractice: false },
    { type: 'match', matchNum: 2, isPractice: false },
    { type: 'match', matchNum: 3, isPractice: false },
  ];
  const live1 = {
    1: { actual_time: t0 },
    2: { actual_time: t0 + 7 * 60 },
    3: { actual_time: t0 + 7 * 60 + 8 * 60 },
  };
  const resolveTs1 = e => (t0 + (e.matchNum - 1) * 7 * 60) * 1000;
  const r1 = buildPerMatchCycles(computed1, live1, resolveTs1);
  check('Match 1 (first) has no entry', !r1[1]);
  check('Match 2 cycle = 7 min',
        Math.abs(r1[2].cycleMin - 7) < 1e-6);
  check('Match 2 runningMean = 7 (first in scope)',
        Math.abs(r1[2].runningMeanMin - 7) < 1e-6);
  check('Match 2 delta = 0',
        Math.abs(r1[2].deltaVsMeanMin) < 1e-6);
  check('Match 3 cycle = 8 min',
        Math.abs(r1[3].cycleMin - 8) < 1e-6);
  check('Match 3 runningMean = 7.5 ((7+8)/2)',
        Math.abs(r1[3].runningMeanMin - 7.5) < 1e-6);
  check('Match 3 delta = +0.5',
        Math.abs(r1[3].deltaVsMeanMin - 0.5) < 1e-6);

  // Scenario 2: practice matches are skipped
  const computed2 = [
    { type: 'match', matchNum: 1, isPractice: true },
    { type: 'match', matchNum: 1, isPractice: false },  // P1 and Q1 same num
    { type: 'match', matchNum: 2, isPractice: false },
  ];
  const live2 = {
    1: { actual_time: t0 + 7 * 60 },
    2: { actual_time: t0 + 14 * 60 },
  };
  const r2 = buildPerMatchCycles(computed2, live2,
                                   e => (t0 + e.matchNum * 7 * 60) * 1000);
  // Practice match should not appear; Q1 is first-in-scope (no cycle);
  // Q2 has a cycle
  check('Practice match is not in result', !r2.hasOwnProperty('1') || Object.keys(r2).length === 1);
  check('Q2 cycle = 7 min after Q1',
        r2[2] && Math.abs(r2[2].cycleMin - 7) < 1e-6);

  // Scenario 3: replay (out-of-order actual_time)
  const computed3 = [
    { type: 'match', matchNum: 1, isPractice: false },
    { type: 'match', matchNum: 2, isPractice: false },
    { type: 'match', matchNum: 3, isPractice: false },
  ];
  const live3 = {
    1: { actual_time: t0 },
    2: { actual_time: t0 + 7 * 60 },
    3: { actual_time: t0 + 6 * 60 },   // replay, went back
  };
  const r3 = buildPerMatchCycles(computed3, live3,
                                   e => (t0 + (e.matchNum - 1) * 7 * 60) * 1000);
  check('Match 3 marked isReplay',
        r3[3] && r3[3].isReplay === true);
  check('Match 3 has no deltaVsMeanMin (replay)',
        r3[3] && r3[3].deltaVsMeanMin === undefined);

  // Scenario 4: break boundary (>15 min scheduled gap)
  const computed4 = [
    { type: 'match', matchNum: 1, isPractice: false },
    { type: 'match', matchNum: 2, isPractice: false },
    { type: 'match', matchNum: 3, isPractice: false },
  ];
  const live4 = {
    1: { actual_time: t0 },
    2: { actual_time: t0 + 7 * 60 },
    3: { actual_time: t0 + 7 * 60 + 30 * 60 },  // 30 min later
  };
  // Schedule shows 30-min planned gap between m2 and m3
  const resolveTs4 = e => {
    const offsets = { 1: 0, 2: 7, 3: 7 + 30 };
    return (t0 + offsets[e.matchNum] * 60) * 1000;
  };
  const r4 = buildPerMatchCycles(computed4, live4, resolveTs4);
  check('Match 3 marked isBreak (post-break-gap)',
        r4[3] && r4[3].isBreak === true);
  check('Match 3 has no deltaVsMeanMin (break)',
        r4[3] && r4[3].deltaVsMeanMin === undefined);

  // Scenario 5: matches without actual_time skipped
  const computed5 = [
    { type: 'match', matchNum: 1, isPractice: false },
    { type: 'match', matchNum: 2, isPractice: false },
    { type: 'match', matchNum: 3, isPractice: false },
  ];
  const live5 = {
    1: { actual_time: t0 },
    // Match 2 has no live entry
    3: { actual_time: t0 + 14 * 60 },
  };
  const r5 = buildPerMatchCycles(computed5, live5,
                                   e => (t0 + (e.matchNum - 1) * 7 * 60) * 1000);
  // Match 3's cycle is computed from match 1 (the previous one WITH
  // actual_time), so cycleMin = 14
  check('Match 3 cycle bridges over match 2 with no actual_time',
        r5[3] && Math.abs(r5[3].cycleMin - 14) < 1e-6,
        'got: ' + (r5[3] && r5[3].cycleMin));
}

// ── Day-divider match count algorithm ───────────────────────────

console.log('\nDay-divider match counts:');
{
  function countPerDivider(computed) {
    const counts = {};
    for (let di = 0; di < computed.length; di++) {
      if (computed[di].type !== 'day-divider') continue;
      let count = 0;
      for (let dj = di + 1; dj < computed.length; dj++) {
        if (computed[dj].type === 'day-divider') break;
        if (computed[dj].type === 'match') count++;
      }
      counts[di] = count;
    }
    return counts;
  }

  const ev = [
    { type: 'day-divider', label: 'Practice', dayNum: 0 },         // idx 0
    { type: 'match', matchNum: 1, isPractice: true },              // idx 1
    { type: 'match', matchNum: 2, isPractice: true },              // idx 2
    { type: 'break', name: 'Lunch' },                              // idx 3
    { type: 'match', matchNum: 3, isPractice: true },              // idx 4
    { type: 'day-divider', label: 'Day 2', dayNum: 1 },            // idx 5
    { type: 'match', matchNum: 1, isPractice: false },             // idx 6
    { type: 'match', matchNum: 2, isPractice: false },             // idx 7
    { type: 'break', name: 'Awards' },                             // idx 8
    { type: 'match', matchNum: 3, isPractice: false },             // idx 9
    { type: 'match', matchNum: 4, isPractice: false },             // idx 10
    { type: 'match', matchNum: 5, isPractice: false },             // idx 11
  ];
  const counts = countPerDivider(ev);
  check('Practice divider counts 3 matches', counts[0] === 3,
        'got: ' + counts[0]);
  check('Day 2 divider counts 5 matches', counts[5] === 5,
        'got: ' + counts[5]);
  check('Breaks not counted as matches',
        counts[0] === 3 && counts[5] === 5);

  // Empty day
  const ev2 = [
    { type: 'day-divider', label: 'Day 1', dayNum: 1 },
    { type: 'day-divider', label: 'Day 2', dayNum: 2 },
  ];
  const c2 = countPerDivider(ev2);
  check('Empty day counts 0', c2[0] === 0);

  // Trailing day with no further divider
  const ev3 = [
    { type: 'day-divider', label: 'Day 1', dayNum: 1 },
    { type: 'match', matchNum: 1, isPractice: false },
  ];
  const c3 = countPerDivider(ev3);
  check('Trailing day with one match counts 1', c3[0] === 1);
}

// ── Practice vs qual matchNum disambiguation ────────────────────
//
// Practice and qualification matches share numbering (P3 and Q3 both
// have matchNum=3). The schedule-table row pill logic must compare
// BOTH matchNum AND isPractice when deciding whether to apply the
// on-field / on-deck / queueing pill. Without this, marking "P3 on
// field" causes Q3 to inherit the pill — the bug visible when
// practice was running and tomorrow's Q3/Q4/Q5 incorrectly showed
// on-field/on-deck/queueing.
//
// We can't easily run renderTable in isolation; instead, source-
// substring-guard that the production code carries the isPractice
// comparison alongside the matchNum comparison for all three slots.

console.log('\nProduction source guards (P-vs-Q pill disambiguation):');
{
  // The full guards check both that the pill assignment references
  // an isPractice flag AND that each slot has its own *IsPractice
  // tracking variable declared.
  const guards = [
    // Three *IsPractice tracking variables exist
    /currentFieldIsPractice/,
    /upcomingFieldIsPractice/,
    /queueingFieldIsPractice/,
    // And the pill comparison uses isPractice as part of the predicate
    /currentFieldIsPractice\s*===\s*_entryIsPractice/,
    /upcomingFieldIsPractice\s*===\s*_entryIsPractice/,
    /queueingFieldIsPractice\s*===\s*_entryIsPractice/,
  ];
  guards.forEach((re, i) => {
    check('production source guard #' + (i + 1) + ': ' + re.source.slice(0, 50),
          re.test(VIEW),
          'did not match production source');
  });
}

// ── Completed-row layout mode (toolbar dropdown + persistence) ────
//
// The "Completed:" dropdown in the table-actions toolbar offers
// three layouts (A / B / C). Choice is persisted to localStorage
// under 'frc_view_completed_mode' and applied as data-completed-mode
// on <html>. Default is 'c' (compact). Verify the production
// source carries:
//   - the dropdown element + onchange handler
//   - the helper functions (get/set/init)
//   - the storage key + valid-set + default
//   - the three mode branches in the render emission
//   - CSS hooks for all three modes

console.log('\nCompleted-mode dropdown + mode-aware render:');
{
  const guards = [
    // Toolbar dropdown
    /<select\s+id="completedModeSel"\s+onchange="setCompletedMode\(this\.value\)"/,
    /<option value="a"/,
    /<option value="b"/,
    /<option value="c"/,
    // Helper plumbing
    /COMPLETED_MODE_KEY\s*=\s*['"]frc_view_completed_mode['"]/,
    /COMPLETED_MODE_DEFAULT\s*=\s*['"]c['"]/,
    /COMPLETED_MODE_VALID\s*=\s*\{\s*a:\s*1,\s*b:\s*1,\s*c:\s*1\s*\}/,
    /function getCompletedMode\s*\(/,
    /function setCompletedMode\s*\(\s*mode\s*\)/,
    /function initCompletedMode\s*\(/,
    // initCompletedMode called from boot
    /initCompletedMode\(\)/,
    // Mode is read from getCompletedMode() inside renderTable's
    // completed branch
    /var\s+_mode\s*=\s*getCompletedMode\(\);/,
    // Mode B has a dedicated branch with a team-list row and a
    // score+tags row. Source string check both pieces:
    /class="b-score-cell"/,
    /class="b-inline-stats"/,
    /class="col-blue alliance-teams-row blue"/,
    // Mode A/C emit the stats strip
    /class="completed-stat-strip"/,
    // CSS hooks per mode
    /html\[data-completed-mode="a"\]/,
    /tr\.completed\.mode-b/,
  ];
  guards.forEach((re, i) => {
    check('mode dropdown guard #' + (i + 1) + ': ' + re.source.slice(0, 50),
          re.test(VIEW),
          'did not match production source');
  });
}

// ── Margin computation (sanity) ─────────────────────────────────
//
// The completed-stats strip uses Math.abs(b - r) for margin. Verify
// the source emits the right tag class for each outcome (blue win,
// red win, tie). Substring-level — actual margin numbers are part
// of the runtime DOM.

console.log('\nMargin tag conditional emission:');
{
  // Blue win: winBlue branch attaches .margin-tag.blue
  check('source emits "margin-tag blue" for Blue wins',
        /margin-tag blue/.test(VIEW));
  check('source emits "margin-tag red" for Red wins',
        /margin-tag red/.test(VIEW));
  check('source emits "margin-tag tie" for ties',
        /margin-tag tie/.test(VIEW));
  // The formula is Math.abs(b - r) and gates on r != null && b != null
  check('margin uses Math.abs(b - r)',
        /Math\.abs\(b\s*-\s*r\)/.test(VIEW));
  check('margin gates on r != null && b != null',
        /r\s*!=\s*null\s*&&\s*b\s*!=\s*null/.test(VIEW));
}

// ── Compact view toggle plumbing ────────────────────────────────
//
// The compact-view toggle is a body-level CSS hook with two
// activation paths:
//   1. html[data-compact="1"] — opt-in via the toolbar button
//   2. @media (max-width: 750px) — automatic on phones
// Both should hit the same CSS rules. Test that the source carries
// the expected key behaviors:
//   - getCompactView / setCompactView / toggleCompactView functions
//   - localStorage key 'frc_view_compact'
//   - The "Compact" toolbar button exists
//   - initCompactView is called from boot
//   - CSS rules exist for both activation paths

console.log('\nCompact view toggle:');
{
  const guards = [
    /function\s+getCompactView\s*\(/,
    /function\s+setCompactView\s*\(/,
    /function\s+toggleCompactView\s*\(/,
    /function\s+initCompactView\s*\(/,
    /COMPACT_KEY\s*=\s*['"]frc_view_compact['"]/,
    /id="btnCompactToggle"/,
    /id="compactLabel"/,
    /initCompactView\(\);/,
    // CSS — both paths must hit the brand-header
    /@media\s*\(max-width:\s*750px\)[\s\S]{0,200}\.brand-header/,
    /html\[data-compact="1"\]\s*\.brand-header/,
    // Status section header hidden in both
    /@media\s*\(max-width:\s*750px\)\s*\{\s*\.status-section-header\s*\{\s*display:\s*none/,
    /html\[data-compact="1"\]\s*\.status-section-header\s*\{\s*display:\s*none/,
    // Empty team-next-section hidden in both
    /\.team-next-section\.empty\s*\{\s*display:\s*none/,
    // Delta-ok class added at the < 5min threshold
    /absMin\s*<\s*5\.0/,
    /box\.classList\.add\(\s*['"]delta-ok['"]/,
    // Field-view toggle relocator
    /_relocateFieldViewToggle/,
  ];
  guards.forEach((re, i) => {
    check('compact-view guard #' + (i + 1) + ': ' + re.source.slice(0, 60),
          re.test(VIEW),
          'did not match production source');
  });
}

// ── Split-layout plumbing ──────────────────────────────────────
//
// Source-substring guards for the split-view layout work. The
// renderers themselves can't be unit-tested without a DOM, so we
// verify the production source carries the expected plumbing:
//   - Toggle / state functions exist
//   - localStorage keys defined
//   - Tile-summary updater hooks into rerender()
//   - Wrap/unwrap reciprocity (every wrap has an unwrap path)
//   - renderFrcBanner extended to update brand-strip pill
//   - Toolbar button exists

console.log('\nSplit-layout plumbing:');
{
  const guards = [
    /function\s+getSplitLayout\s*\(/,
    /function\s+setSplitLayout\s*\(/,
    /function\s+toggleSplitLayout\s*\(/,
    /function\s+initSplitLayout\s*\(/,
    /function\s+toggleTile\s*\(/,
    /function\s+_wrapForSplitLayout\s*\(/,
    /function\s+_unwrapForSplitLayout\s*\(/,
    /function\s+_updateTileSummaries\s*\(/,
    /SPLIT_LAYOUT_KEY\s*=\s*['"]frc_view_split_layout['"]/,
    /TILE_STATE_KEY\s*=\s*['"]frc_view_tile_state['"]/,
    /id="btnSplitLayoutToggle"/,
    /id="splitLayoutLabel"/,
    /initSplitLayout\(\);/,
    // Tile summaries refresh after every rerender
    /_updateTileSummaries\(\)/,
    // renderFrcBanner extended for the pill
    /brandApprovalPill/,
    /pill\.classList\.add\(\s*pillClass\s*\)/,
    // CSS hooks for both layout activations
    /html\[data-layout="split"\]\s*\.split-shell/,
    /html\[data-layout="split"\]\s*#frcBanner/,
    /\.tile\[data-expanded="1"\]\s*\.tile-body/,
    // Sticky-rail rule
    /\.split-left\s*\{[\s\S]{0,200}position:\s*sticky/,
  ];
  guards.forEach((re, i) => {
    check('split-layout guard #' + (i + 1) + ': ' + re.source.slice(0, 60),
          re.test(VIEW),
          'did not match production source');
  });
}

// ── Nexus queue → liveByMatch merge ────────────────────────────
//
// The server returns matches[] (TBA: scores, actual_time, …) and
// queue[] (Nexus: status per match number) as separate arrays. The
// 3-up renderer reads liveByMatch[N].queue_status, so the client
// must MERGE the Nexus queue rows into the corresponding match
// entries. Without the merge, queue_status is never set anywhere
// in liveByMatch and the 3-up never renders queued matches.
//
// Bug was: client wrote nothing onto liveByMatch from data.queue,
// and the DB column is `status` not `queue_status` so even a naive
// merge using the wrong field name would fail.
//
// Source guards confirm:
//   - We walk data.queue and stamp q.status onto entry.queue_status
//   - We CREATE a stub entry when Nexus has a match number not yet
//     in TBA (common — Nexus reports staging before TBA picks up
//     scoring)

console.log('\nNexus queue → liveByMatch merge:');
{
  const guards = [
    /\(data\.queue\s*\|\|\s*\[\]\)\.forEach\b/,
    /entry\.queue_status\s*=\s*q\.status/,
    /STATE\.liveByMatch\[q\.match_number\]\s*=\s*entry/,
    /MERGE the Nexus queue/i,
  ];
  guards.forEach((re, i) => {
    check('nexus-merge guard #' + (i + 1) + ': ' + re.source.slice(0, 60),
          re.test(VIEW),
          'did not match production source');
  });
}

// ── Mobile-first layout plumbing ─────────────────────────────────
//
// Source-substring guards for the mobile-first layout work. Like the
// split-layout tests, we can't unit-test renderers without a DOM, so
// we verify the production source carries the expected plumbing:
//   - Toggle / state functions
//   - localStorage keys
//   - Agenda variant toggle (1/2)
//   - Mobile shell DOM template
//   - _updateMobileLayout called from rerender
//   - 3-up forced unconditionally in mobile mode
//   - Approval pill shared with split layout
//   - CSS hooks for mobile activation

console.log('\nMobile-first layout plumbing:');
{
  const guards = [
    /function\s+getMobileLayout\s*\(/,
    /function\s+setMobileLayout\s*\(/,
    /function\s+toggleMobileLayout\s*\(/,
    /function\s+initMobileLayout\s*\(/,
    /function\s+toggleMobileTile\s*\(/,
    /function\s+toggleMobileAgendaExpand\s*\(/,
    /function\s+toggleAgendaVariant\s*\(/,
    /function\s+_wrapForMobileLayout\s*\(/,
    /function\s+_unwrapForMobileLayout\s*\(/,
    /function\s+_updateMobileLayout\s*\(/,
    /function\s+_renderMobileTileSummaries\s*\(/,
    /function\s+_renderMobileFieldHeader\s*\(/,
    /function\s+_renderMobileAgendaStrip\s*\(/,
    /MOBILE_LAYOUT_KEY\s*=\s*['"]frc_view_mobile_layout['"]/,
    /AGENDA_VARIANT_KEY\s*=\s*['"]frc_view_agenda_variant['"]/,
    /id="btnMobileLayoutToggle"/,
    /id="mobileLayoutLabel"/,
    /shell\.id\s*=\s*['"]mobileShell['"]/,
    /id="mobileFieldSection"/,
    /id="mobileAgendaStrip"/,
    /id="mobileSchedulePane"/,
    /initMobileLayout\(\);/,
    // _updateMobileLayout called from rerender alongside tile summaries
    /_updateMobileLayout\(\)/,
    // 3-up forced unconditionally in mobile mode
    /3-up override/,
    // CSS hooks
    /html\[data-layout="mobile"\]\s*\.action-grid/,
    /html\[data-layout="mobile"\]\s*\.brand-header/,
    /html\[data-layout="mobile"\]\s*\.mobile-shell/,
    /\.mobile-agenda-strip/,
    /\.m-agenda-now/,
    /agenda-variant-btn/,
  ];
  guards.forEach((re, i) => {
    check('mobile-layout guard #' + (i + 1) + ': ' + re.source.slice(0, 60),
          re.test(VIEW),
          'did not match production source');
  });
}

// ── Field-status dispatcher: 3-up wrap ID guard ─────────────────
//
// Regression guard for the bug where updateFieldStatus hid the
// INNER grid (statusThreeUp) before re-rendering, while
// _renderFieldThreeUp only toggles the OUTER wrap (statusThreeUpWrap).
// The result was an invisible 3-up: outer wrap shown, inner grid
// hidden. The fix is to hide statusThreeUpWrap in the dispatcher.
// This guard ensures the dispatcher's hide-before-render targets the
// wrap, not the inner grid.

console.log('\nField-status dispatcher 3-up wrap guard:');
{
  // The dispatcher should reference statusThreeUpWrap (the wrap),
  // matching what _renderFieldThreeUp toggles. Match the actual
  // dispatcher code, not _renderFieldThreeUp's reference (which
  // already correctly uses the wrap).
  const dispatcherSlice = (VIEW.match(/Hide everything first[\s\S]{0,400}/) || [''])[0];
  check(
    'dispatcher hides statusThreeUpWrap (not statusThreeUp)',
    /statusThreeUpWrap/.test(dispatcherSlice) &&
    !/getElementById\(\s*['"]statusThreeUp['"]\s*\)/.test(dispatcherSlice),
    'dispatcher should target the wrap; inner grid stays available for renderer'
  );
}

// ── Mobile-layout 3-up presentation guards ──────────────────────
//
// Verifies that mobile-layout overrides the generic max-width:480px
// stack-vertically rule so the 3-up cells sit side-by-side (a single
// timeline read: Field → Deck → Queueing). The original stack rule
// is preserved for non-mobile-layout viewports (split, compact,
// standard). Also verifies the "Next match expected" panel is
// hidden in mobile layout to avoid redundancy with the 3-up
// on-field cell.

console.log('\nMobile 3-up presentation:');
{
  check(
    '3-up side-by-side in mobile layout',
    /html\[data-layout="mobile"\]\s*\.status-three-up\s*\{[\s\S]{0,200}grid-template-columns:\s*repeat\(3/.test(VIEW),
    'mobile layout should override .status-three-up to repeat(3, 1fr)'
  );
  check(
    'Next-only panel hidden in mobile layout',
    /html\[data-layout="mobile"\]\s*#statusNextOnly\s*\{\s*display:\s*none/.test(VIEW),
    'mobile layout should suppress #statusNextOnly to avoid 3-up duplication'
  );
}

// ── _renderNextOnly Nexus-priority guard ────────────────────────
//
// When Nexus reports queue_status, _renderNextOnly should pick the
// next match from Nexus pointers (on_deck → now_queueing →
// queueing_soon) rather than the schedule-walker's "first
// incomplete match." Without this, if Q12 is deferred and Q13 is
// on the field, the panel says "Next: Q12" while the 3-up
// correctly says "On field: Q13" — a contradiction.

console.log('\n_renderNextOnly Nexus priority:');
{
  const nextOnlySlice = (VIEW.match(/function _renderNextOnly\(\)\s*\{[\s\S]{0,4000}/) || [''])[0];
  check(
    '_renderNextOnly checks queue_status on_deck/now_queueing/queueing_soon',
    /on_deck/.test(nextOnlySlice) &&
    /now_queueing/.test(nextOnlySlice) &&
    /queueing_soon/.test(nextOnlySlice),
    'should consult Nexus pointers before falling back to schedule walker'
  );
}

// ── Summary ─────────────────────────────────────────────────────

console.log();
if (_failures > 0) {
  console.log(_failures + ' failure(s).');
  process.exit(1);
}
console.log('All view UI helpers tests passed.');
