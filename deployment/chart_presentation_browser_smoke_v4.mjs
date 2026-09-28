import fs from 'node:fs/promises';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8502/';
const OUT_DIR = process.env.CHART_PRESENTATION_SMOKE_DIR || 'artifacts/chart-presentation-smoke';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const CANVAS_INDEX = new Map([
  ['Auto', 0],
  ['16:9 — Wide', 1],
  ['4:3 — Presentation', 2],
  ['1:1 — Square', 3],
  ['3:4 — Portrait', 4],
  ['Custom', 5],
]);

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

async function chooseCanvas(page, value) {
  const index = CANVAS_INDEX.get(value);
  if (index === undefined) throw new Error(`Unknown canvas option: ${value}`);

  let frame = await openPresentation(page);
  const control = frame.getByRole('combobox', { name: 'Canvas', exact: true }).first();
  await control.click({ timeout: 10000 });
  await page.keyboard.press('Home');
  for (let i = 0; i < index; i += 1) await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');

  await waitForCharts(page);
  frame = await openPresentation(page);
  if (value === 'Custom') {
    const started = Date.now();
    while (Date.now() - started < 10000) {
      const text = await bodyText(frame);
      if (text.includes('Width [px]') && text.includes('Height [px]')) return frame;
      await sleep(150);
      frame = await openPresentation(page);
    }
    throw new Error('Custom canvas selected but width/height controls did not appear.');
  }
  return frame;
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

async function setSliderFromMinimum(page, label, target, minimum, step) {
  const steps = Math.round((Number(target) - Number(minimum)) / Number(step));
  if (steps < 0) throw new Error(`Invalid slider target: ${label}`);

  let frame = await openPresentation(page);
  let slider = await sliderControl(frame, label);
  await slider.focus();
  await slider.press('Home');
  await waitForCharts(page);

  for (let i = 0; i < steps; i += 1) {
    frame = await openPresentation(page);
    slider = await sliderControl(frame, label);
    await slider.focus();
    await slider.press('ArrowRight');
    await sleep(180);
    await waitForCharts(page);
  }
}

async function setNumberInput(page, label, value) {
  const frame = await openPresentation(page);
  const container = frame.locator('[data-testid="stNumberInput"]').filter({ hasText: label }).first();
  if (!(await container.count().catch(() => 0))) throw new Error(`Number input not found: ${label}`);
  const input = container.locator('input').first();
  await input.fill(String(value));
  await input.press('Enter');
  await sleep(300);
  await waitForCharts(page);
}

async function chartMetrics(page) {
  const frame = await waitForCharts(page);
  return frame.locator('.js-plotly-plot').evaluateAll((nodes) => nodes.map((node) => {
    const layout = node._fullLayout || {};
    const exportOptions = node._context?.toImageButtonOptions || {};
    return {
      width: Number(layout.width),
      height: Number(layout.height),
      font: Number(layout.font?.size || 0),
      xTickFont: Number(layout.xaxis?.tickfont?.size || 0),
      legendFont: Number(layout.legend?.font?.size || 0),
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

function assertDims(metrics, width, height, label) {
  if (metrics.length !== 4) throw new Error(`${label}: expected 4 charts, got ${metrics.length}`);
  metrics.forEach((m, i) => {
    assertNear(m.width, width, 3, `${label} chart ${i + 1} width`);
    assertNear(m.height, height, 3, `${label} chart ${i + 1} height`);
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
  assertDims(metrics, 900, 900, 'Square');
  report.metrics.square = metrics;

  await setSliderFromMinimum(page, 'Chart font size [pt]', 20, 8, 1);
  metrics = await chartMetrics(page);
  metrics.forEach((m, i) => assertNear(m.font, 20, 0.1, `20 pt chart ${i + 1}`));
  assertNear(metrics[0].xTickFont, 20, 0.1, 'Line axis font');
  assertNear(metrics[1].colorbarFont, 20, 0.1, 'Heatmap colorbar font');
  assertNear(metrics[2].legendFont, 20, 0.1, 'Psychrometric legend font');
  assertNear(metrics[3].polarAngularFont, 20, 0.1, 'Wind rose angular font');
  assertNear(metrics[3].polarRadialFont, 20, 0.1, 'Wind rose radial font');
  report.checks.globalFontPropagation = true;
  report.metrics.square20pt = metrics;
  await page.screenshot({ path: `${OUT_DIR}/02-square-20pt.png`, fullPage: true });

  await chooseCanvas(page, '16:9 — Wide');
  metrics = await chartMetrics(page);
  assertDims(metrics, 1280, 720, 'Wide');
  report.checks.wideCanvas = true;
  report.metrics.wide = metrics;
  await page.screenshot({ path: `${OUT_DIR}/03-wide.png`, fullPage: true });

  await chooseCanvas(page, '3:4 — Portrait');
  metrics = await chartMetrics(page);
  assertDims(metrics, 900, 1200, 'Portrait');
  report.checks.portraitCanvas = true;
  report.metrics.portrait = metrics;
  await page.screenshot({ path: `${OUT_DIR}/04-portrait.png`, fullPage: true });

  await chooseCanvas(page, 'Custom');
  await setNumberInput(page, 'Width [px]', 1000);
  await setNumberInput(page, 'Height [px]', 700);
  await setSliderFromMinimum(page, 'Display width [%]', 75, 50, 5);
  metrics = await chartMetrics(page);
  assertDims(metrics, 750, 525, 'Custom 75%');
  metrics.forEach((m, i) => {
    assertNear(m.exportWidth, 1000, 0.1, `Custom export chart ${i + 1} width`);
    assertNear(m.exportHeight, 700, 0.1, `Custom export chart ${i + 1} height`);
    assertNear(m.exportScale, 2, 0.1, `Custom export chart ${i + 1} scale`);
  });
  report.checks.customCanvasAndExport = true;
  report.metrics.custom = metrics;
  await page.screenshot({ path: `${OUT_DIR}/05-custom-75pct.png`, fullPage: true });

  await chooseCanvas(page, 'Auto');
  metrics = await chartMetrics(page);
  report.checks.autoRestored = metrics.length === 4 && metrics.some((m) => m.height !== 525);
  if (!report.checks.autoRestored) throw new Error('Auto canvas did not restore responsive geometry.');
  report.metrics.autoRestored = metrics;
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
