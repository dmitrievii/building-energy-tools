import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { TOOL_VERSION, PROJECT_NAME, PUBLICATION_STATUS } from '../src/releaseInfo.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = p => readFileSync(path.join(root,p), 'utf8');

test('public release identity is stable and fail-closed', () => {
  assert.equal(PROJECT_NAME, 'Building Energy Tools');
  assert.equal(TOOL_VERSION, '0.1.0-beta.1');
  assert.equal(PUBLICATION_STATUS, 'BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED');
});

test('entrypoint is GitHub Pages project-path safe', () => {
  const index = read('index.html');
  assert.match(index, /href="\.\/src\/styles\/main\.css/);
  assert.match(index, /src="\.\/src\/main\.js/);
  assert.doesNotMatch(index, /(?:href|src)="\//);
  const presets = read('src/data/clothingPresets.js');
  assert.doesNotMatch(presets, /"src": "\//);
});

test('development cache-reset UI and legacy files are absent', () => {
  const app = read('src/App.js');
  assert.doesNotMatch(app, /resetCache|cacheResetUrl|currentCacheBuster/);
  assert.equal(existsSync(path.join(root,'src','cacheCleaner.js')), false);
  assert.equal(existsSync(path.join(root,'START_THERMAL_COMFORT_STUDIO.bat')), false);
});
