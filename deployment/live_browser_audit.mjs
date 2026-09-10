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

async function firstHttpResponse(url) {
  const started = performance.now();
  try {
    const response = await fetch(url, {
      redirect: 'manual',
      signal: AbortSignal.timeout(30_000),
    });
    return {
      status: response.status,
      elapsed_ms: Math.round(performance.now() - started),
      location: response.headers.get('location'),
      server: response.headers.get('server'),
      content_type: response.headers.get('content-type'),
    };
  } catch (error) {
    return {
      status: null,
      elapsed_ms: Math.round(performance.now() - started),
      error: String(error),
    };
  }
}

async function bodyText(frame) {
  try {
    return await frame.locator('body').innerText({ timeout: 2_000 });
  } catch {
    return '';
  }
}

async function waitForFrameContaining(page, text, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) {
      const textContent = await bodyText(frame);
      if (textContent.includes(text)) {
        return {
          frame,
          detected_ms: Math.round(performance.now() - started),
          text_preview: textContent.slice(0, 2_000),
        };
      }
    }
    await sleep(500);
  }
  return null;
}

async function collectStorage(frame) {
  return frame.evaluate(() => ({
    local_storage_keys: Object.keys(localStorage).sort(),
    session_storage_keys: Object.keys(sessionStorage).sort(),
  }));
}

async function collectAttribution(page) {
  const results = [];
  for (const frame of page.frames()) {
    try {
      const text = (await bodyText(frame)).slice(0, 20_000);
      const links = await frame.locator('a').evaluateAll((nodes) => nodes.map((node) => ({
        text: (node.textContent || '').trim(),
        href: node.href || '',
      })));
      results.push({
        url: frame.url(),
        has_openstreetmap_text: /OpenStreetMap/i.test(text),
        osm_links: links.filter((item) => /openstreetmap\.org/i.test(item.href) || /OpenStreetMap/i.test(item.text)),
      });
    } catch (error) {
      results.push({ url: frame.url(), error: String(error) });
    }
  }
  return results;
}

async function runAxe(frame) {
  try {
    await frame.addScriptTag({ content: axe.source });
    const raw = await frame.evaluate(async () => window.axe.run(document, {
      runOnly: {
        type: 'tag',
        values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'],
      },
    }));
    return {
      violations: raw.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        description: v.description,
        help: v.help,
        help_url: v.helpUrl,
        nodes: v.nodes.length,
        targets: v.nodes.slice(0, 8).map((n) => n.target),
      })),
      incomplete: raw.incomplete.map((v) => ({
        id: v.id,
        impact: v.impact,
        nodes: v.nodes.length,
      })),
      passes: raw.passes.map((v) => v.id),
    };
  } catch (error) {
    return { error: String(error), violations: [], incomplete: [], passes: [] };
  }
}

function domainSet(urls) {
  return [...new Set([...urls].map((url) => {
    try {
      return new URL(url).hostname;
    } catch {
      return null;
    }
  }).filter(Boolean))].sort();
}

async function runViewportAudit(browser, name, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const requestUrls = new Set();
  const responseErrors = [];
  const failedRequests = [];
  const consoleMessages = [];
  const pageErrors = [];

  page.on('request', (request) => requestUrls.add(request.url()));
  page.on('response', (response) => {
    if (response.status() >= 400) {
      responseErrors.push({ status: response.status(), url: response.url() });
    }
  });
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
  let navigationStatus = null;
  try {
    const response = await page.goto(TARGET_URL, {
      waitUntil: 'domcontentloaded',
      timeout: 60_000,
    });
    navigationStatus = response?.status() ?? null;
  } catch (error) {
    navigationError = String(error);
  }

  const appHit = await waitForFrameContaining(page, 'Climate Analyzer', 60_000);
  const appVisible = Boolean(appHit);
  const appFrame = appHit?.frame || page.mainFrame();
  const appDetectedMs = appHit?.detected_ms ?? null;
  const initialLoadMs = Math.round(performance.now() - started);

  await sleep(2_000);
  const initialRequestDomains = domainSet(requestUrls);
  const initialOsmRequested = initialRequestDomains.includes('tile.openstreetmap.org');

  const appText = await bodyText(appFrame);
  const pageText = await bodyText(page.mainFrame());
  const title = await page.title().catch(() => '');
  const headings = await appFrame.locator('h1,h2,h3').allInnerTexts().catch(() => []);
  const frameUrls = page.frames().map((frame) => frame.url());
  const viewportMetrics = await page.evaluate(() => ({
    client_width: document.documentElement.clientWidth,
    scroll_width: document.documentElement.scrollWidth,
    client_height: document.documentElement.clientHeight,
    scroll_height: document.documentElement.scrollHeight,
    horizontal_overflow_px: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
  })).catch(() => null);

  const throttleVisible = /Your app has been throttled/i.test(`${pageText}\n${appText}`);
  const resourceLimitVisible = /resource limits|gone over its resource limits/i.test(`${pageText}\n${appText}`);
  const accessibility = await runAxe(appFrame);
  const cookies = await context.cookies().catch(() => []);
  const storage = await collectStorage(page.mainFrame()).catch(() => ({
    local_storage_keys: [],
    session_storage_keys: [],
  }));

  await page.screenshot({
    path: path.join(OUT_DIR, `${name}-landing.png`),
    fullPage: true,
  }).catch(() => {});

  const findClimate = {
    attempted: false,
    clicked: false,
    openstreetmap_visible: false,
    frame_attribution: [],
  };
  if (appVisible) {
    try {
      let locator = appFrame.getByRole('tab', { name: 'Find climate', exact: true });
      if (!(await locator.count())) {
        locator = appFrame.getByText('Find climate', { exact: true }).first();
      }
      if (await locator.count()) {
        findClimate.attempted = true;
        await locator.click({ timeout: 15_000 });
        findClimate.clicked = true;
        await sleep(5_000);
        findClimate.frame_attribution = await collectAttribution(page);
        findClimate.openstreetmap_visible = findClimate.frame_attribution.some((item) =>
          item.has_openstreetmap_text || (item.osm_links || []).length > 0
        );
        await page.screenshot({
          path: path.join(OUT_DIR, `${name}-find-climate.png`),
          fullPage: true,
        }).catch(() => {});
      }
    } catch (error) {
      findClimate.error = String(error);
    }
  }

  const allDomains = domainSet(requestUrls);
  const result = {
    name,
    viewport,
    navigation_status: navigationStatus,
    navigation_error: navigationError,
    app_visible: appVisible,
    app_frame_url: appFrame.url(),
    app_detected_ms: appDetectedMs,
    total_initial_audit_ms: initialLoadMs,
    title,
    headings,
    frame_urls: frameUrls,
    throttle_visible: throttleVisible,
    resource_limit_visible: resourceLimitVisible,
    viewport_metrics: viewportMetrics,
    console_messages: consoleMessages.slice(0, 100),
    page_errors: pageErrors.slice(0, 100),
    failed_requests: failedRequests.slice(0, 100),
    http_error_responses: responseErrors.slice(0, 150),
    initial_network_domains: initialRequestDomains,
    initial_osm_requested_before_find_climate: initialOsmRequested,
    network_domains_after_find_climate: allDomains,
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
    accessibility,
    find_climate: findClimate,
  };

  await context.close();
  return result;
}

const report = {
  schema: 'building-energy-tools-live-audit-v2',
  target_url: TARGET_URL,
  audited_at_utc: nowIso(),
  first_http_response: await firstHttpResponse(TARGET_URL),
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

await fs.writeFile(
  path.join(OUT_DIR, 'live-audit.json'),
  JSON.stringify(report, null, 2),
);

const views = report.browser && !report.browser.error
  ? [report.browser.desktop, report.browser.mobile]
  : [];
const critical = [];
const findings = [];
for (const view of views) {
  if (!view.app_visible) critical.push(`${view.name}: Climate Analyzer UI was not detected.`);
  if (view.page_errors.length) critical.push(`${view.name}: ${view.page_errors.length} uncaught page error(s).`);
  if (view.viewport_metrics?.horizontal_overflow_px > 0) {
    findings.push(`${view.name}: horizontal overflow ${view.viewport_metrics.horizontal_overflow_px}px.`);
  }
  if (view.initial_osm_requested_before_find_climate) {
    findings.push(`${view.name}: OpenStreetMap tiles were requested before the user selected Find climate.`);
  }
  if (view.find_climate.clicked && !view.find_climate.openstreetmap_visible) {
    critical.push(`${view.name}: OpenStreetMap attribution was not detected after opening Find climate.`);
  }
  if ((view.accessibility.violations || []).length) {
    findings.push(`${view.name}: ${view.accessibility.violations.length} axe WCAG A/AA violation group(s) in the detected app frame.`);
  }
}

const md = [
  '# Climate Analyzer live deployment audit',
  '',
  `- Target: ${TARGET_URL}`,
  `- Audited at: ${report.audited_at_utc}`,
  `- First unauthenticated HTTP response: ${report.first_http_response.status ?? 'ERROR'} (${report.first_http_response.elapsed_ms} ms)`,
  '',
  '## Browser summary',
  '',
  ...views.flatMap((view) => [
    `### ${view.name}`,
    '',
    `- Viewport: ${view.viewport.width} × ${view.viewport.height}`,
    `- Navigation HTTP: ${view.navigation_status ?? 'n/a'}`,
    `- UI detected: ${view.app_visible}`,
    `- App frame: ${view.app_frame_url}`,
    `- Time to detected app text: ${view.app_detected_ms ?? 'n/a'} ms`,
    `- Throttle banner detected for anonymous viewer: ${view.throttle_visible}`,
    `- Horizontal overflow: ${view.viewport_metrics?.horizontal_overflow_px ?? 'n/a'} px`,
    `- Uncaught page errors: ${view.page_errors.length}`,
    `- HTTP 4xx/5xx responses observed: ${view.http_error_responses.length}`,
    `- Cookies observed: ${view.cookies.length}`,
    `- localStorage keys: ${view.storage.local_storage_keys.length}`,
    `- Axe WCAG A/AA violation groups in app frame: ${view.accessibility.violations?.length ?? 'n/a'}`,
    `- OSM requested before Find climate: ${view.initial_osm_requested_before_find_climate}`,
    `- Find climate clicked: ${view.find_climate.clicked}`,
    `- OSM attribution detected after Find climate: ${view.find_climate.openstreetmap_visible}`,
    '',
  ]),
  '## Critical findings',
  '',
  ...(critical.length ? critical.map((item) => `- ${item}`) : ['- None detected by the automated critical gate.']),
  '',
  '## Non-critical findings',
  '',
  ...(findings.length ? findings.map((item) => `- ${item}`) : ['- None recorded.']),
  '',
  '> Automated browser audit is evidence, not full manual accessibility or legal/privacy clearance.',
  '',
].join('\n');
await fs.writeFile(path.join(OUT_DIR, 'LIVE_AUDIT.md'), md);

console.log(md);
console.log(`Audit JSON: ${path.join(OUT_DIR, 'live-audit.json')}`);

if (critical.length || report.browser?.error) {
  process.exitCode = 1;
}
