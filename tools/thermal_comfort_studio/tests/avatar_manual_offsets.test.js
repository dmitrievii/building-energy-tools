import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const alignment = JSON.parse(readFileSync(resolve(root, 'public/assets/avatars/avatar_alignment.json'), 'utf8'));
const appSource = readFileSync(resolve(root, 'src/App.js'), 'utf8');

const expected = {
  preset_04_cool_indoor_layered: 10,
  preset_06_cold_indoor_heavy_layered: 10,
  preset_07_winter_outdoor: 14,
  preset_08_extreme_winter_outdoor: 5,
};

test('manual preset-level avatar vertical offsets are present', () => {
  for (const [preset, y] of Object.entries(expected)) {
    const matches = Object.entries(alignment).filter(([key]) => key.startsWith(`${preset}:`));
    assert.equal(matches.length, 7, `${preset} has all 7 states`);
    for (const [key, value] of matches) {
      assert.equal(value.yOffsetPx, y, `${key} yOffsetPx`);
    }
  }
});

test('stable reference presets have no manual vertical offset', () => {
  for (const preset of [
    'preset_00_underwear',
    'preset_01_summer_light',
    'preset_02_light_indoor',
    'preset_03_neutral_indoor',
    'preset_05_warm_office'
  ]) {
    const matches = Object.entries(alignment).filter(([key]) => key.startsWith(`${preset}:`));
    assert.equal(matches.length, 7, `${preset} has all 7 states`);
    for (const [key, value] of matches) {
      assert.equal(value.yOffsetPx, 0, `${key} yOffsetPx`);
    }
  }
});

test('runtime applies manual avatar offsets', () => {
  assert.match(appSource, /const manualY = Number\(layout\.yOffsetPx \?\? 0\)/);
  assert.match(appSource, /const bottom = floorMargin - \(\(sourceHeight - y1\) \* scale\) \+ manualY/);
  assert.match(appSource, /const manualX = Number\(layout\.xOffsetPx \?\? 0\)/);
});
