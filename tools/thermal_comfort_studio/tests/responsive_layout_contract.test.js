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
const visualFixesCss = fs.readFileSync(path.join(ROOT, 'src', 'styles', 'visual-fixes.css'), 'utf8');

test('responsive and visual-fix layers load after base CSS with current cache identity', () => {
  const basePos = index.indexOf('./src/styles/main.css');
  const responsivePos = index.indexOf('./src/styles/responsive.css');
  const visualFixesPos = index.indexOf('./src/styles/visual-fixes.css');
  assert.ok(basePos >= 0, 'base stylesheet must be present');
  assert.ok(responsivePos > basePos, 'responsive stylesheet must load after base stylesheet');
  assert.ok(visualFixesPos > responsivePos, 'visual fixes must load after responsive CSS');
  assert.match(index, /main\.css\?v=comfort-0\.1\.4/);
  assert.match(index, /responsive\.css\?v=comfort-0\.1\.4/);
  assert.match(index, /visual-fixes\.css\?v=comfort-0\.1\.4/);
  assert.match(index, /main\.js\?v=comfort-0\.1\.4/);
});

test('laptop layout uses fluid three-column tracks instead of fixed desktop widths', () => {
  assert.match(responsiveCss, /@media\s*\(max-width:\s*1750px\)\s*and\s*\(min-width:\s*1201px\)/);
  assert.match(responsiveCss, /minmax\(300px,\s*0\.82fr\)/);
  assert.match(responsiveCss, /minmax\(0,\s*1\.35fr\)/);
  assert.match(responsiveCss, /minmax\(350px,\s*1fr\)/);
  assert.match(responsiveCss, /\.dashboard-grid\s*>\s*\*/);
  assert.match(responsiveCss, /min-width:\s*0/);
});

test('header is auto-height and typography is fluid', () => {
  assert.match(responsiveCss, /\.app-header\s*\{[\s\S]*?height:\s*auto/);
  assert.match(responsiveCss, /grid-template-columns:\s*minmax\(0,\s*1fr\)\s*auto/);
  assert.match(responsiveCss, /\.brand h1\s*\{[\s\S]*?font-size:\s*clamp\(/);
  assert.match(responsiveCss, /\.brand p\s*\{[\s\S]*?font-size:\s*clamp\(/);
  assert.match(responsiveCss, /\.badge\s*\{[\s\S]*?font-size:\s*clamp\(/);
});

test('laptop avatar is fitted inside the stage instead of being cropped at 116 percent height', () => {
  assert.match(responsiveCss, /\.avatar-image\s*\{[\s\S]*?height:\s*calc\(100%\s*-\s*8px\)/);
  assert.match(responsiveCss, /max-height:\s*calc\(100%\s*-\s*8px\)/);
  assert.match(responsiveCss, /@media\s*\(max-height:\s*860px\)\s*and\s*\(min-width:\s*1201px\)/);
  assert.match(responsiveCss, /height:\s*calc\(100%\s*-\s*6px\)/);
});

test('stage overlay is removed and respiration label is lowered', () => {
  assert.match(visualFixesCss, /\.avatar-stage::before\s*\{[\s\S]*?content:\s*none\s*!important/);
  assert.match(visualFixesCss, /display:\s*none\s*!important/);
  assert.match(visualFixesCss, /\.heat-resp\s*\{[\s\S]*?top:\s*46%/);
  assert.match(visualFixesCss, /@media\s*\(max-width:\s*900px\)[\s\S]*?\.heat-resp\s*\{[\s\S]*?top:\s*auto/);
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
