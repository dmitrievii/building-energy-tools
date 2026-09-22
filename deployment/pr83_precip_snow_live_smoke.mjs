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

async function text(frame) { try { return await frame.locator('body').innerText({ timeout: 2000 }); } catch { return ''; } }
async function appFrame(page, needle = 'Climate Analyzer', timeoutMs = 90000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) if ((await text(frame)).includes(needle)) return frame;
    await sleep(250);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}
async function visibleOption(page, frame, predicate) {
  for (const options of [frame.getByRole('option'), page.getByRole('option'), frame.locator('[data-baseweb="menu"] li'), page.locator('[data-baseweb="menu"] li')]) {
    const count = await options.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const option = options.nth(i);
      if (!(await option.isVisible().catch(() => false))) continue;
      const value = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
      if (predicate(value)) return option;
    }
  }
  return null;
}
async function chooseSource(page) {
  const frame = await appFrame(page);
  for (const candidate of [frame.getByRole('radio', { name: 'GeoSphere Austria', exact: true }).last(), frame.getByText('GeoSphere Austria', { exact: true }).last()]) {
    if (!(await candidate.count().catch(() => 0))) continue;
    await candidate.click({ force: true, timeout: 10000 }).catch(() => {});
    try { return await appFrame(page, 'GeoSphere Austria — measured historical station data', 20000); } catch {}
  }
  throw new Error('Could not select GeoSphere Austria.');
}
async function input(frame, label) {
  for (const candidate of [frame.getByLabel(label, { exact: true }).first(), frame.locator(`input[aria-label="${label}"]`).first()]) {
    if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
  }
  throw new Error(`Input not found: ${label}`);
}
async function selectStation(page) {
  let frame = await appFrame(page, 'Search GeoSphere station', 60000);
  const search = await input(frame, 'Search GeoSphere station');
  await search.fill(String(fixture.station_name));
  await search.press('Tab').catch(() => {});
  frame = await appFrame(page, 'Manual station selection', 60000);
  const combo = frame.getByRole('combobox', { name: 'Search-result stations', exact: true }).first();
  await combo.click({ timeout: 10000 });
  const option = await visibleOption(page, frame, (value) => value.includes(fixture.station_name) && value.includes(String(fixture.station_id)));
  if (!option) throw new Error(`Station option missing: ${fixture.station_name} (${fixture.station_id})`);
  await option.click({ timeout: 10000 });
  frame = await appFrame(page, 'Manual station selection', 30000);
  const use = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
  await use.click({ timeout: 15000 });
  return await appFrame(page, 'Measured variables to load', 60000);
}
async function setDate(page, label, iso) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const frame = await appFrame(page, 'Measured variables to load', 30000);
    const control = await input(frame, label);
    await control.click({ timeout: 5000 });
    await control.fill(iso).catch(async () => { await control.fill(iso.replaceAll('-', '/')); });
    await control.press('Enter').catch(() => {});
    await control.press('Tab').catch(() => {});
    await sleep(750);
    const refreshed = await input(await appFrame(page, 'Measured variables to load', 30000), label);
    const observed = await refreshed.inputValue().catch(() => '');
    const nums = observed.split(/\D+/).filter(Boolean).map(Number);
    const [y, m, d] = iso.split('-').map(Number);
    if (nums.includes(y) && nums.includes(m) && nums.includes(d)) return observed;
  }
  throw new Error(`Date input ${label} did not accept ${iso}.`);
}
async function measuredControl(page) {
  const frame = await appFrame(page, 'Select measured variables', 30000);
  const control = frame.getByRole('combobox', { name: 'Select measured variables', exact: true }).first();
  if (!(await control.count().catch(() => 0))) throw new Error('Measured-variable multiselect missing.');
  return { frame, control };
}
async function selectProvider(page, provider) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const { frame, control } = await measuredControl(page);
    const shell = control.locator('xpath=ancestor::*[@data-baseweb="select"][1]').first();
    if ((await shell.innerText().catch(() => '')).includes(provider)) return;
    await control.click({ timeout: 10000 });
    const option = await visibleOption(page, frame, (value) => value.includes(`[${provider}]`));
    if (option) {
      await option.click({ timeout: 10000 });
      await page.keyboard.press('Escape').catch(() => {});
      await sleep(200);
      const refreshed = await measuredControl(page);
      const after = refreshed.control.locator('xpath=ancestor::*[@data-baseweb="select"][1]').first();
      if ((await after.innerText().catch(() => '')).includes(provider)) return;
    }
  }
  throw new Error(`Could not stage provider ${provider}.`);
}
async function openPrecipitation(page) {
  let frame = await appFrame(page, 'Climate — Precipitation & snow', 180000);
  const nav = frame.getByText('Climate — Precipitation & snow', { exact: true }).last();
  await nav.click({ timeout: 15000 });
  return await appFrame(page, 'Precipitation and snow', 60000);
}
async function analysisOptions(page) {
  const frame = await appFrame(page, 'Precipitation and snow', 30000);
  const control = frame.getByRole('combobox', { name: 'Analysis type' }).first();
  await control.click({ timeout: 10000 });
  await sleep(300);
  const values = [];
  for (const options of [frame.getByRole('option'), page.getByRole('option')]) {
    const count = await options.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const option = options.nth(i);
      if (await option.isVisible().catch(() => false)) values.push((await option.innerText().catch(() => '')).trim());
    }
  }
  await page.keyboard.press('Escape').catch(() => {});
  return [...new Set(values.filter(Boolean))];
}

const report = { schema: 'climate-analyzer-pr83-precip-snow-live-smoke-v4-form-native-selector', target_url: TARGET_URL, fixture, checks: {}, page_errors: [], console_errors: [], http_errors: [], success: false, error: null };
let browser; let page;
try {
  if (!fixture.success) throw new Error(`Provider fixture failed: ${fixture.error ?? 'unknown'}`);
  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => { if (message.type() === 'error') report.console_errors.push(message.text()); });
  page.on('response', (response) => { if (response.status() >= 400) report.http_errors.push({ status: response.status(), url: response.url() }); });
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await chooseSource(page);
  await appFrame(page, 'Selected resource: klima-v2-10min', 30000); report.checks.resource = 'klima-v2-10min';
  await selectStation(page); report.checks.station_id = String(fixture.station_id);
  const from = await setDate(page, 'From date (UTC)', fixture.ui_start_date);
  const through = await setDate(page, 'Through date (UTC)', fixture.ui_end_date);
  report.checks.date_interval = { from, through };
  for (const provider of fixture.required_provider_parameters) await selectProvider(page, provider);
  report.checks.selected_provider_parameters = [...fixture.required_provider_parameters];
  const frame = await appFrame(page, 'Measured variables to load', 30000);
  const load = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  if (!(await load.count().catch(() => 0))) throw new Error('GeoSphere load button missing.');
  await load.click({ timeout: 15000 });
  await openPrecipitation(page); report.checks.precipitation_page_opened = true;
  const options = await analysisOptions(page); report.checks.analysis_options = options;
  const expected = ['Precipitation totals', 'Annual precipitation indices', 'Liquid precipitation explorer', 'Precipitation-record occurrence', 'Measured precipitation duration', 'Snow-cover duration', 'Snow-season indices'];
  if (fixture.hourly_snow_available) expected.push('Snow depth explorer');
  const missing = expected.filter((value) => !options.includes(value));
  if (missing.length) throw new Error(`Missing precipitation/snow analysis option(s): ${missing.join(', ')}`);
  if (report.page_errors.length) throw new Error(`Browser page error(s): ${report.page_errors.join(' | ')}`);
  await page.screenshot({ path: path.join(OUT_DIR, 'precipitation-snow-final.png'), fullPage: true });
  report.success = true;
} catch (error) {
  report.error = String(error?.stack || error);
  if (page) await page.screenshot({ path: path.join(OUT_DIR, 'precipitation-snow-failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await fs.writeFile(path.join(OUT_DIR, 'pr83-precip-snow-live-smoke.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (browser) await browser.close().catch(() => {});
}
