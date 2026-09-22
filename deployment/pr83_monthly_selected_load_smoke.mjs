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
const PROVIDER_LABELS = {
  rf_mittel: 'Relative humidity — monthly mean',
  p: 'Station pressure — monthly mean',
  tl_mittel: 'Air temperature — monthly mean',
};

async function bodyText(frame) {
  try { return await frame.locator('body').innerText({ timeout: 2000 }); }
  catch { return ''; }
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
    if (option) await option.click({ timeout: 5000 }).catch(() => {});
    await sleep(500);
  }
  throw new Error('Could not commit klima-v2-1m.');
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

async function selectStation(page, stationName, stationId) {
  const targetId = String(stationId);
  let frame = await appFrame(page, 'Search GeoSphere station', 60000);
  const search = await labelledInput(frame, 'Search GeoSphere station');
  await search.fill(String(stationName), { timeout: 15000 });
  await search.press('Tab').catch(() => {});
  await sleep(800);

  const started = performance.now();
  let observed = '';
  while (performance.now() - started < 60000) {
    frame = await appFrame(page, 'Manual station selection', 5000);

    const control = await combo(frame, 'Search-result stations', 5000).catch(() => null);
    if (!control) {
      await sleep(250);
      continue;
    }

    observed = await rendered(control);
    const matches = (text) => text.includes(stationName) && (text.includes(`ID ${targetId}`) || text.includes(targetId));
    if (!matches(observed)) {
      await control.click({ timeout: 5000 }).catch(() => {});
      const option = await visibleOption(page, frame, matches);
      if (option) await option.click({ timeout: 5000 }).catch(() => {});
      await sleep(500);
      continue;
    }

    const button = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
    if (await button.count().catch(() => 0) && await button.isVisible().catch(() => false)) {
      try {
        await button.click({ timeout: 10000 });
        return await appFrame(page, 'Measured variables to load', 60000);
      } catch {}
    }
    await sleep(250);
  }
  throw new Error(`Could not commit station ${stationName} ID ${targetId}; observed=${observed}`);
}

async function waitMonthlySurface(page, timeoutMs = 60000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const frame = await appFrame(page, 'Measured variables to load', 5000);
    const text = await bodyText(frame);
    if (
      text.includes('Selected resource: klima-v2-1m') &&
      text.includes('Parameter set') &&
      text.includes('Core variables') &&
      text.includes('Core + additional statistics') &&
      text.includes('All provider parameters') &&
      text.includes('Select at least one measured GeoSphere variable to load.')
    ) return frame;
    await sleep(300);
  }
  throw new Error('Monthly mature-loader selection surface did not settle.');
}

async function selectParameterSet(page, name) {
  const started = performance.now();
  while (performance.now() - started < 30000) {
    const frame = await appFrame(page, 'Measured variables to load', 5000);
    const radio = frame.getByRole('radio', { name, exact: true }).last();

    if (await radio.count().catch(() => 0) && await radio.isVisible().catch(() => false)) {
      if (await radio.isChecked().catch(() => false)) return frame;
      await radio.check({ force: true, timeout: 5000 }).catch(() => {});
    } else {
      await frame.getByText(name, { exact: true }).last().click({ force: true, timeout: 5000 }).catch(() => {});
    }

    await sleep(500);
    const settled = await appFrame(page, 'Measured variables to load', 5000).catch(() => null);
    if (settled) {
      const selected = settled.getByRole('radio', { name, exact: true }).last();
      if (await selected.count().catch(() => 0) && await selected.isChecked().catch(() => false)) return settled;
    }
  }
  throw new Error(`Parameter set did not commit: ${name}`);
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
  });
  await sleep(400);
  return variableEditor(page);
}

async function providerState(page, provider) {
  const label = PROVIDER_LABELS[provider];
  let current = await resetEditor(page);

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
        throw new Error(`Invalid row index for ${provider}: ${ariaRowIndex}`);
      }

      const load = String(
        await row.locator('[role="gridcell"][aria-colindex="1"]').first().textContent().catch(() => ''),
      ).trim().toLowerCase();

      return { ...current, load, ariaRowIndex, dataIndex: ariaRowIndex - 2 };
    }

    const moved = await current.editor.locator('.dvn-scroller').first().evaluate((node) => {
      const before = node.scrollTop;
      const max = Math.max(0, node.scrollHeight - node.clientHeight);
      node.scrollTop = Math.min(max, before + Math.max(80, Math.floor(node.clientHeight * 0.75)));
      node.dispatchEvent(new Event('scroll', { bubbles: true }));
      return node.scrollTop > before;
    }).catch(() => false);

    if (!moved) break;
    await sleep(300);
    current = await variableEditor(page);
  }

  throw new Error(`Provider ${provider} (${label}) not found in monthly editor.`);
}

async function selectProvider(page, provider) {
  const state = await providerState(page, provider);
  if (state.load === 'true') return state;
  if (state.load !== 'false') throw new Error(`Unexpected Load state for ${provider}: ${state.load}`);

  const current = await resetEditor(page);
  const box = await current.canvas.boundingBox();
  if (!box) throw new Error(`Could not address editor canvas for ${provider}.`);

  await current.canvas.click({
    position: {
      x: Math.min(box.width - 10, box.width * 0.55),
      y: Math.min(box.height - 10, 52),
    },
    force: true,
    timeout: 5000,
  });
  await current.canvas.focus();
  await page.keyboard.press('Control+Home');
  await sleep(150);

  const selected = current.editor.locator('[role="gridcell"][aria-selected="true"]').first();
  if (await selected.getAttribute('data-testid').catch(() => null) !== 'glide-cell-0-0') {
    throw new Error(`Could not focus first Load cell for ${provider}.`);
  }

  for (let row = 0; row < state.dataIndex; row += 1) await page.keyboard.press('ArrowDown');

  const expected = `glide-cell-0-${state.dataIndex}`;
  if (await selected.getAttribute('data-testid').catch(() => null) !== expected) {
    throw new Error(`Could not address Load cell for ${provider}.`);
  }

  await page.keyboard.press('Space');

  const started = performance.now();
  while (performance.now() - started < 12000) {
    const after = await providerState(page, provider).catch(() => null);
    if (after?.load === 'true') return after;
    await sleep(300);
  }
  throw new Error(`Provider ${provider} did not commit Load=true.`);
}

const report = {
  schema: 'climate-analyzer-monthly-selected-load-smoke-v6-minimal',
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
  if (!fixture.success || String(fixture.station_id) !== '105') {
    throw new Error('Monthly fixture must resolve Wien Hohe Warte ID 105 successfully.');
  }

  browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  const page = await context.newPage();

  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => {
    if (message.type() === 'error') report.console_errors.push(message.text());
  });

  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await chooseSource(page);
  await selectDataset(page);
  await selectStation(page, fixture.station_name, fixture.station_id);

  let frame = await waitMonthlySurface(page);
  if (await frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).count().catch(() => 0)) {
    throw new Error('Mature load button must be hidden for an empty monthly selection.');
  }
  report.checks.initial_selection_zero = true;
  report.checks.empty_selection_warning = true;

  await selectParameterSet(page, 'All provider parameters');

  const selected = {};
  for (const provider of REQUIRED) {
    const state = await selectProvider(page, provider);
    selected[provider] = {
      label: PROVIDER_LABELS[provider],
      load: state.load,
      row: state.ariaRowIndex,
    };
  }
  report.checks.selected_provider_parameters = selected;

  frame = await appFrame(page, 'Measured variables to load', 20000);
  if ((await bodyText(frame)).includes('GeoSphere load complete')) {
    throw new Error('Checkbox edit triggered provider loading before mature load button.');
  }
  report.checks.checkbox_edit_did_not_activate_dataset = true;

  await selectParameterSet(page, 'Core variables');
  frame = await appFrame(page, 'Measured variables to load', 20000);
  if (!(await frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).count().catch(() => 0))) {
    throw new Error('Selection was lost on All -> Core transition.');
  }

  await selectParameterSet(page, 'All provider parameters');
  for (const provider of REQUIRED) {
    const state = await providerState(page, provider);
    if (state.load !== 'true') throw new Error(`Provider-keyed roundtrip lost ${provider}.`);
  }
  report.checks.provider_keyed_roundtrip = true;

  await selectParameterSet(page, 'Core variables');
  frame = await appFrame(page, 'Measured variables to load', 20000);
  const loadButton = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  if (!(await loadButton.count().catch(() => 0))) throw new Error('Mature GeoSphere load button missing.');

  await loadButton.click({ timeout: 15000 });
  frame = await appFrame(page, 'Climate overview', 180000);
  if (!(await bodyText(frame)).includes('Climate overview')) {
    throw new Error('Monthly canonical dataset did not activate Overview.');
  }

  report.checks.mature_loader_invoked = true;
  report.checks.canonical_dataset_activated = true;
  report.checks.summary_overview = true;

  if (report.page_errors.length) {
    throw new Error(`Browser page error(s): ${report.page_errors.join(' | ')}`);
  }

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
