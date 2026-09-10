import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import axe from 'axe-core';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'https://building-climate-analyzer.streamlit.app/';
const OUT_DIR = process.env.AUDIT_OUTPUT_DIR || 'artifacts/live-audit';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';

await fs.mkdir(OUT_DIR, { recursive: true });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const nowIso = () => new Date().toISOString();

async function timedFetch(url) {
  const started = performance.now();
  try {
    const response = await fetch(url, { redirect: 'follow', signal: AbortSignal.timeout(120_000) });
    const text = await response.text();
    return {
      ok: response.ok,
      status: response.status,
      final_url: response.url,
      elapsed_ms: Math.round(performance.now() - started),
      body_preview: text.slice(0, 500),
      headers: Object.fromEntries(
        ['content-type', 'content-length', 'server', 'cache-control', 'strict-transport-security']
          .map((name) => [name, response.headers.get(name)])
          .filter(([, value]) => value !== null),
      ),
    };
  } catch (error) {
    return {
      ok: false,
      status: null,
      final_url: url,
      elapsed_ms: Math.round(performance.now() - started),
      error: String(error),
    };
  }
}

async function collectStorage(page) {
  return page.evaluate(() => ({
    local_storage_keys: Object.keys(localStorage).sort(),
    session_storage_keys: Object.keys(sessionStorage).sort(),
  }));
}

async function collectFrameAttribution(page) {
  const frameResults = [];
  for (const frame of page.frames()) {
    try {
      const text = (await frame.locator('body').innerText({ timeout: 5_000 })).slice(0, 20_000);
      const links = await frame.locator('a').evaluateAll((nodes) => nodes.map((node) => ({
        text: (node.textContent || '').trim(),
        href: node.href || '',
      })));
      frameResults.push({
        url: frame.url(),
        has_openstreetmap_text: /OpenStreetMap/i.test(text),
        osm_links: links.filter((item) => /openstreetmap\.org/i.test(item.href) || /OpenStreetMap/i.test(item.text)),
      });
    } catch (error) {
      frameResults.push({ url: frame.url(), error: String(error) });
    }
  }
  return frameResults;
}

async function runViewportAudit(browser, name, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const requestUrls = new Set();
  const failedRequests = [];
  const consoleMessages = [];
  const pageErrors = [];

  page.on('request', (request) => requestUrls.add(request.url()));
  page.on('requestfailed', (request) => failedRequests.push({
    url: request.url(),
    error: request.failure()?.errorText || 'unknown',
  }));
  page.on('console', (message) => {
    if (['warning', 'error'].includes(message.type())) {
      consoleMessages.push({ type: message.type(), text: message.text() });
    }
  });
  page.on('pageerror', (error) => pageErrors.push(String(error)));

  const started = performance.now();
  let navigationError = null;
  try {
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  } catch (error) {
    navigationError = String(error);
  }

  let appVisible = false;
  try {
    await page.getByText('Climate Analyzer', { exact: false }).first().waitFor({ state: 'visible', timeout: 120_000 });
    appVisible = true;
  } catch {
    appVisible = false;
  }
  await sleep(4_000);

  const initialLoadMs = Math.round(performance.now() - started);
  const title = await page.title().catch(() => '');
  const bodyText = await page.locator('body').innerText().catch(() => '');
  const headings = await page.locator('h1,h2,h3').allInnerTexts().catch(() => []);
  const viewportMetrics = await page.evaluate(() => ({
    client_width: document.documentElement.clientWidth,
    scroll_width: document.documentElement.scrollWidth,
    client_height: document.documentElement.clientHeight,
    scroll_height: document.documentElement.scrollHeight,
    horizontal_overflow_px: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
  })).catch(() => null);

  const throttleVisible = /Your app has been throttled/i.test(bodyText);
  const resourceLimitVisible = /resource limits|gone over its resource limits/i.test(bodyText);

  let axeResults = { violations: [], incomplete: [], passes: [] };
  try {
    await page.addScriptTag({ content: axe.source });
    const raw = await page.evaluate(async () => axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
    }));
    axeResults = {
      violations: raw.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        description: v.description,
        help: v.help,
        help_url: v.helpUrl,
        nodes: v.nodes.length,
        targets: v.nodes.slice(0, 8).map((n) => n.target),
      })),
      incomplete: raw.incomplete.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
      passes: raw.passes.map((v) => v.id),
    };
  } catch (error) {
    axeResults = { error: String(error), violations: [], incomplete: [], passes: [] };
  }

  const cookies = await context.cookies().catch(() => []);
  const storage = await collectStorage(page).catch(() => ({ local_storage_keys: [], session_storage_keys: [] }));

  await page.screenshot({ path: path.join(OUT_DIR, `${name}-landing.png`), fullPage: true }).catch(() => {});

  let findClimate = {
    attempted: false,
    clicked: false,
    openstreetmap_visible: false,
    frame_attribution: [],
  };
  try {
    const findClimateLocator = page.getByText('Find climate', { exact: true }).first();
    if (await findClimateLocator.count()) {
      findClimate.attempted = true;
      await findClimateLocator.click({ timeout: 20_000 });
      findClimate.clicked = true;
      await sleep(8_000);
      const afterText = await page.locator('body').innerText();
      findClimate.openstreetmap_visible = /OpenStreetMap/i.test(afterText);
      findClimate.frame_attribution = await collectFrameAttribution(page);
      await page.screenshot({ path: path.join(OUT_DIR, `${name}-find-climate.png`), fullPage: true }).catch(() => {});
    }
  } catch (error) {
    findClimate.error = String(error);
  }

  const domains = [...new Set([...requestUrls].map((url) => {
    try { return new URL(url).hostname; } catch { return null; }
  }).filter(Boolean))].sort();

  const result = {
    name,
    viewport,
    navigation_error: navigationError,
    app_visible: appVisible,
    initial_load_ms: initialLoadMs,
    title,
    headings,
    throttle_visible: throttleVisible,
    resource_limit_visible: resourceLimitVisible,
    viewport_metrics: viewportMetrics,
    console_messages: consoleMessages.slice(0, 100),
    page_errors: pageErrors.slice(0, 100),
    failed_requests: failedRequests.slice(0, 100),
    network_domains: domains,
    cookies: cookies.map((cookie) => ({
      name: cookie.name,
      domain: cookie.domain,
      path: cookie.path,
      secure: cookie.secure,
      http_only: cookie.httpOnly,
      same_site: cookie.sameSite,
      expires: cookie.expires,
    })),
    storage,
    accessibility: axeResults,
    find_climate: findClimate,
  };

  await context.close();
  return result;
}

const healthUrl = new URL('/_stcore/health', TARGET_URL).toString();
const report = {
  schema: 'building-energy-tools-live-audit-v1',
  target_url: TARGET_URL,
  audited_at_utc: nowIso(),
  http: {
    root: await timedFetch(TARGET_URL),
    health: await timedFetch(healthUrl),
  },
  browser: null,
};

let browser;
try {
  browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  report.browser = {
    desktop: await runViewportAudit(browser, 'desktop', { width: 1440, height: 1000 }),
    mobile: await runViewportAudit(browser, 'mobile', { width: 390, height: 844 }),
  };
} catch (error) {
  report.browser = { error: String(error) };
} finally {
  if (browser) await browser.close();
}

await fs.writeFile(path.join(OUT_DIR, 'live-audit.json'), JSON.stringify(report, null, 2));

const views = report.browser && !report.browser.error ? [report.browser.desktop, report.browser.mobile] : [];
const critical = [];
if (!report.http.health.ok) critical.push('Health endpoint did not return a successful response.');
if (!report.http.root.ok) critical.push('Root URL did not return a successful response.');
for (const view of views) {
  if (!view.app_visible) critical.push(`${view.name}: Climate Analyzer UI was not detected.`);
  if (view.page_errors.length) critical.push(`${view.name}: ${view.page_errors.length} uncaught page error(s).`);
}

const md = [
  '# Climate Analyzer live deployment audit',
  '',
  `- Target: ${TARGET_URL}`,
  `- Audited at: ${report.audited_at_utc}`,
  `- Root HTTP: ${report.http.root.status ?? 'ERROR'} (${report.http.root.elapsed_ms} ms)`,
  `- Health HTTP: ${report.http.health.status ?? 'ERROR'} (${report.http.health.elapsed_ms} ms)`,
  '',
  '## Browser summary',
  '',
  ...views.flatMap((view) => [
    `### ${view.name}`,
    '',
    `- Viewport: ${view.viewport.width} × ${view.viewport.height}`,
    `- UI detected: ${view.app_visible}`,
    `- Initial load: ${view.initial_load_ms} ms`,
    `- Throttle banner detected: ${view.throttle_visible}`,
    `- Horizontal overflow: ${view.viewport_metrics?.horizontal_overflow_px ?? 'n/a'} px`,
    `- Console warnings/errors: ${view.console_messages.length}`,
    `- Uncaught page errors: ${view.page_errors.length}`,
    `- Failed requests: ${view.failed_requests.length}`,
    `- Cookies: ${view.cookies.length}`,
    `- localStorage keys: ${view.storage.local_storage_keys.length}`,
    `- sessionStorage keys: ${view.storage.session_storage_keys.length}`,
    `- Axe WCAG A/AA violations: ${view.accessibility.violations?.length ?? 'n/a'}`,
    `- Find climate clicked: ${view.find_climate.clicked}`,
    '',
  ]),
  '## Critical findings',
  '',
  ...(critical.length ? critical.map((item) => `- ${item}`) : ['- None detected by the automated critical gate.']),
  '',
  '> Automated browser audit is evidence, not full manual accessibility or legal/privacy clearance.',
  '',
].join('\n');
await fs.writeFile(path.join(OUT_DIR, 'LIVE_AUDIT.md'), md);

console.log(md);
console.log(`Audit JSON: ${path.join(OUT_DIR, 'live-audit.json')}`);

if (!report.http.health.ok || !report.http.root.ok || report.browser?.error) {
  process.exitCode = 1;
}
