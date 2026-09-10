import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { createRequire } from 'node:module';
import puppeteer from 'puppeteer-core';

const require = createRequire(import.meta.url);
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

const baseUrl = (process.env.SITE_AUDIT_BASE_URL || 'http://127.0.0.1:8765').replace(/\/$/, '');
const outputDir = process.env.SITE_AUDIT_OUTPUT || 'artifacts/site-browser-audit';
const chromePath = process.env.CHROME_PATH;
if (!chromePath) throw new Error('CHROME_PATH is required');

const routes = [
  ['home', '/'],
  ['tools', '/tools/'],
  ['teaching', '/teaching/'],
  ['research', '/research/'],
  ['documentation', '/documentation/'],
  ['about', '/about/'],
  ['privacy', '/privacy/'],
  ['accessibility', '/accessibility/'],
  ['legal', '/legal/'],
];

const viewports = [
  { name: 'desktop', width: 1440, height: 1000, deviceScaleFactor: 1 },
  { name: 'tablet', width: 820, height: 1180, deviceScaleFactor: 1 },
  { name: 'mobile', width: 390, height: 844, deviceScaleFactor: 1 },
];

const zoomProxy = { name: 'desktop-200pct-layout-proxy', width: 720, height: 500, deviceScaleFactor: 2 };
const localHosts = new Set(['127.0.0.1', 'localhost']);
const report = {
  schema: 'building-energy-tools-site-browser-audit-v1',
  generatedAtUtc: new Date().toISOString(),
  baseUrl,
  chromePath,
  viewports,
  zoomProxy,
  routes: [],
  keyboard: [],
  summary: {},
};

fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(path.join(outputDir, 'screenshots'), { recursive: true });

function isExternal(urlString) {
  try {
    const url = new URL(urlString);
    return (url.protocol === 'http:' || url.protocol === 'https:') && !localHosts.has(url.hostname);
  } catch {
    return false;
  }
}

function simpleAxeViolations(results) {
  return results.violations.map(v => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    helpUrl: v.helpUrl,
    nodes: v.nodes.map(n => ({ target: n.target, html: n.html, failureSummary: n.failureSummary })),
  }));
}

async function auditRoute(browser, viewport, routeName, routePath) {
  const page = await browser.newPage();
  await page.setViewport(viewport);
  const externalRequests = new Set();
  const failedRequests = [];
  const badResponses = [];
  const consoleErrors = [];
  const pageErrors = [];

  page.on('request', req => {
    if (isExternal(req.url())) externalRequests.add(req.url());
  });
  page.on('requestfailed', req => {
    failedRequests.push({ url: req.url(), errorText: req.failure()?.errorText || 'unknown' });
  });
  page.on('response', res => {
    if (res.status() >= 400) badResponses.push({ url: res.url(), status: res.status() });
  });
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', err => pageErrors.push(String(err)));

  const url = `${baseUrl}${routePath}`;
  const started = Date.now();
  const response = await page.goto(url, { waitUntil: 'networkidle0', timeout: 30000 });
  const loadMs = Date.now() - started;

  const layout = await page.evaluate(() => {
    const navLinks = [...document.querySelectorAll('.site-nav a')].map((el, i) => {
      const r = el.getBoundingClientRect();
      return { i, text: el.textContent.trim(), left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
    });
    const overlaps = [];
    for (let i = 0; i < navLinks.length; i += 1) {
      for (let j = i + 1; j < navLinks.length; j += 1) {
        const a = navLinks[i];
        const b = navLinks[j];
        const overlap = a.left < b.right - 0.5 && a.right > b.left + 0.5 && a.top < b.bottom - 0.5 && a.bottom > b.top + 0.5;
        if (overlap) overlaps.push([a.text, b.text]);
      }
    }
    const clipped = [...document.querySelectorAll('body *')]
      .filter(el => {
        const style = getComputedStyle(el);
        if (style.position === 'fixed' || style.position === 'absolute') return false;
        const r = el.getBoundingClientRect();
        return r.width > 1 && (r.left < -1 || r.right > window.innerWidth + 1);
      })
      .slice(0, 20)
      .map(el => ({ tag: el.tagName, className: String(el.className || ''), text: (el.textContent || '').trim().slice(0, 120) }));
    return {
      title: document.title,
      h1Count: document.querySelectorAll('h1').length,
      mainCount: document.querySelectorAll('main').length,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      overflowX: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      bodyHeight: document.body.scrollHeight,
      navHeight: document.querySelector('.site-nav')?.getBoundingClientRect().height || 0,
      navLinkCount: navLinks.length,
      navOverlaps: overlaps,
      clipped,
    };
  });

  await page.addScriptTag({ content: axeSource });
  const axe = await page.evaluate(async () => {
    const result = await window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] },
    });
    return result;
  });

  const screenshot = path.join(outputDir, 'screenshots', `${viewport.name}-${routeName}.png`);
  await page.screenshot({ path: screenshot, fullPage: true });
  await page.close();

  return {
    viewport: viewport.name,
    route: routeName,
    path: routePath,
    status: response?.status() ?? null,
    loadMs,
    layout,
    externalRequests: [...externalRequests].sort(),
    failedRequests,
    badResponses,
    consoleErrors,
    pageErrors,
    axeViolations: simpleAxeViolations(axe),
    screenshot: path.relative(outputDir, screenshot),
  };
}

async function auditKeyboard(browser, viewport) {
  const page = await browser.newPage();
  await page.setViewport(viewport);
  await page.goto(`${baseUrl}/`, { waitUntil: 'networkidle0', timeout: 30000 });
  const sequence = [];
  for (let i = 0; i < 10; i += 1) {
    await page.keyboard.press('Tab');
    sequence.push(await page.evaluate(() => {
      const el = document.activeElement;
      const r = el?.getBoundingClientRect();
      return {
        tag: el?.tagName || null,
        className: String(el?.className || ''),
        text: (el?.textContent || '').trim().slice(0, 100),
        href: el?.getAttribute?.('href') || null,
        visible: !!r && r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight,
      };
    }));
  }
  await page.close();
  return {
    viewport: viewport.name,
    firstFocusIsSkipLink: sequence[0]?.className.split(/\s+/).includes('skip-link') || false,
    firstFocusVisible: sequence[0]?.visible || false,
    sequence,
  };
}

const browser = await puppeteer.launch({
  headless: 'new',
  executablePath: chromePath,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});

try {
  for (const viewport of viewports) {
    for (const [routeName, routePath] of routes) {
      report.routes.push(await auditRoute(browser, viewport, routeName, routePath));
    }
    report.keyboard.push(await auditKeyboard(browser, viewport));
  }
  report.routes.push(await auditRoute(browser, zoomProxy, 'home', '/'));
} finally {
  await browser.close();
}

const routeFailures = [];
for (const item of report.routes) {
  const failures = [];
  if (item.status !== 200) failures.push(`HTTP ${item.status}`);
  if (item.layout.h1Count !== 1) failures.push(`h1Count=${item.layout.h1Count}`);
  if (item.layout.mainCount !== 1) failures.push(`mainCount=${item.layout.mainCount}`);
  if (item.layout.overflowX > 1) failures.push(`overflowX=${item.layout.overflowX}`);
  if (item.layout.navOverlaps.length) failures.push(`navOverlaps=${JSON.stringify(item.layout.navOverlaps)}`);
  if (item.layout.clipped.length) failures.push(`clipped=${item.layout.clipped.length}`);
  if (item.externalRequests.length) failures.push(`externalRequests=${item.externalRequests.length}`);
  if (item.failedRequests.length) failures.push(`failedRequests=${item.failedRequests.length}`);
  if (item.badResponses.length) failures.push(`badResponses=${item.badResponses.length}`);
  if (item.consoleErrors.length) failures.push(`consoleErrors=${item.consoleErrors.length}`);
  if (item.pageErrors.length) failures.push(`pageErrors=${item.pageErrors.length}`);
  if (item.axeViolations.length) failures.push(`axeViolations=${item.axeViolations.map(v => v.id).join(',')}`);
  if (failures.length) routeFailures.push({ viewport: item.viewport, route: item.route, failures });
}

const keyboardFailures = report.keyboard
  .filter(k => !k.firstFocusIsSkipLink || !k.firstFocusVisible)
  .map(k => ({ viewport: k.viewport, firstFocusIsSkipLink: k.firstFocusIsSkipLink, firstFocusVisible: k.firstFocusVisible }));

report.summary = {
  routeCount: report.routes.length,
  screenshotCount: report.routes.length,
  routeFailures,
  keyboardFailures,
  pass: routeFailures.length === 0 && keyboardFailures.length === 0,
  note: 'desktop-200pct-layout-proxy approximates 200% browser zoom by halving the CSS viewport while using deviceScaleFactor=2; manual browser zoom review remains a separate publication task.',
};

fs.writeFileSync(path.join(outputDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);

const lines = [
  '# Building Energy Tools — browser audit',
  '',
  `Generated: ${report.generatedAtUtc}`,
  `Base URL: ${baseUrl}`,
  `Overall: ${report.summary.pass ? 'PASS' : 'FAIL'}`,
  '',
  '| Viewport | Route | HTTP | Load ms | Overflow px | Axe | External requests |',
  '| --- | --- | ---: | ---: | ---: | ---: | ---: |',
  ...report.routes.map(r => `| ${r.viewport} | ${r.route} | ${r.status} | ${r.loadMs} | ${r.layout.overflowX} | ${r.axeViolations.length} | ${r.externalRequests.length} |`),
  '',
  '## Keyboard entry',
  ...report.keyboard.map(k => `- ${k.viewport}: skip-link first=${k.firstFocusIsSkipLink}, visible=${k.firstFocusVisible}`),
  '',
  '## Failures',
  ...(routeFailures.length ? routeFailures.map(f => `- ${f.viewport}/${f.route}: ${f.failures.join('; ')}`) : ['- None']),
  ...(keyboardFailures.length ? keyboardFailures.map(f => `- keyboard/${f.viewport}: ${JSON.stringify(f)}`) : []),
  '',
  `Note: ${report.summary.note}`,
];
fs.writeFileSync(path.join(outputDir, 'report.md'), `${lines.join('\n')}\n`);
console.log(lines.join('\n'));

if (!report.summary.pass) process.exit(1);
