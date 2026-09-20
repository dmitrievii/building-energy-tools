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
    await sleep(300);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}

async function chooseAndWait(page, name, expectedText, timeoutMs = 45_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    let frame;
    try { frame = await appFrame(page, 'Climate Analyzer', 8_000); }
    catch { await sleep(350); continue; }
    const candidates = [
      frame.locator('label').filter({ hasText: name }).last(),
      frame.getByText(name, { exact: true }).last(),
      frame.getByRole('radio', { name, exact: true }).last(),
    ];
    for (const candidate of candidates) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try { await candidate.click({ force: true, timeout: 5_000 }); }
      catch { continue; }
      try { return await appFrame(page, expectedText, 8_000); }
      catch { /* rerun in flight */ }
    }
    await sleep(400);
  }
  throw new Error(`Timed out selecting ${name}.`);
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

async function stationMetadata(frame) {
  const tables = frame.locator('[data-testid="stDataFrame"]');
  if (!(await tables.count())) return {};
  const rows = tables.first().locator('[role="grid"] tr[role="row"]');
  const result = {};
  const count = await rows.count();
  for (let index = 0; index < count; index += 1) {
    const cells = rows.nth(index).locator('[role="gridcell"]');
    if (await cells.count() < 2) continue;
    const key = (await cells.nth(0).textContent().catch(() => '')).trim();
    const value = (await cells.nth(1).textContent().catch(() => '')).trim();
    if (key) result[key] = value;
  }
  return result;
}

async function selectStationByName(page, frame, stationName, stationId, timeoutMs = 60_000) {
  const search = await labelledInput(frame, 'Search GeoSphere station');
  await search.fill(String(stationName), { timeout: 15_000 });
  await search.press('Tab').catch(() => {});

  const started = performance.now();
  let observed = {};
  while (performance.now() - started < timeoutMs) {
    try {
      frame = await appFrame(page, 'Selected station', 5_000);
      frame = await appFrame(page, 'Measured variables to load', 5_000);
      observed = await stationMetadata(frame);
      if (String(observed.ID || '') === String(stationId) && String(observed.Station || '').includes(stationName)) {
        return { frame, metadata: observed };
      }
    } catch { /* rerun in flight */ }
    await sleep(300);
  }
  throw new Error(`Station search did not settle on ${stationName} (ID ${stationId}); observed ${JSON.stringify(observed)}.`);
}

function dateValueMatches(value, iso) {
  const [year, month, day] = iso.split('-').map(Number);
  const parts = String(value).split(/\D+/).filter(Boolean).map(Number);
  return parts.includes(year) && parts.includes(month) && parts.includes(day);
}

async function dateControl(frame, label, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const labelled = frame.getByLabel(label, { exact: true }).first();
    if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) {
      const tag = await labelled.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
      const role = await labelled.getAttribute('role').catch(() => null);
      if (['input', 'textarea', 'select'].includes(tag)) return { kind: 'input', locator: labelled };
      if (role === 'group' && await labelled.locator('[role="spinbutton"]').count().catch(() => 0) >= 3) return { kind: 'segmented', locator: labelled };
    }
    const aria = frame.locator(`input[aria-label="${label}"]`).first();
    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return { kind: 'input', locator: aria };
    await sleep(250);
  }
  throw new Error(`Timed out waiting for date control: ${label}`);
}

async function segmentedDateValue(group) {
  const segments = group.locator('[role="spinbutton"]');
  const values = {};
  for (let index = 0; index < await segments.count(); index += 1) {
    const segment = segments.nth(index);
    const label = String(await segment.getAttribute('aria-label').catch(() => '')).toLowerCase();
    const value = Number(await segment.getAttribute('aria-valuenow').catch(() => NaN));
    if (!Number.isFinite(value)) continue;
    if (label.includes('year')) values.year = value;
    else if (label.includes('month')) values.month = value;
    else if (label.includes('day')) values.day = value;
  }
  if ([values.year, values.month, values.day].every(Number.isFinite)) return `${values.year}-${String(values.month).padStart(2, '0')}-${String(values.day).padStart(2, '0')}`;
  return (await group.innerText().catch(() => '')).trim();
}

async function setSegmentedDate(frame, group, iso) {
  const [year, month, day] = iso.split('-').map(Number);
  const desired = { year, month, day };
  const segments = group.locator('[role="spinbutton"]');
  const byPart = {};
  for (let index = 0; index < await segments.count(); index += 1) {
    const segment = segments.nth(index);
    const label = String(await segment.getAttribute('aria-label').catch(() => '')).toLowerCase();
    if (label.includes('year')) byPart.year = segment;
    else if (label.includes('month')) byPart.month = segment;
    else if (label.includes('day')) byPart.day = segment;
  }
  for (const part of ['year', 'month', 'day']) {
    const segment = byPart[part];
    if (!segment) throw new Error(`Could not identify ${part} segment for ${iso}.`);
    await segment.click({ timeout: 10_000 });
    const editable = await segment.getAttribute('contenteditable').catch(() => null);
    if (editable === 'true') await segment.fill(String(desired[part]), { timeout: 10_000 });
    else {
      await segment.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {});
      await segment.press('Backspace').catch(() => {});
      await frame.page().keyboard.type(String(desired[part]), { delay: 50 });
    }
    await sleep(160);
  }
  await frame.page().keyboard.press('Tab').catch(() => {});
}

async function setDateInput(page, label, iso) {
  let lastValue = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const frame = await appFrame(page, 'Measured variables to load', 20_000);
    const control = await dateControl(frame, label);
    if (control.kind === 'input') {
      const candidate = attempt === 0 ? iso.replaceAll('-', '/') : iso;
      await control.locator.click({ timeout: 10_000 });
      await control.locator.fill(candidate, { timeout: 10_000 });
      await control.locator.press('Enter').catch(() => {});
      await control.locator.press('Tab').catch(() => {});
    } else await setSegmentedDate(frame, control.locator, iso);
    await sleep(1_000);
    const refreshedFrame = await appFrame(page, 'Measured variables to load', 20_000);
    const refreshed = await dateControl(refreshedFrame, label);
    lastValue = refreshed.kind === 'input' ? await refreshed.locator.inputValue().catch(() => null) : await segmentedDateValue(refreshed.locator);
    if (dateValueMatches(lastValue, iso)) return lastValue;
  }
  throw new Error(`Date input ${label} did not accept ${iso}; observed ${lastValue}.`);
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

async function scrollEditorBottom(editor) {
  return await editor.locator('.dvn-scroller').first().evaluate((node) => {
    node.scrollTop = node.scrollHeight;
    node.dispatchEvent(new Event('scroll', { bubbles: true }));
    return { scrollTop: node.scrollTop, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight };
  });
}

async function settledVariableEditor(page) {
  let current = await variableEditor(page);
  await scrollEditorBottom(current.editor);
  await sleep(1_200);
  current = await variableEditor(page);
  return current;
}

async function providerLoadState(page, providerName) {
  const { frame, editor, canvas } = await settledVariableEditor(page);
  const rows = editor.locator('[role="grid"] tr[role="row"]');
  const count = await rows.count();
  for (let index = 0; index < count; index += 1) {
    const row = rows.nth(index);
    const provider = (await row.locator('[role="gridcell"][aria-colindex="4"]').textContent().catch(() => '')).trim();
    if (provider !== providerName) continue;
    const load = (await row.locator('[role="gridcell"][aria-colindex="1"]').textContent().catch(() => '')).trim().toLowerCase();
    const ariaRowIndex = Number(await row.getAttribute('aria-rowindex'));
    if (!Number.isFinite(ariaRowIndex) || ariaRowIndex < 2) throw new Error(`Invalid Glide row index for ${providerName}: ${ariaRowIndex}`);
    return { frame, editor, canvas, provider, load, ariaRowIndex, dataIndex: ariaRowIndex - 2 };
  }
  throw new Error(`Provider parameter ${providerName} is not visible after scrolling the measured-variable editor to the bottom.`);
}

async function waitProviderLoadState(page, providerName, expected, timeoutMs = 12_000) {
  const started = performance.now(); let last = null;
  while (performance.now() - started < timeoutMs) {
    try { last = await providerLoadState(page, providerName); if (last.load === expected) return last; }
    catch { /* rerun in flight */ }
    await sleep(300);
  }
  throw new Error(`Provider ${providerName} Load did not become ${expected}; last=${last?.load ?? 'unavailable'}.`);
}

async function navigateToLoadCell(page, state, providerName) {
  const expectedTestId = `glide-cell-0-${state.dataIndex}`;
  let lastSelectedTestId = null; let lastHomeTestId = null; let lastFocused = false; let lastMouseInitialized = false;
  for (let navigationAttempt = 0; navigationAttempt < 3; navigationAttempt += 1) {
    const current = await settledVariableEditor(page);
    const box = await current.canvas.boundingBox().catch(() => null);
    if (!box || box.width < 100 || box.height < 80) { await sleep(250); continue; }
    await current.canvas.click({ position: { x: Math.min(box.width - 10, box.width * 0.55), y: Math.min(box.height - 10, 52) }, force: true, timeout: 5_000 }).catch(() => {});
    await sleep(180); lastMouseInitialized = true;
    await current.canvas.focus();
    lastFocused = await current.canvas.evaluate((node) => document.activeElement === node).catch(() => false);
    if (!lastFocused) { await sleep(250); continue; }
    await page.keyboard.press('Control+Home'); await sleep(250);
    const homeSelected = current.editor.locator('[role="gridcell"][aria-selected="true"]').first();
    lastHomeTestId = await homeSelected.getAttribute('data-testid').catch(() => null);
    if (lastHomeTestId !== 'glide-cell-0-0') { await sleep(350); continue; }
    for (let row = 0; row < state.dataIndex; row += 1) { await page.keyboard.press('ArrowDown'); await sleep(40); }
    await sleep(300);
    const selected = current.editor.locator('[role="gridcell"][aria-selected="true"]').first();
    lastSelectedTestId = await selected.getAttribute('data-testid').catch(() => null);
    if (lastSelectedTestId === expectedTestId) return expectedTestId;
    await sleep(350);
  }
  throw new Error(`Glide navigation could not address ${expectedTestId} for ${providerName}; mouseInitialized=${lastMouseInitialized}, focused=${lastFocused}, home=${lastHomeTestId}, last selected=${lastSelectedTestId}.`);
}

async function selectLoadProvider(page, providerName) {
  let state = await providerLoadState(page, providerName);
  if (state.load === 'true') return state;
  if (state.load !== 'false') throw new Error(`Unexpected Load state for ${providerName}: ${state.load}`);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    state = await providerLoadState(page, providerName);
    if (state.load === 'true') return state;
    await navigateToLoadCell(page, state, providerName);
    await page.keyboard.press('Space');
    try { return await waitProviderLoadState(page, providerName, 'true', 10_000); }
    catch { await sleep(500); }
  }
  throw new Error(`Could not toggle Load for provider ${providerName}.`);
}

async function visibleOption(page, frame, text) {
  for (const options of [frame.getByRole('option'), page.getByRole('option'), frame.locator('[data-baseweb="menu"] li'), page.locator('[data-baseweb="menu"] li')]) {
    const count = await options.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const option = options.nth(index);
      if (!await option.isVisible().catch(() => false)) continue;
      if ((await option.innerText().catch(() => '')).trim() === text) return option;
    }
  }
  return null;
}

async function sidebarNavigation(page, name) {
  const started = performance.now();
  while (performance.now() - started < 120_000) {
    const frame = await appFrame(page, 'Climate Analyzer', 10_000);
    const candidates = [
      frame.locator('section[data-testid="stSidebar"] label').filter({ hasText: name }).last(),
      frame.locator('section[data-testid="stSidebar"]').getByText(name, { exact: true }).last(),
      frame.getByRole('radio', { name, exact: true }).last(),
    ];
    for (const candidate of candidates) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try { await candidate.click({ force: true, timeout: 5_000 }); await sleep(500); return; }
      catch { /* retry */ }
    }
    await sleep(400);
  }
  throw new Error(`Sidebar navigation item not found: ${name}`);
}

async function analysisCombo(frame) {
  const byLabel = frame.getByLabel('Analysis type', { exact: true }).first();
  if (await byLabel.count().catch(() => 0)) return byLabel;
  const control = frame.getByRole('combobox', { name: 'Analysis type' }).first();
  if (await control.count().catch(() => 0)) return control;
  throw new Error('Could not locate Analysis type selectbox.');
}

async function analysisOptions(page) {
  const frame = await appFrame(page, 'Precipitation and snow', 30_000);
  const control = await analysisCombo(frame);
  await control.click({ timeout: 10_000 }); await sleep(300);
  const values = [];
  for (const options of [frame.getByRole('option'), page.getByRole('option'), frame.locator('[data-baseweb="menu"] li'), page.locator('[data-baseweb="menu"] li')]) {
    const count = await options.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const option = options.nth(index); if (!await option.isVisible().catch(() => false)) continue;
      const text = (await option.innerText().catch(() => '')).trim(); if (text && !values.includes(text)) values.push(text);
    }
  }
  await page.keyboard.press('Escape').catch(() => {}); return values;
}

async function selectAnalysis(page, name) {
  const frame = await appFrame(page, 'Precipitation and snow', 30_000);
  const control = await analysisCombo(frame); await control.click({ timeout: 10_000 });
  const started = performance.now();
  while (performance.now() - started < 10_000) {
    const option = await visibleOption(page, frame, name);
    if (option) { await option.click({ timeout: 10_000 }); await sleep(500); return; }
    await sleep(200);
  }
  throw new Error(`Analysis option not found: ${name}`);
}

async function openPrecipitationPage(page) {
  let frame = await appFrame(page, 'Climate — Precipitation & snow', 180_000);
  const exact = frame.getByText('Climate — Precipitation & snow', { exact: true }).last();
  if (!(await exact.count().catch(() => 0))) throw new Error('Precipitation & snow navigation item not found.');
  await exact.click({ timeout: 15_000 });
  // The renderer's contract is asserted below through its actual analysis modes
  // and semantics captions. Do not depend on an obsolete page-level caption.
  frame = await appFrame(page, 'Precipitation and snow', 60_000);
  return frame;
}

const report = { schema: 'climate-analyzer-pr83-precip-snow-live-smoke-v2', target_url: TARGET_URL, fixture, started_at_utc: new Date().toISOString(), checks: {}, page_errors: [], console_errors: [], http_errors: [], success: false, error: null };
let browser; let page;
try {
  if (!fixture.success) throw new Error(`Provider fixture failed: ${fixture.error ?? 'unknown'}`);
  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => { if (message.type() === 'error') report.console_errors.push(message.text()); });
  page.on('response', (response) => { if (response.status() >= 400) report.http_errors.push({ status: response.status(), url: response.url() }); });
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  let frame = await chooseAndWait(page, 'GeoSphere Austria', 'GeoSphere Austria — measured historical station data');
  frame = await appFrame(page, 'Selected resource: klima-v2-10min', 30_000); report.checks.resource = 'klima-v2-10min';
  const station = await selectStationByName(page, frame, fixture.station_name, fixture.station_id); frame = station.frame; report.checks.station = station.metadata;
  const fromValue = await setDateInput(page, 'From date (UTC)', fixture.ui_start_date);
  const throughValue = await setDateInput(page, 'Through date (UTC)', fixture.ui_end_date);
  report.checks.date_interval = { requested_start: fixture.ui_start_date, requested_end: fixture.ui_end_date, rendered_start: fromValue, rendered_end: throughValue };
  const selected = {};
  for (const provider of fixture.required_provider_parameters) { const state = await selectLoadProvider(page, provider); selected[provider] = { load: state.load, row: state.ariaRowIndex, data_index: state.dataIndex }; }
  report.checks.selected_provider_parameters = selected;
  frame = await appFrame(page, 'Measured variables to load', 30_000);
  const loadButton = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  if (!(await loadButton.count().catch(() => 0))) throw new Error('GeoSphere load button not found after selecting rr/rrm/sh.');
  await loadButton.click({ timeout: 15_000 });
  frame = await openPrecipitationPage(page); report.checks.precipitation_page_opened = true;
  const expectedOptions = ['Precipitation totals','Annual precipitation indices','Liquid precipitation explorer','Precipitation-record occurrence','Measured precipitation duration','Snow-cover duration','Snow-season indices'];
  if (fixture.hourly_snow_available) expectedOptions.push('Snow depth explorer');
  const options = await analysisOptions(page); report.checks.analysis_options = options;
  const missing = expectedOptions.filter((value) => !options.includes(value)); if (missing.length) throw new Error(`Missing precipitation/snow analysis option(s): ${missing.join(', ')}`);
  await selectAnalysis(page, 'Annual precipitation indices'); await appFrame(page, 'Wet day ≥ 1 mm/day', 60_000); report.checks.annual_precipitation_indices = true;
  await selectAnalysis(page, 'Measured precipitation duration'); await appFrame(page, 'never inferred from precipitation depth rr', 60_000); report.checks.measured_precipitation_duration = true;
  await selectAnalysis(page, 'Precipitation-record occurrence'); await appFrame(page, 'record-occurrence metric, not rainfall duration', 60_000); report.checks.native_precipitation_occurrence = true;
  await selectAnalysis(page, 'Snow-cover duration'); await appFrame(page, 'source-state cadence', 60_000); report.checks.native_snow_cover_duration = true;
  await selectAnalysis(page, 'Snow-season indices'); await appFrame(page, 'July–June analysis year', 60_000); report.checks.snow_season_indices = true;
  if (report.page_errors.length) throw new Error(`Browser page error(s): ${report.page_errors.join(' | ')}`);
  await page.screenshot({ path: path.join(OUT_DIR, 'precipitation-snow-final.png'), fullPage: true }); report.success = true;
} catch (error) {
  report.error = String(error?.stack || error); if (page) await page.screenshot({ path: path.join(OUT_DIR, 'precipitation-snow-failure.png'), fullPage: true }).catch(() => {}); process.exitCode = 1;
} finally {
  report.completed_at_utc = new Date().toISOString(); await fs.writeFile(path.join(OUT_DIR, 'pr83-precip-snow-live-smoke.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report, null, 2)); if (browser) await browser.close().catch(() => {});
}
