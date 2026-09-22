import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8501/';
const FIXTURE_PATH = process.env.PR83_MONTHLY_FIXTURE || 'artifacts/pr83-contract-smoke/monthly-provider.json';
const OUT_DIR = process.env.PR83_VISUAL_DIR || 'artifacts/pr83-visual-walkthrough';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await fs.mkdir(OUT_DIR, { recursive: true });

async function bodyText(frame) {
  try { return await frame.locator('body').innerText({ timeout: 2000 }); } catch { return ''; }
}

async function appFrame(page, needle = 'Climate Analyzer', timeoutMs = 90000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      if ((await bodyText(frame)).includes(needle)) return frame;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}

async function combo(frame, label, timeoutMs = 60000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const candidate of [
      frame.getByRole('combobox', { name: label, exact: true }).first(),
      frame.getByLabel(label, { exact: true }).first(),
    ]) {
      if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    }
    await sleep(250);
  }
  throw new Error(`Combobox not found: ${label}`);
}

async function labelledInput(frame, label, timeoutMs = 60000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const candidate = frame.getByLabel(label, { exact: true }).first();
    if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    await sleep(250);
  }
  throw new Error(`Input not found: ${label}`);
}

async function rendered(control) {
  return [
    await control.innerText().catch(() => ''),
    await control.textContent().catch(() => ''),
    await control.inputValue().catch(() => ''),
  ].join(' ').replace(/\s+/g, ' ').trim();
}

async function visibleOption(page, frame, predicate) {
  for (const options of [frame.getByRole('option'), page.getByRole('option')]) {
    const count = await options.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const option = options.nth(i);
      if (!(await option.isVisible().catch(() => false))) continue;
      const text = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
      if (predicate(text)) return option;
    }
  }
  return null;
}

async function chooseSource(page) {
  const started = performance.now();
  while (performance.now() - started < 60000) {
    const frame = await appFrame(page, 'Climate Analyzer', 10000);
    for (const candidate of [
      frame.getByRole('radio', { name: 'GeoSphere Austria', exact: true }).last(),
      frame.getByText('GeoSphere Austria', { exact: true }).last(),
    ]) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try {
        await candidate.click({ force: true, timeout: 5000 });
        return await appFrame(page, 'GeoSphere Austria — measured historical station data', 15000);
      } catch {}
    }
    await sleep(300);
  }
  throw new Error('Could not select GeoSphere Austria.');
}

async function selectDataset(page) {
  const started = performance.now();
  while (performance.now() - started < 60000) {
    const frame = await appFrame(page, 'Climate Analyzer', 5000);
    const control = await combo(frame, 'GeoSphere dataset', 5000);
    const text = await bodyText(frame);
    if ((await rendered(control)).includes('1 month') && text.includes('Selected resource: klima-v2-1m')) return frame;
    await control.click({ timeout: 5000 }).catch(() => {});
    const option = await visibleOption(page, frame, (value) => value.includes('1 month'));
    if (option) await option.click({ timeout: 8000 }).catch(() => {});
    await sleep(500);
  }
  throw new Error('Could not commit klima-v2-1m.');
}

function stationMatches(text, name, id) {
  return text.includes(name) && (text.includes(`ID ${id}`) || text.includes(String(id)));
}

async function selectStation(page) {
  const name = String(fixture.station_name);
  const targetId = String(fixture.station_id);
  let frame = await appFrame(page, 'Search GeoSphere station', 60000);
  const search = await labelledInput(frame, 'Search GeoSphere station');
  await search.fill(name, { timeout: 15000 });
  await search.press('Tab').catch(() => {});
  await sleep(800);

  const started = performance.now();
  while (performance.now() - started < 60000) {
    frame = await appFrame(page, 'Manual station selection', 5000);
    const control = await combo(frame, 'Search-result stations', 5000);
    const current = await rendered(control);
    if (!stationMatches(current, name, targetId)) {
      await control.click({ timeout: 5000 }).catch(() => {});
      const option = await visibleOption(page, frame, (text) => stationMatches(text, name, targetId));
      if (option) await option.click({ timeout: 8000 }).catch(() => {});
      await sleep(500);
      continue;
    }
    const button = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
    if (await button.count().catch(() => 0) && await button.isVisible().catch(() => false)) {
      await button.click({ timeout: 15000 });
      return await appFrame(page, 'Measured variables to load', 60000);
    }
    await sleep(250);
  }
  throw new Error(`Could not commit station ${name} ID ${targetId}.`);
}

async function selectParameterSet(page, name) {
  const started = performance.now();
  while (performance.now() - started < 30000) {
    const frame = await appFrame(page, 'Parameter set', 5000);
    for (const candidate of [
      frame.getByRole('radio', { name, exact: true }).last(),
      frame.getByText(name, { exact: true }).last(),
    ]) {
      if (!(await candidate.count().catch(() => 0)) || !(await candidate.isVisible().catch(() => false))) continue;
      try {
        await candidate.click({ force: true, timeout: 5000 });
        await sleep(600);
        return await appFrame(page, 'Measured variables to load', 10000);
      } catch {}
    }
    await sleep(250);
  }
  throw new Error(`Parameter set did not settle: ${name}`);
}

async function assertEmptySelection(frame, label) {
  const text = await bodyText(frame);
  if (!text.includes('Select at least one measured GeoSphere variable to load.')) {
    throw new Error(`${label}: empty-selection warning is missing.`);
  }
  const load = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true });
  if (await load.count().catch(() => 0)) {
    throw new Error(`${label}: load action is visible with zero selected variables.`);
  }
  return text;
}

async function screenshot(page, name) {
  await page.screenshot({ path: path.join(OUT_DIR, name), fullPage: true });
}

const report = {
  schema: 'climate-analyzer-pr83-extended-visual-v6-empty-default',
  success: false,
  checks: {},
  page_errors: [],
  console_errors: [],
  error: null,
};
let browser;
let page;

try {
  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => { if (message.type() === 'error') report.console_errors.push(message.text()); });

  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await chooseSource(page);
  await selectDataset(page);
  let frame = await selectStation(page);

  await assertEmptySelection(frame, 'Initial monthly view');
  report.checks.initial_selection_empty = true;
  await screenshot(page, '01-monthly-initial-empty.png');

  frame = await selectParameterSet(page, 'Core variables');
  await assertEmptySelection(frame, 'Core variables');
  report.checks.core_view_selection_still_empty = true;
  await screenshot(page, '02-monthly-core-empty.png');

  frame = await selectParameterSet(page, 'All provider parameters');
  await assertEmptySelection(frame, 'All provider parameters');
  report.checks.all_view_selection_still_empty = true;
  await screenshot(page, '03-monthly-all-empty.png');

  frame = await selectParameterSet(page, 'Core variables');
  await assertEmptySelection(frame, 'Core variables roundtrip');
  report.checks.core_roundtrip_selection_still_empty = true;
  await screenshot(page, '04-monthly-core-empty-roundtrip.png');

  if (report.page_errors.length) throw new Error(`Page errors: ${report.page_errors.join(' | ')}`);
  report.success = true;
} catch (error) {
  report.error = String(error?.stack || error);
  if (page) await screenshot(page, '99-failure.png').catch(() => {});
  process.exitCode = 1;
} finally {
  await fs.writeFile(path.join(OUT_DIR, 'visual-walkthrough.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (browser) await browser.close().catch(() => {});
}
