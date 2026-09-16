import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'https://building-climate-analyzer.streamlit.app/';
const OUT_DIR = process.env.PERF_OUTPUT_DIR || 'artifacts/live-map-performance';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const REPETITIONS = Number.parseInt(process.env.REPETITIONS || '3', 10);
const EXPECTED_RUNTIME = process.env.EXPECTED_RUNTIME || '';
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
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      if ((await bodyText(frame)).includes('Climate Analyzer')) return frame;
    }
    await sleep(250);
  }
  throw new Error('Climate Analyzer app frame was not detected.');
}

async function runtimeBuild(page) {
  for (const frame of page.frames()) {
    const marker = frame.locator('#climate-analyzer-runtime-build').first();
    if (await marker.count().catch(() => 0)) {
      return await marker.getAttribute('data-runtime-build');
    }
  }
  return null;
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
    await sleep(100);
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
    await sleep(100);
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

async function chooseVisibleStationMarker(frame) {
  const mapId = await frame.locator('.folium-map').first().getAttribute('id');
  if (!mapId) throw new Error('Folium map id missing.');
  await frame.evaluate(({ mapId }) => {
    const map = window[mapId];
    if (!map) throw new Error(`Leaflet map ${mapId} unavailable.`);
    map.setView([47.0707, 15.4395], 10, { animate: false });
  }, { mapId });
  await sleep(1_000);

  const markers = frame.locator('path.leaflet-interactive');
  const count = await markers.count();
  if (!count) throw new Error('No unclustered station circle marker visible near Graz.');

  for (let i = 0; i < Math.min(count, 30); i += 1) {
    const marker = markers.nth(i);
    try {
      await marker.hover({ force: true, timeout: 2_000 });
      await sleep(80);
      const tooltip = frame.locator('.leaflet-tooltip').last();
      const text = (await tooltip.innerText({ timeout: 500 }).catch(() => '')).trim();
      if (text.includes('station_group_id=')) return { marker, tooltip_text: text, marker_count: count };
    } catch {}
  }
  throw new Error(`No station marker with station_group_id tooltip found among ${count} visible paths.`);
}

function stationNameFromTooltip(text) {
  const after = String(text).split(' | ', 2)[1] || '';
  return after.split(' — ', 1)[0].trim();
}

async function waitForStationRerun(page, appFrame, oldFrame, stationName, started) {
  let iframeDetachedMs = null;
  const oldFrameElement = await oldFrame.frameElement().catch(() => null);
  const deadline = performance.now() + 20_000;
  while (performance.now() < deadline) {
    if (iframeDetachedMs == null && oldFrameElement) {
      const detached = await oldFrameElement.evaluate((node) => !node.isConnected).catch(() => true);
      if (detached) iframeDetachedMs = Math.round(performance.now() - started);
    }
    const text = await bodyText(appFrame);
    if (stationName && text.includes(stationName) && text.includes('Available climates at this station')) {
      const panelReadyMs = Math.round(performance.now() - started);
      const fresh = await waitForFoliumFrame(page, 20_000);
      return {
        iframe_detached_ms: iframeDetachedMs,
        station_panel_ready_ms: panelReadyMs,
        map_remount_ready_ms: Math.round(performance.now() - started),
        remount_zoom: fresh.zoom,
      };
    }
    await sleep(100);
  }
  throw new Error(`Selected station panel did not update to ${stationName || 'clicked station'}.`);
}

async function runSample(browser, index) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(String(error)));
  const sample = { repetition: index, page_errors: pageErrors };
  try {
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    const appFrame = await waitForAppFrame(page);
    const build = await runtimeBuild(page);
    sample.runtime_build = build;
    if (EXPECTED_RUNTIME && build !== EXPECTED_RUNTIME) {
      throw new Error(`Runtime mismatch: expected ${EXPECTED_RUNTIME}, observed ${build}`);
    }

    const findStarted = performance.now();
    await clickFindClimate(appFrame);
    const map = await waitForCatalogAndMap(page, appFrame, findStarted);
    sample.find_climate_catalog_ready_ms = map.catalog_ready_ms;
    sample.find_climate_map_ready_ms = map.map_ready_ms;
    sample.initial_map_zoom = map.initial_zoom;

    const chosen = await chooseVisibleStationMarker(map.frame);
    sample.visible_station_paths = chosen.marker_count;
    sample.clicked_tooltip = chosen.tooltip_text;
    sample.clicked_station = stationNameFromTooltip(chosen.tooltip_text);

    const stationStarted = performance.now();
    await chosen.marker.click({ force: true, timeout: 5_000 });
    const station = await waitForStationRerun(page, appFrame, map.frame, sample.clicked_station, stationStarted);
    Object.assign(sample, station);
    sample.page_errors = [...pageErrors];
    await page.screenshot({ path: path.join(OUT_DIR, `sample-${index}.png`), fullPage: true }).catch(() => {});
    return sample;
  } finally {
    await context.close();
  }
}

function median(values) {
  const nums = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!nums.length) return null;
  const mid = Math.floor(nums.length / 2);
  return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
}

const browser = await chromium.launch({
  executablePath: CHROME_PATH,
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});

const samples = [];
let failure = null;
try {
  // Warm-up run: populate Streamlit resource caches and browser/CDN paths, but
  // do not include it in the reported latency distribution.
  const warmup = await runSample(browser, 0);
  await fs.writeFile(path.join(OUT_DIR, 'warmup.json'), JSON.stringify(warmup, null, 2));
  for (let i = 1; i <= REPETITIONS; i += 1) {
    samples.push(await runSample(browser, i));
  }
} catch (error) {
  failure = String(error);
} finally {
  await browser.close();
}

const result = {
  target_url: TARGET_URL,
  expected_runtime: EXPECTED_RUNTIME || null,
  repetitions_requested: REPETITIONS,
  samples,
  medians_ms: {
    find_climate_catalog_ready: median(samples.map((s) => s.find_climate_catalog_ready_ms)),
    find_climate_map_ready: median(samples.map((s) => s.find_climate_map_ready_ms)),
    station_panel_ready: median(samples.map((s) => s.station_panel_ready_ms)),
    station_map_remount_ready: median(samples.map((s) => s.map_remount_ready_ms)),
  },
  failure,
};
await fs.writeFile(path.join(OUT_DIR, 'performance.json'), JSON.stringify(result, null, 2));
console.log('LIVE_MAP_PERFORMANCE=' + JSON.stringify(result));

if (failure || samples.length !== REPETITIONS || samples.some((s) => s.page_errors?.length)) {
  process.exitCode = 1;
}
