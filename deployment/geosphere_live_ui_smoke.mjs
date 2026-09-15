import fs from 'node:fs/promises';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'https://building-climate-analyzer.streamlit.app/';
const EXPECTED_RUNTIME_BUILD = process.env.EXPECTED_RUNTIME_BUILD || '';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const OUT_DIR = process.env.OUT_DIR || 'artifacts/geosphere-provider';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await fs.mkdir(OUT_DIR, { recursive: true });

async function bodyText(frame) {
  try {
    return await frame.locator('body').innerText({ timeout: 2_000 });
  } catch {
    return '';
  }
}

async function waitForAppFrame(page, timeoutMs = 60_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      const text = await bodyText(frame);
      if (text.includes('Climate Analyzer')) return frame;
    }
    await sleep(500);
  }
  throw new Error('Climate Analyzer application frame was not detected.');
}

async function waitForRuntime(frame, timeoutMs = 60_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const marker = frame.locator('#climate-analyzer-runtime-build').first();
    if (await marker.count().catch(() => 0)) {
      const build = await marker.getAttribute('data-runtime-build').catch(() => null);
      if (!EXPECTED_RUNTIME_BUILD || build === EXPECTED_RUNTIME_BUILD) return build;
    }
    await sleep(500);
  }
  throw new Error(`Production runtime did not match expected build ${EXPECTED_RUNTIME_BUILD}.`);
}

const browser = await chromium.launch({ headless: true, executablePath: CHROME_PATH });
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
const page = await context.newPage();
const pageErrors = [];
page.on('pageerror', (error) => pageErrors.push(String(error)));

const evidence = {
  status: 'FAIL',
  target: TARGET_URL,
  expected_runtime_build: EXPECTED_RUNTIME_BUILD,
  runtime_build: null,
  source_option_clicked: false,
  geosphere_panel_visible: false,
  station_controls_visible: false,
  date_controls_visible: false,
  request_plan_visible: false,
  metadata_error_visible: false,
  page_errors: pageErrors,
};

try {
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  let appFrame = await waitForAppFrame(page);
  evidence.runtime_build = await waitForRuntime(appFrame);

  const sourceOption = appFrame.getByText('GeoSphere Austria', { exact: true }).first();
  await sourceOption.waitFor({ state: 'visible', timeout: 30_000 });
  await sourceOption.click({ timeout: 10_000 });
  evidence.source_option_clicked = true;

  const started = Date.now();
  let text = '';
  while (Date.now() - started < 90_000) {
    appFrame = await waitForAppFrame(page, 5_000);
    text = await bodyText(appFrame);
    evidence.metadata_error_visible = text.includes('GeoSphere metadata could not be loaded or validated:');
    if (evidence.metadata_error_visible) break;
    evidence.geosphere_panel_visible = text.includes('GeoSphere Austria — measured historical station data');
    evidence.station_controls_visible = text.includes('Search GeoSphere station') && text.includes('Provider validity');
    evidence.date_controls_visible = text.includes('From date (UTC)') && text.includes('Through date (UTC)');
    evidence.request_plan_visible = text.includes('10-minute source data') && text.includes('bounded API batches');
    if (
      evidence.geosphere_panel_visible
      && evidence.station_controls_visible
      && evidence.date_controls_visible
      && evidence.request_plan_visible
    ) break;
    await sleep(750);
  }

  await page.screenshot({ path: `${OUT_DIR}/production-geosphere-ui.png`, fullPage: true });
  if (evidence.metadata_error_visible) {
    throw new Error('Production GeoSphere source displayed a metadata validation/load error.');
  }
  const required = [
    'geosphere_panel_visible',
    'station_controls_visible',
    'date_controls_visible',
    'request_plan_visible',
  ];
  const missing = required.filter((key) => !evidence[key]);
  if (missing.length) {
    throw new Error(`Production GeoSphere UI did not reach ready state: ${missing.join(', ')}`);
  }
  if (pageErrors.length) {
    throw new Error(`Production UI emitted uncaught page error(s): ${pageErrors.join(' | ')}`);
  }
  evidence.status = 'PASS';
} catch (error) {
  evidence.error = String(error);
  try {
    await page.screenshot({ path: `${OUT_DIR}/production-geosphere-ui-failure.png`, fullPage: true });
  } catch {
    // Best-effort evidence only.
  }
} finally {
  await context.close();
  await browser.close();
}

await fs.writeFile(`${OUT_DIR}/ui-smoke.json`, JSON.stringify(evidence, null, 2), 'utf8');
console.log(JSON.stringify(evidence, null, 2));
if (evidence.status !== 'PASS') process.exit(1);
