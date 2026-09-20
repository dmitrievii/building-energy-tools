import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8501/';
const FIXTURE_PATH = process.env.GEOSPHERE_SMOKE_FIXTURE || 'artifacts/geosphere-precip-snow-smoke/provider-fixture.json';
const OUT_DIR = process.env.AUDIT_OUTPUT_DIR || 'artifacts/geosphere-precip-snow-smoke';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await fs.mkdir(OUT_DIR, { recursive: true });

async function bodyText(frame) {
  try { return await frame.locator('body').innerText({ timeout: 2_000 }); }
  catch { return ''; }
}

async function appFrame(page, needle = 'Climate Analyzer', timeoutMs = 90_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      if ((await bodyText(frame)).includes(needle)) return frame;
    }
    await sleep(300);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}

async function chooseAndWait(page, name, expected, timeoutMs = 45_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const frame = await appFrame(page, 'Climate Analyzer', 10_000);
    const candidates = [
      frame.locator('label').filter({ hasText: name }).last(),
      frame.getByText(name, { exact: true }).last(),
      frame.getByRole('radio', { name, exact: true }).last(),
    ];
    for (const candidate of candidates) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try { await candidate.click({ force: true, timeout: 5_000 }); }
      catch { continue; }
      try { return await appFrame(page, expected, 7_000); }
      catch { /* retry */ }
    }
    await sleep(400);
  }
  throw new Error(`Timed out selecting ${name}`);
}

async function labelledInput(frame, label, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const labelled = frame.getByLabel(label, { exact: true }).first();
    if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) return labelled;
    const aria = frame.locator(`input[aria-label="${label}"]`).first();
    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return aria;
    await sleep(250);
  }
  throw new Error(`Timed out waiting for input: ${label}`);
}

async function selectDataset10min(page, frame) {
  let combo = frame.getByRole('combobox', { name: 'GeoSphere dataset', exact: true }).first();
  if (!(await combo.count().catch(() => 0))) combo = frame.getByLabel('GeoSphere dataset', { exact: true }).first();
  if (!(await combo.count().catch(() => 0))) throw new Error('GeoSphere dataset combobox not found.');
  const rendered = [await combo.innerText().catch(() => ''), await combo.textContent().catch(() => '')].join(' ');
  if (rendered.includes('10 min')) return frame;
  await combo.click({ timeout: 10_000 });
  const started = performance.now();
  while (performance.now() - started < 10_000) {
    for (const options of [page.getByRole('option'), page.locator('[data-baseweb="menu"] li')]) {
      const texts = await options.allInnerTexts().catch(() => []);
      const index = texts.findIndex((value) => value.includes('10 min'));
      if (index >= 0) {
        await options.nth(index).click({ timeout: 10_000 });
        return await appFrame(page, 'GeoSphere Austria — measured historical station data', 30_000);
      }
    }
    await sleep(250);
  }
  throw new Error('10-minute dataset option did not materialize.');
}

let browser;
let page;
const report = { success: false, fixture, roles: [], data_testids: [], canvases: [], body_excerpt: '', error: null };
try {
  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  page = await context.newPage();
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  let frame = await chooseAndWait(page, 'GeoSphere Austria', 'GeoSphere Austria — measured historical station data');
  frame = await selectDataset10min(page, frame);

  const search = await labelledInput(frame, 'Search GeoSphere station');
  await search.fill(String(fixture.station_name), { timeout: 15_000 });
  await search.press('Tab').catch(() => {});
  frame = await appFrame(page, 'Manual station selection', 60_000);
  frame = await appFrame(page, 'Measured variables to load', 60_000);
  await sleep(1500);

  report.body_excerpt = (await bodyText(frame)).slice(0, 14000);
  report.roles = await frame.locator('[role]').evaluateAll((nodes) => nodes.slice(0, 1200).map((node) => ({
    tag: node.tagName,
    role: node.getAttribute('role'),
    ariaLabel: node.getAttribute('aria-label'),
    ariaRowIndex: node.getAttribute('aria-rowindex'),
    ariaColIndex: node.getAttribute('aria-colindex'),
    ariaChecked: node.getAttribute('aria-checked'),
    text: (node.innerText || node.textContent || '').trim().slice(0, 300),
  })));
  report.data_testids = await frame.locator('[data-testid]').evaluateAll((nodes) => nodes
    .filter((node) => /data|grid|editor|table/i.test(node.getAttribute('data-testid') || ''))
    .slice(0, 400)
    .map((node) => ({
      tag: node.tagName,
      testid: node.getAttribute('data-testid'),
      role: node.getAttribute('role'),
      ariaLabel: node.getAttribute('aria-label'),
      text: (node.innerText || node.textContent || '').trim().slice(0, 1000),
      html: node.outerHTML.slice(0, 5000),
    })));
  report.canvases = await frame.locator('canvas').evaluateAll((nodes) => nodes.map((node) => ({
    width: node.width,
    height: node.height,
    clientWidth: node.clientWidth,
    clientHeight: node.clientHeight,
    ariaLabel: node.getAttribute('aria-label'),
    role: node.getAttribute('role'),
    parent: node.parentElement?.outerHTML?.slice(0, 4000) || '',
  })));
  report.success = true;
  await page.screenshot({ path: path.join(OUT_DIR, 'data-editor-dom-probe.png'), fullPage: true });
} catch (error) {
  report.error = String(error?.stack || error);
  if (page) await page.screenshot({ path: path.join(OUT_DIR, 'data-editor-dom-probe-failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await fs.writeFile(path.join(OUT_DIR, 'data-editor-dom-probe.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ success: report.success, error: report.error, role_count: report.roles.length, data_testid_count: report.data_testids.length, canvas_count: report.canvases.length }, null, 2));
  if (browser) await browser.close().catch(() => {});
}
