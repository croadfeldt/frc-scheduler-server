// Tests for _v2BuildSchedulerInput (the V2 day_config → V1-shape
// scheduler input transform) and the per-block helpers it relies on.
//
// Run via: node tests/test_v2_scheduler_input.js
//
// Specifically exercises phase 5c — multi-qual-block-per-day support:
//   - Per-block cycleTime emitted as cycle-change at block boundary
//   - Synthetic gap break inserted when no sibling break covers the gap
//   - Single-block days produce identical output to the pre-5c path

'use strict';

const fs   = require('fs');
const path = require('path');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'index.html'),
  'utf8'
);

// Pull a self-contained slice of the helper functions into a local
// eval context. The functions transitively need _v2timeStrToMin,
// _v2minToTimeStr, _v2subtypeDefaultName, and _v2dayClassifierFromBlocks
// — all defined nearby — plus _v2dayCycleChanges itself and
// _v2BuildSchedulerInput. We grab everything between the
// "// V2 day_config → flat list of playoff blocks" comment (which
// _v2ExtractPlayoffs starts with) and the "// Read v2 form state"
// comment (which marks the start of the DOM-reader code we don't
// need). Anchored on stable comments rather than line numbers.

function extractRange(needleStart, needleEnd) {
  const s = html.indexOf(needleStart);
  const e = html.indexOf(needleEnd, s);
  if (s < 0 || e < 0) {
    throw new Error(`Could not locate range: ${needleStart} ... ${needleEnd}`);
  }
  return html.slice(s, e);
}

// _v2timeStrToMin / _v2minToTimeStr / _v2subtypeDefaultName /
// _v2dayClassifierFromBlocks are all in the V2 block helpers area.
// Easiest: pull a generous chunk that covers all of them.
const helpersStart = 'function _v2timeStrToMin';
const helpersEnd   = '// Read v2 form state from DOM';
const helpersIdx   = html.indexOf(helpersStart);
const helpersEndIx = html.indexOf(helpersEnd, helpersIdx);
if (helpersIdx < 0 || helpersEndIx < 0) {
  console.error('Could not locate helper range in index.html');
  process.exit(2);
}
const helpersCode = html.slice(helpersIdx, helpersEndIx);

if (typeof window === 'undefined') global.window = {};

const exposeNames = [
  '_v2timeStrToMin', '_v2minToTimeStr',
  '_v2subtypeDefaultName', '_v2dayClassifierFromBlocks',
  '_v2dayCycleChanges', '_v2blockChangesToV1',
  '_v2BuildSchedulerInput', '_v2ExtractPlayoffs',
];
const wrappedCode = helpersCode + '\n' + exposeNames.map(
  n => `try { globalThis.${n} = ${n}; } catch(e) {}`
).join('\n');
eval(wrappedCode);

const buildSchedulerInput = globalThis._v2BuildSchedulerInput;
const dayCycleChanges     = globalThis._v2dayCycleChanges;
if (!buildSchedulerInput || !dayCycleChanges) {
  console.error('Failed to extract helpers; got:',
    Object.keys(globalThis).filter(k => k.startsWith('_v2')));
  process.exit(2);
}

// ── Helpers ──────────────────────────────────────────────────────────
let testsRun = 0, testsFailed = 0;
function test(name, fn) {
  testsRun++;
  try {
    fn();
    console.log(`  ✓ ${name}`);
  } catch (e) {
    testsFailed++;
    console.log(`  ✗ ${name}: ${e.message}`);
  }
}
function assertEq(actual, expected, label) {
  // Normalize property order for object comparisons. JSON.stringify
  // is otherwise sensitive to key order; the actual data is correct
  // but JS object literals don't guarantee key insertion order
  // alignment with the test fixture.
  const sortedStringify = (v) => JSON.stringify(v, function(k, val) {
    if (val && typeof val === 'object' && !Array.isArray(val)) {
      return Object.keys(val).sort().reduce((o, kk) => { o[kk] = val[kk]; return o; }, {});
    }
    return val;
  });
  const aStr = sortedStringify(actual);
  const eStr = sortedStringify(expected);
  if (aStr !== eStr) {
    throw new Error(`${label || 'mismatch'}\n    expected: ${JSON.stringify(expected)}\n    actual:   ${JSON.stringify(actual)}`);
  }
}
function assertContains(arr, predicate, label) {
  if (!arr.some(predicate)) {
    throw new Error(`${label || 'no match found'} in ${JSON.stringify(arr)}`);
  }
}

// ── Phase 5c: per-block cycleTime ────────────────────────────────────

console.log('\n== _v2dayCycleChanges ==');

test('single block with no changes → just isStart', () => {
  const blocks = [{ type: 'qualification', start: '09:00', end: '17:00', cycleTime: 9, changes: [] }];
  const ccs = dayCycleChanges(blocks, 0);
  assertEq(ccs, [{ isStart: true, time: 9 }]);
});

test('single block with internal change', () => {
  const blocks = [{
    type: 'qualification', start: '09:00', end: '17:00', cycleTime: 9,
    changes: [{ afterMatch: 30, cycleTime: 8 }],
  }];
  const ccs = dayCycleChanges(blocks, 0);
  assertEq(ccs, [
    { isStart: true, time: 9 },
    { isStart: false, afterMatch: 30, time: 8 },
  ]);
});

test('two qual blocks with different cycleTimes', () => {
  // qual1 09:00-12:00 CT=9 → fits floor(180/9) = 20 matches
  // qual2 13:00-17:00 CT=8 → boundary cc emitted at after-match 20
  const blocks = [
    { type: 'qualification', start: '09:00', end: '12:00', cycleTime: 9, changes: [] },
    { type: 'qualification', start: '13:00', end: '17:00', cycleTime: 8, changes: [] },
  ];
  const ccs = dayCycleChanges(blocks, 0);
  assertEq(ccs, [
    { isStart: true, time: 9 },
    { isStart: false, afterMatch: 20, time: 8 },
  ]);
});

test('three blocks with cumulative offset', () => {
  // q1: 90 min @ CT=9 → 10 matches; q2: 80 min @ CT=8 → 10 matches; q3: 70 min @ CT=7 → 10 matches
  const blocks = [
    { type: 'qualification', start: '09:00', end: '10:30', cycleTime: 9, changes: [] },
    { type: 'qualification', start: '11:00', end: '12:20', cycleTime: 8, changes: [] },
    { type: 'qualification', start: '13:00', end: '14:10', cycleTime: 7, changes: [] },
  ];
  const ccs = dayCycleChanges(blocks, 0);
  assertEq(ccs, [
    { isStart: true, time: 9 },
    { isStart: false, afterMatch: 10, time: 8 },
    { isStart: false, afterMatch: 20, time: 7 },
  ]);
});

test('per-block changes with multi-block', () => {
  const blocks = [
    { type: 'qualification', start: '09:00', end: '12:00', cycleTime: 9,
      changes: [{ afterMatch: 5, cycleTime: 10 }] },
    { type: 'qualification', start: '13:00', end: '17:00', cycleTime: 8,
      changes: [{ afterMatch: 5, cycleTime: 7.5 }] },
  ];
  // qual1: dur 180, CT=9 → 20 matches
  // qual1's local change at after-5 → global after-5
  // qual2 boundary cc at after-20 → CT=8
  // qual2's local change at after-5 → global after-25
  const ccs = dayCycleChanges(blocks, 0);
  assertEq(ccs, [
    { isStart: true, time: 9 },
    { isStart: false, afterMatch: 5, time: 10 },
    { isStart: false, afterMatch: 20, time: 8 },
    { isStart: false, afterMatch: 25, time: 7.5 },
  ]);
});

test('baseMatchOffset offsets all afterMatch entries', () => {
  // Day 2 of a multi-day event — 50 matches scheduled before this day
  const blocks = [
    { type: 'qualification', start: '09:00', end: '12:00', cycleTime: 9,
      changes: [{ afterMatch: 5, cycleTime: 10 }] },
    { type: 'qualification', start: '13:00', end: '17:00', cycleTime: 8, changes: [] },
  ];
  const ccs = dayCycleChanges(blocks, 50);
  assertEq(ccs, [
    { isStart: true, time: 9 },
    { isStart: false, afterMatch: 55, time: 10 },     // 5 + 50
    { isStart: false, afterMatch: 70, time: 8 },      // 20 + 50
  ]);
});

console.log('\n== _v2BuildSchedulerInput multi-qual-block ==');

test('two qual blocks separated by sibling lunch — no synthetic gap', () => {
  const v2dc = {
    dayConfigVersion: 2, cycleTime: 9, breakBuffer: 5,
    days: [{
      label: 'Day 1', date: '',
      blocks: [
        { type: 'qualification', start: '09:00', end: '12:00', cycleTime: 9, changes: [], breaks: [] },
        { type: 'break', start: '12:00', end: '13:00', label: 'Lunch', breakKind: 'lunch' },
        { type: 'qualification', start: '13:00', end: '17:00', cycleTime: 8, changes: [], breaks: [] },
      ],
    }],
  };
  const v1 = buildSchedulerInput(v2dc);
  // No synthetic 'Idle' break — lunch covers the gap.
  const idleBreak = (v1.days[0].breaks || []).find(b => b.name === 'Idle');
  if (idleBreak) throw new Error('synthetic Idle break should not be present (lunch covers gap)');
  // CycleChanges captures both qual blocks' cycleTimes.
  assertContains(v1.days[0].cycleChanges, cc => cc.isStart === true && cc.time === 9, 'isStart=9');
  assertContains(v1.days[0].cycleChanges, cc => cc.afterMatch === 20 && cc.time === 8, 'after-20→8');
});

test('two qual blocks with uncovered gap — synthetic Idle break', () => {
  const v2dc = {
    dayConfigVersion: 2, cycleTime: 9, breakBuffer: 5,
    days: [{
      label: 'Day 1', date: '',
      blocks: [
        { type: 'qualification', start: '09:00', end: '12:00', cycleTime: 9, changes: [], breaks: [] },
        // Gap 12:00-12:30 with NO sibling break covering it
        { type: 'qualification', start: '12:30', end: '17:00', cycleTime: 8, changes: [], breaks: [] },
      ],
    }],
  };
  const v1 = buildSchedulerInput(v2dc);
  // Synthetic 'Idle' break should appear for 12:00-12:30
  const idleBreak = (v1.days[0].breaks || []).find(b => b.name === 'Idle');
  if (!idleBreak) throw new Error('expected synthetic Idle break for uncovered gap');
  assertEq(idleBreak.start, '12:00', 'idle.start');
  assertEq(idleBreak.end,   '12:30', 'idle.end');
});

test('block reorder by start time when V2 storage order is wrong', () => {
  // V2 doesn't guarantee block order; the per-block cycleChanges
  // must sort by start time before computing offsets.
  const v2dc = {
    dayConfigVersion: 2, cycleTime: 9, breakBuffer: 5,
    days: [{
      label: 'Day 1', date: '',
      blocks: [
        // Wrong order: qual2 before qual1
        { type: 'qualification', start: '13:00', end: '17:00', cycleTime: 8, changes: [], breaks: [] },
        { type: 'qualification', start: '09:00', end: '12:00', cycleTime: 9, changes: [], breaks: [] },
      ],
    }],
  };
  const v1 = buildSchedulerInput(v2dc);
  // Even though V2 storage order is reversed, cycleChanges should
  // still emit isStart with qual1's CT (9) and after-20 → 8 (qual2's CT).
  assertContains(v1.days[0].cycleChanges, cc => cc.isStart === true && cc.time === 9, 'isStart=9 (qual1)');
  assertContains(v1.days[0].cycleChanges, cc => cc.afterMatch === 20 && cc.time === 8, 'after-20→8 (qual2)');
});

test('single-block day produces same output as pre-5c path', () => {
  // Regression check — the common case shouldn't change.
  const v2dc = {
    dayConfigVersion: 2, cycleTime: 9, breakBuffer: 5,
    days: [{
      label: 'Day 1', date: '',
      blocks: [{
        type: 'qualification', start: '09:00', end: '17:00', cycleTime: 9,
        changes: [{ afterMatch: 30, cycleTime: 8 }],
        breaks: [{ type: 'break', start: '12:00', end: '13:00', label: 'Lunch', breakKind: 'lunch' }],
      }],
    }],
  };
  const v1 = buildSchedulerInput(v2dc);
  assertEq(v1.days[0].cycleChanges, [
    { isStart: true, time: 9 },
    { isStart: false, afterMatch: 30, time: 8 },
  ]);
});

test('practice + qual on same day — both contribute to cycleChanges', () => {
  // Practice 09:00-12:00 CT=11, qual 13:00-17:00 CT=9 — practice first.
  // practice: 180/11 → 16 matches (floor)
  const v2dc = {
    dayConfigVersion: 2, cycleTime: 9, breakBuffer: 5,
    days: [{
      label: 'Day 1', date: '',
      blocks: [
        { type: 'practice', start: '09:00', end: '12:00', cycleTime: 11, guaranteed: 3, maxFiller: 99, changes: [], breaks: [] },
        { type: 'break', start: '12:00', end: '13:00', label: 'Lunch', breakKind: 'lunch' },
        { type: 'qualification', start: '13:00', end: '17:00', cycleTime: 9, changes: [], breaks: [] },
      ],
    }],
  };
  const v1 = buildSchedulerInput(v2dc);
  // Mixed practice+qual day → not emitted as v1.practiceDay
  // (that path is for practice-ONLY days). Goes to v1.days with
  // both blocks contributing to cycleChanges.
  assertContains(v1.days[0].cycleChanges, cc => cc.isStart === true && cc.time === 11, 'isStart=11 (practice)');
  assertContains(v1.days[0].cycleChanges, cc => cc.afterMatch === 16 && cc.time === 9, 'after-16→9 (qual)');
});

console.log(`\n${testsRun - testsFailed}/${testsRun} tests passed.`);
process.exit(testsFailed === 0 ? 0 : 1);
