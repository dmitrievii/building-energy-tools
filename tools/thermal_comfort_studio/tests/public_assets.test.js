import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { CLOTHING_PRESETS } from '../src/data/clothingPresets.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function publicPathFromWebSrc(src) {
  const clean = src.split('?')[0].replace(/^\.\//, '');
  return path.join(root, 'public', clean);
}

test('sample avatar web path is project-relative and resolves to published asset', () => {
  const underwear = CLOTHING_PRESETS.find(p => p.id === 'preset_00_underwear');
  assert.ok(underwear);
  const src = underwear.states.pmv_0_comfortable.src;
  assert.equal(src, './assets/avatars/preset_00_underwear/pmv_0_comfortable.webp');
  assert.ok(existsSync(publicPathFromWebSrc(src)));
});

test('all 63 state avatars are lossless-WebP publication assets', () => {
  const paths = CLOTHING_PRESETS.flatMap(p => Object.values(p.states).map(s => s.src));
  assert.equal(paths.length, 63);
  assert.ok(paths.every(p => p.startsWith('./assets/avatars/') && p.endsWith('.webp')));
  assert.ok(paths.every(p => existsSync(publicPathFromWebSrc(p))));
});

test('internal reference screenshots are not part of public assets', () => {
  assert.equal(existsSync(path.join(root, 'public', 'assets', 'reference')), false);
  assert.equal(existsSync(path.join(root, 'public', 'assets', 'avatars', 'asset_audit.json')), false);
});
