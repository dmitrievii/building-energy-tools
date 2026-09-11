import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
const audit = JSON.parse(readFileSync(resolve(root, 'tests/fixtures/avatar_asset_audit.json'), 'utf8'));
const alignment = JSON.parse(readFileSync(resolve(root, 'public/assets/avatars/avatar_alignment.json'), 'utf8'));

test('all avatar publication assets retain normalized bbox height and foot baseline', () => {
  assert.equal(audit.length, 63);
  for (const row of audit) {
    assert.equal(row.target_visible_height_px, 1430);
    assert.equal(row.target_bottom_y, 1506);
    assert.ok(row.bbox, `${row.output} has bbox`);
    const [x0, y0, x1, y1] = row.bbox;
    assert.equal(y1 - y0 + 1, 1430, `${row.output} visible height`);
    assert.equal(y1, 1506, `${row.output} foot baseline`);
    const center = (x0 + x1) / 2;
    assert.ok(center >= 511 && center <= 512, `${row.output} center ${center}`);
    const webPath = row.output.replace(/^\.\//, '');
    assert.ok(existsSync(resolve(root, `public/${webPath}`)), `${row.output} exists`);
  }
});

test('avatar alignment manifest covers every publication asset', () => {
  for (const row of audit) {
    const key = `${row.preset_id}:${row.state_key}`;
    assert.ok(alignment[key], `alignment missing ${key}`);
    assert.deepEqual(alignment[key].bbox, row.bbox);
    assert.equal(alignment[key].targetVisibleHeightPx, 1430);
  }
});
