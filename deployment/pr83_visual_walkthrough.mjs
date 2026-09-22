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

const MONTHLY_RESOURCE = 'klima-v2-1m';
const FORM_CAPTION = 'Variable choices are staged locally.';
const EMPTY_WARNING = 'Select at least one measured GeoSphere variable to load.';

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

async function waitBody(page, predicate, description, timeoutMs = 90000, stablePasses = 3) {
  const started = performance.now();
  let passes = 0;
  let lastText = '';
  let lastFrame = null;
  while (performance.now() - started < timeoutMs) {
    try {
      lastFrame = await appFrame(page, 'Climate Analyzer', 5000);
      lastText = await bodyText(lastFrame);
      if (predicate(lastText)) {
        passes += 1;
        if (passes >= stablePasses) return { frame: lastFrame, text: lastText };
      } else {
        passes = 0;
      }
    } catch {
      passes = 0;
    }
    await sleep(350);
  }
  throw new Error(
    `Timed out waiting for ${description}; ` +
    `resource=${lastText.match(/Selected resource:[^\n]*/)?.[0] || 'none'}`,
  );
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
        const tag = await candidate.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
        const type = await candidate.getAttribute('type').catch(() => null);
        if (tag === 'input' && type === 'radio') await candidate.check({ force: true, timeout: 5000 });
        else await candidate.click({ force: true, timeout: 5000 });
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
    if ((await rendered(control)).includes('1 month') && text.includes(`Selected resource: ${MONTHLY_RESOURCE}`)) return frame;

    await control.click({ timeout: 5000 }).catch(() => {});
    const option = await visibleOption(page, frame, (value) => value.includes('1 month'));
    if (option) await option.click({ timeout: 8000 }).catch(() => {});
    await sleep(500);
  }
  throw new Error(`Could not commit ${MONTHLY_RESOURCE}.`);
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

async function waitMonthlyEditor(page) {
  return await waitBody(
    page,
    (text) => (
      text.includes(`Selected resource: ${MONTHLY_RESOURCE}`) &&
      text.includes('Parameter set') &&
      text.includes('Measured variables to load') &&
      text.includes(FORM_CAPTION)
    ),
    'stable monthly measured-variable form',
    90000,
    3,
  );
}

async function selectedRadio(frame, name) {
  const radio = frame.getByRole('radio', { name, exact: true }).last();
  if (await radio.count().catch(() => 0) && await radio.isVisible().catch(() => false)) return radio;
  return null;
}

async function selectParameterSet(page, name) {
  const started = performance.now();
  while (performance.now() - started < 45000) {
    const monthly = await waitMonthlyEditor(page);
    const frame = monthly.frame;
    const radio = await selectedRadio(frame, name);
    const textCandidate = frame.getByText(name, { exact: true }).last();

    for (const candidate of [radio, textCandidate].filter(Boolean)) {
      if (!(await candidate.count().catch(() => 0)) || !(await candidate.isVisible().catch(() => false))) continue;
      try {
        const tag = await candidate.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
        const type = await candidate.getAttribute('type').catch(() => null);
        if (tag === 'input' && type === 'radio') await candidate.check({ force: true, timeout: 5000 });
        else await candidate.click({ force: true, timeout: 5000 });

        const settled = await waitMonthlyEditor(page);
        const selected = await selectedRadio(settled.frame, name);
        if (!selected || await selected.isChecked().catch(() => true)) return settled.frame;
      } catch {}
    }
    await sleep(300);
  }
  throw new Error(`Parameter set did not settle: ${name}`);
}

async function assertStagedEmptySelection(frame, label) {
  const text = await bodyText(frame);
  if (!text.includes(`Selected resource: ${MONTHLY_RESOURCE}`)) {
    throw new Error(`${label}: monthly resource is not active.`);
  }
  if (!text.includes('Parameter set')) {
    throw new Error(`${label}: monthly Parameter set control is missing.`);
  }
  if (!text.includes(FORM_CAPTION)) {
    throw new Error(`${label}: measured-variable editor is not staged inside the transactional form.`);
  }
  if (text.includes(EMPTY_WARNING)) {
    throw new Error(`${label}: empty-selection warning is visible before the user submits the form.`);
  }

  const load = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  if (!(await load.count().catch(() => 0)) || !(await load.isVisible().catch(() => false))) {
    throw new Error(`${label}: form submit action is not visible.`);
  }

  // Streamlit DataEditor exposes checkbox inputs in current browser builds. If
  // they are accessibility-visible, verify that the fresh/default view contains
  // no checked Load/quality-flag cells. Unit tests remain the source of truth if
  // the grid implementation stops exposing checkbox roles.
  const checkboxes = frame.getByRole('checkbox');
  const count = await checkboxes.count().catch(() => 0);
  let checked = 0;
  for (let i = 0; i < count; i += 1) {
    if (await checkboxes.nth(i).isChecked().catch(() => false)) checked += 1;
  }
  if (checked !== 0) throw new Error(`${label}: ${checked} checkbox(es) are unexpectedly selected by default.`);

  return { text, checkboxCount: count };
}

async function validateEmptySubmit(page, frame) {
  const load = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  await load.click({ timeout: 10000 });
  const settled = await waitBody(
    page,
    (text) => (
      text.includes(`Selected resource: ${MONTHLY_RESOURCE}`) &&
      text.includes('Parameter set') &&
      text.includes(EMPTY_WARNING)
    ),
    'empty form-submit validation',
    30000,
    2,
  );
  return settled.frame;
}

async function screenshot(page, name) {
  await page.screenshot({ path: path.join(OUT_DIR, name), fullPage: true });
}

const report = {
  schema: 'climate-analyzer-pr83-extended-visual-v7-transactional-form',
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

  // Do not re-select the dataset after station commit. That click creates a
  // second, competing Streamlit state transition. Instead wait for the same
  // stable monthly contract used by the independent source-UI browser smoke.
  let monthly = await waitMonthlyEditor(page);
  let frame = monthly.frame;
  report.checks.monthly_resource_stable_after_station = true;

  const initial = await assertStagedEmptySelection(frame, 'Initial monthly view');
  report.checks.initial_selection_empty = true;
  report.checks.transactional_form_visible = true;
  report.checks.initial_accessible_checkbox_count = initial.checkboxCount;
  await screenshot(page, '01-monthly-initial-empty.png');

  frame = await selectParameterSet(page, 'Core variables');
  await assertStagedEmptySelection(frame, 'Core variables');
  report.checks.core_view_selection_still_empty = true;
  await screenshot(page, '02-monthly-core-empty.png');

  frame = await selectParameterSet(page, 'All provider parameters');
  await assertStagedEmptySelection(frame, 'All provider parameters');
  report.checks.all_view_selection_still_empty = true;
  await screenshot(page, '03-monthly-all-empty.png');

  frame = await selectParameterSet(page, 'Core variables');
  await assertStagedEmptySelection(frame, 'Core variables roundtrip');
  report.checks.core_roundtrip_selection_still_empty = true;
  await screenshot(page, '04-monthly-core-empty-roundtrip.png');

  // Empty submit is a validation event, not a provider load. Before submit the
  // warning must be absent; after submit it must appear while the monthly source
  // and Parameter-set controls remain intact.
  frame = await validateEmptySubmit(page, frame);
  report.checks.empty_submit_warns_without_leaving_monthly = true;
  await screenshot(page, '05-monthly-empty-submit-warning.png');

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
