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
    await sleep(300);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}

async function chooseAndWait(page, name, expectedText, timeoutMs = 45_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    let frame;
    try { frame = await appFrame(page, 'Climate Analyzer', 10_000); }
    catch { await sleep(400); continue; }

    const candidates = [
      frame.locator('label').filter({ hasText: name }).last(),
      frame.getByText(name, { exact: true }).last(),
      frame.getByRole('radio', { name, exact: true }).last(),
    ];
    for (const candidate of candidates) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try {
        const tag = await candidate.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
        const type = await candidate.getAttribute('type').catch(() => null);
        if (tag === 'input' && type === 'radio') await candidate.check({ force: true, timeout: 5_000 });
        else await candidate.click({ force: true, timeout: 5_000 });
      } catch { continue; }
      try { return await appFrame(page, expectedText, 7_000); }
      catch { /* retry */ }
    }
    await sleep(500);
  }
  throw new Error(`Timed out selecting ${name} and waiting for ${expectedText}`);
}

async function labelledInput(frame, label, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const labelled = frame.getByLabel(label, { exact: true }).first();
    if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) return labelled;

    const aria = frame.locator(`input[aria-label="${label}"]`).first();
    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return aria;

    const labels = frame.locator('label').filter({ hasText: label });
    const count = await labels.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const input = labels.nth(i).locator('input').first();
      if (await input.count().catch(() => 0) && await input.isVisible().catch(() => false)) return input;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for visible input: ${label}`);
}

async function combo(frame, label, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    let control = frame.getByRole('combobox', { name: label, exact: true }).first();
    if (await control.count().catch(() => 0) && await control.isVisible().catch(() => false)) return control;
    control = frame.getByLabel(label, { exact: true }).first();
    if (await control.count().catch(() => 0) && await control.isVisible().catch(() => false)) return control;
    await sleep(250);
  }
  throw new Error(`Timed out waiting for visible combobox: ${label}`);
}

async function selectComboContains(page, frame, label, needle) {
  const control = await combo(frame, label);
  await control.click({ timeout: 15_000 });
  await sleep(250);
  let options = frame.getByRole('option');
  let texts = await options.allInnerTexts().catch(() => []);
  let index = texts.findIndex((value) => value.includes(needle));
  if (index < 0) {
    options = frame.locator('[data-baseweb="menu"] li');
    texts = await options.allInnerTexts().catch(() => []);
    index = texts.findIndex((value) => value.includes(needle));
  }
  if (index < 0) throw new Error(`No ${label} option containing ${needle}. Options: ${texts.join(' | ')}`);
  await options.nth(index).click({ timeout: 15_000 });
  await sleep(1_000);
  return await appFrame(page);
}

async function selectExactStation(page, frame, stationName, stationId) {
  const input = await labelledInput(frame, 'Search GeoSphere station');
  await input.fill(String(stationId), { timeout: 15_000 });
  await input.press('Tab').catch(() => {});

  frame = await appFrame(page, 'Visible GeoSphere stations after filters:', 60_000);
  frame = await appFrame(page, 'Manual station selection', 60_000);
  const targetId = `ID ${stationId}`;

  // The application normalizes selected_id to option_ids[0] when the active
  // station no longer belongs to the filtered result set. Searching by an exact
  // station ID therefore auto-selects the singleton result before the manual
  // selectbox is rendered. Verify that settled state first; the manual picker is
  // only a fallback for a non-singleton/unchanged selection.
  const settledText = await bodyText(frame);
  const visibleMatch = settledText.match(/Visible GeoSphere stations after filters:\s*([\d,]+)/);
  const visibleCount = visibleMatch ? Number(visibleMatch[1].replaceAll(',', '')) : null;
  if (
    visibleCount === 1
    && settledText.includes('Selected station')
    && (settledText.includes(stationName) || settledText.includes(targetId))
  ) {
    return frame;
  }

  const stationCombo = await combo(frame, 'Search-result stations', 60_000);
  await stationCombo.click({ timeout: 15_000 });
  await sleep(300);

  let option = frame.getByRole('option').filter({ hasText: targetId }).last();
  if (!(await option.count().catch(() => 0))) {
    option = frame.locator('[data-baseweb="menu"] li').filter({ hasText: targetId }).last();
  }
  if (!(await option.count().catch(() => 0))) {
    const rendered = [
      await stationCombo.innerText().catch(() => ''),
      await stationCombo.textContent().catch(() => ''),
      await stationCombo.inputValue().catch(() => ''),
    ].join(' ');
    if (rendered.includes(targetId) || rendered.includes(stationName)) return frame;
    const roleTexts = await frame.getByRole('option').allInnerTexts().catch(() => []);
    const menuTexts = await frame.locator('[data-baseweb="menu"] li').allInnerTexts().catch(() => []);
    throw new Error(
      `Search-result stations contains no option for ${targetId}. ` +
      `Rendered control: ${rendered}; role options: ${roleTexts.join(' | ')}; menu options: ${menuTexts.join(' | ')}`
    );
  }

  const selectedLabel = (await option.innerText().catch(() => '')).trim();
  await option.click({ timeout: 15_000 });
  await sleep(500);

  const use = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
  if (!(await use.count().catch(() => 0))) throw new Error('Use station from list button not found.');
  await use.click({ timeout: 15_000 });

  const started = performance.now();
  while (performance.now() - started < 60_000) {
    let currentFrame;
    try { currentFrame = await appFrame(page, 'Selected station', 5_000); }
    catch { await sleep(300); continue; }

    const selectedText = await bodyText(currentFrame);
    if (selectedText.includes('Selected station') && (selectedText.includes(stationName) || selectedText.includes(targetId))) {
      return currentFrame;
    }
    await sleep(400);
  }

  throw new Error(`Selected station did not settle on ${stationName} (${targetId}); option=${selectedLabel}.`);
}

async function expandMonthlyContext(frame) {
  const label = 'About this GeoSphere monthly dataset';
  const text = frame.getByText(label, { exact: true }).last();
  if (await text.count().catch(() => 0)) {
    await text.click({ force: true, timeout: 10_000 }).catch(() => {});
    await sleep(350);
  }
}

function occurrences(text, needle) {
  return text.split(needle).length - 1;
}

const report = {
  schema: 'climate-analyzer-pr83-source-ui-smoke-v8',
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

  let frame = await chooseAndWait(page, 'GeoSphere Austria', 'GeoSphere Austria — measured historical station data');
  frame = await selectComboContains(page, frame, 'GeoSphere dataset', '1 month');
  frame = await selectExactStation(page, frame, fixture.station_name, fixture.station_id);
  frame = await appFrame(page, 'Parameter set', 60_000);
  await expandMonthlyContext(frame);
  const monthlyText = await bodyText(frame);

  const requiredSets = ['Core variables', 'Core + additional statistics', 'All provider parameters'];
  for (const name of requiredSets) {
    if (!monthlyText.includes(name)) throw new Error(`Monthly Parameter set option missing: ${name}`);
  }
  if (monthlyText.includes('Parameter catalogue')) throw new Error('Legacy monthly Parameter catalogue control is still visible.');
  const monthlySource = 'Official source: GeoSphere Austria Station Data-v2 (1 m)';
  const monthlyContext = 'About this GeoSphere monthly dataset';
  if (occurrences(monthlyText, monthlySource) !== 1) {
    throw new Error(`Expected one monthly official-source block, found ${occurrences(monthlyText, monthlySource)}.`);
  }
  if (occurrences(monthlyText, monthlyContext) !== 1) {
    throw new Error(`Expected one monthly dataset context, found ${occurrences(monthlyText, monthlyContext)}.`);
  }
  report.checks.monthly_parameter_sets = requiredSets;
  report.checks.monthly_source_block_count = 1;
  report.checks.monthly_context_count = 1;

  frame = await selectComboContains(page, frame, 'GeoSphere dataset', '1 h (long-term)');
  frame = await selectExactStation(page, frame, fixture.station_name, fixture.station_id);
  frame = await appFrame(page, 'Official GeoSphere Austria availability context', 60_000);
  const hourlyText = await bodyText(frame);
  const hourlyInfo = 'Official GeoSphere Austria availability context (translated summary)';
  const hourlySource = 'Authoritative source: GeoSphere Austria Stationsdaten-v2 (1 h)';
  if (occurrences(hourlyText, hourlyInfo) !== 1) {
    throw new Error(`Expected one hourly availability context, found ${occurrences(hourlyText, hourlyInfo)}.`);
  }
  if (occurrences(hourlyText, hourlySource) !== 1) {
    throw new Error(`Expected one hourly authoritative-source caption, found ${occurrences(hourlyText, hourlySource)}.`);
  }
  report.checks.hourly_context_count = 1;
  report.checks.hourly_source_block_count = 1;

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
