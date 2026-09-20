import fs from 'node:fs/promises';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8501/';
const FIXTURE_PATH = process.env.PR83_MONTHLY_FIXTURE || 'artifacts/pr83-contract-smoke/monthly-provider.json';
const OUT_PATH = process.env.PR83_UI_REPORT || 'artifacts/pr83-contract-smoke/source-ui.json';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function bodyText(frame) {
  try { return await frame.locator('body').innerText({ timeout: 2_000 }); }
  catch { return ''; }
}

async function appFrame(page, needle = 'Climate Analyzer', timeoutMs = 90_000) {
  const start = performance.now();
  while (performance.now() - start < timeoutMs) {
    for (const frame of page.frames()) {
      if ((await bodyText(frame)).includes(needle)) return frame;
    }
    await sleep(350);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}

async function chooseAndWait(page, name, expectedText, timeoutMs = 45_000) {
  const started = performance.now();
  let attempts = 0;
  while (performance.now() - started < timeoutMs) {
    attempts += 1;
    let frame;
    try { frame = await appFrame(page, 'Climate Analyzer', 10_000); }
    catch { await sleep(500); continue; }

    const candidates = [
      frame.locator('label').filter({ hasText: name }).last(),
      frame.getByText(name, { exact: true }).last(),
      frame.getByRole('radio', { name, exact: true }).last(),
    ];
    for (const candidate of candidates) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try {
        await candidate.scrollIntoViewIfNeeded({ timeout: 5_000 }).catch(() => {});
        const tagName = await candidate.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
        const inputType = await candidate.getAttribute('type').catch(() => null);
        if (tagName === 'input' && inputType === 'radio') await candidate.check({ force: true, timeout: 5_000 });
        else await candidate.click({ force: true, timeout: 5_000 });
      } catch { continue; }

      const verifyStarted = performance.now();
      while (performance.now() - verifyStarted < 6_000) {
        for (const currentFrame of page.frames()) {
          if ((await bodyText(currentFrame)).includes(expectedText)) return { frame: currentFrame, attempts };
        }
        await sleep(300);
      }
    }
    await sleep(700);
  }
  throw new Error(`Timed out selecting ${name} and waiting for: ${expectedText}`);
}

async function chooseSource(page) {
  const opened = await chooseAndWait(
    page,
    'GeoSphere Austria',
    'GeoSphere Austria — measured historical station data',
    45_000,
  );
  return opened.frame;
}

async function labelledInput(frame, label, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const labelled = frame.getByLabel(label, { exact: true }).first();
    if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) return labelled;

    const aria = frame.locator(`input[aria-label="${label}"]`).first();
    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return aria;

    const domLabels = frame.locator('label').filter({ hasText: label });
    const count = await domLabels.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const input = domLabels.nth(index).locator('input').first();
      if (await input.count().catch(() => 0) && await input.isVisible().catch(() => false)) return input;
    }

    const text = frame.getByText(label, { exact: true }).first();
    if (await text.count().catch(() => 0)) {
      for (const container of [text.locator('xpath=..'), text.locator('xpath=../..'), text.locator('xpath=../../..')]) {
        const input = container.locator('input').first();
        if (await input.count().catch(() => 0) && await input.isVisible().catch(() => false)) return input;
      }
    }
    await sleep(300);
  }
  throw new Error(`Timed out waiting for visible input: ${label}`);
}

async function findCombo(frame, label) {
  let combo = frame.getByRole('combobox', { name: label, exact: true }).first();
  if (!(await combo.count().catch(() => 0))) combo = frame.getByLabel(label, { exact: true }).first();
  if (!(await combo.count().catch(() => 0))) throw new Error(`Combobox not found: ${label}`);
  return combo;
}

async function selectComboContains(page, frame, label, optionNeedle) {
  const combo = await findCombo(frame, label);
  await combo.click({ timeout: 15_000 });
  await sleep(250);
  let options = frame.getByRole('option');
  let texts = await options.allInnerTexts().catch(() => []);
  let index = texts.findIndex((value) => value.includes(optionNeedle));
  if (index < 0) {
    options = frame.locator('[data-baseweb="menu"] li');
    texts = await options.allInnerTexts().catch(() => []);
    index = texts.findIndex((value) => value.includes(optionNeedle));
  }
  if (index < 0) throw new Error(`No option containing ${optionNeedle} in ${label}. Options: ${texts.join(' | ')}`);
  await options.nth(index).click({ timeout: 15_000 });
  await sleep(1_200);
  return await appFrame(page);
}

async function fillStationSearch(page, frame, stationId) {
  const input = await labelledInput(frame, 'Search GeoSphere station', 60_000);
  await input.fill(String(stationId), { timeout: 15_000 });
  await input.press('Tab').catch(() => {});
  return await appFrame(page, 'Visible GeoSphere stations after filters:', 60_000);
}

async function selectStation(page, frame, stationId, stationName) {
  frame = await appFrame(page, 'Manual station selection', 60_000);
  const combo = await findCombo(frame, 'Search-result stations');
  await combo.click({ timeout: 15_000 });
  await sleep(300);
  const needle = `ID ${stationId}`;
  let options = frame.getByRole('option');
  let texts = await options.allInnerTexts().catch(() => []);
  let index = texts.findIndex((value) => value.includes(needle) || value.includes(stationName));
  if (index < 0) {
    options = frame.locator('[data-baseweb="menu"] li');
    texts = await options.allInnerTexts().catch(() => []);
    index = texts.findIndex((value) => value.includes(needle) || value.includes(stationName));
  }
  if (index < 0) throw new Error(`Station option not found: ${stationName} (${stationId})`);
  await options.nth(index).click({ timeout: 15_000 });
  await sleep(500);
  const use = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
  if (!(await use.count().catch(() => 0))) throw new Error('Use station from list button not found.');
  await use.click({ timeout: 15_000 });
  return await appFrame(page, 'Selected station', 60_000);
}

async function expandMonthlyContext(frame) {
  const label = 'About this GeoSphere monthly dataset';
  const exact = frame.getByText(label, { exact: true }).last();
  if (await exact.count().catch(() => 0)) {
    await exact.click({ force: true, timeout: 10_000 }).catch(() => {});
    await sleep(400);
    return;
  }
  const summary = frame.locator('summary').filter({ hasText: label }).last();
  if (await summary.count().catch(() => 0)) {
    await summary.click({ force: true, timeout: 10_000 }).catch(() => {});
    await sleep(400);
  }
}

function occurrences(text, needle) {
  return text.split(needle).length - 1;
}

const report = {
  schema: 'climate-analyzer-pr83-source-ui-smoke-v3',
  target_url: TARGET_URL,
  fixture,
  checks: {},
  page_errors: [],
  console_errors: [],
  success: false,
  error: null,
};

let browser;
try {
  if (!fixture.success) throw new Error('Monthly provider fixture is not successful.');
  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  const page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => { if (message.type() === 'error') report.console_errors.push(message.text()); });
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });

  let frame = await chooseSource(page);
  frame = await selectComboContains(page, frame, 'GeoSphere dataset', '1 month');
  frame = await fillStationSearch(page, frame, fixture.station_id);
  frame = await selectStation(page, frame, fixture.station_id, fixture.station_name);
  frame = await appFrame(page, 'Parameter set', 60_000);
  await expandMonthlyContext(frame);
  const monthlyText = await bodyText(frame);

  const requiredSets = ['Core variables', 'Core + additional statistics', 'All provider parameters'];
  for (const name of requiredSets) {
    if (!monthlyText.includes(name)) throw new Error(`Monthly Parameter set option missing: ${name}`);
  }
  if (monthlyText.includes('Parameter catalogue')) throw new Error('Legacy monthly Parameter catalogue control is still visible.');
  const monthlySourceNeedle = 'Official source: GeoSphere Austria Station Data-v2 (1 m)';
  if (occurrences(monthlyText, monthlySourceNeedle) !== 1) {
    throw new Error(`Expected one monthly official-source block, found ${occurrences(monthlyText, monthlySourceNeedle)}.`);
  }
  if (occurrences(monthlyText, 'About this GeoSphere monthly dataset') !== 1) {
    throw new Error('Monthly dataset context expander is missing or duplicated.');
  }
  report.checks.monthly_parameter_sets = requiredSets;
  report.checks.monthly_source_block_count = occurrences(monthlyText, monthlySourceNeedle);
  report.checks.monthly_context_count = occurrences(monthlyText, 'About this GeoSphere monthly dataset');

  frame = await selectComboContains(page, frame, 'GeoSphere dataset', '1 h (long-term)');
  frame = await fillStationSearch(page, frame, fixture.station_id);
  frame = await selectStation(page, frame, fixture.station_id, fixture.station_name);
  frame = await appFrame(page, 'Official GeoSphere Austria availability context', 60_000);
  const hourlyText = await bodyText(frame);
  const hourlyInfoNeedle = 'Official GeoSphere Austria availability context (translated summary)';
  const hourlySourceNeedle = 'Authoritative source: GeoSphere Austria Stationsdaten-v2 (1 h)';
  if (occurrences(hourlyText, hourlyInfoNeedle) !== 1) {
    throw new Error(`Expected one hourly availability context, found ${occurrences(hourlyText, hourlyInfoNeedle)}.`);
  }
  if (occurrences(hourlyText, hourlySourceNeedle) !== 1) {
    throw new Error(`Expected one hourly authoritative-source caption, found ${occurrences(hourlyText, hourlySourceNeedle)}.`);
  }
  report.checks.hourly_context_count = occurrences(hourlyText, hourlyInfoNeedle);
  report.checks.hourly_source_block_count = occurrences(hourlyText, hourlySourceNeedle);

  if (report.page_errors.length) throw new Error(`Browser page error(s): ${report.page_errors.join(' | ')}`);
  report.success = true;
  await fs.mkdir('artifacts/pr83-contract-smoke', { recursive: true });
  await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  report.error = String(error?.stack || error);
  await fs.mkdir('artifacts/pr83-contract-smoke', { recursive: true });
  await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2));
  console.error(report.error);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close().catch(() => {});
}
