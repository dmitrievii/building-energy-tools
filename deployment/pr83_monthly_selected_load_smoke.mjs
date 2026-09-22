import fs from 'node:fs/promises';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8501/';
const FIXTURE_PATH = process.env.PR83_MONTHLY_FIXTURE || 'artifacts/pr83-contract-smoke/monthly-provider.json';
const OUT_PATH = process.env.PR83_MONTHLY_LOAD_REPORT || 'artifacts/pr83-contract-smoke/monthly-selected-load.json';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const REQUIRED = ['rf_mittel', 'p', 'tl_mittel'];

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
    for (const candidate of [
      frame.getByRole('combobox', { name: label, exact: true }).first(),
      frame.getByLabel(label, { exact: true }).first(),
    ]) {
      if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for combobox: ${label}`);
}

async function rendered(control) {
  return [
    await control.innerText().catch(() => ''),
    await control.textContent().catch(() => ''),
    await control.inputValue().catch(() => ''),
  ].join(' ').replace(/\s+/g, ' ').trim();
}

async function selectVisibleOption(page, controlLabel, predicate, timeoutMs = 60_000) {
  const started = performance.now();
  let last = [];
  while (performance.now() - started < timeoutMs) {
    const frame = await appFrame(page, 'Climate Analyzer', 5_000);
    let control;
    try { control = await combo(frame, controlLabel, 5_000); }
    catch { await sleep(250); continue; }
    await control.click({ timeout: 5_000 }).catch(() => {});
    const optionStarted = performance.now();
    while (performance.now() - optionStarted < 6_000) {
      for (const options of [frame.getByRole('option'), page.getByRole('option'), frame.locator('[data-baseweb="menu"] li'), page.locator('[data-baseweb="menu"] li')]) {
        const count = await options.count().catch(() => 0);
        if (!count) continue;
        last = await options.allInnerTexts().catch(() => last);
        for (let i = 0; i < count; i += 1) {
          const option = options.nth(i);
          const text = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
          if (!predicate(text) || !(await option.isVisible().catch(() => false))) continue;
          await option.click({ timeout: 8_000 });
          return;
        }
      }
      await sleep(200);
    }
    await page.keyboard.press('Escape').catch(() => {});
  }
  throw new Error(`Could not select ${controlLabel}; last options: ${last.join(' | ')}`);
}

async function chooseSource(page) {
  const started = performance.now();
  while (performance.now() - started < 60_000) {
    const frame = await appFrame(page, 'Climate Analyzer', 10_000);
    for (const candidate of [
      frame.getByRole('radio', { name: 'GeoSphere Austria', exact: true }).last(),
      frame.getByText('GeoSphere Austria', { exact: true }).last(),
      frame.locator('label').filter({ hasText: 'GeoSphere Austria' }).last(),
    ]) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try {
        const tag = await candidate.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
        const type = await candidate.getAttribute('type').catch(() => null);
        if (tag === 'input' && type === 'radio') await candidate.check({ force: true, timeout: 5_000 });
        else await candidate.click({ force: true, timeout: 5_000 });
        return await appFrame(page, 'GeoSphere Austria — measured historical station data', 15_000);
      } catch {}
    }
    await sleep(400);
  }
  throw new Error('Could not select GeoSphere Austria source.');
}

async function selectDataset(page) {
  await selectVisibleOption(page, 'GeoSphere dataset', (text) => text.includes('1 month'));
  const started = performance.now();
  while (performance.now() - started < 60_000) {
    const frame = await appFrame(page, 'Climate Analyzer', 5_000);
    const text = await bodyText(frame);
    const controlText = await rendered(await combo(frame, 'GeoSphere dataset', 5_000)).catch(() => '');
    if (controlText.includes('1 month') && text.includes('Selected resource: klima-v2-1m')) return frame;
    await sleep(300);
  }
  throw new Error('Monthly dataset did not commit klima-v2-1m.');
}

async function labelledInput(frame, label, timeoutMs = 60_000) {
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
  throw new Error(`Timed out waiting for input: ${label}`);
}

async function selectExactStation(page, stationName, stationId) {
  let frame = await appFrame(page, 'Search GeoSphere station', 60_000);
  const input = await labelledInput(frame, 'Search GeoSphere station');
  await input.fill(String(stationName), { timeout: 15_000 });
  await input.press('Tab').catch(() => {});
  frame = await appFrame(page, 'Manual station selection', 60_000);

  const targetId = String(stationId);
  await selectVisibleOption(
    page,
    'Search-result stations',
    (text) => text.includes(stationName) && (text.includes(`ID ${targetId}`) || text.includes(targetId)),
    60_000,
  );

  const settled = performance.now();
  while (performance.now() - settled < 30_000) {
    frame = await appFrame(page, 'Manual station selection', 5_000);
    const controlText = await rendered(await combo(frame, 'Search-result stations', 5_000)).catch(() => '');
    if (controlText.includes(stationName) && (controlText.includes(`ID ${targetId}`) || controlText.includes(targetId))) break;
    await sleep(250);
  }

  const commitStarted = performance.now();
  while (performance.now() - commitStarted < 30_000) {
    frame = await appFrame(page, 'Manual station selection', 5_000);
    const button = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
    if (await button.count().catch(() => 0) && await button.isVisible().catch(() => false)) {
      await button.click({ timeout: 15_000 });
      return await appFrame(page, 'Measured variables to load', 60_000);
    }
    await sleep(250);
  }
  throw new Error('Use station from list button did not become available.');
}

async function waitMonthlySelectionSurface(page, timeoutMs = 60_000) {
  const started = performance.now();
  let stablePasses = 0;
  let lastText = '';
  while (performance.now() - started < timeoutMs) {
    const frame = await appFrame(page, 'Measured variables to load', 5_000);
    const text = await bodyText(frame);
    lastText = text;
    const ready = (
      text.includes('Selected resource: klima-v2-1m') &&
      text.includes('Parameter set') &&
      text.includes('Core variables') &&
      text.includes('Core + additional statistics') &&
      text.includes('All provider parameters') &&
      text.includes('Select at least one measured GeoSphere variable to load.')
    );
    if (ready) {
      stablePasses += 1;
      if (stablePasses >= 3) return frame;
    } else {
      stablePasses = 0;
    }
    await sleep(300);
  }
  throw new Error(`Monthly selection surface did not settle; last text contains Parameter set=${lastText.includes('Parameter set')}.`);
}

async function selectRadio(page, name, expectedNeedle = 'Measured variables to load') {
  const started = performance.now();
  while (performance.now() - started < 30_000) {
    const frame = await appFrame(page, expectedNeedle, 5_000);
    for (const candidate of [
      frame.getByRole('radio', { name, exact: true }).last(),
      frame.locator('label').filter({ hasText: name }).last(),
      frame.getByText(name, { exact: true }).last(),
    ]) {
      if (!(await candidate.count().catch(() => 0)) || !(await candidate.isVisible().catch(() => false))) continue;
      try {
        const tag = await candidate.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
        if (tag === 'input') await candidate.check({ force: true, timeout: 5_000 });
        else await candidate.click({ force: true, timeout: 5_000 });
        await sleep(700);
        return await appFrame(page, expectedNeedle, 15_000);
      } catch {}
    }
    await sleep(300);
  }
  throw new Error(`Could not select radio option: ${name}`);
}

async function variableEditor(page) {
  const frame = await appFrame(page, 'Measured variables to load', 30_000);
  const tables = frame.locator('[data-testid="stDataFrame"]');
  if (await tables.count() < 2) throw new Error('Measured-variable data editor not found.');
  const editor = tables.last();
  const canvas = editor.locator('canvas[data-testid="data-grid-canvas"]').first();
  if (!(await canvas.count())) throw new Error('Measured-variable Glide canvas not found.');
  return { frame, editor, canvas };
}

async function settleEditor(page) {
  const current = await variableEditor(page);
  await current.editor.locator('.dvn-scroller').first().evaluate((node) => {
    node.scrollTop = 0;
    node.dispatchEvent(new Event('scroll', { bubbles: true }));
  }).catch(() => {});
  await sleep(700);
  return variableEditor(page);
}

async function providerLoadState(page, providerName) {
  const { frame, editor, canvas } = await settleEditor(page);
  const rows = editor.locator('[role="grid"] tr[role="row"]');
  const count = await rows.count();
  for (let index = 0; index < count; index += 1) {
    const row = rows.nth(index);
    const cells = row.locator('[role="gridcell"]');
    const texts = [];
    for (let cellIndex = 0; cellIndex < await cells.count(); cellIndex += 1) {
      texts.push((await cells.nth(cellIndex).textContent().catch(() => '')).trim());
    }
    if (!texts.includes(providerName)) continue;
    const load = String(texts[0] ?? '').trim().toLowerCase();
    const ariaRowIndex = Number(await row.getAttribute('aria-rowindex'));
    if (!Number.isFinite(ariaRowIndex) || ariaRowIndex < 2) throw new Error(`Invalid Glide row index for ${providerName}: ${ariaRowIndex}`);
    return { frame, editor, canvas, load, ariaRowIndex, dataIndex: ariaRowIndex - 2, rowTexts: texts };
  }
  throw new Error(`Provider ${providerName} is not visible in the All provider parameters view.`);
}

async function waitProviderLoadState(page, providerName, expected, timeoutMs = 15_000) {
  const started = performance.now();
  let last = null;
  while (performance.now() - started < timeoutMs) {
    try {
      last = await providerLoadState(page, providerName);
      if (last.load === expected) return last;
    } catch {}
    await sleep(300);
  }
  throw new Error(`Provider ${providerName} Load did not become ${expected}; last=${last?.load ?? 'unavailable'}.`);
}

async function navigateToLoadCell(page, state, providerName) {
  const expectedTestId = `glide-cell-0-${state.dataIndex}`;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const current = await settleEditor(page);
    const box = await current.canvas.boundingBox().catch(() => null);
    if (!box || box.width < 100 || box.height < 80) continue;
    await current.canvas.click({ position: { x: Math.min(box.width - 10, box.width * 0.55), y: Math.min(box.height - 10, 52) }, force: true, timeout: 5_000 }).catch(() => {});
    await current.canvas.focus();
    await page.keyboard.press('Control+Home');
    await sleep(200);
    const home = current.editor.locator('[role="gridcell"][aria-selected="true"]').first();
    if (await home.getAttribute('data-testid').catch(() => null) !== 'glide-cell-0-0') continue;
    for (let row = 0; row < state.dataIndex; row += 1) await page.keyboard.press('ArrowDown');
    await sleep(200);
    const selected = current.editor.locator('[role="gridcell"][aria-selected="true"]').first();
    if (await selected.getAttribute('data-testid').catch(() => null) === expectedTestId) return;
  }
  throw new Error(`Could not address Load cell for ${providerName}.`);
}

async function selectProvider(page, providerName) {
  let state = await providerLoadState(page, providerName);
  if (state.load === 'true') return state;
  if (state.load !== 'false') throw new Error(`Unexpected Load state for ${providerName}: ${state.load}`);
  await navigateToLoadCell(page, state, providerName);
  await page.keyboard.press('Space');
  return waitProviderLoadState(page, providerName, 'true');
}

async function clickSidebar(page, label, expectedText) {
  const started = performance.now();
  while (performance.now() - started < 60_000) {
    const frame = await appFrame(page, 'Climate Analyzer', 10_000);
    const sidebar = frame.locator('section[data-testid="stSidebar"]');
    for (const candidate of [
      sidebar.getByText(label, { exact: true }).last(),
      sidebar.locator('label').filter({ hasText: label }).last(),
    ]) {
      if (!(await candidate.count().catch(() => 0)) || !(await candidate.isVisible().catch(() => false))) continue;
      try {
        await candidate.click({ force: true, timeout: 5_000 });
        return await appFrame(page, expectedText, 30_000);
      } catch {}
    }
    await sleep(300);
  }
  throw new Error(`Sidebar navigation item not found: ${label}`);
}

const report = {
  schema: 'climate-analyzer-monthly-selected-load-smoke-v2',
  target_url: TARGET_URL,
  fixture,
  checks: {},
  page_errors: [],
  console_errors: [],
  success: false,
  error: null,
};

let browser;
let page;
try {
  if (!fixture.success) throw new Error('Monthly provider fixture is not successful.');
  if (String(fixture.station_id) !== '105') throw new Error(`Monthly fixture must resolve station 105; got ${fixture.station_id}.`);

  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => { if (message.type() === 'error') report.console_errors.push(message.text()); });
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });

  await chooseSource(page);
  await selectDataset(page);
  await selectExactStation(page, fixture.station_name, fixture.station_id);
  let frame = await waitMonthlySelectionSurface(page);
  let text = await bodyText(frame);
  if (!text.includes('Select at least one measured GeoSphere variable to load.')) throw new Error('Empty monthly selection warning is missing.');
  if (await frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).count().catch(() => 0)) {
    throw new Error('Mature load button must not be reachable while monthly selection is empty.');
  }
  report.checks.initial_selection = 'zero';
  report.checks.empty_selection_warning = true;
  report.checks.initial_core_view = true;

  await selectRadio(page, 'All provider parameters');
  const selected = {};
  for (const provider of REQUIRED) {
    const state = await selectProvider(page, provider);
    selected[provider] = { load: state.load, row: state.ariaRowIndex };
  }
  report.checks.selected_provider_parameters = selected;

  frame = await appFrame(page, 'Measured variables to load', 20_000);
  text = await bodyText(frame);
  if (text.includes('GeoSphere load complete')) throw new Error('Checkbox edit unexpectedly triggered provider loading before the mature load button was clicked.');
  report.checks.checkbox_edit_did_not_activate_dataset = true;

  await selectRadio(page, 'Core variables');
  frame = await appFrame(page, 'Measured variables to load', 20_000);
  const coreLoad = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  if (!(await coreLoad.count().catch(() => 0))) throw new Error('Selected monthly providers were lost on All -> Core transition.');
  report.checks.core_all_core_load_button_preserved = true;

  await selectRadio(page, 'All provider parameters');
  for (const provider of REQUIRED) await waitProviderLoadState(page, provider, 'true');
  report.checks.provider_keyed_roundtrip = true;

  await selectRadio(page, 'Core variables');
  frame = await appFrame(page, 'Measured variables to load', 20_000);
  const loadButton = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  if (!(await loadButton.count().catch(() => 0))) throw new Error('Existing mature GeoSphere load button is missing after monthly selection.');
  await loadButton.click({ timeout: 15_000 });

  frame = await appFrame(page, 'Summary — Overview', 180_000);
  text = await bodyText(frame);
  if (!text.includes('Climate overview')) throw new Error('Monthly canonical dataset did not activate Overview.');
  report.checks.canonical_dataset_activated = true;
  report.checks.summary_overview = true;

  frame = await clickSidebar(page, 'Climate — Temperature', 'Temperature and extremes');
  text = await bodyText(frame);
  if (!text.includes('Dew-point temperature')) throw new Error('Temperature page does not expose derived dew-point capability from tl_mittel + rf_mittel.');
  report.checks.temperature_dew_point_capability = true;

  frame = await clickSidebar(page, 'Climate — Moisture & psychrometrics', 'Humidity and psychrometrics');
  text = await bodyText(frame);
  if (!text.includes('Station pressure')) throw new Error('Monthly moisture page does not expose station pressure.');
  if (!text.includes('published monthly mean is available')) throw new Error('Measured monthly station-pressure capability note is missing.');
  report.checks.measured_monthly_station_pressure = true;

  if (report.page_errors.length) throw new Error(`Browser page error(s): ${report.page_errors.join(' | ')}`);
  report.success = true;
} catch (error) {
  report.error = String(error?.stack || error);
  process.exitCode = 1;
} finally {
  report.completed_at_utc = new Date().toISOString();
  await fs.mkdir('artifacts/pr83-contract-smoke', { recursive: true });
  await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (browser) await browser.close().catch(() => {});
}
