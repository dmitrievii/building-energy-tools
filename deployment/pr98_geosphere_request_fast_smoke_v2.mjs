import fs from 'node:fs/promises';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8501/';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const FAST_MODE = ['1', 'true', 'yes'].includes(String(process.env.REQUEST_FAST_GATE || '1').toLowerCase());
const OUT_PATH = process.env.PR98_REQUEST_REPORT || 'artifacts/pr98-request-fast/request-report.json';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const LOAD_LABEL = 'Load measured GeoSphere interval';
const EMPTY_WARNING = 'Select at least one measured GeoSphere variable to load.';
const FORM_CAPTION = 'Variable choices are staged locally.';
const STATION_NAME = 'Wien Hohe Warte';
const STATION_ID = '105';
const REQUIRED = ['rf_mittel', 'p', 'tl_mittel'];
const LABELS = {
  rf_mittel: 'Relative humidity — monthly mean',
  p: 'Station pressure — monthly mean',
  tl_mittel: 'Air temperature — monthly mean',
};

async function bodyText(frame) {
  try { return await frame.locator('body').innerText({ timeout: 2000 }); }
  catch { return ''; }
}

async function appFrame(page, needle = 'Climate Analyzer', timeoutMs = 60000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      if ((await bodyText(frame)).includes(needle)) return frame;
    }
    await sleep(180);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}

async function combo(frame, label, timeoutMs = 20000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const candidate of [
      frame.getByRole('combobox', { name: label, exact: true }).first(),
      frame.getByLabel(label, { exact: true }).first(),
    ]) {
      if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    }
    await sleep(150);
  }
  throw new Error(`Combobox not found: ${label}`);
}

async function visibleOption(page, frame, predicate) {
  for (const options of [
    frame.getByRole('option'),
    page.getByRole('option'),
    frame.locator('[data-baseweb="menu"] li'),
    page.locator('[data-baseweb="menu"] li'),
  ]) {
    const count = await options.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const option = options.nth(index);
      if (!(await option.isVisible().catch(() => false))) continue;
      const text = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
      if (predicate(text)) return option;
    }
  }
  return null;
}

async function rendered(control) {
  return [
    await control.innerText().catch(() => ''),
    await control.textContent().catch(() => ''),
    await control.inputValue().catch(() => ''),
  ].join(' ').replace(/\s+/g, ' ').trim();
}

async function chooseSource(page) {
  const started = performance.now();
  while (performance.now() - started < 30000) {
    const frame = await appFrame(page, 'Climate Analyzer', 5000);
    for (const candidate of [
      frame.getByRole('radio', { name: 'GeoSphere Austria', exact: true }).last(),
      frame.getByText('GeoSphere Austria', { exact: true }).last(),
      frame.locator('label').filter({ hasText: 'GeoSphere Austria' }).last(),
    ]) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try {
        await candidate.click({ force: true, timeout: 5000 });
        return await appFrame(page, 'GeoSphere Austria — measured historical station data', 12000);
      } catch {}
    }
    await sleep(180);
  }
  throw new Error('Could not select GeoSphere Austria.');
}

async function selectMonthlyDataset(page) {
  const started = performance.now();
  while (performance.now() - started < 30000) {
    const frame = await appFrame(page, 'Climate Analyzer', 5000);
    const control = await combo(frame, 'GeoSphere dataset', 5000);
    const current = await rendered(control);
    const text = await bodyText(frame);
    if (current.includes('1 month') && text.includes('Selected resource: klima-v2-1m')) return frame;
    await control.click({ timeout: 5000 }).catch(() => {});
    const option = await visibleOption(page, frame, (value) => value.includes('1 month'));
    if (option) await option.click({ timeout: 5000 }).catch(() => {});
    await sleep(300);
  }
  throw new Error('Could not commit klima-v2-1m.');
}

async function labelledInput(frame, label, timeoutMs = 20000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const candidate of [
      frame.getByLabel(label, { exact: true }).first(),
      frame.locator(`input[aria-label="${label}"]`).first(),
    ]) {
      if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    }
    await sleep(150);
  }
  throw new Error(`Input not found: ${label}`);
}

async function selectStation(page) {
  let frame = await appFrame(page, 'Search GeoSphere station', 30000);
  const search = await labelledInput(frame, 'Search GeoSphere station');
  await search.fill(STATION_NAME, { timeout: 10000 });
  await search.press('Tab').catch(() => {});
  await sleep(400);

  const started = performance.now();
  while (performance.now() - started < 30000) {
    frame = await appFrame(page, 'Manual station selection', 5000);
    const control = await combo(frame, 'Search-result stations', 5000).catch(() => null);
    if (!control) { await sleep(180); continue; }
    const value = await rendered(control);
    const matches = (text) => text.includes(STATION_NAME) && (text.includes(`ID ${STATION_ID}`) || text.includes(STATION_ID));
    if (!matches(value)) {
      await control.click({ timeout: 5000 }).catch(() => {});
      const option = await visibleOption(page, frame, matches);
      if (option) await option.click({ timeout: 5000 }).catch(() => {});
      await sleep(300);
      continue;
    }
    const button = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
    if (await button.count().catch(() => 0) && await button.isVisible().catch(() => false)) {
      await button.click({ timeout: 10000 });
      return appFrame(page, 'Measured variables to load', 30000);
    }
    await sleep(180);
  }
  throw new Error(`Could not commit ${STATION_NAME} ID ${STATION_ID}.`);
}

async function waitMonthlySurface(page, timeoutMs = 20000) {
  const started = performance.now();
  let stable = 0;
  while (performance.now() - started < timeoutMs) {
    const frame = await appFrame(page, 'Measured variables to load', 5000);
    const text = await bodyText(frame);
    const ready = text.includes('Selected resource: klima-v2-1m')
      && text.includes('Parameter set')
      && text.includes('Core variables')
      && text.includes('All provider parameters')
      && text.includes(FORM_CAPTION);
    const load = frame.getByRole('button', { name: LOAD_LABEL, exact: true }).first();
    if (ready && await load.count().catch(() => 0) && await load.isVisible().catch(() => false)) {
      stable += 1;
      if (stable >= 2) return frame;
    } else stable = 0;
    await sleep(160);
  }
  throw new Error('Monthly request surface did not settle.');
}

async function assertEmptySubmitBlocked(page) {
  const frame = await waitMonthlySurface(page);
  const load = frame.getByRole('button', { name: LOAD_LABEL, exact: true }).first();
  await load.click({ timeout: 10000 });
  const validated = await appFrame(page, EMPTY_WARNING, 15000);
  const text = await bodyText(validated);
  if (!text.includes(EMPTY_WARNING)) throw new Error('Empty Load did not show validation warning.');
  if (text.includes('GeoSphere load complete')) throw new Error('Empty Load activated provider loading.');
  return validated;
}

async function measuredEditorRowCount(frame) {
  const tables = frame.locator('[data-testid="stDataFrame"]');
  if (await tables.count().catch(() => 0) < 2) return null;
  const raw = await tables.last().locator('[role="grid"]').first().getAttribute('aria-rowcount').catch(() => null);
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

async function selectParameterSet(page, name) {
  const initial = await waitMonthlySurface(page, 12000);
  const radio = initial.getByRole('radio', { name, exact: true }).last();
  if (await radio.count().catch(() => 0) && await radio.isChecked().catch(() => false)) return initial;

  const beforeRows = await measuredEditorRowCount(initial);
  const oldLoadHandle = await initial.getByRole('button', { name: LOAD_LABEL, exact: true }).first().elementHandle().catch(() => null);
  if (await radio.count().catch(() => 0) && await radio.isVisible().catch(() => false)) {
    await radio.check({ force: true, timeout: 5000 }).catch(async () => {
      await initial.getByText(name, { exact: true }).last().click({ force: true, timeout: 5000 });
    });
  } else {
    await initial.getByText(name, { exact: true }).last().click({ force: true, timeout: 5000 });
  }

  const started = performance.now();
  while (performance.now() - started < 20000) {
    const frame = await appFrame(page, 'Measured variables to load', 5000).catch(() => null);
    if (!frame) continue;
    const selected = frame.getByRole('radio', { name, exact: true }).last();
    const checked = Boolean(await selected.count().catch(() => 0) && await selected.isChecked().catch(() => false));
    const afterRows = await measuredEditorRowCount(frame);
    const oldDetached = oldLoadHandle ? await oldLoadHandle.evaluate((node) => !node.isConnected).catch(() => true) : true;
    const editorChanged = beforeRows != null && afterRows != null && beforeRows !== afterRows;
    if (checked && (oldDetached || editorChanged)) return waitMonthlySurface(page, 10000);
    await sleep(160);
  }
  throw new Error(`Parameter set did not finish Streamlit rerun: ${name}`);
}

async function variableEditor(page) {
  const frame = await appFrame(page, 'Measured variables to load', 15000);
  const tables = frame.locator('[data-testid="stDataFrame"]');
  if (await tables.count().catch(() => 0) < 2) throw new Error('Measured-variable editor not found.');
  const editor = tables.last();
  const canvas = editor.locator('canvas[data-testid="data-grid-canvas"]').first();
  if (!(await canvas.count().catch(() => 0))) throw new Error('Measured-variable Glide canvas not found.');
  return { frame, editor, canvas };
}

async function resetEditor(page) {
  let current = await variableEditor(page);
  await current.editor.locator('.dvn-scroller').first().evaluate((node) => {
    node.scrollLeft = 0;
    node.scrollTop = 0;
    node.dispatchEvent(new Event('scroll', { bubbles: true }));
  }).catch(() => {});
  await sleep(180);
  current = await variableEditor(page);
  return current;
}

async function providerState(page, provider) {
  const label = LABELS[provider];
  let current = await resetEditor(page);
  let previous = -1;

  for (let scan = 0; scan < 45; scan += 1) {
    const rows = current.editor.locator('[role="grid"] tr[role="row"]');
    const rowCount = await rows.count().catch(() => 0);
    for (let index = 0; index < rowCount; index += 1) {
      const row = rows.nth(index);
      const texts = (await row.locator('[role="gridcell"]').allTextContents().catch(() => []))
        .map((value) => value.replace(/\s+/g, ' ').trim());
      if (!texts.includes(label)) continue;
      const ariaRowIndex = Number(await row.getAttribute('aria-rowindex'));
      if (!Number.isFinite(ariaRowIndex) || ariaRowIndex < 2) {
        throw new Error(`Invalid Glide row index for ${provider}: ${ariaRowIndex}`);
      }
      const load = String(await row.locator('[role="gridcell"][aria-colindex="1"]').first().textContent().catch(() => '')).trim().toLowerCase();
      return { ...current, load, ariaRowIndex, dataIndex: ariaRowIndex - 2 };
    }
    const moved = await current.editor.locator('.dvn-scroller').first().evaluate((node) => {
      const before = node.scrollTop;
      const max = Math.max(0, node.scrollHeight - node.clientHeight);
      node.scrollTop = Math.min(max, before + Math.max(80, Math.floor(node.clientHeight * 0.7)));
      node.dispatchEvent(new Event('scroll', { bubbles: true }));
      return { before, after: node.scrollTop };
    }).catch(() => null);
    if (!moved || moved.after <= moved.before || moved.after === previous) break;
    previous = moved.after;
    await sleep(180);
    current = await variableEditor(page);
  }
  throw new Error(`Provider row not found: ${provider}`);
}

async function selectedCellId(editor) {
  const selected = editor.locator('[role="gridcell"][aria-selected="true"]').first();
  if (!(await selected.count().catch(() => 0))) return null;
  return selected.getAttribute('data-testid').catch(() => null);
}

async function waitSelectedCell(page, expected, timeoutMs = 2500) {
  const started = performance.now();
  let last = null;
  while (performance.now() - started < timeoutMs) {
    const current = await variableEditor(page);
    last = await selectedCellId(current.editor);
    if (last === expected) return current;
    await sleep(80);
  }
  throw new Error(`Glide selection did not reach ${expected}; last=${last ?? 'none'}`);
}

async function addressLoadCell(page, provider, dataIndex) {
  const expected = `glide-cell-0-${dataIndex}`;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const current = await resetEditor(page);
    const box = await current.canvas.boundingBox().catch(() => null);
    if (!box || box.width < 80 || box.height < 60) {
      await sleep(180);
      continue;
    }

    await current.canvas.click({
      position: { x: Math.min(box.width - 12, Math.max(40, box.width * 0.45)), y: Math.min(box.height - 12, 52) },
      force: true,
      timeout: 5000,
    }).catch(() => {});
    await current.canvas.focus();
    await page.keyboard.press('Control+Home');
    try { await waitSelectedCell(page, 'glide-cell-0-0', 2500); }
    catch { continue; }

    let ok = true;
    for (let row = 1; row <= dataIndex; row += 1) {
      const target = `glide-cell-0-${row}`;
      let reached = false;
      for (let keyAttempt = 0; keyAttempt < 3 && !reached; keyAttempt += 1) {
        await page.keyboard.press('ArrowDown');
        try {
          await waitSelectedCell(page, target, 1200);
          reached = true;
        } catch {
          const live = await variableEditor(page);
          const observed = await selectedCellId(live.editor);
          if (observed === target) reached = true;
        }
      }
      if (!reached) {
        ok = false;
        break;
      }
    }
    if (ok) {
      const finalEditor = await variableEditor(page);
      if (await selectedCellId(finalEditor.editor) === expected) return;
    }
  }
  throw new Error(`Could not deterministically address Load cell ${expected} for ${provider}.`);
}

async function waitProviderState(page, provider, expected, timeoutMs = 7000) {
  const started = performance.now();
  let last = null;
  while (performance.now() - started < timeoutMs) {
    try {
      last = await providerState(page, provider);
      if (last.load === expected) return last;
    } catch {}
    await sleep(180);
  }
  throw new Error(`Provider ${provider} did not become ${expected}; last=${last?.load ?? 'unavailable'}`);
}

async function selectProvider(page, provider) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const state = await providerState(page, provider);
    if (state.load === 'true') return state;
    if (state.load !== 'false') throw new Error(`Unexpected Load state for ${provider}: ${state.load}`);

    await addressLoadCell(page, provider, state.dataIndex);
    await page.keyboard.press('Space');
    try { return await waitProviderState(page, provider, 'true', 8000); }
    catch (error) {
      if (attempt === 2) throw error;
    }
  }
  throw new Error(`Could not select provider ${provider}.`);
}

const report = {
  schema: 'climate-analyzer-geosphere-request-fast-v2-stepwise-glide',
  mode: FAST_MODE ? 'fast' : 'load-path',
  target_url: TARGET_URL,
  checks: {},
  page_errors: [],
  console_errors: [],
  success: false,
  error: null,
};

let browser;
try {
  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  const page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => { if (message.type() === 'error') report.console_errors.push(message.text()); });

  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await chooseSource(page);
  await selectMonthlyDataset(page);
  await selectStation(page);
  await waitMonthlySurface(page);
  await assertEmptySubmitBlocked(page);
  report.checks.initial_empty_submit_blocked = true;

  await selectParameterSet(page, 'All provider parameters');
  for (const provider of REQUIRED) await selectProvider(page, provider);
  report.checks.all_three_selected = true;
  if ((await bodyText(await appFrame(page, 'Measured variables to load'))).includes('GeoSphere load complete')) {
    throw new Error('Checkbox edit triggered provider loading.');
  }
  report.checks.selection_is_local_until_load = true;

  await selectParameterSet(page, 'Core variables');
  await assertEmptySubmitBlocked(page);
  report.checks.all_to_core_reset = true;

  await selectParameterSet(page, 'All provider parameters');
  await assertEmptySubmitBlocked(page);
  report.checks.core_to_all_stays_empty = true;

  await selectParameterSet(page, 'Core variables');
  for (const provider of REQUIRED) await selectProvider(page, provider);
  report.checks.reselection_after_roundtrip = true;

  if (!FAST_MODE) {
    const frame = await waitMonthlySurface(page);
    await frame.getByRole('button', { name: LOAD_LABEL, exact: true }).first().click({ timeout: 10000 });
    await appFrame(page, 'Explore — Time series & overlay', 120000);
    report.checks.dataset_activated_after_explicit_load = true;
  } else {
    const frame = await appFrame(page, 'Measured variables to load');
    if ((await bodyText(frame)).includes('GeoSphere load complete')) throw new Error('Fast gate performed a measurement load.');
    report.checks.no_measurement_load_in_fast_mode = true;
  }

  if (report.page_errors.length) throw new Error(`Browser page error(s): ${report.page_errors.join(' | ')}`);
  report.success = true;
} catch (error) {
  report.error = String(error?.stack || error);
  process.exitCode = 1;
} finally {
  report.completed_at_utc = new Date().toISOString();
  await fs.mkdir(OUT_PATH.split('/').slice(0, -1).join('/') || '.', { recursive: true });
  await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (browser) await browser.close().catch(() => {});
}
