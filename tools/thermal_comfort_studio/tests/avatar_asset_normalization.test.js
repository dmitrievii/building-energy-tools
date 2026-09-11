import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { CLOTHING_PRESETS } from '../src/data/clothingPresets.js';

const root = resolve(new URL('..', import.meta.url).pathname);
const alignment = JSON.parse(readFileSync(resolve(root, 'public/assets/avatars/avatar_alignment.json'), 'utf8'));

const expectedFilename = {
  'pmv_-3_freezing': 'pmv_m3_freezing.webp',
  'pmv_-2_cold': 'pmv_m2_cold.webp',
  'pmv_-1_slightly_cool': 'pmv_m1_slightly_cool.webp',
  'pmv_0_comfortable': 'pmv_0_comfortable.webp',
  'pmv_+1_slightly_warm': 'pmv_p1_slightly_warm.webp',
  'pmv_+2_warm': 'pmv_p2_warm.webp',
  'pmv_+3_overheated': 'pmv_p3_overheated.webp'
};

test('all 63 avatar publication states use the canonical PMV filename convention', () => {
  assert.equal(CLOTHING_PRESETS.length, 9);
  assert.equal(Object.keys(alignment).length, 63);

  for (const preset of CLOTHING_PRESETS) {
    for (const [stateKey, filename] of Object.entries(expectedFilename)) {
      const state = preset.states[stateKey];
      assert.ok(state, `${preset.id}:${stateKey} state exists`);
      assert.ok(state.src.endsWith(`/${preset.id}/${filename}`), `${preset.id}:${stateKey} canonical filename`);
      const webPath = state.src.replace(/^\.\//, '');
      assert.ok(existsSync(resolve(root, `public/${webPath}`)), `${preset.id}:${stateKey} asset exists`);
    }
  }
});

test('alignment manifest covers every canonical publication state with normalized geometry', () => {
  for (const preset of CLOTHING_PRESETS) {
    for (const stateKey of Object.keys(expectedFilename)) {
      const key = `${preset.id}:${stateKey}`;
      const row = alignment[key];
      assert.ok(row, `alignment missing ${key}`);
      assert.equal(row.targetVisibleHeightPx, 1430, `${key} visible height target`);
      assert.equal(row.targetBottomY, 1506, `${key} foot baseline target`);
      assert.ok(row.bbox, `${key} has bbox`);
      const [x0, y0, x1, y1] = row.bbox;
      assert.equal(y1 - y0 + 1, 1430, `${key} bbox visible height`);
      assert.equal(y1, 1506, `${key} bbox foot baseline`);
      const center = (x0 + x1) / 2;
      assert.ok(center >= 511 && center <= 512, `${key} center ${center}`);
    }
  }
});
