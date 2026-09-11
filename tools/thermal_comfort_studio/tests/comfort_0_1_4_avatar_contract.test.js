import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const EXTREME = path.join(ROOT, 'public', 'assets', 'avatars', 'preset_08_extreme_winter_outdoor');

function sha256(name) {
  return crypto.createHash('sha256').update(fs.readFileSync(path.join(EXTREME, name))).digest('hex');
}

test('COMFORT-0.1.4 cold-side correction remains preserved', () => {
  assert.equal(sha256('pmv_m1_slightly_cool.webp'), 'de94f740dd23de3dd7368342a0de9ebe933184f54f451266b8e4e8f71a2eccb4');
  assert.equal(sha256('pmv_m2_cold.webp'), '4bc65feb74f2709091860de0e74450428844ce89fa4524d6b6657fd18dcdcf0f');
  assert.equal(sha256('pmv_m3_freezing.webp'), 'fa02f96f89340ff54dfde925769d4997d50c8536ebe3bbc0f630490477bd1e4b');
});
