import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { CLOTHING_PRESETS } from '../src/data/clothingPresets.js';
import { ASSET_VERSION } from '../src/releaseInfo.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const EXTREME = path.join(ROOT, 'public', 'assets', 'avatars', 'preset_08_extreme_winter_outdoor');

function sha256(name) {
  return crypto.createHash('sha256').update(fs.readFileSync(path.join(EXTREME, name))).digest('hex');
}

test('COMFORT-0.1.5 uses a fresh canonical avatar asset identity', () => {
  assert.equal(ASSET_VERSION, 'tcs-comfort-0.1.5');
});

test('Extreme Winter Outdoor physical filenames are canonical from PMV -3 through +3', () => {
  const expected = {
    'pmv_m3_freezing.webp': 'fa02f96f89340ff54dfde925769d4997d50c8536ebe3bbc0f630490477bd1e4b',
    'pmv_m2_cold.webp': '4bc65feb74f2709091860de0e74450428844ce89fa4524d6b6657fd18dcdcf0f',
    'pmv_m1_slightly_cool.webp': 'de94f740dd23de3dd7368342a0de9ebe933184f54f451266b8e4e8f71a2eccb4',
    'pmv_0_comfortable.webp': 'e8a646983fbb60a4083ab0e403453a89cee3f056d7c7e5e8e4d6702d0bae5d83',
    'pmv_p1_slightly_warm.webp': '4f8bc8ea91c9bec85216d8a99773dce322528af47787452f0365e5b607270a75',
    'pmv_p2_warm.webp': '48d5d5932d3b679a91d3c2df13946a06e5fc24d156590d00d705206c67e31fea',
    'pmv_p3_overheated.webp': '7a9dc4bba7715f17b61b62c3ce3cbed0f6782fe7ede618e70476f13426db42ae'
  };
  for (const [name, hash] of Object.entries(expected)) assert.equal(sha256(name), hash, name);
});

test('Extreme Winter Outdoor runtime uses the same direct filename convention as every other preset', () => {
  const preset = CLOTHING_PRESETS.find(p => p.id === 'preset_08_extreme_winter_outdoor');
  assert.ok(preset);
  const expected = {
    'pmv_-3_freezing': 'pmv_m3_freezing.webp',
    'pmv_-2_cold': 'pmv_m2_cold.webp',
    'pmv_-1_slightly_cool': 'pmv_m1_slightly_cool.webp',
    'pmv_0_comfortable': 'pmv_0_comfortable.webp',
    'pmv_+1_slightly_warm': 'pmv_p1_slightly_warm.webp',
    'pmv_+2_warm': 'pmv_p2_warm.webp',
    'pmv_+3_overheated': 'pmv_p3_overheated.webp'
  };
  for (const [state, filename] of Object.entries(expected)) {
    assert.ok(preset.states[state].src.endsWith(`/preset_08_extreme_winter_outdoor/${filename}`), state);
  }
});
