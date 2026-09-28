import fs from 'node:fs/promises';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8502/';
const OUT_DIR = process.env.CHART_PRESENTATION_SMOKE_DIR || 'artifacts/chart-presentation-smoke';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await fs.mkdir(OUT_DIR, { recursive: true });

async function bodyText(frame) {
  try { return await frame.locator('body').innerText({ timeout: 2000 }); } catch { return ''; }
}

async function appFrame(page, needle = 'Chart presentation visual harness', timeoutMs = 60000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      if ((await bodyText(frame)).includes(needle)) return frame;
    }
    await sleep(200);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}

async function waitForCharts(page, expected = 4, timeoutMs = 60000) {
  const started = Date.now();
  let stable = 0;
  while (Date.now() - started < timeoutMs) {
    const frame = await appFrame(page, 'Chart presentation visual harness', 5000);
    const plots = frame.locator('.js-plotly-plot');
    const count = await plots.count().catch(() => 0);
    const ready = count === expected && await plots.evaluateAll(
      (nodes) => nodes.every((node) => Boolean(node._fullLayout)),
    ).catch(() => false);
    stable = ready ? stable + 1 : 0;
    if (stable >= 3) return frame;
    await sleep(250);
  }
  throw new Error(`Timed out waiting for ${expected} Plotly charts.`);
}

async function openPresentation(page) {
  let frame = await appFrame(page);
  if ((await bodyText(frame)).includes('Chart font size [pt]')) return frame;
  await frame.getByText('Presentation', { exact: true }).first().click({ timeout: 10000 });
  const started = Date.now();
  while (Date.now() - started < 10000) {
    frame = await appFrame(page);
    if ((await bodyText(frame)).includes('Chart font size [pt]')) return frame;
    await sleep(150);
  }
  throw new Error('Presentation sidebar did not expand.');
}

async function visibleOption(page, frame, text) {
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
      const value = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
      if (value === text) return option;
    }
  }
  return null;
}

async function chooseCanvas(page, value) {
  let frame = await openPresentation(page);
  const control = frame.getByRole('combobox', { name: 'Canvas', exact: true }).first();
  await control.click({ timeout: 10000 });
  const option = await visibleOption(page, frame, value);
  if (!option) throw new Error(`Canvas option not found: ${value}`);
  await option.click({ timeout: 10000 });
  await waitForCharts(page);
  return openPresentation(page);
}

async function sliderControl(frame, label) {
  const byContainerText = frame.locator('[data-testid="stSlider"]').filter({ hasText: label }).first();
  if (await byContainerText.count().catch(() => 0)) {
    const slider = byContainerText.getByRole('slider').first();
    if (await slider.count().catch(() => 0)) return slider;
  }
  const labelled = frame.getByRole('slider', { name: label, exact: false }).first();
  if (await labelled.count().catch(() => 0)) return labelled;
  throw new Error(`Slider control not found: ${label}`);
}

async function setSlider(page, label, target) {
  for (let iteration = 0; iteration < 50; iteration += 1) {
    const frame = await openPresentation(page);
    const slider = await sliderControl(frame, label);
    const now = Number(await slider.getAttribute('aria-valuenow'));
    if (Math.abs(now - target) < 1e-9) return waitForCharts(page);
    await slider.press(target > now ? 'ArrowRight' : 'ArrowLeft');
    await sleep(220);
  }
  throw new Error(`Could not set ${label} to ${target}.`);
}

async function setNumberInput(page, label, value) {
  const frame = await openPresentation(page);
  const container = frame.locator('[data-testid="stNumberInput"]').filter({ hasText: label }).first();
  if (!(await container.count().catch(() => 0))) throw new Error(`Number input not found: ${label}`);
  const input = container.locator('input').first();
  await input.fill(String(value));
  await input.press('Enter');
  await sleep(350);
  return waitForCharts(page);
}

async function chartMetrics(page) {
  const frame = await waitForCharts(page);
  return frame.locator('.js-plotly-plot').evaluateAll((nodes) => nodes.map((node) => {
    const layout = node._fullLayout || {};
    const context = node._context || {};
    const exportOptions = context.toImageButtonOptions || {};
    return {
      title: layout.title?.text || '',
      width: Number(layout.width),
      height: Number(layout.height),
      autosize: Boolean(layout.autosize),
      font: Number(layout.font?.size || 0),
      xTickFont: Number(layout.xaxis?.tickfont?.size || 0),
      yTickFont: Number(layout.yaxis?.tickfont?.size || 0),
      legendFont: Number(layout.legend?.font?.size || 0),
      legend2Font: Number(layout.legend2?.font?.size || 0),
      polarAngularFont: Number(layout.polar?.angularaxis?.tickfont?.size || 0),
      polarRadialFont: Number(layout.polar?.radialaxis?.tickfont?.size || 0),
      colorbarFont: Number(layout.coloraxis?.colorbar?.tickfont?.size || 0),
      exportWidth: Number(exportOptions.width || 0),
      exportHeight: Number(exportOptions.height || 0),
      exportScale: Number(exportOptions.scale || 0),
    };
  }));
}

function assertNear(actual, expected, tolerance, label) {
  if (!Number.isFinite(actual) || Math.abs(actual - expected) > tolerance) {
    throw new Error(`${label}: expected ${expected}±${tolerance}, got ${actual}`);
  }
}

function assertAllDimensions(metrics, width, height, label) {
  if (metrics.length !== 4) throw new Error(`${label}: expected 4 charts, got ${metrics.length}`);
  metrics.forEach((metric, index) => {
    assertNear(metric.width, width, 3, `${label} chart ${index + 1} width`);
    assertNear(metric.height, height, 3, `${label} chart ${index + 1} height`);
  });
}

const browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1800, height: 1200 }, deviceScaleFactor: 1 });
const report = { target: TARGET_URL, checks: {}, metrics: {} };

try {
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await waitForCharts(page);
  await openPresentation(page);

  report.metrics.auto = await chartMetrics(page);
  report.checks.fourRepresentativeCharts = report.metrics.auto.length === 4;
  await page.screenshot({ path: `${OUT_DIR}/01-auto.png`, fullPage: true });

  await chooseCanvas(page, '1:1 — Square');
  let metrics = await chartMetrics(page);
  assertAllDimensions(metrics, 900, 900, 'Square');
  report.metrics.square = metrics;

  await setSlider(page, 'Chart font size [pt]', 20);
  metrics = await chartMetrics(page);
  metrics.forEach((metric, index) => assertNear(metric.font, 20, 0.1, `20 pt chart ${index + 1} layout font`));
  assertNear(metrics[0].xTickFont, 20, 0.1, 'Line x-axis font');
  assertNear(metrics[1].colorbarFont, 20, 0.1, 'Heatmap colorbar font');
  assertNear(metrics[2].legendFont, 20, 0.1, 'Psychrometric legend font');
  if (metrics[2].legend2Font > 0) assertNear(metrics[2].legend2Font, 20, 0.1, 'Psychrometric secondary legend font');
  assertNear(metrics[3].polarAngularFont, 20, 0.1, 'Wind-rose angular-axis font');
  assertNear(metrics[3].polarRadialFont, 20, 0.1, 'Wind-rose radial-axis font');
  report.metrics.square20pt = metrics;
  report.checks.globalFontPropagation = true;
  await page.screenshot({ path: `${OUT_DIR}/02-square-20pt.png`, fullPage: true });

  await chooseCanvas(page, '16:9 — Wide');
  metrics = await chartMetrics(page);
  assertAllDimensions(metrics, 1280, 720, 'Wide');
  report.metrics.wide = metrics;
  report.checks.wideCanvas = true;
  await page.screenshot({ path: `${OUT_DIR}/03-wide.png`, fullPage: true });

  await chooseCanvas(page, '3:4 — Portrait');
  metrics = await chartMetrics(page);
  assertAllDimensions(metrics, 900, 1200, 'Portrait');
  report.metrics.portrait = metrics;
  report.checks.portraitCanvas = true;
  await page.screenshot({ path: `${OUT_DIR}/04-portrait.png`, fullPage: true });

  await chooseCanvas(page, 'Custom');
  await setNumberInput(page, 'Width [px]', 1000);
  await setNumberInput(page, 'Height [px]', 700);
  await setSlider(page, 'Display width [%]', 75);
  metrics = await chartMetrics(page);
  assertAllDimensions(metrics, 750, 525, 'Custom 75%');
  metrics.forEach((metric, index) => {
    assertNear(metric.exportWidth, 1000, 0.1, `Custom export chart ${index + 1} width`);
    assertNear(metric.exportHeight, 700, 0.1, `Custom export chart ${index + 1} height`);
    assertNear(metric.exportScale, 2, 0.1, `Custom export chart ${index + 1} scale`);
  });
  report.metrics.custom = metrics;
  report.checks.customCanvasAndExport = true;
  await page.screenshot({ path: `${OUT_DIR}/05-custom-75pct.png`, fullPage: true });

  await chooseCanvas(page, 'Auto');
  metrics = await chartMetrics(page);
  report.metrics.autoRestored = metrics;
  report.checks.autoRestored = metrics.length === 4 && metrics.some((metric) => metric.height !== 525);
  if (!report.checks.autoRestored) throw new Error('Auto canvas did not restore responsive chart geometry.');
  await page.screenshot({ path: `${OUT_DIR}/06-auto-restored.png`, fullPage: true });

  report.success = Object.values(report.checks).every(Boolean);
  if (!report.success) throw new Error(`Chart presentation browser smoke failed: ${JSON.stringify(report.checks)}`);
  await fs.writeFile(`${OUT_DIR}/report.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  report.success = false;
  report.error = String(error?.stack || error);
  await fs.writeFile(`${OUT_DIR}/report.json`, JSON.stringify(report, null, 2));
  await page.screenshot({ path: `${OUT_DIR}/failure.png`, fullPage: true }).catch(() => {});
  console.error(JSON.stringify(report, null, 2));
  process.exitCode = 1;
} finally {
  await browser.close();
}
