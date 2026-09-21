import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8502/';
const FIXTURE_PATH = process.env.PR83_MONTHLY_FIXTURE || 'artifacts/pr83-visual/monthly-provider.json';
const OUT_DIR = process.env.PR83_VISUAL_DIR || 'artifacts/pr83-visual/screenshots';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const VARIABLES = [
  'Air temperature — monthly mean',
  'Air temperature — absolute monthly minimum',
  'Air temperature — absolute monthly maximum',
  'Relative humidity — monthly mean',
  'Station pressure — monthly mean',
  'Dew-point temperature — monthly mean',
  'Ground temperature 0.10 m — monthly mean',
];

await fs.mkdir(OUT_DIR, { recursive: true });

async function bodyText(frame) {
  try { return await frame.locator('body').innerText({ timeout: 2000 }); } catch { return ''; }
}
async function appFrame(page, needle = 'Climate Analyzer', timeoutMs = 90000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) if ((await bodyText(frame)).includes(needle)) return frame;
    await sleep(250);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}
async function combo(frame, label, timeoutMs = 60000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const c of [frame.getByRole('combobox', { name: label, exact: true }).first(), frame.getByLabel(label, { exact: true }).first()]) {
      if (await c.count().catch(() => 0) && await c.isVisible().catch(() => false)) return c;
    }
    await sleep(250);
  }
  throw new Error(`Combobox not found: ${label}`);
}
async function rendered(control) {
  return [await control.innerText().catch(() => ''), await control.textContent().catch(() => ''), await control.inputValue().catch(() => '')].join(' ').replace(/\s+/g, ' ').trim();
}
async function visibleOption(page, frame, predicate) {
  for (const options of [frame.getByRole('option'), page.getByRole('option'), frame.locator('[data-baseweb="menu"] li'), page.locator('[data-baseweb="menu"] li')]) {
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
    for (const c of [frame.getByRole('radio', { name: 'GeoSphere Austria', exact: true }).last(), frame.getByText('GeoSphere Austria', { exact: true }).last(), frame.locator('label').filter({ hasText: 'GeoSphere Austria' }).last()]) {
      if (!(await c.count().catch(() => 0))) continue;
      try { await c.click({ force: true, timeout: 5000 }); return await appFrame(page, 'GeoSphere Austria — measured historical station data', 15000); } catch {}
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
    if ((await rendered(control)).includes('1 month') && (await bodyText(frame)).includes('Selected resource: klima-v2-1m')) return frame;
    await control.click({ timeout: 5000 }).catch(() => {});
    const option = await visibleOption(page, frame, (text) => text.includes('1 month'));
    if (option) await option.click({ timeout: 8000 }).catch(() => {});
    await sleep(500);
  }
  throw new Error('Could not commit klima-v2-1m.');
}
async function input(frame, label, timeoutMs = 60000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const c = frame.getByLabel(label, { exact: true }).first();
    if (await c.count().catch(() => 0) && await c.isVisible().catch(() => false)) return c;
    const aria = frame.locator(`input[aria-label="${label}"]`).first();
    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return aria;
    await sleep(250);
  }
  throw new Error(`Input not found: ${label}`);
}
async function selectStation(page) {
  let frame = await appFrame(page, 'Search GeoSphere station', 60000);
  const search = await input(frame, 'Search GeoSphere station');
  await search.fill(String(fixture.station_name));
  await search.press('Tab').catch(() => {});
  frame = await appFrame(page, 'Manual station selection', 60000);
  const control = await combo(frame, 'Search-result stations', 60000);
  await control.click({ timeout: 10000 });
  const started = performance.now();
  while (performance.now() - started < 30000) {
    const option = await visibleOption(page, frame, (text) => text.includes(fixture.station_name) && (text.includes(`ID ${fixture.station_id}`) || text.includes(String(fixture.station_id))));
    if (option) { await option.click({ timeout: 10000 }); break; }
    await sleep(200);
  }
  return await appFrame(page, 'Measured variables to load', 60000);
}
async function editor(page) {
  const frame = await appFrame(page, 'Measured variables to load', 30000);
  const tables = frame.locator('[data-testid="stDataFrame"]');
  if (!(await tables.count())) throw new Error('Variable table missing.');
  const grid = tables.last();
  const canvas = grid.locator('canvas[data-testid="data-grid-canvas"]').first();
  if (!(await canvas.count())) throw new Error('Variable editor canvas missing.');
  return { frame, grid, canvas };
}
async function rowForLabel(page, label) {
  for (const fraction of [0, .2, .4, .6, .8, 1]) {
    let state = await editor(page);
    await state.grid.locator('.dvn-scroller').first().evaluate((node, f) => {
      node.scrollTop = Math.max(0, (node.scrollHeight - node.clientHeight) * f);
      node.dispatchEvent(new Event('scroll', { bubbles: true }));
    }, fraction);
    await sleep(350);
    state = await editor(page);
    const rows = state.grid.locator('[role="grid"] tr[role="row"]');
    for (let i = 0; i < await rows.count(); i += 1) {
      const row = rows.nth(i);
      const text = (await row.textContent().catch(() => '')).replace(/\s+/g, ' ').trim();
      if (!text.includes(label)) continue;
      const load = (await row.locator('[role="gridcell"][aria-colindex="1"]').textContent().catch(() => '')).trim().toLowerCase();
      const ariaRowIndex = Number(await row.getAttribute('aria-rowindex'));
      if (!Number.isFinite(ariaRowIndex) || ariaRowIndex < 2) throw new Error(`Bad row index for ${label}`);
      return { ...state, load, dataIndex: ariaRowIndex - 2 };
    }
  }
  throw new Error(`Core variable row not found: ${label}`);
}
async function enableVariable(page, label) {
  let state = await rowForLabel(page, label);
  if (state.load === 'true') return;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    state = await rowForLabel(page, label);
    const box = await state.canvas.boundingBox();
    if (!box) throw new Error(`No editor bounds for ${label}`);
    await state.canvas.click({ position: { x: Math.min(box.width - 10, box.width * 0.5), y: Math.min(box.height - 10, 52) }, force: true });
    await state.canvas.focus();
    await page.keyboard.press('Control+Home');
    await sleep(180);
    for (let i = 0; i < state.dataIndex; i += 1) await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Space');
    await sleep(600);
    if ((await rowForLabel(page, label)).load === 'true') return;
  }
  throw new Error(`Could not enable ${label}`);
}
async function shot(page, name) { await page.screenshot({ path: path.join(OUT_DIR, name), fullPage: true }); }
async function nav(page, label, needle) {
  const frame = await appFrame(page, 'Climate Analyzer', 30000);
  const target = frame.getByText(label, { exact: true }).last();
  if (!(await target.count().catch(() => 0))) throw new Error(`Navigation missing: ${label}`);
  await target.click({ force: true, timeout: 10000 });
  return await appFrame(page, needle, 60000);
}
async function selectAnalysis(page, name) {
  const frame = await appFrame(page, 'Analysis type', 30000);
  const control = await combo(frame, 'Analysis type', 30000);
  await control.click({ timeout: 10000 });
  const started = performance.now();
  while (performance.now() - started < 15000) {
    const option = await visibleOption(page, frame, (text) => text === name);
    if (option) { await option.click({ timeout: 10000 }); await sleep(700); return; }
    await sleep(200);
  }
  throw new Error(`Analysis option missing: ${name}`);
}

const report = { success: false, checks: {}, page_errors: [], console_errors: [], error: null };
let browser;
let page;
try {
  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  page = await context.newPage();
  page.on('pageerror', (e) => report.page_errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') report.console_errors.push(m.text()); });
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await chooseSource(page);
  await selectDataset(page);
  await selectStation(page);
  const sourceFrame = await appFrame(page, 'Parameter set', 30000);
  const sourceText = await bodyText(sourceFrame);
  report.checks.parameter_set_core = sourceText.includes('Core variables');
  report.checks.monthly_context_once = (sourceText.match(/About this GeoSphere monthly dataset/g) || []).length === 1;
  await shot(page, '01-monthly-core-source.png');

  for (const variable of VARIABLES) await enableVariable(page, variable);
  report.checks.loaded_variables = VARIABLES;
  await shot(page, '02-monthly-core-selected.png');

  let frame = await appFrame(page, 'Measured variables to load', 30000);
  const load = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  if (!(await load.count())) throw new Error('Load button missing.');
  await load.click({ timeout: 15000 });
  await appFrame(page, 'Summary — Overview', 180000);

  await nav(page, 'Summary — Overview', 'Climate overview');
  await shot(page, '03-monthly-overview.png');

  await nav(page, 'Climate — Temperature', 'Temperature and extremes');
  let text = await bodyText(await appFrame(page, 'Temperature and extremes', 30000));
  report.checks.temperature_threshold_sliders_hidden = !text.includes('Heating threshold [°C]') && !text.includes('Cooling threshold [°C]');
  report.checks.dew_point_in_temperature = text.includes('Dew-point temperature');
  await shot(page, '04-monthly-temperature.png');

  if (text.includes('Ground temperature')) {
    await selectAnalysis(page, 'Ground temperature');
    await appFrame(page, 'Ground temperature', 30000);
    await shot(page, '05-monthly-ground-temperature.png');
  }

  await nav(page, 'Climate — Moisture & psychrometrics', 'Humidity and psychrometrics');
  text = await bodyText(await appFrame(page, 'Humidity and psychrometrics', 30000));
  report.checks.station_pressure_in_humidity = text.includes('Station pressure');
  await selectAnalysis(page, 'Psychrometric chart');
  await appFrame(page, 'Psychrometric axes', 30000);
  await shot(page, '06-monthly-psychrometric.png');

  await nav(page, 'Explore — Time series & overlay', 'Time series');
  await shot(page, '07-monthly-overlay.png');

  if (report.page_errors.length) throw new Error(`Page errors: ${report.page_errors.join(' | ')}`);
  report.success = true;
} catch (error) {
  report.error = String(error?.stack || error);
  if (page) await shot(page, '99-failure.png').catch(() => {});
  process.exitCode = 1;
} finally {
  await fs.writeFile(path.join(OUT_DIR, 'visual-walkthrough-core.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (browser) await browser.close().catch(() => {});
}
