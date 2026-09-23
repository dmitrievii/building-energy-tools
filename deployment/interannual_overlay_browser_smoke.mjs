import fs from 'node:fs/promises';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8501/';
const FIXTURE_PATH = process.env.INTERANNUAL_HOURLY_FIXTURE || 'artifacts/interannual-overlay/hourly-provider.json';
const OUT_PATH = process.env.INTERANNUAL_BROWSER_REPORT || 'artifacts/interannual-overlay/browser-report.json';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

async function combo(frame, label, timeoutMs = 30000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const candidate of [
      frame.getByRole('combobox', { name: label, exact: true }).first(),
      frame.getByLabel(label, { exact: true }).first(),
    ]) {
      if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    }
    await sleep(200);
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
    for (let i = 0; i < count; i += 1) {
      const option = options.nth(i);
      if (!(await option.isVisible().catch(() => false))) continue;
      const text = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
      if (predicate(text)) return option;
    }
  }
  return null;
}

async function selectComboOption(page, label, predicate) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const frame = await appFrame(page);
    const control = await combo(frame, label, 10000);
    await control.click({ timeout: 5000 });
    const option = await visibleOption(page, frame, predicate);
    if (option) {
      await option.click({ timeout: 5000 });
      await sleep(600);
      return appFrame(page);
    }
    await sleep(300);
  }
  throw new Error(`Could not select option for ${label}.`);
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

async function selectHourlyDataset(page) {
  await selectComboOption(page, 'GeoSphere dataset', (text) => text.includes('1 h') || text.includes('hour'));
  const frame = await appFrame(page, 'Selected resource: klima-v2-1h', 30000);
  return frame;
}

async function labelledInput(frame, label, timeoutMs = 30000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const candidate of [
      frame.getByLabel(label, { exact: true }).first(),
      frame.locator(`input[aria-label="${label}"]`).first(),
    ]) {
      if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    }
    await sleep(200);
  }
  throw new Error(`Input not found: ${label}`);
}

async function selectStation(page) {
  let frame = await appFrame(page, 'Search GeoSphere station');
  const search = await labelledInput(frame, 'Search GeoSphere station');
  await search.fill(String(fixture.station_name));
  await search.press('Tab').catch(() => {});
  await sleep(700);

  const started = performance.now();
  while (performance.now() - started < 45000) {
    frame = await appFrame(page, 'Manual station selection', 5000);
    const control = await combo(frame, 'Search-result stations', 5000).catch(() => null);
    if (!control) { await sleep(250); continue; }
    const text = [
      await control.textContent().catch(() => ''),
      await control.inputValue().catch(() => ''),
    ].join(' ');
    const matches = (value) => value.includes(fixture.station_name) && value.includes(String(fixture.station_id));
    if (!matches(text)) {
      await control.click({ timeout: 5000 }).catch(() => {});
      const option = await visibleOption(page, frame, matches);
      if (option) await option.click({ timeout: 5000 });
      await sleep(500);
      continue;
    }
    const button = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
    if (await button.count().catch(() => 0)) {
      await button.click({ timeout: 10000 });
      return appFrame(page, 'Measured variables to load', 30000);
    }
  }
  throw new Error('Could not commit station 105.');
}

function dateValueMatches(value, iso) {
  const [year, month, day] = iso.split('-').map(Number);
  const parts = String(value).split(/\D+/).filter(Boolean).map(Number);
  return parts.includes(year) && parts.includes(month) && parts.includes(day);
}

async function dateControl(frame, label) {
  const labelled = frame.getByLabel(label, { exact: true }).first();
  if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) {
    const tag = await labelled.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
    const role = await labelled.getAttribute('role').catch(() => null);
    if (['input', 'textarea', 'select'].includes(tag)) return { kind: 'input', locator: labelled };
    if (role === 'group' && await labelled.locator('[role="spinbutton"]').count().catch(() => 0) >= 3) {
      return { kind: 'segmented', locator: labelled };
    }
  }
  const aria = frame.locator(`input[aria-label="${label}"]`).first();
  if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return { kind: 'input', locator: aria };
  throw new Error(`Date control unavailable: ${label}`);
}

async function segmentedDateValue(group) {
  const segments = group.locator('[role="spinbutton"]');
  const values = {};
  for (let i = 0; i < await segments.count(); i += 1) {
    const segment = segments.nth(i);
    const label = String(await segment.getAttribute('aria-label').catch(() => '')).toLowerCase();
    const value = Number(await segment.getAttribute('aria-valuenow').catch(() => NaN));
    if (label.includes('year')) values.year = value;
    else if (label.includes('month')) values.month = value;
    else if (label.includes('day')) values.day = value;
  }
  if ([values.year, values.month, values.day].every(Number.isFinite)) {
    return `${values.year}-${String(values.month).padStart(2, '0')}-${String(values.day).padStart(2, '0')}`;
  }
  return await group.innerText().catch(() => '');
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
    await segment.click({ timeout: 10000 });
    const editable = await segment.getAttribute('contenteditable').catch(() => null);
    if (editable === 'true') await segment.fill(String(desired[part]), { timeout: 10000 });
    else {
      await segment.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {});
      await segment.press('Backspace').catch(() => {});
      await frame.page().keyboard.type(String(desired[part]), { delay: 50 });
    }
    await sleep(160);
  }
  await frame.page().keyboard.press('Tab').catch(() => {});
}

async function setDate(page, label, iso) {
  let lastValue = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const frame = await appFrame(page, 'Measured variables to load', 20000);
    const control = await dateControl(frame, label);
    if (control.kind === 'input') {
      const candidate = attempt === 0 ? iso.replaceAll('-', '/') : iso;
      await control.locator.click({ timeout: 10000 });
      await control.locator.fill(candidate, { timeout: 10000 });
      await control.locator.press('Enter').catch(() => {});
      await control.locator.press('Tab').catch(() => {});
    } else await setSegmentedDate(frame, control.locator, iso);
    await sleep(1000);
    const refreshedFrame = await appFrame(page, 'Measured variables to load', 20000);
    const refreshed = await dateControl(refreshedFrame, label);
    lastValue = refreshed.kind === 'input'
      ? await refreshed.locator.inputValue().catch(() => null)
      : await segmentedDateValue(refreshed.locator);
    if (dateValueMatches(lastValue, iso)) return lastValue;
  }
  throw new Error(`Date input ${label} did not accept ${iso}; observed ${lastValue}.`);
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
  await sleep(450);
  return variableEditor(page);
}

async function providerState(page, providerName) {
  let current = await resetEditor(page);
  let lastScrollTop = -1;
  for (let scan = 0; scan < 40; scan += 1) {
    const rows = current.editor.locator('[role="grid"] tr[role="row"]');
    const count = await rows.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const row = rows.nth(i);
      const provider = (await row.locator('[role="gridcell"][aria-colindex="4"]').textContent().catch(() => '')).trim();
      if (provider !== providerName) continue;
      const ariaRowIndex = Number(await row.getAttribute('aria-rowindex'));
      if (!Number.isFinite(ariaRowIndex) || ariaRowIndex < 2) throw new Error(`Invalid row index for ${providerName}: ${ariaRowIndex}`);
      const load = String(await row.locator('[role="gridcell"][aria-colindex="1"]').first().textContent().catch(() => '')).trim().toLowerCase();
      return { ...current, load, ariaRowIndex, dataIndex: ariaRowIndex - 2 };
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
  throw new Error(`Provider parameter ${providerName} not visible while scanning the measured-variable editor.`);
}

async function navigateToLoadCell(page, state, providerName) {
  const expected = `glide-cell-0-${state.dataIndex}`;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const current = await resetEditor(page);
    const box = await current.canvas.boundingBox().catch(() => null);
    if (!box || box.width < 100 || box.height < 80) continue;
    await current.canvas.click({ position: { x: Math.min(box.width - 10, box.width * 0.55), y: Math.min(box.height - 10, 52) }, force: true, timeout: 5000 }).catch(() => {});
    await current.canvas.focus();
    await page.keyboard.press('Control+Home');
    await sleep(220);
    const selected = current.editor.locator('[role="gridcell"][aria-selected="true"]').first();
    if (await selected.getAttribute('data-testid').catch(() => null) !== 'glide-cell-0-0') continue;
    for (let row = 0; row < state.dataIndex; row += 1) {
      await page.keyboard.press('ArrowDown');
      await sleep(35);
    }
    await sleep(220);
    if (await selected.getAttribute('data-testid').catch(() => null) === expected) return;
  }
  throw new Error(`Could not address Load cell for ${providerName}.`);
}

async function selectProvider(page, providerName) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const state = await providerState(page, providerName);
    if (state.load === 'true') return state;
    if (state.load !== 'false') throw new Error(`Unexpected Load state for ${providerName}: ${state.load}`);
    await navigateToLoadCell(page, state, providerName);
    await page.keyboard.press('Space');
    await sleep(150);
    await page.keyboard.press('Tab').catch(() => {});
    const started = performance.now();
    while (performance.now() - started < 15000) {
      const frame = await appFrame(page, 'Measured variables to load', 10000).catch(() => null);
      if (frame) {
        const button = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
        if (await button.count().catch(() => 0)) {
          const committed = await providerState(page, providerName).catch(() => null);
          if (committed?.load === 'true') return committed;
        }
      }
      await sleep(300);
    }
  }
  throw new Error(`Could not commit Load selection for provider ${providerName}.`);
}

async function allProviderStates(page) {
  let current = await resetEditor(page);
  let lastScrollTop = -1;
  const states = new Map();
  for (let scan = 0; scan < 40; scan += 1) {
    const rows = current.editor.locator('[role="grid"] tr[role="row"]');
    const count = await rows.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const row = rows.nth(i);
      const provider = (await row.locator('[role="gridcell"][aria-colindex="4"]').textContent().catch(() => '')).trim();
      if (!provider) continue;
      const ariaRowIndex = Number(await row.getAttribute('aria-rowindex'));
      if (!Number.isFinite(ariaRowIndex) || ariaRowIndex < 2) continue;
      const load = String(await row.locator('[role="gridcell"][aria-colindex="1"]').first().textContent().catch(() => '')).trim().toLowerCase();
      states.set(provider, { provider, load, ariaRowIndex, dataIndex: ariaRowIndex - 2 });
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
    await sleep(300);
    current = await variableEditor(page);
  }
  return [...states.values()].sort((a, b) => a.dataIndex - b.dataIndex);
}

async function setProviderLoadState(page, providerName, expected) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const state = await providerState(page, providerName);
    if (state.load === expected) return state;
    if (!['true', 'false'].includes(state.load)) throw new Error(`Unexpected Load state for ${providerName}: ${state.load}`);
    await navigateToLoadCell(page, state, providerName);
    await page.keyboard.press('Space');
    await sleep(150);
    await page.keyboard.press('Tab').catch(() => {});
    const started = performance.now();
    while (performance.now() - started < 12000) {
      const after = await providerState(page, providerName).catch(() => null);
      if (after?.load === expected) return after;
      await sleep(300);
    }
  }
  throw new Error(`Could not set provider ${providerName} Load=${expected}.`);
}

async function selectOnlyProvider(page, providerName) {
  const initial = await allProviderStates(page);
  if (!initial.some((item) => item.provider === providerName)) {
    throw new Error(`Required provider ${providerName} is absent from measured-variable editor.`);
  }
  for (const item of initial) {
    if (item.provider !== providerName && item.load === 'true') {
      await setProviderLoadState(page, item.provider, 'false');
    }
  }
  await setProviderLoadState(page, providerName, 'true');
  const final = await allProviderStates(page);
  const selected = final.filter((item) => item.load === 'true').map((item) => item.provider);
  if (selected.length !== 1 || selected[0] !== providerName) {
    throw new Error(`Expected only ${providerName} selected before load, got: ${selected.join(', ')}`);
  }
  return final.find((item) => item.provider === providerName);
}

async function loadDataset(page) {
  const started = performance.now();
  while (performance.now() - started < 30000) {
    const frame = await appFrame(page, 'Measured variables to load', 10000);
    const button = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
    if (await button.count().catch(() => 0)) {
      await button.click({ timeout: 15000 });
      return appFrame(page, 'Explore — Time series & overlay', 120000);
    }
    await sleep(300);
  }
  const state = await providerState(page, 'tl').catch(() => null);
  throw new Error(`GeoSphere load button did not appear after committed tl selection; tl=${state?.load ?? 'unavailable'}.`);
}

async function chooseTimeBasis(page) {
  await selectComboOption(page, 'Time basis', (text) => text.trim() === 'Interannual overlay');
  const frame = await appFrame(page);
  const control = await combo(frame, 'Time basis');
  const rendered = `${await control.textContent().catch(() => '')} ${await control.inputValue().catch(() => '')}`;
  if (!rendered.includes('Interannual overlay')) throw new Error('Interannual overlay time basis did not commit.');
}

async function openOverlay(page) {
  const frame = await appFrame(page);
  const target = frame.getByText('Explore — Time series & overlay', { exact: true }).last();
  if (!(await target.count().catch(() => 0))) throw new Error('Time series & overlay navigation item missing.');
  await target.click({ force: true, timeout: 10000 });
  return appFrame(page, 'Time series and overlay', 30000);
}

async function setSeriesCountOne(page) {
  const frame = await appFrame(page, 'Time series and overlay');
  const slider = frame.getByRole('slider', { name: 'Number of series', exact: true }).first();
  if (!(await slider.count().catch(() => 0))) return;
  await slider.focus();
  await slider.press('Home');
  await sleep(500);
}

async function setResolution(page, resolution) {
  await selectComboOption(page, 'Series 1 resolution', (text) => text.trim() === resolution);
  await appFrame(page, 'Time series and overlay');
  await sleep(500);
}

async function plotSnapshot(page) {
  const frame = await appFrame(page, 'Time series and overlay');
  const plots = frame.locator('.js-plotly-plot');
  if (!(await plots.count().catch(() => 0))) throw new Error('No Plotly chart found on overlay page.');
  const plot = plots.last();
  return plot.evaluate((node) => ({
    traces: (node.data || []).map((trace) => ({
      name: trace.name,
      legendgroup: trace.legendgroup,
      visible: trace.visible ?? true,
      x: Array.from(trace.x || []).map((value) => value == null ? null : String(value)),
      y: Array.from(trace.y || []).map((value) => value == null ? null : Number(value)),
      customdata: Array.from(trace.customdata || []),
      hovertemplate: String(trace.hovertemplate || ''),
    })),
    xaxisTitle: node.layout?.xaxis?.title?.text || '',
  }));
}

function assertYears(snapshot, expectedYears, label) {
  const names = snapshot.traces.map((trace) => trace.name || '');
  for (const year of expectedYears) {
    if (!names.some((name) => name.includes(String(year)))) throw new Error(`${label}: legend does not contain ${year}: ${names.join(' | ')}`);
  }
  for (const trace of snapshot.traces) {
    if (!trace.hovertemplate.includes('Year:') || !trace.hovertemplate.includes('Value:')) {
      throw new Error(`${label}: trace hover template lost real-year/value semantics.`);
    }
  }
}

async function exerciseHover(page) {
  const frame = await appFrame(page, 'Time series and overlay');
  const plot = frame.locator('.js-plotly-plot').last();
  await plot.evaluate((node) => {
    if (!window.Plotly) throw new Error('Plotly global unavailable');
    window.Plotly.Fx.hover(node, [{ curveNumber: 0, pointNumber: 0 }]);
  });
  await sleep(250);
  const hover = frame.locator('.hoverlayer').last();
  const text = await hover.innerText().catch(() => '');
  if (!text.includes('Year:') || !text.includes('Value:')) throw new Error(`Hover did not expose Year and Value: ${text}`);
  return text.replace(/\s+/g, ' ').trim();
}

async function exerciseLegendToggle(page) {
  const frame = await appFrame(page, 'Time series and overlay');
  const plot = frame.locator('.js-plotly-plot').last();
  const firstLegend = plot.locator('.legend .traces').first();
  if (!(await firstLegend.count().catch(() => 0))) throw new Error('Legend item unavailable for toggle test.');
  await firstLegend.click({ timeout: 5000 });
  await sleep(350);
  const visible = await plot.evaluate((node) => node.data?.[0]?.visible ?? true);
  if (visible !== 'legendonly') throw new Error(`Legend click did not hide first yearly trace; visible=${visible}`);
  await firstLegend.click({ timeout: 5000 });
  await sleep(250);
  return true;
}

const report = { schema: 'climate-analyzer-interannual-overlay-browser-v1', fixture, checks: {}, page_errors: [], success: false, error: null };
let browser;
try {
  if (!fixture.success || fixture.resource_id !== 'klima-v2-1h') throw new Error('Invalid hourly interannual fixture.');
  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  const page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await chooseSource(page);
  await selectHourlyDataset(page);
  await selectStation(page);
  await setDate(page, 'From date (UTC)', fixture.ui_start_date);
  await setDate(page, 'Through date (UTC)', fixture.ui_end_date);
  await selectOnlyProvider(page, 'tl');
  await loadDataset(page);
  report.checks.hourly_multiyear_loaded = true;

  await chooseTimeBasis(page);
  await openOverlay(page);
  await setSeriesCountOne(page);

  await setResolution(page, 'Daily');
  const daily = await plotSnapshot(page);
  assertYears(daily, [2024, 2025], 'Daily');
  report.checks.daily_years = daily.traces.map((trace) => trace.name);
  report.checks.daily_hover = await exerciseHover(page);
  report.checks.legend_toggle = await exerciseLegendToggle(page);

  await setResolution(page, 'Monthly');
  const monthly = await plotSnapshot(page);
  assertYears(monthly, [2024, 2025], 'Monthly');
  const months = monthly.traces.flatMap((trace) => trace.x.filter(Boolean));
  if (!months.some((value) => value.includes('2000-12')) || !months.some((value) => value.includes('2000-01'))) {
    throw new Error(`Monthly calendar axis does not contain Dec and Jan positions: ${months.join(' | ')}`);
  }
  report.checks.monthly_years = monthly.traces.map((trace) => trace.name);
  report.checks.calendar_axis_title = monthly.xaxisTitle;

  if (report.page_errors.length) throw new Error(`Browser page errors: ${report.page_errors.join(' | ')}`);
  report.success = true;
} catch (error) {
  report.error = String(error?.stack || error);
  process.exitCode = 1;
} finally {
  report.completed_at_utc = new Date().toISOString();
  await fs.mkdir('artifacts/interannual-overlay', { recursive: true });
  await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (browser) await browser.close().catch(() => {});
}
