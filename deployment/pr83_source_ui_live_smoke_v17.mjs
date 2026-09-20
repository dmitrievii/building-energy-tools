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
const HOURLY_INFO = 'Official GeoSphere Austria availability context (translated summary)';
const HOURLY_SOURCE = 'Authoritative source: GeoSphere Austria Stationsdaten-v2 (1 h)';

function occurrences(text, needle) {
  return text.split(needle).length - 1;
}

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
    await sleep(250);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}

async function combo(frame, label, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const byRole = frame.getByRole('combobox', { name: label, exact: true }).first();
    if (await byRole.count().catch(() => 0) && await byRole.isVisible().catch(() => false)) return byRole;
    const byLabel = frame.getByLabel(label, { exact: true }).first();
    if (await byLabel.count().catch(() => 0) && await byLabel.isVisible().catch(() => false)) return byLabel;
    await sleep(250);
  }
  throw new Error(`Timed out waiting for combobox: ${label}`);
}

async function renderedControlText(control) {
  return [
    await control.innerText().catch(() => ''),
    await control.textContent().catch(() => ''),
    await control.inputValue().catch(() => ''),
  ].join(' ').replace(/\s+/g, ' ').trim();
}

async function chooseSource(page) {
  const started = performance.now();
  while (performance.now() - started < 60_000) {
    const frame = await appFrame(page, 'Climate Analyzer', 10_000);
    const candidates = [
      frame.getByRole('radio', { name: 'GeoSphere Austria', exact: true }).last(),
      frame.getByText('GeoSphere Austria', { exact: true }).last(),
      frame.locator('label').filter({ hasText: 'GeoSphere Austria' }).last(),
    ];
    for (const candidate of candidates) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try {
        const tag = await candidate.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
        const type = await candidate.getAttribute('type').catch(() => null);
        if (tag === 'input' && type === 'radio') await candidate.check({ force: true, timeout: 5_000 });
        else await candidate.click({ force: true, timeout: 5_000 });
        return await appFrame(page, 'GeoSphere Austria — measured historical station data', 15_000);
      } catch { /* try another candidate */ }
    }
    await sleep(400);
  }
  throw new Error('Could not select GeoSphere Austria source.');
}

async function waitComboContains(page, label, needle, timeoutMs = 30_000) {
  const started = performance.now();
  let rendered = '';
  while (performance.now() - started < timeoutMs) {
    try {
      const frame = await appFrame(page, 'Climate Analyzer', 5_000);
      const control = await combo(frame, label, 5_000);
      rendered = await renderedControlText(control);
      if (rendered.includes(needle)) return frame;
    } catch { /* rerun in flight */ }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for ${label}=${needle}. Last rendered value: ${rendered}`);
}

async function selectDataset(page, labelNeedle, resourceId) {
  const started = performance.now();
  let lastOptions = [];
  while (performance.now() - started < 60_000) {
    let frame;
    try { frame = await appFrame(page, 'Climate Analyzer', 5_000); }
    catch { await sleep(250); continue; }
    let control;
    try { control = await combo(frame, 'GeoSphere dataset', 5_000); }
    catch { await sleep(250); continue; }

    try {
      await control.scrollIntoViewIfNeeded({ timeout: 3_000 }).catch(() => {});
      await control.click({ timeout: 5_000 });
    } catch { await sleep(300); continue; }

    const optionStarted = performance.now();
    let selected = false;
    while (performance.now() - optionStarted < 5_000 && !selected) {
      for (const options of [frame.getByRole('option'), page.getByRole('option'), frame.locator('[data-baseweb="menu"] li'), page.locator('[data-baseweb="menu"] li')]) {
        const count = await options.count().catch(() => 0);
        if (!count) continue;
        lastOptions = await options.allInnerTexts().catch(() => lastOptions);
        for (let i = 0; i < count; i += 1) {
          const option = options.nth(i);
          const text = await option.innerText().catch(() => '');
          if (!text.includes(labelNeedle) || !(await option.isVisible().catch(() => false))) continue;
          await option.click({ timeout: 8_000 });
          selected = true;
          break;
        }
        if (selected) break;
      }
      if (!selected) await sleep(200);
    }
    if (!selected) {
      await page.keyboard.press('Escape').catch(() => {});
      await sleep(300);
      continue;
    }

    await waitComboContains(page, 'GeoSphere dataset', labelNeedle, 30_000);
    try {
      return await appFrame(page, `Selected resource: ${resourceId}`, 45_000);
    } catch { await sleep(500); }
  }
  throw new Error(`Could not commit GeoSphere dataset ${labelNeedle} (${resourceId}). Last options: ${lastOptions.join(' | ')}`);
}

async function labelledInput(frame, label, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const byLabel = frame.getByLabel(label, { exact: true }).first();
    if (await byLabel.count().catch(() => 0) && await byLabel.isVisible().catch(() => false)) return byLabel;
    const aria = frame.locator(`input[aria-label="${label}"]`).first();
    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return aria;
    await sleep(250);
  }
  throw new Error(`Timed out waiting for input: ${label}`);
}

async function filterStation(page, stationName, stationId) {
  let frame = await appFrame(page, 'Search GeoSphere station', 60_000);
  const input = await labelledInput(frame, 'Search GeoSphere station');
  await input.fill(String(stationName), { timeout: 15_000 });
  await input.press('Tab').catch(() => {});
  frame = await appFrame(page, 'Visible GeoSphere stations after filters:', 60_000);

  const started = performance.now();
  let lastCount = null;
  let lastRendered = '';
  while (performance.now() - started < 60_000) {
    frame = await appFrame(page, 'Climate Analyzer', 5_000);
    const text = await bodyText(frame);
    const match = text.match(/Visible GeoSphere stations after filters:\s*([\d,]+)/);
    lastCount = match ? Number(match[1].replaceAll(',', '')) : null;
    if (lastCount === 1) {
      try {
        const stationCombo = await combo(frame, 'Search-result stations', 5_000);
        lastRendered = await renderedControlText(stationCombo);
        if (lastRendered.includes(stationName) || lastRendered.includes(`ID ${stationId}`)) return frame;
      } catch { /* rerun in flight */ }
      if (text.includes('Selected station') && text.includes(stationName)) return frame;
    }
    await sleep(300);
  }
  throw new Error(`Station filter did not settle on ${stationName} (ID ${stationId}); visibleCount=${lastCount}, control=${lastRendered}`);
}

async function waitBody(page, predicate, description, timeoutMs = 60_000, stablePasses = 2) {
  const started = performance.now();
  let passes = 0;
  let lastText = '';
  let lastFrame = null;
  while (performance.now() - started < timeoutMs) {
    try {
      lastFrame = await appFrame(page, 'Climate Analyzer', 5_000);
      lastText = await bodyText(lastFrame);
      if (predicate(lastText)) {
        passes += 1;
        if (passes >= stablePasses) return { frame: lastFrame, text: lastText };
      } else passes = 0;
    } catch { passes = 0; }
    await sleep(400);
  }
  throw new Error(`Timed out waiting for ${description}. Resource: ${lastText.match(/Selected resource:[^\n]*/)?.[0] || 'unavailable'}`);
}

async function expandMonthlyContext(frame) {
  const expander = frame.getByText(MONTHLY_CONTEXT, { exact: true }).last();
  if (await expander.count().catch(() => 0)) {
    await expander.click({ force: true, timeout: 10_000 }).catch(() => {});
    await sleep(350);
  }
}

const report = {
  schema: 'climate-analyzer-pr83-source-ui-smoke-v17',
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

  await chooseSource(page);
  await selectDataset(page, '1 month', 'klima-v2-1m');
  await filterStation(page, fixture.station_name, fixture.station_id);

  const monthly = await waitBody(page, (text) => (
    text.includes('Selected resource: klima-v2-1m') &&
    text.includes('Parameter set') &&
    text.includes(MONTHLY_CONTEXT)
  ), 'monthly source UI');
  await expandMonthlyContext(monthly.frame);
  const monthlyExpanded = await waitBody(page, (text) => (
    text.includes('Core variables') &&
    text.includes('Core + additional statistics') &&
    text.includes('All provider parameters') &&
    occurrences(text, MONTHLY_CONTEXT) === 1 &&
    occurrences(text, MONTHLY_SOURCE) === 1
  ), 'expanded monthly source UI');
  if (monthlyExpanded.text.includes('Parameter catalogue')) throw new Error('Legacy monthly Parameter catalogue is still visible.');
  report.checks.monthly_context_count = occurrences(monthlyExpanded.text, MONTHLY_CONTEXT);
  report.checks.monthly_source_block_count = occurrences(monthlyExpanded.text, MONTHLY_SOURCE);
  report.checks.monthly_parameter_sets = ['Core variables', 'Core + additional statistics', 'All provider parameters'];

  await selectDataset(page, '1 h (long-term)', 'klima-v2-1h');
  await filterStation(page, fixture.station_name, fixture.station_id);
  const hourly = await waitBody(page, (text) => (
    text.includes('Selected resource: klima-v2-1h') &&
    text.includes('Station metadata validity') &&
    occurrences(text, HOURLY_INFO) === 1 &&
    occurrences(text, HOURLY_SOURCE) === 1
  ), 'hourly source UI', 90_000, 3);
  if (hourly.text.includes(MONTHLY_CONTEXT) || hourly.text.includes('Parameter set')) {
    throw new Error('Monthly-only controls remained visible after committing the hourly resource.');
  }
  report.checks.hourly_context_count = occurrences(hourly.text, HOURLY_INFO);
  report.checks.hourly_source_block_count = occurrences(hourly.text, HOURLY_SOURCE);
  report.checks.hourly_station_metadata_visible = true;

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
