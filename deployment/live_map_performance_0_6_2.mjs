import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'https://building-climate-analyzer.streamlit.app/';
const OUT_DIR = process.env.PERF_OUTPUT_DIR || 'artifacts/live-map-performance-0.6.2';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const REPETITIONS = Number.parseInt(process.env.REPETITIONS || '5', 10);
const EXPECTED_RUNTIME = process.env.EXPECTED_RUNTIME || '';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await fs.mkdir(OUT_DIR, { recursive: true });

async function bodyText(frame) {
  try { return await frame.locator('body').innerText({ timeout: 2_000 }); }
  catch { return ''; }
}

async function waitForAppFrame(page, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      if ((await bodyText(frame)).includes('Climate Analyzer')) return frame;
    }
    await sleep(100);
  }
  throw new Error('Climate Analyzer app frame was not detected.');
}

async function readRuntime(page) {
  for (const frame of page.frames()) {
    const marker = frame.locator('#climate-analyzer-runtime-build').first();
    if (await marker.count().catch(() => 0)) {
      return await marker.getAttribute('data-runtime-build').catch(() => null);
    }
  }
  return null;
}

async function waitForRuntime(page, expected, timeoutMs = 30_000) {
  const started = performance.now();
  let observed = null;
  while (performance.now() - started < timeoutMs) {
    observed = await readRuntime(page);
    if (observed && (!expected || observed === expected)) return observed;
    await sleep(100);
  }
  throw new Error(`Runtime mismatch/timeout: expected ${expected || 'any'}, observed ${observed}`);
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

async function waitForFoliumFrame(page, timeoutMs = 30_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      if (!frame.url().includes('streamlit_folium.st_folium')) continue;
      if (!(await frame.locator('.leaflet-control-zoom-in').count().catch(() => 0))) continue;
      const zoom = await tileZoom(frame);
      if (Number.isInteger(zoom)) return { frame, zoom };
    }
    await sleep(50);
  }
  throw new Error('Ready Leaflet/Folium component was not detected.');
}

async function clickFindClimate(appFrame) {
  let locator = appFrame.getByRole('tab', { name: 'Find climate', exact: true });
  if (!(await locator.count())) locator = appFrame.getByText('Find climate', { exact: true }).first();
  if (!(await locator.count())) throw new Error('Find climate control not found.');
  await locator.click({ timeout: 15_000 });
}

async function waitForCatalogAndMap(page, appFrame, started) {
  const deadline = performance.now() + 30_000;
  let catalogReadyMs = null;
  while (performance.now() < deadline) {
    const text = await bodyText(appFrame);
    if (/Visible catalog records after filters:\s*98[,.]?047\s+of\s+98[,.]?047/i.test(text)) {
      catalogReadyMs = Math.round(performance.now() - started);
      break;
    }
    await sleep(50);
  }
  if (catalogReadyMs == null) throw new Error('Full catalog identity did not become visible.');
  const anchor = appFrame.getByText('Clustered overview is active.', { exact: false }).first();
  await anchor.scrollIntoViewIfNeeded({ timeout: 5_000 }).catch(() => {});
  const ready = await waitForFoliumFrame(page);
  return {
    catalog_ready_ms: catalogReadyMs,
    map_ready_ms: Math.round(performance.now() - started),
    initial_zoom: ready.zoom,
    frame: ready.frame,
  };
}

async function prepareGrazStationClick(frame) {
  const mapLocator = frame.locator('.leaflet-container').first();
  await mapLocator.waitFor({ state: 'visible', timeout: 10_000 });

  const result = await frame.evaluate(async () => {
    let map = null;
    let mapKey = null;
    for (const key of Object.keys(window)) {
      let value = null;
      try { value = window[key]; } catch { continue; }
      if (
        value
        && typeof value.setView === 'function'
        && typeof value.latLngToContainerPoint === 'function'
        && value._container
        && value._container.classList
        && value._container.classList.contains('leaflet-container')
      ) {
        map = value;
        mapKey = key;
        break;
      }
    }
    if (!map) throw new Error('Leaflet map object was not found on the component window.');

    map.setView([47.0707, 15.4395], 11, { animate: false });
    await new Promise((resolve) => setTimeout(resolve, 650));

    const seen = new Set();
    const candidates = [];
    function visit(layer) {
      if (!layer || seen.has(layer)) return;
      seen.add(layer);
      if (typeof layer.getLayers === 'function') {
        for (const child of layer.getLayers()) visit(child);
      }
      if (typeof layer.getLatLng === 'function' && typeof layer.getTooltip === 'function') {
        const ll = layer.getLatLng();
        const tooltip = layer.getTooltip();
        const content = tooltip && typeof tooltip.getContent === 'function' ? String(tooltip.getContent() || '') : '';
        if (ll && content.includes('station_idx=')) {
          const d = Math.abs(ll.lat - 47.0707) + Math.abs(ll.lng - 15.4395);
          candidates.push({ ll, content, d });
        }
      }
    }
    for (const layer of Object.values(map._layers || {})) visit(layer);
    candidates.sort((a, b) => a.d - b.d);
    const chosen = candidates[0];
    if (!chosen) throw new Error('No station layer found near Graz.');

    map.panTo(chosen.ll, { animate: false });
    await new Promise((resolve) => setTimeout(resolve, 300));
    const point = map.latLngToContainerPoint(chosen.ll);
    return {
      x: point.x,
      y: point.y,
      tooltip: chosen.content,
      lat: chosen.ll.lat,
      lon: chosen.ll.lng,
      candidate_count: candidates.length,
      map_key: mapKey,
    };
  });

  return { mapLocator, ...result };
}

function stationNameFromTooltip(text) {
  const after = String(text).split(' | ', 2)[1] || '';
  return after.split(' — ', 1)[0].trim();
}

async function waitForStationPanel(page, appFrame, oldFrame, stationName, started) {
  const oldFrameElement = await oldFrame.frameElement().catch(() => null);
  let iframeDetachedMs = null;
  const deadline = performance.now() + 20_000;
  while (performance.now() < deadline) {
    if (iframeDetachedMs == null && oldFrameElement) {
      const detached = await oldFrameElement.evaluate((node) => !node.isConnected).catch(() => true);
      if (detached) iframeDetachedMs = Math.round(performance.now() - started);
    }
    const text = await bodyText(appFrame);
    if (stationName && text.includes(stationName) && text.includes('Available climates at this station')) {
      const panelMs = Math.round(performance.now() - started);
      const fresh = await waitForFoliumFrame(page, 10_000);
      const oldStillConnected = oldFrameElement
        ? await oldFrameElement.evaluate((node) => node.isConnected).catch(() => false)
        : false;
      return {
        station_panel_ready_ms: panelMs,
        map_ready_after_click_ms: Math.round(performance.now() - started),
        iframe_detached_ms: iframeDetachedMs,
        map_frame_persisted: fresh.frame === oldFrame && oldStillConnected,
        post_click_zoom: fresh.zoom,
      };
    }
    await sleep(50);
  }
  throw new Error(`Selected station panel did not update to ${stationName || 'clicked station'}.`);
}

async function runSample(context, index) {
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(String(error)));
  const sample = { repetition: index };
  try {
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    const appFrame = await waitForAppFrame(page);
    sample.runtime_build = await waitForRuntime(page, EXPECTED_RUNTIME);

    const findStarted = performance.now();
    await clickFindClimate(appFrame);
    const map = await waitForCatalogAndMap(page, appFrame, findStarted);
    sample.find_climate_catalog_ready_ms = map.catalog_ready_ms;
    sample.find_climate_map_ready_ms = map.map_ready_ms;
    sample.initial_map_zoom = map.initial_zoom;

    const chosen = await prepareGrazStationClick(map.frame);
    sample.station_candidates = chosen.candidate_count;
    sample.clicked_tooltip = chosen.tooltip;
    sample.clicked_station = stationNameFromTooltip(chosen.tooltip);
    sample.clicked_lat = chosen.lat;
    sample.clicked_lon = chosen.lon;
    sample.map_key = chosen.map_key;

    const stationStarted = performance.now();
    await chosen.mapLocator.click({
      position: { x: Math.max(1, chosen.x), y: Math.max(1, chosen.y) },
      force: true,
      timeout: 5_000,
    });
    Object.assign(sample, await waitForStationPanel(page, appFrame, map.frame, sample.clicked_station, stationStarted));
    sample.page_errors = [...pageErrors];
    await page.screenshot({ path: path.join(OUT_DIR, `sample-${index}.png`), fullPage: true }).catch(() => {});
    return sample;
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
  const idx = Math.min(nums.length - 1, Math.ceil(p * nums.length) - 1);
  return nums[idx];
}

const browser = await chromium.launch({
  executablePath: CHROME_PATH,
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const samples = [];
let warmup = null;
let failure = null;
try {
  warmup = await runSample(context, 0);
  await fs.writeFile(path.join(OUT_DIR, 'warmup.json'), JSON.stringify(warmup, null, 2));
  for (let i = 1; i <= REPETITIONS; i += 1) {
    samples.push(await runSample(context, i));
  }
} catch (error) {
  failure = String(error);
} finally {
  await context.close();
  await browser.close();
}

const findMap = samples.map((s) => s.find_climate_map_ready_ms);
const stationPanel = samples.map((s) => s.station_panel_ready_ms);
const result = {
  schema: 'climate-0.6.2-live-map-performance-v2',
  target_url: TARGET_URL,
  expected_runtime: EXPECTED_RUNTIME || null,
  repetitions_requested: REPETITIONS,
  warmup,
  samples,
  medians_ms: {
    find_climate_catalog_ready: median(samples.map((s) => s.find_climate_catalog_ready_ms)),
    find_climate_map_ready: median(findMap),
    station_panel_ready: median(stationPanel),
    map_ready_after_station_click: median(samples.map((s) => s.map_ready_after_click_ms)),
  },
  p90_ms: {
    find_climate_map_ready: percentile(findMap, 0.90),
    station_panel_ready: percentile(stationPanel, 0.90),
  },
  map_frame_persisted_samples: samples.filter((s) => s.map_frame_persisted).length,
  failure,
};
await fs.writeFile(path.join(OUT_DIR, 'performance.json'), JSON.stringify(result, null, 2));
console.log('LIVE_MAP_PERFORMANCE_0_6_2=' + JSON.stringify(result));

if (failure || samples.length !== REPETITIONS || samples.some((s) => s.page_errors?.length)) {
  process.exitCode = 1;
}
