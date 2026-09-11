import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../src/App.js', import.meta.url), 'utf8');
const cssSource = readFileSync(new URL('../src/styles/main.css', import.meta.url), 'utf8');

test('heat-flow unit toggle and body-area conversion are present', () => {
  assert.match(appSource, /showTotalWatts: false/);
  assert.match(appSource, /bodySurfaceAreaM2: 1\.8/);
  assert.match(appSource, /Heat-flow display/);
  assert.match(appSource, /Total W instead of W\/m²/);
  assert.match(appSource, /Number\(value\) \* this\.state\.bodySurfaceAreaM2/);
});

test('heat-flow SVG supports dynamic width and gain direction classes', () => {
  assert.match(appSource, /flowStrokeWidth/);
  assert.match(appSource, /classList\.toggle\('is-gain', value < 0\)/);
  assert.match(appSource, /head-loss/);
  assert.match(appSource, /head-gain/);
  assert.match(cssSource, /--flow-width/);
  assert.match(cssSource, /\.flow\.is-gain \.head-loss/);
  assert.match(cssSource, /\.flow:not\(\.is-gain\) \.head-gain/);
});

test('evaporation has dedicated reversed gain stream', () => {
  assert.match(appSource, /evaporation-flow/);
  assert.match(appSource, /gain-stream/);
  assert.match(cssSource, /\.flow \.gain-stream \{ display: none; \}/);
  assert.match(cssSource, /\.flow\.is-gain \.loss-stream \{ display: none; \}/);
  assert.match(cssSource, /\.flow\.is-gain \.gain-stream \{ display: inline; \}/);
});

test('PMV strip includes icon and value markup', () => {
  assert.match(appSource, /<i>\$\{icons\[k\]\}<\/i>/);
  assert.match(appSource, /<em>\$\{values\[k\]\}<\/em>/);
  assert.match(cssSource, /state-strip::before/);
});


test('visual PMV clamp and restored avatar-state helper are present', () => {
  assert.match(appSource, /function boundedPmv\(value\)/);
  assert.match(appSource, /function avatarStateKeyForPmv\(pmv\)/);
  assert.match(appSource, /if \(value <= -2\.5\) return 'pmv_-3_freezing'/);
  assert.match(appSource, /if \(value < 2\.5\) return 'pmv_\+2_warm'/);
  assert.match(appSource, /return 'pmv_\+3_overheated'/);
  assert.match(appSource, /signedPmv\(result\.pmv, 2\)/);
});

test('conduction label remains below-left of the feet and avatar layout is normalized', () => {
  assert.match(cssSource, /\.heat-cond \{ left: 19\.8%; bottom: 10px; transform: translateX\(-50%\)/);
  assert.match(cssSource, /height: min\(116%, 980px\)/);
  assert.match(cssSource, /max-width: none/);
  assert.match(appSource, /applyAvatarLayout\(presetId, stateKey, options = \{\}\)/);
  assert.match(appSource, /const layout = AVATAR_LAYOUTS\[`\$\{presetId\}:\$\{stateKey\}`\]/);
  assert.match(appSource, /targetBBoxHeight = Math.min\(stageHeight \* 0\.94, 650\)/);
});

test('input-panel typography is enlarged for readability', () => {
  assert.match(cssSource, /\.control-row span \{ font-size: 17\.4px/);
  assert.match(cssSource, /\.control-row input, \.control-row select \{ width: 100%; height: 42px/);
  assert.match(cssSource, /outline: none; font-size: 18px/);
});
