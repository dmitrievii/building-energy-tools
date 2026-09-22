import fs from 'node:fs/promises';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8501/';
const FIXTURE_PATH = process.env.PR83_MONTHLY_FIXTURE || 'artifacts/pr83-contract-smoke/monthly-provider.json';
const OUT_PATH = process.env.PR83_UI_REPORT || 'artifacts/pr83-contract-smoke/source-ui.json';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const MONTHLY_SOURCE = 'Official source: GeoSphere Austria Station Data-v2 (1 m)';
const MONTHLY_CONTEXT = 'About this GeoSphere monthly dataset';
const RESOURCE_CONTEXT = 'Official GeoSphere Austria availability context (translated summary)';

function occurrences(text, needle) { return text.split(needle).length - 1; }
async function bodyText(frame) { try { return await frame.locator('body').innerText({ timeout: 2000 }); } catch { return ''; } }

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
    for (const candidate of [frame.getByRole('combobox', { name: label, exact: true }).first(), frame.getByLabel(label, { exact: true }).first()]) {
      if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for combobox: ${label}`);
}

async function rendered(control) { return [await control.innerText().catch(() => ''), await control.textContent().catch(() => ''), await control.inputValue().catch(() => '')].join(' ').replace(/\s+/g, ' ').trim(); }
async function visibleOption(page, frame, predicate) {
  for (const options of [frame.getByRole('option'), page.getByRole('option'), frame.locator('[data-baseweb="menu"] li'), page.locator('[data-baseweb="menu"] li')]) {
    const count = await options.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const option = options.nth(i); if (!(await option.isVisible().catch(() => false))) continue;
      const text = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim(); if (predicate(text)) return option;
    }
  }
  return null;
}
async function chooseSource(page) {
  const frame = await appFrame(page, 'Climate Analyzer');
  for (const candidate of [frame.getByRole('radio', { name: 'GeoSphere Austria', exact: true }).last(), frame.getByText('GeoSphere Austria', { exact: true }).last(), frame.locator('label').filter({ hasText: 'GeoSphere Austria' }).last()]) {
    if (await candidate.count().catch(() => 0)) { await candidate.click({ force: true, timeout: 5000 }).catch(() => {}); if ((await bodyText(await appFrame(page, 'GeoSphere Austria — measured historical station data', 15000))).includes('GeoSphere dataset')) return; }
  }
  throw new Error('Could not select GeoSphere Austria.');
}
async function selectDataset(page, optionNeedle, resourceId) {
  const started = performance.now();
  while (performance.now() - started < 60000) {
    const frame = await appFrame(page, 'Climate Analyzer', 5000); const control = await combo(frame, 'GeoSphere dataset', 5000);
    const text = await bodyText(frame); if ((await rendered(control)).includes(optionNeedle) && text.includes(`Selected resource: ${resourceId}`)) return frame;
    await control.click({ timeout: 5000 }).catch(() => {}); const option = await visibleOption(page, frame, (value) => value.includes(optionNeedle)); if (option) await option.click({ timeout: 8000 }).catch(() => {}); await sleep(500);
  }
  throw new Error(`Could not commit ${resourceId}.`);
}
async function labelledInput(frame, label, timeoutMs = 60000) {
  const started = performance.now(); while (performance.now() - started < timeoutMs) {
    for (const candidate of [frame.getByLabel(label, { exact: true }).first(), frame.locator(`input[aria-label="${label}"]`).first()]) if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    await sleep(250);
  } throw new Error(`Input not found: ${label}`);
}
async function selectExactStation(page, stationName, stationId) {
  let frame = await appFrame(page, 'Search GeoSphere station', 60000); const search = await labelledInput(frame, 'Search GeoSphere station'); await search.fill(String(stationName)); await search.press('Tab').catch(() => {}); frame = await appFrame(page, 'Manual station selection', 60000);
  const control = await combo(frame, 'Search-result stations'); await control.click(); const option = await visibleOption(page, frame, (text) => text.includes(stationName) && (text.includes(`ID ${stationId}`) || text.includes(String(stationId)))); if (!option) throw new Error(`Station option missing: ${stationName} ${stationId}`); await option.click(); await sleep(500);
  frame = await appFrame(page, 'Manual station selection', 30000); const button = frame.getByRole('button', { name: 'Use station from list', exact: true }).first(); await button.click({ timeout: 15000 }); return appFrame(page, 'Measured variables to load', 60000);
}
async function waitBody(page, predicate, description, timeoutMs = 60000, stable = 2) {
  const started = performance.now(); let passes = 0; let lastText = ''; let frame;
  while (performance.now() - started < timeoutMs) { try { frame = await appFrame(page, 'Climate Analyzer', 5000); lastText = await bodyText(frame); if (predicate(lastText)) { passes += 1; if (passes >= stable) return { frame, text: lastText }; } else passes = 0; } catch { passes = 0; } await sleep(400); }
  throw new Error(`Timed out waiting for ${description}; resource=${lastText.match(/Selected resource:[^\n]*/)?.[0] || 'none'}`);
}
async function expandMonthly(frame) { const expander = frame.getByText(MONTHLY_CONTEXT, { exact: true }).last(); if (await expander.count().catch(() => 0)) { await expander.click({ force: true, timeout: 10000 }).catch(() => {}); await sleep(350); } }

const report = { schema: 'climate-analyzer-pr83-source-ui-smoke-v20', target_url: TARGET_URL, fixture, checks: {}, page_errors: [], console_errors: [], success: false, error: null };
let browser;
try {
  if (!fixture.success) throw new Error('Monthly provider fixture is not successful.');
  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' }); const page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error))); page.on('console', (message) => { if (message.type() === 'error') report.console_errors.push(message.text()); }); await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await chooseSource(page); await selectDataset(page, '1 month', 'klima-v2-1m'); await selectExactStation(page, fixture.station_name, fixture.station_id);
  const monthly = await waitBody(page, (text) => text.includes('Selected resource: klima-v2-1m') && text.includes('Parameter set') && text.includes(MONTHLY_CONTEXT) && occurrences(text, RESOURCE_CONTEXT) === 1, 'monthly source UI');
  await expandMonthly(monthly.frame);
  const monthlyExpanded = await waitBody(page, (text) => text.includes('Core variables') && text.includes('Core + additional statistics') && text.includes('All provider parameters') && occurrences(text, MONTHLY_CONTEXT) === 1 && occurrences(text, MONTHLY_SOURCE) === 1 && occurrences(text, RESOURCE_CONTEXT) === 1, 'expanded monthly source UI');
  if (monthlyExpanded.text.includes('Parameter catalogue')) throw new Error('Legacy monthly Parameter catalogue is still visible.');
  report.checks.monthly_context_count = occurrences(monthlyExpanded.text, RESOURCE_CONTEXT); report.checks.monthly_source_block_count = occurrences(monthlyExpanded.text, MONTHLY_SOURCE);
  await selectDataset(page, '1 h (long-term)', 'klima-v2-1h'); await selectExactStation(page, fixture.station_name, fixture.station_id);
  const hourly = await waitBody(page, (text) => text.includes('Selected resource: klima-v2-1h') && text.includes('Station metadata validity') && occurrences(text, RESOURCE_CONTEXT) === 1, 'hourly source UI', 90000, 3);
  if (hourly.text.includes(MONTHLY_CONTEXT) || hourly.text.includes('Parameter set')) throw new Error('Monthly-only controls remained visible for hourly resource.');
  report.checks.hourly_context_count = occurrences(hourly.text, RESOURCE_CONTEXT);
  if (report.page_errors.length) throw new Error(`Browser page error(s): ${report.page_errors.join(' | ')}`);
  report.success = true; await fs.mkdir('artifacts/pr83-contract-smoke', { recursive: true }); await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2)); console.log(JSON.stringify(report, null, 2));
} catch (error) { report.error = String(error?.stack || error); await fs.mkdir('artifacts/pr83-contract-smoke', { recursive: true }); await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2)); console.error(report.error); process.exitCode = 1; } finally { if (browser) await browser.close().catch(() => {}); }
