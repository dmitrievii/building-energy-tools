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

async function selectComboOption(page, label, predicate) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const frame = await appFrame(page);
    const control = await combo(frame, label, 10000);
    await control.click({ timeout: 5000 });
    const option = await visibleOption(page, frame, predicate);
    if (option) {
      await option.click({ timeout: 5000 });
      await sleep(700);
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
  let search = await labelledInput(frame, 'Search GeoSphere station');
  await search.fill(String(stationName), { timeout: 15000 });
  await search.press('Tab').catch(() => {});
  await sleep(800);

  const started = performance.now();
  let observed = '';
  while (performance.now() - started < 60000) {
    frame = await appFrame(page, 'Manual station selection', 5000);
    search = await labelledInput(frame, 'Search GeoSphere station', 5000).catch(() => null);
    if (search && await search.inputValue().catch(() => '') !== String(stationName)) {
      await search.fill(String(stationName), { timeout: 5000 }).catch(() => {});
      await search.press('Tab').catch(() => {});
      await sleep(500);
    }

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

function dateValueMatches(value, iso) {
  const [year, month, day] = iso.split('-').map(Number);
  const parts = String(value).split(/\D+/).filter(Boolean).map(Number);
  return parts.includes(year) && parts.includes(month) && parts.includes(day);
}

async function dateControl(frame, label, timeoutMs = 30000) {
  const started = performance.now();
  let current = frame;
  while (performance.now() - started < timeoutMs) {
    const labelled = current.getByLabel(label, { exact: true }).first();
    if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) {
      const tag = await labelled.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
      const role = await labelled.getAttribute('role').catch(() => null);
      if (['input', 'textarea', 'select'].includes(tag)) return { kind: 'input', locator: labelled };
      if (role === 'group' && await labelled.locator('[role="spinbutton"]').count().catch(() => 0) >= 3) {
        return { kind: 'segmented', locator: labelled };
      }
    }
    const aria = current.locator(`input[aria-label="${label}"]`).first();
    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return { kind: 'input', locator: aria };
    await sleep(200);
    current = await appFrame(current.page(), 'Measured variables to load', 5000).catch(() => current);
  }
  throw new Error(`Date control unavailable after ${timeoutMs} ms: ${label}`);
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
    } else {
      await setSegmentedDate(frame, control.locator, iso);
    }
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

async function waitMonthlySurface(page, timeoutMs = 60000) {
  const started = performance.now();
  let stable = 0;
  let last = '';
  while (performance.now() - started < timeoutMs) {
    const frame = await appFrame(page, 'Measured variables to load', 5000);
    const text = await bodyText(frame);
    last = text;
    const ready = (
      text.includes('Selected resource: klima-v2-1m') &&
      text.includes('Parameter set') &&
      text.includes('Core variables') &&
      text.includes('Core + additional statistics') &&
      text.includes('All provider parameters') &&
      text.includes('Select at least one measured GeoSphere variable to load.')
    );
    if (ready) {
      stable += 1;
      if (stable >= 3) return frame;
    } else {
      stable = 0;
    }
    await sleep(300);
  }
  throw new Error(`Monthly selector did not settle; Parameter set=${last.includes('Parameter set')}`);
}

async function selectParameterSet(page, name) {
  const started = performance.now();
  while (performance.now() - started < 45000) {
    const frame = await appFrame(page, 'Measured variables to load', 5000);
    const radio = frame.getByRole('radio', { name, exact: true }).last();
    if (await radio.count().catch(() => 0) && await radio.isVisible().catch(() => false)) {
      if (await radio.isChecked().catch(() => false)) return frame;
      await radio.check({ force: true, timeout: 5000 }).catch(async () => {
        await frame.getByText(name, { exact: true }).last().click({ force: true, timeout: 5000 }).catch(() => {});
      });
    } else {
      await frame.getByText(name, { exact: true }).last().click({ force: true, timeout: 5000 }).catch(() => {});
    }
    await sleep(600);
    const settled = await appFrame(page, 'Measured variables to load', 10000).catch(() => null);
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
      return { ...current, load, ariaRowIndex, dataIndex: ariaRowIndex - 2 };
    }

    const scroll = await current.editor.locator('.dvn-scroller').first().evaluate((node) => {
      const before = node.scrollTop;
      const max = Math.max(0, node.scrollHeight - node.clientHeight);
      const step = Math.max(80, Math.floor(node.clientHeight * 0.75));
      node.scrollTop = Math.min(max, before + step);
      node.dispatchEvent(new Event('scroll', { bubbles: true }));
      return { before, after: node.scrollTop, max };
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
      position: {
        x: Math.min(box.width - 10, box.width * 0.55),
        y: Math.min(box.height - 10, 52),
      },
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
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const state = await providerState(page, provider);
    if (state.load === 'true') return state;
    if (state.load !== 'false') throw new Error(`Unexpected Load state for ${provider}: ${state.load}`);

    await navigateLoadCell(page, state, provider);
    await page.keyboard.press('Space');

    const started = performance.now();
    while (performance.now() - started < 12000) {
      const after = await providerState(page, provider).catch(() => null);
      if (after?.load === 'true') return after;
      await sleep(300);
    }
  }
  throw new Error(`Could not select provider ${provider}.`);
}


async function chooseTimeBasis(page) {
  await selectComboOption(page, 'Time basis', (text) => text.trim() === 'Interannual overlay');
  const frame = await appFrame(page);
  const control = await combo(frame, 'Time basis');
  const value = `${await control.textContent().catch(() => '')} ${await control.inputValue().catch(() => '')}`;
  if (!value.includes('Interannual overlay')) throw new Error('Interannual overlay time basis did not commit.');
}

async function openOverlay(page) {
  const frame = await appFrame(page);
  const target = frame.getByText('Explore — Time series & overlay', { exact: true }).last();
  if (!(await target.count().catch(() => 0))) throw new Error('Time series & overlay navigation item missing.');
  await target.click({ force: true, timeout: 10000 });
  return appFrame(page, 'Time series and overlay', 30000);
}

async function seriesCountSlider(frame) {
  const labels = frame.getByText('Number of series', { exact: true });
  const labelCount = await labels.count().catch(() => 0);
  for (let index = 0; index < labelCount; index += 1) {
    const label = labels.nth(index);
    if (!(await label.isVisible().catch(() => false))) continue;
    const container = label.locator(
      'xpath=ancestor::*[descendant::*[@role="slider"] or descendant::input[@type="range"]][1]'
    );
    if (!(await container.count().catch(() => 0))) continue;
    let slider = container.locator('[role="slider"]').first();
    if (!(await slider.count().catch(() => 0))) slider = container.locator('input[type="range"]').first();
    if (await slider.count().catch(() => 0) && await slider.isVisible().catch(() => false)) return slider;
  }

  const candidates = frame.locator('[role="slider"], input[type="range"]');
  const candidateCount = await candidates.count().catch(() => 0);
  for (let index = 0; index < candidateCount; index += 1) {
    const candidate = candidates.nth(index);
    if (!(await candidate.isVisible().catch(() => false))) continue;
    const min = await candidate.getAttribute('aria-valuemin').catch(() => null) ?? await candidate.getAttribute('min').catch(() => null);
    const max = await candidate.getAttribute('aria-valuemax').catch(() => null) ?? await candidate.getAttribute('max').catch(() => null);
    if (String(min) === '1' && String(max) === '6') return candidate;
  }
  return null;
}

async function sliderNumericValue(slider) {
  const aria = await slider.getAttribute('aria-valuenow').catch(() => null);
  if (aria != null && aria !== '') return Number(aria);
  const raw = await slider.inputValue().catch(() => null);
  return raw == null || raw === '' ? NaN : Number(raw);
}

async function setSeriesCountOne(page) {
  let lastValue = NaN;
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const frame = await appFrame(page, 'Time series and overlay', 10000);
    const slider = await seriesCountSlider(frame);
    if (!slider) {
      const text = (await bodyText(frame).catch(() => '')).replace(/\s+/g, ' ').trim();
      throw new Error(`Number of series slider is unavailable. Page text: ${text.slice(-900)}`);
    }
    lastValue = await sliderNumericValue(slider);
    if (lastValue === 1) {
      await sleep(700);
      return;
    }
    await slider.focus();
    await slider.press('Home', { timeout: 5000 }).catch(async () => {
      await slider.press('ArrowLeft', { timeout: 5000 });
    });
    await frame.page().keyboard.press('Tab').catch(() => {});
    await sleep(900);
  }
  const frame = await appFrame(page, 'Time series and overlay', 10000);
  const slider = await seriesCountSlider(frame);
  lastValue = slider ? await sliderNumericValue(slider) : NaN;
  if (lastValue !== 1) throw new Error(`Could not commit Number of series = 1; observed ${lastValue}.`);
}

async function inspectResolutionControl(page) {
  const frame = await appFrame(page, 'Time series and overlay', 10000);
  const control = await combo(frame, 'Series 1 resolution', 10000);
  const renderedValue = await rendered(control);
  const options = [];

  await control.click({ timeout: 5000 }).catch(() => {});
  await sleep(250);
  for (const candidates of [
    frame.getByRole('option'),
    page.getByRole('option'),
    frame.locator('[data-baseweb="menu"] li'),
    page.locator('[data-baseweb="menu"] li'),
  ]) {
    const count = await candidates.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const option = candidates.nth(index);
      if (!(await option.isVisible().catch(() => false))) continue;
      const value = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
      if (value && !options.includes(value)) options.push(value);
    }
  }
  await page.keyboard.press('Escape').catch(() => {});
  return { rendered: renderedValue, visible_options: options };
}

async function plotSnapshot(page, timeoutMs = 30000) {
  const started = performance.now();
  let lastBody = '';
  while (performance.now() - started < timeoutMs) {
    const frame = await appFrame(page, 'Time series and overlay', 10000);
    const plots = frame.locator('.js-plotly-plot');
    const count = await plots.count().catch(() => 0);
    if (count) {
      const plot = plots.last();
      const snapshot = await plot.evaluate((node) => ({
        traces: (node.data || []).map((trace) => ({
          name: String(trace.name || ''),
          legendgroup: String(trace.legendgroup || ''),
          mode: String(trace.mode || ''),
          x: Array.from(trace.x || []).map((value) => value == null ? null : String(value)),
          y: Array.from(trace.y || []).map((value) => value == null ? null : Number(value)),
          customdata: Array.from(trace.customdata || []),
          hovertemplate: String(trace.hovertemplate || ''),
        })),
        tickformat: String(node.layout?.xaxis?.tickformat || ''),
        dtick: node.layout?.xaxis?.dtick ?? null,
        xaxisTitle: String(node.layout?.xaxis?.title?.text || ''),
      })).catch(() => null);
      if (snapshot && snapshot.traces.length) return snapshot;
    }
    lastBody = (await bodyText(frame).catch(() => '')).replace(/\s+/g, ' ').trim();
    await sleep(250);
  }
  throw new Error(`Native monthly Plotly chart did not render within ${timeoutMs} ms. Page text: ${lastBody.slice(-1200)}`);
}

function assertNativeMonthlyInterannual(snapshot) {
  const expectedYears = [2020, 2021, 2022, 2023, 2024, 2025];
  if (snapshot.traces.length !== expectedYears.length) {
    throw new Error(`Expected 6 Native monthly yearly traces, got ${snapshot.traces.length}: ${snapshot.traces.map((trace) => trace.name).join(' | ')}`);
  }
  for (const year of expectedYears) {
    const matches = snapshot.traces.filter((trace) => trace.name.includes(String(year)));
    if (matches.length !== 1) throw new Error(`Expected exactly one Native monthly trace for ${year}, got ${matches.length}.`);
    const trace = matches[0];
    if (!trace.mode.includes('markers')) throw new Error(`Native monthly ${year} trace must expose markers; mode=${trace.mode}`);
    const positions = trace.x.filter(Boolean);
    if (positions.length !== 12) throw new Error(`Native monthly ${year} trace has ${positions.length} calendar positions, expected 12.`);
    const months = positions.map((value) => {
      const match = String(value).match(/2000-(\d{2})-/);
      return match ? Number(match[1]) : NaN;
    });
    if (months.join(',') !== '1,2,3,4,5,6,7,8,9,10,11,12') {
      throw new Error(`Native monthly ${year} calendar positions are not Jan-Dec: ${positions.join(' | ')}`);
    }
    const custom = trace.customdata.filter((row) => Array.isArray(row) && row[0] != null);
    if (custom.length !== 12) throw new Error(`Native monthly ${year} customdata has ${custom.length} rows, expected 12.`);
    for (const row of custom) {
      if (Number(row[0]) !== year) throw new Error(`Native monthly ${year} customdata lost real-year identity: ${JSON.stringify(row)}`);
      if (!String(row[1] || '').startsWith(`${year}-`)) throw new Error(`Native monthly ${year} source timestamp is not real-year provenance: ${JSON.stringify(row)}`);
      if (String(row[3] || '') !== 'Native') throw new Error(`Native monthly ${year} resolution provenance is not Native: ${JSON.stringify(row)}`);
    }
    if (!trace.hovertemplate.includes('Year:') || !trace.hovertemplate.includes('Source:') || !trace.hovertemplate.includes('Value:')) {
      throw new Error(`Native monthly ${year} hover template lost Year/Source/Value semantics.`);
    }
  }
  if (snapshot.tickformat !== '%b') throw new Error(`Native monthly x-axis tickformat must be %b, got ${snapshot.tickformat}.`);
  if (String(snapshot.dtick) !== 'M1') throw new Error(`Native monthly x-axis dtick must be M1, got ${snapshot.dtick}.`);
  if (snapshot.xaxisTitle !== 'Calendar position') throw new Error(`Native monthly x-axis title changed: ${snapshot.xaxisTitle}`);
  return expectedYears;
}

async function renderedHoverText(plot) {
  const labels = await plot.locator('.hoverlayer text').allTextContents().catch(() => []);
  return labels.join(' ').replace(/\s+/g, ' ').trim();
}

async function waitForHoverText(plot, timeoutMs = 5000) {
  const started = performance.now();
  let text = '';
  while (performance.now() - started < timeoutMs) {
    text = await renderedHoverText(plot);
    if (text.includes('Year:') && text.includes('Value:')) return text;
    await sleep(100);
  }
  return text;
}

async function exerciseHover(page) {
  const frame = await appFrame(page, 'Time series and overlay');
  const plot = frame.locator('.js-plotly-plot').last();
  const target = await plot.evaluate((node) => {
    if (!window.Plotly) throw new Error('Plotly global unavailable');
    const traces = Array.from(node.data || []);
    for (let curveNumber = 0; curveNumber < traces.length; curveNumber += 1) {
      const values = Array.from(traces[curveNumber].y || []);
      const pointNumber = values.findIndex((value) => value != null && Number.isFinite(Number(value)));
      if (pointNumber >= 0) {
        window.Plotly.Fx.hover(node, [{ curveNumber, pointNumber }]);
        return { curveNumber, pointNumber };
      }
    }
    throw new Error('No finite Native monthly point is available for hover exercise.');
  });
  const text = await waitForHoverText(plot, 5000);
  if (!text.includes('Year:') || !text.includes('Value:')) {
    throw new Error(`Native monthly hover did not expose Year and Value for curve ${target.curveNumber}, point ${target.pointNumber}: ${text}`);
  }
  return text;
}

const report = {
  schema: 'climate-analyzer-monthly-selected-load-smoke-v8-native-interannual',
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
    throw new Error('Monthly fixture must resolve station 105 successfully.');
  }
  if (!(Number(fixture.valid_dew_point_months) > 0)) {
    throw new Error('Monthly fixture does not prove dew-point capability.');
  }
  if (!(Number(fixture.measured_station_pressure_months) > 0)) {
    throw new Error('Monthly fixture does not prove measured station pressure.');
  }

  browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
    locale: 'en-US',
  });
  const page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => {
    if (message.type() === 'error') report.console_errors.push(message.text());
  });

  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await chooseSource(page);
  await selectDataset(page);
  await selectStation(page, fixture.station_name, fixture.station_id);
  await setDate(page, 'From date (UTC)', '2020-01-01');
  await setDate(page, 'Through date (UTC)', '2025-12-31');
  report.checks.requested_interval = ['2020-01-01', '2025-12-31'];

  let frame = await waitMonthlySurface(page);
  let text = await bodyText(frame);
  if (!text.includes('Select at least one measured GeoSphere variable to load.')) {
    throw new Error('Empty monthly selection warning is missing.');
  }
  if (await frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).count().catch(() => 0)) {
    throw new Error('Load button reachable with empty selection.');
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
  text = await bodyText(frame);
  if (text.includes('GeoSphere load complete')) {
    throw new Error('Checkbox edit triggered provider loading before mature load button.');
  }
  report.checks.checkbox_edit_did_not_activate_dataset = true;

  await selectParameterSet(page, 'Core variables');
  frame = await appFrame(page, 'Measured variables to load', 20000);
  if (!(await frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).count().catch(() => 0))) {
    throw new Error('Selection lost on All -> Core transition.');
  }
  report.checks.core_all_core_load_button_preserved = true;

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

  frame = await appFrame(page, 'Explore — Time series & overlay', 180000);
  report.checks.canonical_dataset_activated = true;
  report.checks.dew_point_contract_from_fixture = true;
  report.checks.measured_station_pressure_contract_from_fixture = true;

  await chooseTimeBasis(page);
  await openOverlay(page);
  await setSeriesCountOne(page);
  report.checks.resolution_ui = await inspectResolutionControl(page);
  const nativeMonthly = await plotSnapshot(page);
  report.checks.native_monthly_years = assertNativeMonthlyInterannual(nativeMonthly);
  report.checks.native_monthly_trace_names = nativeMonthly.traces.map((trace) => trace.name);
  report.checks.native_monthly_positions_per_year = Object.fromEntries(
    nativeMonthly.traces.map((trace) => [trace.legendgroup, trace.x.filter(Boolean).length]),
  );
  report.checks.native_monthly_axis = { tickformat: nativeMonthly.tickformat, dtick: nativeMonthly.dtick };
  report.checks.native_monthly_hover = await exerciseHover(page);

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
