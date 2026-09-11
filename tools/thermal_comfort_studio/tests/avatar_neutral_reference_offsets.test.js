import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const alignment = JSON.parse(readFileSync(resolve(root, 'public/assets/avatars/avatar_alignment.json'), 'utf8'));

test('Neutral Indoor reference offsets are calibrated for v1.0.15', () => {
  const expected = {
    preset_00_underwear: 0,
    preset_01_summer_light: 0,
    preset_02_light_indoor: 0,
    preset_03_neutral_indoor: 0,
    preset_05_warm_office: 0,
    preset_04_cool_indoor_layered: 10,
    preset_06_cold_indoor_heavy_layered: 10,
    preset_07_winter_outdoor: 14,
    preset_08_extreme_winter_outdoor: 5,
  };
  for (const [preset, yOffset] of Object.entries(expected)) {
    const rows = Object.entries(alignment).filter(([key]) => key.startsWith(`${preset}:`));
    assert.equal(rows.length, 7, `${preset} has 7 PMV states`);
    for (const [key, value] of rows) {
      assert.equal(value.yOffsetPx, yOffset, key);
    }
  }
});
