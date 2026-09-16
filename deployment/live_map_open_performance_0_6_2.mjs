import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET = process.env.TARGET_URL;
const OUT = process.env.PERF_OUTPUT_DIR;
const CHROME = process.env.CHROME_PATH;
const EXPECTED = process.env.EXPECTED_RUNTIME;
const N = Number.parseInt(process.env.REPETITIONS || '5', 10);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await fs.mkdir(OUT, { recursive: true });

async function bodyText(frame) {
  try { return await frame.locator('body').innerText({ timeout: 1500 }); } catch { return ''; }
}

async function waitForAppFrame(page, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      if ((await bodyText(frame)).includes('Climate Analyzer')) return frame;
    }
    await sleep(100);
  }
  throw new Error('Climate Analyzer app frame timeout');
}

async function waitForRuntime(page, timeoutMs = 30_000) {
  const started = performance.now();
  let observed = null;
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      const marker = frame.locator('#climate-analyzer-runtime-build').first();
      if (!(await marker.count().catch(() => 0))) continue;
      observed = await marker.getAttribute('data-runtime-build').catch(() => null);
      if (observed === EXPECTED) return observed;
    }
    await sleep(100);
  }
  throw new Error(`runtime timeout: expected=${EXPECTED}, observed=${observed}`);
}

async function tileZoom(frame) {
  const urls = await frame.locator('img.leaflet-tile').evaluateAll((nodes) =>
    nodes.map((node) => node.src || '').filter(Boolean)
  ).catch(() => []);
  const levels = [];
  for (const raw of urls) {
    try {
      const match = new URL(raw).pathname.match(/^\/(\d+)\//);
      if (match) levels.push(Number.parseInt(match[1], 10));
    } catch {}
  }
  return levels.length ? Math.max(...levels) : null;
}

async function leafletReadiness(page, timeoutMs = 30_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      if (!frame.url().includes('streamlit_folium.st_folium')) continue;
      const zoomControl = frame.locator('.leaflet-control-zoom-in').first();
      if (!(await zoomControl.count().catch(() => 0))) continue;
      const zoom = await tileZoom(frame);
      if (!Number.isInteger(zoom)) continue;
      const clusterCount = await frame.locator('.marker-cluster, .leaflet-interactive').count().catch(() => 0);
      return { frame, zoom, clusterCount, waitMs: Math.round(performance.now() - started) };
    }
    await sleep(50);
  }
  throw new Error('Leaflet readiness timeout');
}

async function clickFindClimate(appFrame) {
  let control = appFrame.getByRole('tab', { name: 'Find climate', exact: true });
  if (!(await control.count())) control = appFrame.getByText('Find climate', { exact: true }).first();
  if (!(await control.count())) throw new Error('Find climate control not found');
  await control.click({ timeout: 10_000 });
}

async function runSample(context, index) {
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(String(error)));
  try {
    await page.goto(TARGET, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    const app = await waitForAppFrame(page);
    const runtime = await waitForRuntime(page);

    const started = performance.now();
    await clickFindClimate(app);

    let catalogReadyMs = null;
    let anchorReadyMs = null;
    const deadline = performance.now() + 30_000;
    while (performance.now() < deadline) {
      const text = await bodyText(app);
      if (catalogReadyMs == null && /Visible catalog records after filters:\s*98[,.]?047\s+of\s+98[,.]?047/i.test(text)) {
        catalogReadyMs = Math.round(performance.now() - started);
      }
      if (anchorReadyMs == null && text.includes('Clustered overview is active.')) {
        anchorReadyMs = Math.round(performance.now() - started);
      }
      if (catalogReadyMs != null && anchorReadyMs != null) break;
      await sleep(50);
    }
    if (catalogReadyMs == null || anchorReadyMs == null) throw new Error('Find climate UI readiness timeout');

    await app.getByText('Clustered overview is active.', { exact: false }).first().scrollIntoViewIfNeeded().catch(() => {});
    const leaflet = await leafletReadiness(page);
    const mapReadyMs = Math.round(performance.now() - started);

    await page.screenshot({ path: path.join(OUT, `map-open-${index}.png`), fullPage: true }).catch(() => {});
    return {
      repetition: index,
      runtime,
      catalog_ready_ms: catalogReadyMs,
      map_anchor_ready_ms: anchorReadyMs,
      map_ready_ms: mapReadyMs,
      leaflet_wait_after_scroll_ms: leaflet.waitMs,
      initial_zoom: leaflet.zoom,
      visible_cluster_or_interactive_nodes: leaflet.clusterCount,
      page_errors: pageErrors,
    };
  } finally {
    await page.close();
  }
}

function median(values) {
  const nums = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!nums.length) return null;
  const mid = Math.floor(nums.length / 2);
  return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
}

function percentile(values, p) {
  const nums = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!nums.length) return null;
  return nums[Math.min(nums.length - 1, Math.ceil(nums.length * p) - 1)];
}

const browser = await chromium.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
let warmup = null;
const samples = [];
let failure = null;
try {
  warmup = await runSample(context, 0);
  await fs.writeFile(path.join(OUT, 'warmup-map-open.json'), JSON.stringify(warmup, null, 2));
  for (let i = 1; i <= N; i += 1) samples.push(await runSample(context, i));
} catch (error) {
  failure = String(error);
}
await context.close();
await browser.close();

const mapTimes = samples.map((s) => s.map_ready_ms);
const result = {
  schema: 'climate-0.6.2-live-map-open-performance-v1',
  target_url: TARGET,
  expected_runtime: EXPECTED,
  repetitions_requested: N,
  warmup,
  samples,
  medians_ms: {
    catalog_ready: median(samples.map((s) => s.catalog_ready_ms)),
    map_anchor_ready: median(samples.map((s) => s.map_anchor_ready_ms)),
    map_ready: median(mapTimes),
  },
  p90_ms: {
    map_ready: percentile(mapTimes, 0.90),
  },
  min_ms: samples.length ? Math.min(...mapTimes) : null,
  max_ms: samples.length ? Math.max(...mapTimes) : null,
  failure,
};
await fs.writeFile(path.join(OUT, 'map-open-performance.json'), JSON.stringify(result, null, 2));
console.log('LIVE_MAP_OPEN_PERFORMANCE_0_6_2=' + JSON.stringify(result));
if (failure || samples.length !== N || samples.some((s) => s.page_errors.length)) process.exitCode = 1;
