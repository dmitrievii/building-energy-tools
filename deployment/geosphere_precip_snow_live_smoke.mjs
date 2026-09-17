import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'https://building-climate-analyzer.streamlit.app/';
const FIXTURE_PATH = process.env.GEOSPHERE_SMOKE_FIXTURE || 'artifacts/geosphere-precip-snow-smoke/provider-fixture.json';
const OUT_DIR = process.env.AUDIT_OUTPUT_DIR || 'artifacts/geosphere-precip-snow-smoke';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));

await fs.mkdir(OUT_DIR, { recursive: true });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function bodyText(frame) {
  try {
    return await frame.locator('body').innerText({ timeout: 2_000 });
  } catch {
    return '';
  }
}

async function waitForFrameContaining(page, text, timeoutMs = 90_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      const textContent = await bodyText(frame);
      if (textContent.includes(text)) return frame;
    }
    await sleep(400);
  }
  throw new Error(`Timed out waiting for app text: ${text}`);
}

async function waitForText(frame, text, timeoutMs = 90_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const textContent = await bodyText(frame);
    if (textContent.includes(text)) return textContent;
    await sleep(400);
  }
  throw new Error(`Timed out waiting for text: ${text}`);
}

async function clickChoice(frame, name) {
  // Match the strategy used by the stable general live audit: click the
  // visible Streamlit label text first. Clicking the hidden BaseWeb radio input
  // can change DOM checked-state without sending Streamlit's widget event.
  const exactText = frame.getByText(name, { exact: true });
  if (await exactText.count()) {
    await exactText.last().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }

  const label = frame.locator('label').filter({ hasText: name });
  if (await label.count()) {
    await label.last().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }

  const radio = frame.getByRole('radio', { name, exact: true });
  if (await radio.count()) {
    await radio.first().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }
  const tab = frame.getByRole('tab', { name, exact: true });
  if (await tab.count()) {
    await tab.first().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }
  const fuzzyText = frame.getByText(name, { exact: false });
  if (await fuzzyText.count()) {
    await fuzzyText.last().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }
  throw new Error(`Could not locate choice: ${name}`);
}

async function labelledInput(frame, label) {
  const labelled = frame.getByLabel(label, { exact: true });
  if (await labelled.count()) return labelled.first();
  const aria = frame.locator(`input[aria-label="${label}"]`).first();
  if (await aria.count()) return aria;
  const text = frame.getByText(label, { exact: true }).first();
  if (await text.count()) {
    const container = text.locator('xpath=..');
    const input = container.locator('input').first();
    if (await input.count()) return input;
  }
  throw new Error(`Could not locate input: ${label}`);
}

async function fillInput(frame, label, value) {
  const input = await labelledInput(frame, label);
  await input.fill(String(value), { timeout: 15_000 });
  await input.press('Tab').catch(() => {});
}

function dateValueMatches(value, iso) {
  const [year, month, day] = iso.split('-').map(Number);
  const parts = String(value).split(/\D+/).filter(Boolean).map(Number);
  return parts.includes(year) && parts.includes(month) && parts.includes(day);
}

async function setDateInput(frame, label, iso) {
  const displayCandidates = [iso.replaceAll('-', '/'), iso];
  let lastValue = null;
  for (const candidate of displayCandidates) {
    const input = await labelledInput(frame, label);
    await input.click({ timeout: 15_000 });
    await input.fill(candidate, { timeout: 15_000 });
    await input.press('Enter').catch(() => {});
    await input.press('Tab').catch(() => {});
    await sleep(1_200);
    const refreshed = await labelledInput(frame, label);
    lastValue = await refreshed.inputValue().catch(() => null);
    if (dateValueMatches(lastValue, iso)) return lastValue;
  }
  throw new Error(`Date input ${label} did not accept ${iso}; observed value=${lastValue}`);
}

async function analysisCombo(frame) {
  const byRole = frame.getByRole('combobox', { name: 'Analysis type', exact: true });
  if (await byRole.count()) return byRole.first();
  const labelled = frame.getByLabel('Analysis type', { exact: true });
  if (await labelled.count()) return labelled.first();
  const label = frame.getByText('Analysis type', { exact: true }).first();
  if (await label.count()) {
    const parent = label.locator('xpath=..');
    const combo = parent.locator('[role="combobox"]').first();
    if (await combo.count()) return combo;
  }
  throw new Error('Could not locate Analysis type selectbox.');
}

async function analysisOptions(frame) {
  const combo = await analysisCombo(frame);
  await combo.click({ timeout: 15_000 });
  await sleep(400);
  let options = await frame.getByRole('option').allInnerTexts().catch(() => []);
  if (!options.length) {
    options = await frame.locator('[data-baseweb="menu"] li').allInnerTexts().catch(() => []);
  }
  return [...new Set(options.map((value) => value.trim()).filter(Boolean))];
}

async function selectAnalysis(frame, name) {
  const combo = await analysisCombo(frame);
  await combo.click({ timeout: 15_000 });
  await sleep(250);
  const roleOption = frame.getByRole('option', { name, exact: true });
  if (await roleOption.count()) {
    await roleOption.last().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }
  const textOption = frame.getByText(name, { exact: true });
  if (await textOption.count()) {
    await textOption.last().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }
  throw new Error(`Analysis option not found: ${name}`);
}

const report = {
  schema: 'climate-analyzer-geosphere-precip-snow-live-smoke-v2',
  target_url: TARGET_URL,
  fixture,
  started_at_utc: new Date().toISOString(),
  page_errors: [],
  console_errors: [],
  http_errors: [],
  checks: {},
  success: false,
  error: null,
};

let browser;
let page;
try {
  if (!fixture.success) throw new Error(`Provider probe did not produce a valid fixture: ${fixture.error ?? 'unknown'}`);

  browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'en-US' });
  page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => {
    if (message.type() === 'error') report.console_errors.push(message.text());
  });
  page.on('response', (response) => {
    if (response.status() >= 400) report.http_errors.push({ status: response.status(), url: response.url() });
  });

  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  let appFrame = await waitForFrameContaining(page, 'Climate Analyzer');
  report.checks.app_visible = true;

  const initialText = await bodyText(appFrame);
  if (/resource limits|gone over its resource limits/i.test(initialText)) {
    throw new Error('Streamlit resource-limit page detected.');
  }

  await clickChoice(appFrame, 'GeoSphere Austria');
  appFrame = await waitForFrameContaining(page, 'GeoSphere Austria — measured historical station data');
  report.checks.geosphere_source_opened = true;

  await fillInput(appFrame, 'Search GeoSphere station', fixture.station_id);
  await waitForText(appFrame, 'Visible GeoSphere stations after filters:');
  await waitForText(appFrame, `ID ${fixture.station_id}`);
  report.checks.station_selected = `${fixture.station_name} (${fixture.station_id})`;

  const fromValue = await setDateInput(appFrame, 'From date (UTC)', fixture.ui_start_date);
  const throughValue = await setDateInput(appFrame, 'Through date (UTC)', fixture.ui_end_date);
  report.checks.date_interval = {
    requested_start: fixture.ui_start_date,
    requested_end: fixture.ui_end_date,
    rendered_start: fromValue,
    rendered_end: throughValue,
  };

  const loadButton = appFrame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true });
  if (!(await loadButton.count())) throw new Error('GeoSphere load button not found.');
  await loadButton.first().click({ timeout: 15_000 });

  appFrame = await waitForFrameContaining(page, 'Precipitation and Snow', 180_000);
  report.checks.provider_interval_loaded = true;
  await clickChoice(appFrame, 'Precipitation and Snow');
  await waitForText(appFrame, 'Dual-resolution semantics:', 60_000);
  await waitForText(appFrame, 'Precipitation and snow', 60_000);
  report.checks.precipitation_page_opened = true;

  const expectedOptions = [
    'Precipitation totals',
    'Annual precipitation indices',
    'Liquid precipitation explorer',
    'Precipitation-record occurrence',
    'Measured precipitation duration',
    'Snow-cover duration',
    'Snow-season indices',
  ];
  if (fixture.hourly_snow_available) expectedOptions.push('Snow depth explorer');

  const options = await analysisOptions(appFrame);
  report.checks.analysis_options = options;
  report.checks.hourly_snow_available = Boolean(fixture.hourly_snow_available);
  const missing = expectedOptions.filter((value) => !options.includes(value));
  if (missing.length) throw new Error(`Missing precipitation/snow analysis option(s): ${missing.join(', ')}`);
  if (!fixture.hourly_snow_available && options.includes('Snow depth explorer')) {
    throw new Error('Snow depth explorer was exposed despite no strict-complete hourly snow state in the provider probe.');
  }
  await page.keyboard.press('Escape').catch(() => {});

  await selectAnalysis(appFrame, 'Annual precipitation indices');
  await waitForText(appFrame, 'Wet day ≥ 1 mm/day', 60_000);
  report.checks.annual_precipitation_indices = true;

  await selectAnalysis(appFrame, 'Measured precipitation duration');
  await waitForText(appFrame, 'never inferred from precipitation depth rr', 60_000);
  report.checks.measured_precipitation_duration = true;

  await selectAnalysis(appFrame, 'Precipitation-record occurrence');
  await waitForText(appFrame, 'record-occurrence metric, not rainfall duration', 60_000);
  report.checks.native_precipitation_occurrence = true;

  await selectAnalysis(appFrame, 'Snow-cover duration');
  await waitForText(appFrame, 'source-state cadence', 60_000);
  report.checks.native_snow_cover_duration = true;

  await selectAnalysis(appFrame, 'Snow-season indices');
  await waitForText(appFrame, 'July–June analysis year', 60_000);
  report.checks.snow_season_indices = true;

  if (report.page_errors.length) {
    throw new Error(`Uncaught browser page error(s): ${report.page_errors.join(' | ')}`);
  }

  await page.screenshot({
    path: path.join(OUT_DIR, 'precipitation-snow-final.png'),
    fullPage: true,
  });
  report.success = true;
} catch (error) {
  report.error = String(error);
  if (page) {
    await page.screenshot({
      path: path.join(OUT_DIR, 'precipitation-snow-failure.png'),
      fullPage: true,
    }).catch(() => {});
  }
  process.exitCode = 1;
} finally {
  report.completed_at_utc = new Date().toISOString();
  await fs.writeFile(
    path.join(OUT_DIR, 'geosphere-precip-snow-live-smoke.json'),
    JSON.stringify(report, null, 2),
  );
  const summary = [
    '# GeoSphere precipitation/snow live smoke',
    '',
    `- Target: ${TARGET_URL}`,
    `- Station: ${fixture.station_name ?? 'unresolved'} (ID ${fixture.station_id ?? 'n/a'})`,
    `- Provider/browser interval: ${fixture.ui_start_date ?? 'n/a'} → ${fixture.ui_end_date ?? 'n/a'}`,
    `- Native valid records: ${JSON.stringify(fixture.native_valid_records ?? {})}`,
    `- Hourly valid records: ${JSON.stringify(fixture.hourly_valid_records ?? {})}`,
    `- Strict-complete hourly snow available: ${fixture.hourly_snow_available ?? 'n/a'}`,
    `- Success: ${report.success}`,
    `- Page errors: ${report.page_errors.length}`,
    `- Browser HTTP 4xx/5xx observed: ${report.http_errors.length}`,
    `- Error: ${report.error ?? 'none'}`,
    '',
    '## Checks',
    '',
    ...Object.entries(report.checks).map(([key, value]) => `- ${key}: ${JSON.stringify(value)}`),
    '',
    '> This workflow is provider-backed operational evidence. GeoSphere availability is intentionally isolated from the core Climate Analyzer CI gate.',
    '',
  ].join('\n');
  await fs.writeFile(path.join(OUT_DIR, 'LIVE_SMOKE.md'), summary);
  console.log(summary);
  if (browser) await browser.close();
}
