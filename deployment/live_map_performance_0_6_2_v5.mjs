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

async function text(frame) {
  try { return await frame.locator('body').innerText({ timeout: 1500 }); } catch { return ''; }
}

async function appFrame(page) {
  for (let i = 0; i < 600; i += 1) {
    for (const f of page.frames()) if ((await text(f)).includes('Climate Analyzer')) return f;
    await sleep(100);
  }
  throw new Error('app frame timeout');
}

async function waitRuntime(page) {
  for (let i = 0; i < 300; i += 1) {
    for (const f of page.frames()) {
      const m = f.locator('#climate-analyzer-runtime-build').first();
      if (await m.count().catch(() => 0)) {
        const id = await m.getAttribute('data-runtime-build').catch(() => null);
        if (id === EXPECTED) return id;
      }
    }
    await sleep(100);
  }
  throw new Error('runtime marker timeout');
}

async function tileZoom(frame) {
  const urls = await frame.locator('img.leaflet-tile').evaluateAll((nodes) => nodes.map((n) => n.src || '')).catch(() => []);
  const zs = [];
  for (const raw of urls) {
    try {
      const m = new URL(raw).pathname.match(/^\/(\d+)\//);
      if (m) zs.push(Number.parseInt(m[1], 10));
    } catch {}
  }
  return zs.length ? Math.max(...zs) : null;
}

async function foliumFrame(page, timeoutMs = 30000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const f of page.frames()) {
      if (!f.url().includes('streamlit_folium.st_folium')) continue;
      if (!(await f.locator('.leaflet-control-zoom-in').count().catch(() => 0))) continue;
      const z = await tileZoom(f);
      if (Number.isInteger(z)) return { frame: f, zoom: z };
    }
    await sleep(50);
  }
  throw new Error('folium frame timeout');
}

async function openFindClimate(page, app) {
  let ctl = app.getByRole('tab', { name: 'Find climate', exact: true });
  if (!(await ctl.count())) ctl = app.getByText('Find climate', { exact: true }).first();
  const t0 = performance.now();
  await ctl.click({ timeout: 10000 });
  let catalogMs = null;
  for (let i = 0; i < 600; i += 1) {
    const s = await text(app);
    if (/Visible catalog records after filters:\s*98[,.]?047\s+of\s+98[,.]?047/i.test(s)) {
      catalogMs = Math.round(performance.now() - t0);
      break;
    }
    await sleep(50);
  }
  if (catalogMs == null) throw new Error('catalog readiness timeout');
  await app.getByText('Clustered overview is active.', { exact: false }).first().scrollIntoViewIfNeeded().catch(() => {});
  const folium = await foliumFrame(page);
  return { catalogMs, mapMs: Math.round(performance.now() - t0), ...folium };
}

async function chooseGraz(frame) {
  return frame.evaluate(async () => {
    const map = window.map;
    if (!map) throw new Error('window.map unavailable');
    map.setView([47.0707, 15.4395], 11, { animate: false });
    await new Promise((r) => setTimeout(r, 650));
    const seen = new Set();
    const hits = [];
    function visit(layer) {
      if (!layer || seen.has(layer)) return;
      seen.add(layer);
      if (typeof layer.getLayers === 'function') for (const child of layer.getLayers()) visit(child);
      if (typeof layer.getLatLng === 'function' && typeof layer.getTooltip === 'function') {
        const ll = layer.getLatLng();
        const tt = layer.getTooltip();
        const content = tt && typeof tt.getContent === 'function' ? String(tt.getContent() || '') : '';
        if (ll && content.includes('station_idx=')) {
          hits.push({ content, lat: ll.lat, lon: ll.lng, d: Math.abs(ll.lat - 47.0707) + Math.abs(ll.lng - 15.4395) });
        }
      }
    }
    for (const layer of Object.values(map._layers || {})) visit(layer);
    hits.sort((a, b) => a.d - b.d);
    if (!hits.length) throw new Error('no Graz station candidate');
    const hit = hits[0];
    map.panTo([hit.lat, hit.lon], { animate: false });
    await new Promise((r) => setTimeout(r, 200));
    return { ...hit, count: hits.length };
  });
}

function stationName(tooltip) {
  return (String(tooltip).split(' | ', 2)[1] || '').split(' — ', 1)[0].trim();
}

async function fireTopLevelClusterClick(frame, tooltip) {
  await frame.evaluate(async ({ tooltip }) => {
    const map = window.map;
    if (!map) throw new Error('window.map unavailable during synthetic click');
    const seen = new Set();
    let child = null;
    let top = null;
    function find(layer, root) {
      if (!layer || seen.has(layer) || child) return;
      seen.add(layer);
      if (typeof layer.getTooltip === 'function') {
        const tt = layer.getTooltip();
        const content = tt && typeof tt.getContent === 'function' ? String(tt.getContent() || '') : '';
        if (content === tooltip) {
          child = layer;
          top = root;
          return;
        }
      }
      if (typeof layer.getLayers === 'function') for (const nested of layer.getLayers()) find(nested, root);
    }
    for (const root of Object.values(map._layers || {})) {
      find(root, root);
      if (child) break;
    }
    if (!child || !top || typeof top.fire !== 'function') throw new Error('top-level cluster layer for station was not found');
    const ll = child.getLatLng();
    top.fire('click', { latlng: ll, sourceTarget: child, target: top, layer: child }, false);
    await new Promise((r) => setTimeout(r, 300));
  }, { tooltip });
}

async function waitPanel(page, app, oldFrame, name, started) {
  const oldElement = await oldFrame.frameElement().catch(() => null);
  let detachedMs = null;
  for (let i = 0; i < 400; i += 1) {
    if (detachedMs == null && oldElement) {
      const detached = await oldElement.evaluate((n) => !n.isConnected).catch(() => true);
      if (detached) detachedMs = Math.round(performance.now() - started);
    }
    const s = await text(app);
    if (s.includes(name) && s.includes('Available climates at this station')) {
      const panelMs = Math.round(performance.now() - started);
      const fresh = await foliumFrame(page, 10000);
      const oldConnected = oldElement ? await oldElement.evaluate((n) => n.isConnected).catch(() => false) : false;
      return {
        panelMs,
        mapAfterClickMs: Math.round(performance.now() - started),
        detachedMs,
        framePersisted: fresh.frame === oldFrame && oldConnected,
        zoom: fresh.zoom,
      };
    }
    await sleep(50);
  }
  throw new Error(`station panel timeout: ${name}`);
}

async function sample(context, i) {
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  try {
    await page.goto(TARGET, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const app = await appFrame(page);
    const runtime = await waitRuntime(page);
    const opened = await openFindClimate(page, app);
    const chosen = await chooseGraz(opened.frame);
    const name = stationName(chosen.content);
    const t1 = performance.now();
    await fireTopLevelClusterClick(opened.frame, chosen.content);
    const selected = await waitPanel(page, app, opened.frame, name, t1);
    await page.screenshot({ path: path.join(OUT, `sample-${i}.png`), fullPage: true }).catch(() => {});
    return {
      repetition: i,
      runtime,
      find_climate_catalog_ready_ms: opened.catalogMs,
      find_climate_map_ready_ms: opened.mapMs,
      initial_zoom: opened.zoom,
      clicked_station: name,
      clicked_tooltip: chosen.content,
      candidate_count: chosen.count,
      station_panel_ready_ms: selected.panelMs,
      map_ready_after_click_ms: selected.mapAfterClickMs,
      iframe_detached_ms: selected.detachedMs,
      map_frame_persisted: selected.framePersisted,
      post_click_zoom: selected.zoom,
      page_errors: errors,
    };
  } finally { await page.close(); }
}

function median(xs) {
  const a = xs.filter(Number.isFinite).sort((x, y) => x - y);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
function p90(xs) {
  const a = xs.filter(Number.isFinite).sort((x, y) => x - y);
  return a.length ? a[Math.min(a.length - 1, Math.ceil(a.length * 0.9) - 1)] : null;
}

const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
let warmup = null;
const samples = [];
let failure = null;
try {
  warmup = await sample(context, 0);
  await fs.writeFile(path.join(OUT, 'warmup.json'), JSON.stringify(warmup, null, 2));
  for (let i = 1; i <= N; i += 1) samples.push(await sample(context, i));
} catch (e) { failure = String(e); }
await context.close();
await browser.close();

const mapTimes = samples.map((s) => s.find_climate_map_ready_ms);
const panelTimes = samples.map((s) => s.station_panel_ready_ms);
const result = {
  schema: 'climate-0.6.2-live-map-performance-v5',
  expected_runtime: EXPECTED,
  repetitions_requested: N,
  warmup,
  samples,
  medians_ms: {
    find_climate_catalog_ready: median(samples.map((s) => s.find_climate_catalog_ready_ms)),
    find_climate_map_ready: median(mapTimes),
    station_panel_ready: median(panelTimes),
    map_ready_after_station_click: median(samples.map((s) => s.map_ready_after_click_ms)),
  },
  p90_ms: { find_climate_map_ready: p90(mapTimes), station_panel_ready: p90(panelTimes) },
  map_frame_persisted_samples: samples.filter((s) => s.map_frame_persisted).length,
  failure,
};
await fs.writeFile(path.join(OUT, 'performance.json'), JSON.stringify(result, null, 2));
console.log('LIVE_MAP_PERFORMANCE_0_6_2_V5=' + JSON.stringify(result));
if (failure || samples.length !== N || samples.some((s) => s.page_errors.length)) process.exitCode = 1;
