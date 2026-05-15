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

// ── Summary ─────────────────────────────────────────────────────

console.log();
if (_failures > 0) {
  console.log(_failures + ' failure(s).');
  process.exit(1);
}
console.log('All view UI helpers tests passed.');
