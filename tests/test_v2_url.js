// V2 URL round-trip tests (phase 4).
//
// Extracts the _v2EncodeBlockValue / _v2DecodeBlockValue /
// _v2WriteUrlParams / _v2ReadUrlParams functions from
// static/index.html and exercises them against a representative
// V2 day_config. Run via:
//
//   node tests/test_v2_url.js
//
// Tests cover:
//   - Round-trip identity for typical V2 day_configs
//   - All block types encode/decode without loss
//   - Cycle changes survive
//   - Children (tier-3 nested in tier-2) survive
//   - URL-encoded labels with special chars survive
//   - Compact mode (dc=base64) round-trips
//   - V1 URLs (no dcv=) return null from V2 reader

'use strict';

const fs   = require('fs');
const path = require('path');

// Load the index.html file and pull the four V2 URL helper
// functions out into the global scope so they're exercisable.
const html = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'index.html'),
  'utf8'
);

// Extract the chunk between the V2 URL section start and end.
// Anchored on stable comments rather than line numbers.
const startMarker = '// ── V2 URL encoding / decoding';
const endMarker   = '// Given a list of v1-style breaks';
const start = html.indexOf(startMarker);
const end   = html.indexOf(endMarker, start);
if (start === -1 || end === -1) {
  console.error('Could not locate V2 URL helpers in index.html');
  process.exit(2);
}
const v2Code = html.slice(start, end);

// Stub atob/btoa for older Node (>= 16 has them globally).
if (typeof atob === 'undefined') {
  global.atob = function(s) { return Buffer.from(s, 'base64').toString('binary'); };
  global.btoa = function(s) { return Buffer.from(s, 'binary').toString('base64'); };
}
if (typeof window === 'undefined') global.window = {};

// Eval the V2 code in module scope. Functions need to be hoisted
// to globalThis since `eval` in a strict module doesn't write to
// the calling scope. Wrap in a postscript that exposes them.
const exposeNames = [
  '_v2EncodeBlockValue',
  '_v2DecodeBlockValue',
  '_v2WriteUrlParams',
  '_v2ReadUrlParams',
];
const wrappedCode = v2Code + '\n' + exposeNames.map(
  n => `globalThis.${n} = ${n};`
).join('\n');
eval(wrappedCode);
const _v2EncodeBlockValue = globalThis._v2EncodeBlockValue;
const _v2DecodeBlockValue = globalThis._v2DecodeBlockValue;
const _v2WriteUrlParams   = globalThis._v2WriteUrlParams;
const _v2ReadUrlParams    = globalThis._v2ReadUrlParams;

// ── Fixtures ──────────────────────────────────────────────────────────

const V2_TYPICAL = {
  dayConfigVersion: 2,
  cycleTime:   9,
  breakBuffer: 5,
  days: [
    {
      label: 'Day 1',
      labelOverride: null,
      date: '2026-04-04',
      blocks: [
        {
          type: 'ceremony', start: '08:30', end: '09:00',
          label: 'Opening ceremony', ceremonyKind: 'opening',
        },
        {
          type: 'qualification', start: '09:00', end: '17:00',
          cycleTime: 9,
          changes: [
            { afterMatch: 30, cycleTime: 8 },
            { afterMatch: 60, cycleTime: 7.5 },
          ],
          breaks: [
            { type: 'break', start: '12:00', end: '13:00',
              label: 'Lunch', breakKind: 'lunch' },
          ],
        },
        {
          type: 'alliance_selection', start: '17:00', end: '17:30',
          label: 'Alliance selection',
        },
        {
          type: 'playoff', start: '17:30', end: '20:30',
          playoffFormat: 'double_elim', playoffAlliances: 8, cycleTime: 11,
          changes: [], breaks: [],
          alliances: [], matches: [],
        },
        {
          type: 'awards', start: '20:30', end: '21:00',
          label: 'Awards',
        },
        {
          type: 'ceremony', start: '21:00', end: '21:30',
          label: 'Closing ceremony', ceremonyKind: 'closing',
        },
      ],
    },
    {
      label: 'Day 2',
      labelOverride: null,
      date: '2026-04-05',
      blocks: [
        {
          type: 'qualification', start: '09:00', end: '17:00',
          cycleTime: 9, changes: [],
          breaks: [
            { type: 'break', start: '12:00', end: '13:00',
              label: 'Lunch', breakKind: 'lunch' },
          ],
        },
      ],
    },
  ],
};

// ── Helpers ───────────────────────────────────────────────────────────

let passed = 0;
let failed = [];

function ok(condition, label) {
  if (condition) {
    console.log(`  PASS  ${label}`);
    passed++;
  } else {
    console.log(`  FAIL  ${label}`);
    failed.push(label);
  }
}

function eq(a, b, label) {
  const aStr = JSON.stringify(a), bStr = JSON.stringify(b);
  if (aStr === bStr) {
    console.log(`  PASS  ${label}`);
    passed++;
  } else {
    console.log(`  FAIL  ${label}`);
    console.log(`    expected: ${bStr}`);
    console.log(`    actual:   ${aStr}`);
    failed.push(label);
  }
}

function roundTrip(dc) {
  const params = new URLSearchParams();
  _v2WriteUrlParams(dc, params);
  return _v2ReadUrlParams(params);
}

// ── Tests ─────────────────────────────────────────────────────────────

console.log('TestEncodeBlockValue');

ok(_v2EncodeBlockValue({ type: 'qualification', start: '09:00', end: '17:00', cycleTime: 9 })
   === 'qual|09:00|17:00|9', 'qualification block');

ok(_v2EncodeBlockValue({ type: 'practice', start: '12:00', end: '17:00',
                         cycleTime: 11, guaranteed: 3, maxFiller: 5 })
   === 'practice|12:00|17:00|11|3|5', 'practice block');

ok(_v2EncodeBlockValue({ type: 'playoff', start: '17:30', end: '20:30',
                         playoffFormat: 'double_elim', playoffAlliances: 8, cycleTime: 11 })
   === 'playoff|17:30|20:30|double_elim|8|11', 'playoff block');

ok(_v2EncodeBlockValue({ type: 'break', start: '12:00', end: '13:00',
                         label: 'Lunch', breakKind: 'lunch' })
   === 'break|12:00|13:00|Lunch|lunch', 'break block');

ok(_v2EncodeBlockValue({ type: 'ceremony', start: '08:30', end: '09:00',
                         label: 'Opening ceremony', ceremonyKind: 'opening' })
   === 'ceremony|08:30|09:00|Opening ceremony|opening', 'ceremony block');

ok(_v2EncodeBlockValue({ type: 'alliance_selection', start: '17:00', end: '17:30',
                         label: 'Alliance selection' })
   === 'alliance|17:00|17:30|Alliance selection', 'alliance_selection short token');

ok(_v2EncodeBlockValue({ type: 'awards', start: '20:30', end: '21:00', label: 'Awards' })
   === 'awards|20:30|21:00|Awards', 'awards block');

console.log();
console.log('TestDecodeBlockValue');

const decQual = _v2DecodeBlockValue('qual|09:00|17:00|9');
eq(decQual, {
  type: 'qualification', start: '09:00', end: '17:00',
  cycleTime: 9, changes: [], breaks: [],
}, 'decode qualification');

const decPlayoff = _v2DecodeBlockValue('playoff|17:30|20:30|double_elim|8|11');
eq(decPlayoff, {
  type: 'playoff', start: '17:30', end: '20:30',
  playoffFormat: 'double_elim', playoffAlliances: 8, cycleTime: 11,
  changes: [], breaks: [], alliances: [], matches: [],
}, 'decode playoff');

const decAlliance = _v2DecodeBlockValue('alliance|17:00|17:30|Alliance selection');
eq(decAlliance, {
  type: 'alliance_selection', start: '17:00', end: '17:30',
  label: 'Alliance selection',
}, 'decode alliance short token expanded');

ok(_v2DecodeBlockValue(null) === null, 'decode null returns null');
ok(_v2DecodeBlockValue('') === null, 'decode empty returns null');
ok(_v2DecodeBlockValue('qual|09:00') === null, 'decode too-short returns null');
ok(_v2DecodeBlockValue('unknown|09:00|17:00|9') === null, 'decode unknown type returns null');

console.log();
console.log('TestRoundTrip');

const rt = roundTrip(V2_TYPICAL);
ok(rt !== null, 'round-trip returns a dc');
ok(rt.dayConfigVersion === 2, 'round-trip preserves version');
ok(rt.days.length === 2, 'round-trip preserves day count');
ok(rt.days[0].blocks.length === 6, 'round-trip preserves day 1 block count');
ok(rt.days[1].blocks.length === 1, 'round-trip preserves day 2 block count');

// Verify type-aware preservation per block
const rtBlocks = rt.days[0].blocks;
ok(rtBlocks[0].type === 'ceremony' && rtBlocks[0].ceremonyKind === 'opening',
   'opening ceremony preserved with kind');
ok(rtBlocks[1].type === 'qualification' && rtBlocks[1].cycleTime === 9,
   'qualification preserved with cycle time');
ok(rtBlocks[1].changes.length === 2 &&
   rtBlocks[1].changes[0].afterMatch === 30 &&
   rtBlocks[1].changes[0].cycleTime === 8,
   'cycle changes preserved (count and values)');
ok(rtBlocks[1].breaks.length === 1 &&
   rtBlocks[1].breaks[0].type === 'break' &&
   rtBlocks[1].breaks[0].breakKind === 'lunch',
   'nested lunch break preserved');
ok(rtBlocks[2].type === 'alliance_selection',
   'alliance_selection preserved (short token expanded)');
ok(rtBlocks[3].type === 'playoff' &&
   rtBlocks[3].playoffAlliances === 8 &&
   rtBlocks[3].playoffFormat === 'double_elim',
   'playoff preserved with format and alliance count');
ok(rtBlocks[5].type === 'ceremony' && rtBlocks[5].ceremonyKind === 'closing',
   'closing ceremony preserved with kind');

console.log();
console.log('TestEdgeCases');

// V1 URL (no dcv=) → V2 reader returns null
const v1Params = new URLSearchParams('n=12&d1=09:00-17:00&d1b=Lunch|12:00|13:00');
ok(_v2ReadUrlParams(v1Params) === null,
   'V1 URL (no dcv=2) returns null from V2 reader');

// Empty V2 params (just dcv=2)
const emptyParams = new URLSearchParams('dcv=2');
const empty = _v2ReadUrlParams(emptyParams);
ok(empty !== null && empty.dayConfigVersion === 2 && empty.days.length === 0,
   'empty V2 URL returns valid empty dc');

// dN with only a date
const dateOnly = new URLSearchParams('dcv=2&d1=2026-04-04|');
const dateRt = _v2ReadUrlParams(dateOnly);
ok(dateRt.days[0].date === '2026-04-04', 'date-only day metadata preserved');

// Block with no children
const noChildren = new URLSearchParams('dcv=2&d1=|Day 1&d1b1=qual|09:00|17:00|9');
const ncRt = _v2ReadUrlParams(noChildren);
ok(ncRt.days[0].blocks[0].breaks.length === 0,
   'block with no children parses as breaks: []');

// Compact mode round-trip via dc=base64
const params = new URLSearchParams('dcv=2&dc=' + btoa(JSON.stringify(V2_TYPICAL)));
const compactRt = _v2ReadUrlParams(params);
ok(compactRt && compactRt.dayConfigVersion === 2,
   'compact mode (dc=base64) decodes');
ok(compactRt.days.length === 2,
   'compact mode preserves all days');

// Pipe in label gets sanitized
const labelWithPipe = _v2EncodeBlockValue({
  type: 'break', start: '12:00', end: '13:00',
  label: 'Lunch | special', breakKind: 'lunch',
});
ok(labelWithPipe === 'break|12:00|13:00|Lunch   special|lunch',
   'pipe in label scrubbed to space');

// Sparse days (d1 + d3, no d2) — synthesized empty d2
const sparseParams = new URLSearchParams(
  'dcv=2&d1=2026-04-04|Day 1&d3=2026-04-06|Day 3'
);
const sparseRt = _v2ReadUrlParams(sparseParams);
ok(sparseRt.days.length === 3, 'sparse days produces full range');
ok(sparseRt.days[0].date === '2026-04-04' && sparseRt.days[2].date === '2026-04-06',
   'sparse days preserve date metadata at the right indices');
ok(sparseRt.days[1].label === 'Day 2',
   'missing day gets synthesized label');

// ── Summary ───────────────────────────────────────────────────────────

console.log();
console.log('='.repeat(60));
if (failed.length) {
  console.log(`FAILED: ${failed.length} test(s)`);
  failed.forEach(f => console.log(`  • ${f}`));
  process.exit(1);
}
console.log(`All ${passed} V2 URL tests passed.`);
