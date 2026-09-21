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
    for (const candidate of [
      frame.getByLabel(label, { exact: true }).first(),
      frame.locator(`input[aria-label="${label}"]`).first(),
    ]) {
      if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    }
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
  for (const options of [
    frame.getByRole('option'),
    page.getByRole('option'),
    frame.locator('[data-baseweb="menu"] li'),
    page.locator('[data-baseweb="menu"] li'),
  ]) {
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

async function selectVisibleOption(page, frame, controlLabel, predicate, timeoutMs = 60000) {
  const started = performance.now();
  let last = [];
  while (performance.now() - started < timeoutMs) {
    frame = await appFrame(page, 'Climate Analyzer', 5000);
    let control;
    try { control = await combo(frame, controlLabel, 5000); } catch { await sleep(250); continue; }
    try {
      await control.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => {});
      await control.click({ timeout: 5000 });
    } catch { await sleep(250); continue; }
    const optionStarted = performance.now();
    while (performance.now() - optionStarted < 6000) {
      for (const options of [
        frame.getByRole('option'),
        page.getByRole('option'),
        frame.locator('[data-baseweb="menu"] li'),
        page.locator('[data-baseweb="menu"] li'),
      ]) {
        const count = await options.count().catch(() => 0);
        if (!count) continue;
        last = await options.allInnerTexts().catch(() => last);
        for (let i = 0; i < count; i += 1) {
          const option = options.nth(i);
          const text = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
          if (!predicate(text) || !(await option.isVisible().catch(() => false))) continue;
          await option.click({ timeout: 8000 });
          return await appFrame(page, 'Climate Analyzer', 10000);
        }
      }
      await sleep(200);
    }
    await page.keyboard.press('Escape').catch(() => {});
    await sleep(300);
  }
  throw new Error(`Could not select ${controlLabel}; last options: ${last.join(' | ')}`);
}

async function chooseSource(page) {
  const started = performance.now();
  while (performance.now() - started < 60000) {
    const frame = await appFrame(page, 'Climate Analyzer', 10000);
    for (const candidate of [
      frame.getByRole('radio', { name: 'GeoSphere Austria', exact: true }).last(),
      frame.getByText('GeoSphere Austria', { exact: true }).last(),
      frame.locator('label').filter({ hasText: 'GeoSphere Austria' }).last(),
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

async function selectStation(page) {
  let frame = await appFrame(page, 'Search GeoSphere station', 60000);
  const search = await labelledInput(frame, 'Search GeoSphere station');
  await search.fill(String(fixture.station_name), { timeout: 15000 });
  await search.press('Tab').catch(() => {});
  frame = await appFrame(page, 'Manual station selection', 60000);

  const targetId = String(fixture.station_id);
  frame = await selectVisibleOption(
    page,
    frame,
    'Search-result stations',
    (text) => text.includes(fixture.station_name) && (text.includes(`ID ${targetId}`) || text.includes(targetId)),
    60000,
  );

  const settleStarted = performance.now();
  let lastControl = '';
  while (performance.now() - settleStarted < 30000) {
    frame = await appFrame(page, 'Climate Analyzer', 5000);
    try {
      lastControl = await rendered(await combo(frame, 'Search-result stations', 5000));
      if (lastControl.includes(fixture.station_name) && (lastControl.includes(`ID ${targetId}`) || lastControl.includes(targetId))) break;
    } catch {}
    await sleep(250);
  }
  if (!lastControl.includes(fixture.station_name) || (!lastControl.includes(`ID ${targetId}`) && !lastControl.includes(targetId))) {
    throw new Error(`Exact station ID ${targetId} did not settle; control=${lastControl}`);
  }

  const commitStarted = performance.now();
  while (performance.now() - commitStarted < 30000) {
    frame = await appFrame(page, 'Manual station selection', 5000);
    const button = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
    if (await button.count().catch(() => 0) && await button.isVisible().catch(() => false)) {
      await button.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
      await button.click({ timeout: 15000 });
      return await appFrame(page, 'Parameter set', 60000);
    }
    await sleep(250);
  }
  throw new Error('Use station from list button did not become available.');
}

async function selectParameterSet(page, name) {
  const started = performance.now();
  while (performance.now() - started < 30000) {
    const frame = await appFrame(page, 'Parameter set', 5000);
    const radio = frame.getByRole('radio', { name, exact: true }).last();
    if (await radio.count().catch(() => 0) && await radio.isVisible().catch(() => false)) {
      try {
        const tag = await radio.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
        if (tag === 'input') await radio.check({ force: true, timeout: 5000 });
        else await radio.click({ force: true, timeout: 5000 });
        await sleep(700);
        const refreshed = await appFrame(page, 'Measured variables to load', 10000);
        return { frame: refreshed, text: await bodyText(refreshed) };
      } catch {}
    }
    const label = frame.getByText(name, { exact: true }).last();
    if (await label.count().catch(() => 0) && await label.isVisible().catch(() => false)) {
      try {
        await label.click({ force: true, timeout: 5000 });
        await sleep(700);
        const refreshed = await appFrame(page, 'Measured variables to load', 10000);
        return { frame: refreshed, text: await bodyText(refreshed) };
      } catch {}
    }
    await sleep(250);
  }
  throw new Error(`Parameter set did not settle: ${name}`);
}

async function screenshot(page, name) {
  await page.screenshot({ path: path.join(OUT_DIR, name), fullPage: true });
}

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
    if (option) {
      await option.click({ timeout: 10000 });
      await sleep(700);
      return;
    }
    await sleep(200);
  }
  throw new Error(`Analysis option missing: ${name}`);
}

const report = {
  schema: 'climate-analyzer-pr83-extended-visual-v3',
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
  await selectStation(page);

  // Exercise the catalogue view transition itself without scripting Glide cells.
  // The product contract keeps provider selection keyed by provider ID, so opening
  // All provider parameters must not convert the 13 curated Core fields into an
  // all-provider load or clear them when returning to Core.
  const allView = await selectParameterSet(page, 'All provider parameters');
  report.checks.all_provider_view_visible = allView.text.includes('All provider parameters');
  report.checks.all_view_keeps_core_selection = allView.text.includes('13 selected measured variables') && allView.text.includes('monthly source data');
  await screenshot(page, '01-monthly-all-provider-catalogue.png');

  const coreView = await selectParameterSet(page, 'Core variables');
  report.checks.core_selection_restored = coreView.text.includes('13 selected measured variables') && coreView.text.includes('monthly source data');
  await screenshot(page, '02-monthly-core-roundtrip.png');

  const loadFrame = await appFrame(page, 'Measured variables to load', 30000);
  const load = loadFrame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  if (!(await load.count().catch(() => 0))) throw new Error('Load button missing.');
  await load.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
  await load.click({ timeout: 15000 });
  await appFrame(page, 'Summary — Overview', 180000);

  await nav(page, 'Summary — Overview', 'Climate overview');
  await screenshot(page, '03-monthly-overview.png');

  await nav(page, 'Climate — Temperature', 'Temperature and extremes');
  let text = await bodyText(await appFrame(page, 'Temperature and extremes', 30000));
  report.checks.temperature_no_threshold_sliders = !text.includes('Heating threshold [°C]') && !text.includes('Cooling threshold [°C]');
  await screenshot(page, '04-monthly-temperature.png');

  if (text.includes('Ground temperature')) {
    await selectAnalysis(page, 'Ground temperature');
    await appFrame(page, 'Ground temperature', 30000);
    await screenshot(page, '05-monthly-ground-temperature.png');
  }

  await nav(page, 'Climate — Moisture & psychrometrics', 'Humidity and psychrometrics');
  text = await bodyText(await appFrame(page, 'Humidity and psychrometrics', 30000));
  report.checks.station_pressure_in_humidity = text.includes('Station pressure');
  await selectAnalysis(page, 'Psychrometric chart');
  await appFrame(page, 'Psychrometric axes', 30000);
  await screenshot(page, '06-monthly-psychrometric.png');

  await nav(page, 'Explore — Time series & overlay', 'Time series');
  await screenshot(page, '07-monthly-overlay.png');

  if (!report.checks.all_provider_view_visible) throw new Error('All provider parameters view was not exposed.');
  if (!report.checks.all_view_keeps_core_selection) throw new Error('Opening All provider parameters changed the curated default selection.');
  if (!report.checks.core_selection_restored) throw new Error('Core selection did not survive the catalogue-view round trip.');
  if (!report.checks.temperature_no_threshold_sliders) throw new Error('Threshold-only sliders leaked into default Temperature analysis.');
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
