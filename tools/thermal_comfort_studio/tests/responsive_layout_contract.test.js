import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const index = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const mainCss = fs.readFileSync(path.join(ROOT, 'src', 'styles', 'main.css'), 'utf8');
const responsiveCss = fs.readFileSync(path.join(ROOT, 'src', 'styles', 'responsive.css'), 'utf8');

test('responsive layer is loaded after base CSS with the current cache identity', () => {
  const basePos = index.indexOf('./src/styles/main.css');
  const responsivePos = index.indexOf('./src/styles/responsive.css');
  assert.ok(basePos >= 0, 'base stylesheet must be present');
  assert.ok(responsivePos > basePos, 'responsive stylesheet must load after base stylesheet');
  assert.match(index, /main\.css\?v=comfort-0\.1\.2/);
  assert.match(index, /responsive\.css\?v=comfort-0\.1\.2/);
});

test('laptop layout uses fluid three-column tracks instead of fixed desktop widths', () => {
  assert.match(responsiveCss, /@media\s*\(max-width:\s*1750px\)\s*and\s*\(min-width:\s*1201px\)/);
  assert.match(responsiveCss, /minmax\(300px,\s*0\.82fr\)/);
  assert.match(responsiveCss, /minmax\(0,\s*1\.35fr\)/);
  assert.match(responsiveCss, /minmax\(350px,\s*1fr\)/);
  assert.match(responsiveCss, /\.dashboard-grid\s*>\s*\*/);
  assert.match(responsiveCss, /min-width:\s*0/);
});

test('narrow layouts reflow rather than crop or globally scale the application', () => {
  assert.match(responsiveCss, /@media\s*\(max-width:\s*1200px\)/);
  assert.match(responsiveCss, /grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.doesNotMatch(responsiveCss, /transform:\s*scale\s*\(/i);
  assert.doesNotMatch(responsiveCss, /zoom\s*:/i);
  assert.match(mainCss, /--app-max-width:\s*1840px/);
});

test('viewport containers use parent percentage geometry instead of 100vw overrides', () => {
  assert.match(responsiveCss, /width:\s*min\(calc\(100%\s*-\s*32px\),\s*var\(--app-max-width\)\)/);
  assert.match(responsiveCss, /overflow-x:\s*hidden/);
});
