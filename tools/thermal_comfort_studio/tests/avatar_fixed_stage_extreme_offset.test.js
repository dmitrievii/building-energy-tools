import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const cssSource = readFileSync(resolve(root, 'src/styles/main.css'), 'utf8');
const alignment = JSON.parse(readFileSync(resolve(root, 'public/assets/avatars/avatar_alignment.json'), 'utf8'));

test('avatar panel height is fixed so PMV strip is not pushed down by presets', () => {
  assert.match(cssSource, /\.avatar-panel \{ position: relative; height: var\(--top-panel-height\); min-height: var\(--top-panel-height\); align-self: start; display: grid; grid-template-rows: var\(--avatar-stage-height\) var\(--pmv-strip-height\); \}/);
  assert.match(cssSource, /\.avatar-stage \{\n  position: relative;\n  height: var\(--avatar-stage-height\);\n  min-height: var\(--avatar-stage-height\);/);
  assert.match(cssSource, /\.state-strip \{ position: relative; height: var\(--pmv-strip-height\);/);
});

test('avatar offsets are recalibrated against Neutral Indoor reference', () => {
  const expected = {
    preset_04_cool_indoor_layered: 10,
    preset_06_cold_indoor_heavy_layered: 10,
    preset_07_winter_outdoor: 14,
    preset_08_extreme_winter_outdoor: 5,
  };
  for (const [key, value] of Object.entries(alignment)) {
    const preset = key.split(':')[0];
    if (expected[preset] !== undefined) {
      assert.equal(value.yOffsetPx, expected[preset], key);
    }
  }
});
