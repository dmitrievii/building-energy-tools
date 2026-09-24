import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8502/';
const FIXTURE_PATH = process.env.PR83_MONTHLY_FIXTURE || 'artifacts/pr83-visual/monthly-provider.json';
const OUT_DIR = process.env.PR83_VISUAL_DIR || 'artifacts/pr83-visual/screenshots';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const REQUIRED = ['rf_mittel', 'p', 'tl_mittel'];
const PROVIDER_LABELS = {
  rf_mittel: 'Relative humidity — monthly mean',
  p: 'Station pressure — monthly mean',
  tl_mittel: 'Air temperature — monthly mean',
};

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
    if (await button.count().catch(() => 0)) {
      await button.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
      await button.click({ timeout: 15000 });
      return await appFrame(page, 'Parameter set', 60000);
    }
    await sleep(250);
  }
  throw new Error('Use station from list button did not become available.');
}

async function variableEditor(page) {
  const frame = await appFrame(page, 'Measured variables to load', 30000);
  const tables = frame.locator('[data-testid="stDataFrame"]');
  if (await tables.count() < 2) throw new Error('Measured-variable editor not found.');
  const editor = tables.last();
  const canvas = editor.locator('canvas[data-testid="data-grid-canvas"]').first();
  if (!(await canvas.count())) throw new Error('Measured-variable Glide canvas not found.');
  return { frame, editor, canvas };
}

async function resetEditor(page) {
  let current = await variableEditor(page);
  await current.editor.locator('.dvn-scroller').first().evaluate((node) => {
    node.scrollLeft = 0;
    node.scrollTop = 0;
    node.dispatchEvent(new Event('scroll', { bubbles: true }));
  }).catch(() => {});
  await sleep(500);
  return variableEditor(page);
}

async function providerState(page, provider) {
  const label = PROVIDER_LABELS[provider];
  if (!label) throw new Error(`No monthly label mapping for provider ${provider}.`);

  let current = await resetEditor(page);
  let lastScrollTop = -1;
  for (let scan = 0; scan < 40; scan += 1) {
    const rows = current.editor.locator('[role="grid"] tr[role="row"]');
    const count = await rows.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const row = rows.nth(i);
      const texts = (await row.locator('[role="gridcell"]').allTextContents().catch(() => []))
        .map((value) => value.replace(/\s+/g, ' ').trim());
      if (!texts.includes(label)) continue;

      const ariaRowIndex = Number(await row.getAttribute('aria-rowindex'));
      if (!Number.isFinite(ariaRowIndex) || ariaRowIndex < 2) {
        throw new Error(`Invalid row index for provider ${provider}: ${ariaRowIndex}`);
      }
      const load = String(
        await row.locator('[role="gridcell"][aria-colindex="1"]').first().textContent().catch(() => ''),
      ).trim().toLowerCase();
      return { ...current, load, dataIndex: ariaRowIndex - 2 };
    }

    const scroll = await current.editor.locator('.dvn-scroller').first().evaluate((node) => {
      const before = node.scrollTop;
      const max = Math.max(0, node.scrollHeight - node.clientHeight);
      const step = Math.max(80, Math.floor(node.clientHeight * 0.75));
      node.scrollTop = Math.min(max, before + step);
      node.dispatchEvent(new Event('scroll', { bubbles: true }));
      return { before, after: node.scrollTop };
    }).catch(() => null);
    if (!scroll || scroll.after <= scroll.before || scroll.after === lastScrollTop) break;
    lastScrollTop = scroll.after;
    await sleep(350);
    current = await variableEditor(page);
  }
  throw new Error(`Provider ${provider} (${label}) not visible while scanning the monthly variable editor.`);
}

async function navigateLoadCell(page, state, provider) {
  const expected = `glide-cell-0-${state.dataIndex}`;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const current = await resetEditor(page);
    const box = await current.canvas.boundingBox().catch(() => null);
    if (!box) continue;
    await current.canvas.click({
      position: { x: Math.min(box.width - 10, box.width * 0.55), y: Math.min(box.height - 10, 52) },
      force: true,
      timeout: 5000,
    }).catch(() => {});
    await current.canvas.focus();
    await page.keyboard.press('Control+Home');
    await sleep(200);

    const selected = current.editor.locator('[role="gridcell"][aria-selected="true"]').first();
    if (await selected.getAttribute('data-testid').catch(() => null) !== 'glide-cell-0-0') continue;
    for (let row = 0; row < state.dataIndex; row += 1) await page.keyboard.press('ArrowDown');
    await sleep(200);
    if (await selected.getAttribute('data-testid').catch(() => null) === expected) return;
  }
  throw new Error(`Could not address Load cell for ${provider}.`);
}

async function selectProvider(page, provider) {
  // This walkthrough starts from the product contract's fresh empty-selection
  // state. Glide's accessibility text for a boolean cell can lag the canvas and
  // report "true" even while the visible checkbox is empty. Do not use that
  // shadow text as permission to skip the real user interaction: address the
  // Load cell and toggle it exactly once from the known-fresh baseline.
  const state = await providerState(page, provider);
  await navigateLoadCell(page, state, provider);
  await page.keyboard.press('Space');
  await sleep(500);
  return {
    ...state,
    accessibilityStateBeforeToggle: state.load,
    toggledFromFreshBaseline: true,
  };
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
  schema: 'climate-analyzer-pr83-core-visual-v2',
  success: false,
  checks: {},
  page_errors: [],
  console_errors: [],
  error: null,
};
let browser;
let page;

try {
  browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => { if (message.type() === 'error') report.console_errors.push(message.text()); });

  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await chooseSource(page);
  await selectDataset(page);
  await selectStation(page);

  // A Streamlit fragment emits deltas incrementally. Seeing the Parameter-set
  // radio is not proof that the request form and DataEditor have completed their
  // render. Wait for the form heading that is emitted after both dates before
  // taking the visual/DOM contract snapshot.
  const sourceFrame = await appFrame(page, 'Measured variables to load', 30000);
  const sourceText = await bodyText(sourceFrame);
  report.checks.parameter_set_core = sourceText.includes('Core variables');
  report.checks.monthly_context_once = (sourceText.match(/About this GeoSphere monthly dataset/g) || []).length === 1;
  report.checks.core_editor_visible = sourceText.includes('Measured variables to load');
  await screenshot(page, '01-monthly-core-source.png');

  // GeoSphere selection is intentionally opt-in. Exercise the same three Core
  // variables used by the selected-load browser smoke. The boolean accessibility
  // shadow is diagnostic only; each visible Load cell is physically toggled once
  // from the fresh empty-selection baseline.
  const toggleEvidence = {};
  for (const provider of REQUIRED) {
    const state = await selectProvider(page, provider);
    toggleEvidence[provider] = {
      label: PROVIDER_LABELS[provider],
      accessibility_before_toggle: state.accessibilityStateBeforeToggle,
      data_index: state.dataIndex,
      toggled_from_fresh_baseline: state.toggledFromFreshBaseline,
    };
  }
  report.checks.required_core_variable_toggles = toggleEvidence;

  const loadFrame = await appFrame(page, 'Measured variables to load', 30000);
  const load = loadFrame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  if (!(await load.count().catch(() => 0))) throw new Error('Load button missing after explicit Core selection.');
  await load.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
  await sleep(700);
  await screenshot(page, '02-monthly-core-selected.png');
  await load.click({ timeout: 15000 });
  await appFrame(page, 'Summary — Overview', 180000);
  // Only the successful provider-load transition proves that the three staged
  // checkbox edits reached Python. Do not mark selection success before this.
  report.checks.required_core_variables_selected = true;
  report.checks.one_click_load_activated_dataset = true;

  await nav(page, 'Summary — Overview', 'Climate overview');
  await screenshot(page, '03-monthly-overview.png');

  await nav(page, 'Climate — Temperature', 'Temperature and extremes');
  let text = await bodyText(await appFrame(page, 'Temperature and extremes', 30000));
  report.checks.temperature_threshold_sliders_hidden = !text.includes('Heating threshold [°C]') && !text.includes('Cooling threshold [°C]');
  report.checks.dew_point_in_temperature = text.includes('Dew-point temperature');
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

  if (!report.checks.parameter_set_core) throw new Error('Core variables parameter set is not visible.');
  if (!report.checks.monthly_context_once) throw new Error('Monthly context is duplicated or missing.');
  if (!report.checks.core_editor_visible) throw new Error('Monthly variable editor is not visible.');
  if (!report.checks.required_core_variables_selected) throw new Error('Required Core variables were not committed through the provider load.');
  if (!report.checks.one_click_load_activated_dataset) throw new Error('One-click monthly Load did not activate the dataset.');
  if (!report.checks.temperature_threshold_sliders_hidden) throw new Error('Threshold-only temperature sliders leaked into the default Temperature view.');
  if (report.page_errors.length) throw new Error(`Page errors: ${report.page_errors.join(' | ')}`);
  report.success = true;
} catch (error) {
  report.error = String(error?.stack || error);
  if (page) await screenshot(page, '99-failure.png').catch(() => {});
  process.exitCode = 1;
} finally {
  await fs.writeFile(path.join(OUT_DIR, 'visual-walkthrough-core.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (browser) await browser.close().catch(() => {});
}
