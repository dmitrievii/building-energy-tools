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

test('responsive hotfix is loaded after the base stylesheet', () => {
  const basePos = index.indexOf('./src/styles/main.css');
  const responsivePos = index.indexOf('./src/styles/responsive.css');
  assert.ok(basePos >= 0, 'base stylesheet must be present');
  assert.ok(responsivePos > basePos, 'responsive stylesheet must load after base stylesheet');
});

test('laptop-width layout collapses before narrow intrinsic grid widths can overflow', () => {
  assert.match(responsiveCss, /@media\s*\(max-width:\s*1180px\)/);
  assert.match(responsiveCss, /\.dashboard-grid\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.match(responsiveCss, /\.dashboard-grid\s*>\s*\*/);
  assert.match(responsiveCss, /min-width:\s*0/);
  assert.match(responsiveCss, /overflow-x:\s*clip/);
});

test('hotfix remains responsive CSS rather than scaling the whole application', () => {
  assert.doesNotMatch(responsiveCss, /transform:\s*scale\s*\(/i);
  assert.doesNotMatch(responsiveCss, /zoom\s*:/i);
  assert.match(mainCss, /--app-max-width:\s*1840px/);
});
