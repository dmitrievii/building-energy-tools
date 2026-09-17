import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'https://building-climate-analyzer.streamlit.app/';
const FIXTURE_PATH = process.env.GEOSPHERE_SMOKE_FIXTURE || 'artifacts/geosphere-precip-snow-smoke/provider-fixture.json';
const OUT_DIR = process.env.AUDIT_OUTPUT_DIR || 'artifacts/geosphere-precip-snow-smoke';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));

await fs.mkdir(OUT_DIR, { recursive: true });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function bodyText(frame) {
  try {
    return await frame.locator('body').innerText({ timeout: 2_000 });
  } catch {
    return '';
  }
}

async function waitForFrameContaining(page, text, timeoutMs = 90_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      const textContent = await bodyText(frame);
      if (textContent.includes(text)) return frame;
    }
    await sleep(400);
  }
  throw new Error(`Timed out waiting for app text: ${text}`);
}

async function waitForText(frame, text, timeoutMs = 90_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const textContent = await bodyText(frame);
    if (textContent.includes(text)) return textContent;
    await sleep(400);
  }
  throw new Error(`Timed out waiting for text: ${text}`);
}

async function clickChoice(frame, name) {
  // Match the strategy used by the stable general live audit: click the
  // visible Streamlit label text first. Clicking the hidden BaseWeb radio input
  // can change DOM checked-state without sending Streamlit's widget event.
  const exactText = frame.getByText(name, { exact: true });
  if (await exactText.count()) {
    await exactText.last().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }

  const label = frame.locator('label').filter({ hasText: name });
  if (await label.count()) {
    await label.last().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }

  const radio = frame.getByRole('radio', { name, exact: true });
  if (await radio.count()) {
    await radio.first().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }
  const tab = frame.getByRole('tab', { name, exact: true });
  if (await tab.count()) {
    await tab.first().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }
  const fuzzyText = frame.getByText(name, { exact: false });
  if (await fuzzyText.count()) {
    await fuzzyText.last().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }
  throw new Error(`Could not locate choice: ${name}`);
}

async function chooseAndWait(page, name, expectedText, timeoutMs = 45_000) {
  const started = performance.now();
  let attempts = 0;
  while (performance.now() - started < timeoutMs) {
    attempts += 1;
    let frame;
    try {
      frame = await waitForFrameContaining(page, 'Climate Analyzer', 10_000);
    } catch {
      await sleep(500);
      continue;
    }

    const candidates = [
      frame.locator('label').filter({ hasText: name }).last(),
      frame.getByText(name, { exact: true }).last(),
      frame.getByRole('radio', { name, exact: true }).last(),
    ];

    for (const candidate of candidates) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try {
        await candidate.scrollIntoViewIfNeeded({ timeout: 5_000 }).catch(() => {});
        const tagName = await candidate.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
        const inputType = await candidate.getAttribute('type').catch(() => null);
        if (tagName === 'input' && inputType === 'radio') {
          await candidate.check({ force: true, timeout: 5_000 });
        } else {
          await candidate.click({ force: true, timeout: 5_000 });
        }
      } catch {
        continue;
      }

      const verifyStarted = performance.now();
      while (performance.now() - verifyStarted < 6_000) {
        for (const currentFrame of page.frames()) {
          const textContent = await bodyText(currentFrame);
          if (textContent.includes(expectedText)) {
            return { frame: currentFrame, attempts };
          }
        }
        await sleep(300);
      }
    }

    await sleep(700);
  }
  throw new Error(`Timed out selecting ${name} and waiting for: ${expectedText}`);
}

async function labelledInput(frame, label, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const labelled = frame.getByLabel(label, { exact: true }).first();
    if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) {
      return labelled;
    }

    const aria = frame.locator(`input[aria-label="${label}"]`).first();
    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) {
      return aria;
    }

    // Streamlit can briefly render a widget skeleton before the real input is
    // mounted after a source-mode rerun. Resolve the input structurally from
    // the visible label only after the descendant input itself is visible.
    const domLabels = frame.locator('label').filter({ hasText: label });
    const domLabelCount = await domLabels.count().catch(() => 0);
    for (let index = 0; index < domLabelCount; index += 1) {
      const input = domLabels.nth(index).locator('input').first();
      if (await input.count().catch(() => 0) && await input.isVisible().catch(() => false)) {
        return input;
      }
    }

    const text = frame.getByText(label, { exact: true }).first();
    if (await text.count().catch(() => 0)) {
      const containers = [
        text.locator('xpath=..'),
        text.locator('xpath=../..'),
        text.locator('xpath=../../..'),
      ];
      for (const container of containers) {
        const input = container.locator('input').first();
        if (await input.count().catch(() => 0) && await input.isVisible().catch(() => false)) {
          return input;
        }
      }
    }
    await sleep(300);
  }
  throw new Error(`Timed out waiting for visible input: ${label}`);
}

async function fillInput(frame, label, value) {
  const input = await labelledInput(frame, label, 60_000);
  await input.fill(String(value), { timeout: 15_000 });
  await input.press('Tab').catch(() => {});
  await sleep(800);
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
      const tagName = await labelled.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
      const role = await labelled.getAttribute('role').catch(() => null);
      if (['input', 'textarea', 'select'].includes(tagName)) {
        return { kind: 'input', locator: labelled };
      }
      if (role === 'group') {
        const segmentCount = await labelled.locator('[role="spinbutton"]').count().catch(() => 0);
        if (segmentCount >= 3) return { kind: 'segmented', locator: labelled };
      }
    }

    const input = frame.locator(`input[aria-label="${label}"]`).first();
    if (await input.count().catch(() => 0) && await input.isVisible().catch(() => false)) {
      return { kind: 'input', locator: input };
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for date control: ${label}`);
}

async function segmentedDateValue(group) {
  const segments = group.locator('[role="spinbutton"]');
  const count = await segments.count();
  const values = {};
  for (let index = 0; index < count; index += 1) {
    const segment = segments.nth(index);
    const ariaLabel = String(await segment.getAttribute('aria-label').catch(() => '')).toLowerCase();
    const value = Number(await segment.getAttribute('aria-valuenow').catch(() => NaN));
    if (!Number.isFinite(value)) continue;
    if (ariaLabel.includes('month')) values.month = value;
    else if (ariaLabel.includes('day')) values.day = value;
    else if (ariaLabel.includes('year')) values.year = value;
  }
  if ([values.year, values.month, values.day].every(Number.isFinite)) {
    return `${values.year}-${String(values.month).padStart(2, '0')}-${String(values.day).padStart(2, '0')}`;
  }
  return (await group.innerText().catch(() => '')).trim();
}

async function setSegmentedDate(frame, group, iso) {
  const [year, month, day] = iso.split('-').map(Number);
  const desired = { year, month, day };
  const segments = group.locator('[role="spinbutton"]');
  const count = await segments.count();
  if (count < 3) throw new Error(`Segmented date control for ${iso} exposes only ${count} segment(s).`);

  const byPart = {};
  for (let index = 0; index < count; index += 1) {
    const segment = segments.nth(index);
    const ariaLabel = String(await segment.getAttribute('aria-label').catch(() => '')).toLowerCase();
    if (ariaLabel.includes('year')) byPart.year = segment;
    else if (ariaLabel.includes('month')) byPart.month = segment;
    else if (ariaLabel.includes('day')) byPart.day = segment;
  }
  const missingParts = ['year', 'month', 'day'].filter((part) => !byPart[part]);
  if (missingParts.length) {
    throw new Error(`Could not identify date segment(s) for ${iso}: ${missingParts.join(', ')}`);
  }

  // React-Aria date segments are contenteditable spinbuttons. Playwright fill()
  // dispatches the input events React expects; typing digit-by-digit can leave
  // the year unchanged because DateSegment applies partial-value semantics.
  // Set the year first, then month/day, and verify every aria-valuenow before
  // moving to the next segment.
  for (const part of ['year', 'month', 'day']) {
    const segment = byPart[part];
    const expected = desired[part];
    await segment.click({ timeout: 10_000 });
    const editable = await segment.getAttribute('contenteditable').catch(() => null);
    if (editable === 'true') {
      await segment.fill(String(expected), { timeout: 10_000 });
    } else {
      await segment.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {});
      await segment.press('Backspace').catch(() => {});
      await frame.page().keyboard.type(String(expected), { delay: 60 });
    }
    await sleep(180);
    const observed = Number(await segment.getAttribute('aria-valuenow').catch(() => NaN));
    if (Number.isFinite(observed) && observed !== expected) {
      // A second explicit keyboard replacement covers React-Aria variants that
      // expose contenteditable but defer normalization until a key event.
      await segment.click({ timeout: 10_000 });
      await segment.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {});
      await frame.page().keyboard.type(String(expected), { delay: 60 });
      await sleep(180);
    }
  }
  await frame.page().keyboard.press('Tab').catch(() => {});
}

async function setDateInput(frame, label, iso) {
  let lastValue = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const control = await dateControl(frame, label);
    if (control.kind === 'input') {
      const candidate = attempt === 0 ? iso.replaceAll('-', '/') : iso;
      await control.locator.click({ timeout: 15_000 });
      await control.locator.fill(candidate, { timeout: 15_000 });
      await control.locator.press('Enter').catch(() => {});
      await control.locator.press('Tab').catch(() => {});
    } else {
      await setSegmentedDate(frame, control.locator, iso);
    }

    await sleep(1_500);
    const refreshed = await dateControl(frame, label);
    if (refreshed.kind === 'input') {
      lastValue = await refreshed.locator.inputValue().catch(() => null);
    } else {
      lastValue = await segmentedDateValue(refreshed.locator);
    }
    if (dateValueMatches(lastValue, iso)) return lastValue;
  }
  throw new Error(`Date input ${label} did not accept ${iso}; observed value=${lastValue}`);
}

async function selectStationFromList(page, frame, fixture, timeoutMs = 60_000) {
  await waitForText(frame, 'Manual station selection', timeoutMs);

  let combo = frame.getByRole('combobox', { name: 'Search-result stations', exact: true }).first();
  if (!(await combo.count().catch(() => 0))) {
    combo = frame.getByLabel('Search-result stations', { exact: true }).first();
  }
  if (!(await combo.count().catch(() => 0))) {
    throw new Error('Could not locate Search-result stations selectbox.');
  }

  await combo.click({ timeout: 15_000 });
  await sleep(300);
  const targetText = `ID ${fixture.station_id}`;
  let option = frame.getByRole('option').filter({ hasText: targetText }).last();
  if (!(await option.count().catch(() => 0))) {
    option = frame.locator('[data-baseweb="menu"] li').filter({ hasText: targetText }).last();
  }
  if (!(await option.count().catch(() => 0))) {
    throw new Error(`Search-result stations contains no option for ${targetText}.`);
  }
  const selectedLabel = (await option.innerText().catch(() => '')).trim();
  await option.click({ timeout: 15_000 });
  await sleep(500);

  const useButton = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
  if (!(await useButton.count().catch(() => 0))) {
    throw new Error('Could not locate Use station from list button.');
  }
  await useButton.click({ timeout: 15_000 });

  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    let currentFrame;
    try {
      currentFrame = await waitForFrameContaining(page, 'Selected station', 5_000);
    } catch {
      await sleep(300);
      continue;
    }
    let currentCombo = currentFrame.getByRole('combobox', { name: 'Search-result stations', exact: true }).first();
    if (!(await currentCombo.count().catch(() => 0))) {
      currentCombo = currentFrame.getByLabel('Search-result stations', { exact: true }).first();
    }
    if (await currentCombo.count().catch(() => 0)) {
      const rendered = [
        await currentCombo.innerText().catch(() => ''),
        await currentCombo.textContent().catch(() => ''),
        await currentCombo.inputValue().catch(() => ''),
      ].join(' ');
      if (rendered.includes(targetText) || rendered.includes(fixture.station_name)) {
        return { frame: currentFrame, selectedLabel, rendered: rendered.trim() };
      }
    }
    const selectedText = await bodyText(currentFrame);
    if (selectedText.includes('Selected station') && selectedText.includes(fixture.station_name)) {
      return { frame: currentFrame, selectedLabel, rendered: fixture.station_name };
    }
    await sleep(400);
  }
  throw new Error(`Station selection did not settle on ${fixture.station_name} (${targetText}).`);
}

async function analysisCombo(frame) {
  const byRole = frame.getByRole('combobox', { name: 'Analysis type', exact: true });
  if (await byRole.count()) return byRole.first();
  const labelled = frame.getByLabel('Analysis type', { exact: true });
  if (await labelled.count()) return labelled.first();
  const label = frame.getByText('Analysis type', { exact: true }).first();
  if (await label.count()) {
    const parent = label.locator('xpath=..');
    const combo = parent.locator('[role="combobox"]').first();
    if (await combo.count()) return combo;
  }
  throw new Error('Could not locate Analysis type selectbox.');
}

async function analysisOptions(frame) {
  const combo = await analysisCombo(frame);
  await combo.click({ timeout: 15_000 });
  await sleep(400);
  let options = await frame.getByRole('option').allInnerTexts().catch(() => []);
  if (!options.length) {
    options = await frame.locator('[data-baseweb="menu"] li').allInnerTexts().catch(() => []);
  }
  return [...new Set(options.map((value) => value.trim()).filter(Boolean))];
}

async function selectAnalysis(frame, name) {
  const combo = await analysisCombo(frame);
  await combo.click({ timeout: 15_000 });
  await sleep(250);
  const roleOption = frame.getByRole('option', { name, exact: true });
  if (await roleOption.count()) {
    await roleOption.last().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }
  const textOption = frame.getByText(name, { exact: true });
  if (await textOption.count()) {
    await textOption.last().click({ timeout: 15_000 });
    await sleep(500);
    return;
  }
  throw new Error(`Analysis option not found: ${name}`);
}

const report = {
  schema: 'climate-analyzer-geosphere-precip-snow-live-smoke-v2',
  target_url: TARGET_URL,
  fixture,
  started_at_utc: new Date().toISOString(),
  page_errors: [],
  console_errors: [],
  http_errors: [],
  checks: {},
  success: false,
  error: null,
};

let browser;
let page;
try {
  if (!fixture.success) throw new Error(`Provider probe did not produce a valid fixture: ${fixture.error ?? 'unknown'}`);

  browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'en-US' });
  page = await context.newPage();
  page.on('pageerror', (error) => report.page_errors.push(String(error)));
  page.on('console', (message) => {
    if (message.type() === 'error') report.console_errors.push(message.text());
  });
  page.on('response', (response) => {
    if (response.status() >= 400) report.http_errors.push({ status: response.status(), url: response.url() });
  });

  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  let appFrame = await waitForFrameContaining(page, 'Climate Analyzer');
  report.checks.app_visible = true;

  const initialText = await bodyText(appFrame);
  if (/resource limits|gone over its resource limits/i.test(initialText)) {
    throw new Error('Streamlit resource-limit page detected.');
  }

  const sourceOpen = await chooseAndWait(
    page,
    'GeoSphere Austria',
    'GeoSphere Austria — measured historical station data',
    45_000,
  );
  appFrame = sourceOpen.frame;
  report.checks.geosphere_source_opened = true;
  report.checks.geosphere_source_attempts = sourceOpen.attempts;

  await fillInput(appFrame, 'Search GeoSphere station', fixture.station_id);
  await waitForText(appFrame, 'Visible GeoSphere stations after filters:');
  const stationSelection = await selectStationFromList(page, appFrame, fixture);
  appFrame = stationSelection.frame;
  report.checks.station_selected = `${fixture.station_name} (${fixture.station_id})`;
  report.checks.station_selection_option = stationSelection.selectedLabel;
  report.checks.station_selection_rendered = stationSelection.rendered;

  const fromValue = await setDateInput(appFrame, 'From date (UTC)', fixture.ui_start_date);
  const throughValue = await setDateInput(appFrame, 'Through date (UTC)', fixture.ui_end_date);
  report.checks.date_interval = {
    requested_start: fixture.ui_start_date,
    requested_end: fixture.ui_end_date,
    rendered_start: fromValue,
    rendered_end: throughValue,
  };

  const loadButton = appFrame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true });
  if (!(await loadButton.count())) throw new Error('GeoSphere load button not found.');
  await loadButton.first().click({ timeout: 15_000 });

  appFrame = await waitForFrameContaining(page, 'Precipitation and Snow', 180_000);
  report.checks.provider_interval_loaded = true;
  await clickChoice(appFrame, 'Precipitation and Snow');
  await waitForText(appFrame, 'Dual-resolution semantics:', 60_000);
  await waitForText(appFrame, 'Precipitation and snow', 60_000);
  report.checks.precipitation_page_opened = true;

  const expectedOptions = [
    'Precipitation totals',
    'Annual precipitation indices',
    'Liquid precipitation explorer',
    'Precipitation-record occurrence',
    'Measured precipitation duration',
    'Snow-cover duration',
    'Snow-season indices',
  ];
  if (fixture.hourly_snow_available) expectedOptions.push('Snow depth explorer');

  const options = await analysisOptions(appFrame);
  report.checks.analysis_options = options;
  report.checks.hourly_snow_available = Boolean(fixture.hourly_snow_available);
  const missing = expectedOptions.filter((value) => !options.includes(value));
  if (missing.length) throw new Error(`Missing precipitation/snow analysis option(s): ${missing.join(', ')}`);
  if (!fixture.hourly_snow_available && options.includes('Snow depth explorer')) {
    throw new Error('Snow depth explorer was exposed despite no strict-complete hourly snow state in the provider probe.');
  }
  await page.keyboard.press('Escape').catch(() => {});

  await selectAnalysis(appFrame, 'Annual precipitation indices');
  await waitForText(appFrame, 'Wet day ≥ 1 mm/day', 60_000);
  report.checks.annual_precipitation_indices = true;

  await selectAnalysis(appFrame, 'Measured precipitation duration');
  await waitForText(appFrame, 'never inferred from precipitation depth rr', 60_000);
  report.checks.measured_precipitation_duration = true;

  await selectAnalysis(appFrame, 'Precipitation-record occurrence');
  await waitForText(appFrame, 'record-occurrence metric, not rainfall duration', 60_000);
  report.checks.native_precipitation_occurrence = true;

  await selectAnalysis(appFrame, 'Snow-cover duration');
  await waitForText(appFrame, 'source-state cadence', 60_000);
  report.checks.native_snow_cover_duration = true;

  await selectAnalysis(appFrame, 'Snow-season indices');
  await waitForText(appFrame, 'July–June analysis year', 60_000);
  report.checks.snow_season_indices = true;

  if (report.page_errors.length) {
    throw new Error(`Uncaught browser page error(s): ${report.page_errors.join(' | ')}`);
  }

  await page.screenshot({
    path: path.join(OUT_DIR, 'precipitation-snow-final.png'),
    fullPage: true,
  });
  report.success = true;
} catch (error) {
  report.error = String(error);
  if (page) {
    await page.screenshot({
      path: path.join(OUT_DIR, 'precipitation-snow-failure.png'),
      fullPage: true,
    }).catch(() => {});
  }
  process.exitCode = 1;
} finally {
  report.completed_at_utc = new Date().toISOString();
  await fs.writeFile(
    path.join(OUT_DIR, 'geosphere-precip-snow-live-smoke.json'),
    JSON.stringify(report, null, 2),
  );
  const summary = [
    '# GeoSphere precipitation/snow live smoke',
    '',
    `- Target: ${TARGET_URL}`,
    `- Station: ${fixture.station_name ?? 'unresolved'} (ID ${fixture.station_id ?? 'n/a'})`,
    `- Provider/browser interval: ${fixture.ui_start_date ?? 'n/a'} → ${fixture.ui_end_date ?? 'n/a'}`,
    `- Native valid records: ${JSON.stringify(fixture.native_valid_records ?? {})}`,
    `- Hourly valid records: ${JSON.stringify(fixture.hourly_valid_records ?? {})}`,
    `- Strict-complete hourly snow available: ${fixture.hourly_snow_available ?? 'n/a'}`,
    `- Success: ${report.success}`,
    `- Page errors: ${report.page_errors.length}`,
    `- Browser HTTP 4xx/5xx observed: ${report.http_errors.length}`,
    `- Error: ${report.error ?? 'none'}`,
    '',
    '## Checks',
    '',
    ...Object.entries(report.checks).map(([key, value]) => `- ${key}: ${JSON.stringify(value)}`),
    '',
    '> This workflow is provider-backed operational evidence. GeoSphere availability is intentionally isolated from the core Climate Analyzer CI gate.',
    '',
  ].join('\n');
  await fs.writeFile(path.join(OUT_DIR, 'LIVE_SMOKE.md'), summary);
  console.log(summary);
  if (browser) await browser.close();
}
