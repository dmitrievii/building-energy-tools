import fs from 'node:fs/promises';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8501/';
const FIXTURE_PATH = process.env.PR83_MONTHLY_FIXTURE || 'artifacts/pr83-contract-smoke/monthly-provider.json';
const OUT_PATH = process.env.PR83_UI_REPORT || 'artifacts/pr83-contract-smoke/source-ui.json';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const MONTHLY_SOURCE = 'Official source: GeoSphere Austria Station Data-v2 (1 m)';
const MONTHLY_CONTEXT = 'About this GeoSphere monthly dataset';
const HOURLY_INFO = 'Official GeoSphere Austria availability context (translated summary)';
const HOURLY_SOURCE = 'Authoritative source: GeoSphere Austria Stationsdaten-v2 (1 h)';

function occurrences(text, needle) { return text.split(needle).length - 1; }
async function bodyText(frame) { try { return await frame.locator('body').innerText({ timeout: 2000 }); } catch { return ''; } }

async function appFrame(page, needle = 'Climate Analyzer', timeoutMs = 90000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const frame of page.frames()) if ((await bodyText(frame)).includes(needle)) return frame;
    await sleep(250);
  }
  throw new Error(`Timed out waiting for app text: ${needle}`);
}

async function combo(frame, label, timeoutMs = 60000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const candidate of [frame.getByRole('combobox', { name: label, exact: true }).first(), frame.getByLabel(label, { exact: true }).first()]) {
      if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for combobox: ${label}`);
}

async function labelledInput(frame, label, timeoutMs = 60000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const candidate of [frame.getByLabel(label, { exact: true }).first(), frame.locator(`input[aria-label="${label}"]`).first()]) {
      if (await candidate.count().catch(() => 0) && await candidate.isVisible().catch(() => false)) return candidate;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for input: ${label}`);
}

async function rendered(control) {
  return [await control.innerText().catch(() => ''), await control.textContent().catch(() => ''), await control.inputValue().catch(() => '')]
    .join(' ').replace(/\s+/g, ' ').trim();
}

async function selectVisibleOption(page, frame, controlLabel, predicate, timeoutMs = 60000) {
  const started = performance.now();
  let last = [];
  while (performance.now() - started < timeoutMs) {
    frame = await appFrame(page, 'Climate Analyzer', 5000);
    let control;
    try { control = await combo(frame, controlLabel, 5000); } catch { await sleep(250); continue; }
    try { await control.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => {}); await control.click({ timeout: 5000 }); }
    catch { await sleep(250); continue; }

    const optionStarted = performance.now();
    while (performance.now() - optionStarted < 6000) {
      const collections = [frame.getByRole('option'), page.getByRole('option'), frame.locator('[data-baseweb="menu"] li'), page.locator('[data-baseweb="menu"] li')];
      for (const options of collections) {
        const count = await options.count().catch(() => 0);
        if (!count) continue;
        last = await options.allInnerTexts().catch(() => last);
        for (let i = 0; i < count; i += 1) {
          const option = options.nth(i);
          const text = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
          if (!predicate(text) || !(await option.isVisible().catch(() => false))) continue;
          await option.click({ timeout: 8000 });
          return await appFrame(page, 'Climate Analyzer', 10000);
        }
      }
      await sleep(200);
    }
    await page.keyboard.press('Escape').catch(() => {});
    await sleep(300);
  }
  throw new Error(`Could not select ${controlLabel}; last options: ${last.join(' | ')}`);
}

async function chooseSource(page) {
  const started = performance.now();
  while (performance.now() - started < 60000) {
    const frame = await appFrame(page, 'Climate Analyzer', 10000);
    for (const c of [frame.getByRole('radio', { name: 'GeoSphere Austria', exact: true }).last(), frame.getByText('GeoSphere Austria', { exact: true }).last(), frame.locator('label').filter({ hasText: 'GeoSphere Austria' }).last()]) {
      if (!(await c.count().catch(() => 0))) continue;
      try {
        const tag = await c.evaluate((n) => n.tagName.toLowerCase()).catch(() => '');
        const type = await c.getAttribute('type').catch(() => null);
        if (tag === 'input' && type === 'radio') await c.check({ force: true, timeout: 5000 }); else await c.click({ force: true, timeout: 5000 });
        return await appFrame(page, 'GeoSphere Austria — measured historical station data', 15000);
      } catch { /* retry */ }
    }
    await sleep(400);
  }
  throw new Error('Could not select GeoSphere Austria source.');
}

async function selectDataset(page, needle, resourceId) {
  await selectVisibleOption(page, await appFrame(page), 'GeoSphere dataset', (text) => text.includes(needle));
  const started = performance.now();
  let last = '';
  while (performance.now() - started < 60000) {
    const frame = await appFrame(page, 'Climate Analyzer', 5000);
    last = await bodyText(frame);
    const controlText = await rendered(await combo(frame, 'GeoSphere dataset', 5000)).catch(() => '');
    if (controlText.includes(needle) && last.includes(`Selected resource: ${resourceId}`)) return frame;
    await sleep(300);
  }
  throw new Error(`Dataset ${needle} did not commit ${resourceId}; last resource=${last.match(/Selected resource:[^\n]*/)?.[0] || 'none'}`);
}

async function selectExactStation(page, stationName, stationId) {
  let frame = await appFrame(page, 'Search GeoSphere station', 60000);
  const input = await labelledInput(frame, 'Search GeoSphere station');
  await input.fill(String(stationName), { timeout: 15000 });
  await input.press('Tab').catch(() => {});
  frame = await appFrame(page, 'Manual station selection', 60000);

  const targetId = String(stationId);
  frame = await selectVisibleOption(page, frame, 'Search-result stations', (text) => text.includes(stationName) && (text.includes(`ID ${targetId}`) || text.includes(targetId)), 60000);

  const settled = performance.now();
  let lastControl = '';
  while (performance.now() - settled < 30000) {
    frame = await appFrame(page, 'Climate Analyzer', 5000);
    try {
      const stationCombo = await combo(frame, 'Search-result stations', 5000);
      lastControl = await rendered(stationCombo);
      if (lastControl.includes(stationName) && (lastControl.includes(`ID ${targetId}`) || lastControl.includes(targetId))) break;
    } catch { /* rerun */ }
    await sleep(250);
  }
  if (!lastControl.includes(stationName) || (!lastControl.includes(`ID ${targetId}`) && !lastControl.includes(targetId))) {
    throw new Error(`Exact station ID ${targetId} did not settle; control=${lastControl}`);
  }

  // Selecting an option in the search-result combobox is only a preview. The
  // production UI commits the station with this explicit button, so the smoke
  // must exercise the same state transition before asserting monthly/hourly UI.
  const commitStarted = performance.now();
  while (performance.now() - commitStarted < 30000) {
    frame = await appFrame(page, 'Manual station selection', 5000);
    const button = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
    if (await button.count().catch(() => 0) && await button.isVisible().catch(() => false)) {
      await button.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
      await button.click({ timeout: 15000 });
      const committed = await waitBody(
        page,
        (text) => text.includes('Selected station') && text.includes(stationName) && text.includes(targetId),
        `committed station ${stationName} ${targetId}`,
        60000,
        1,
      );
      return committed.frame;
    }
    await sleep(250);
  }
  throw new Error('Use station from list button did not become available.');
}

async function waitBody(page, predicate, description, timeoutMs = 60000, stable = 2) {
  const started = performance.now(); let passes = 0; let lastText = ''; let frame;
  while (performance.now() - started < timeoutMs) {
    try {
      frame = await appFrame(page, 'Climate Analyzer', 5000); lastText = await bodyText(frame);
      if (predicate(lastText)) { passes += 1; if (passes >= stable) return { frame, text: lastText }; } else passes = 0;
    } catch { passes = 0; }
    await sleep(400);
  }
  throw new Error(`Timed out waiting for ${description}; resource=${lastText.match(/Selected resource:[^\n]*/)?.[0] || 'none'}`);
}

async function expandMonthly(frame) {
  const x = frame.getByText(MONTHLY_CONTEXT, { exact: true }).last();
  if (await x.count().catch(() => 0)) { await x.click({ force: true, timeout: 10000 }).catch(() => {}); await sleep(350); }
}

const report = { schema: 'climate-analyzer-pr83-source-ui-smoke-v18', target_url: TARGET_URL, fixture, checks: {}, page_errors: [], console_errors: [], success: false, error: null };
let browser;
try {
  if (!fixture.success) throw new Error('Monthly provider fixture is not successful.');
  browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: 'en-US' });
  const page = await context.newPage();
  page.on('pageerror', (e) => report.page_errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') report.console_errors.push(m.text()); });
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });

  await chooseSource(page);
  await selectDataset(page, '1 month', 'klima-v2-1m');
  await selectExactStation(page, fixture.station_name, fixture.station_id);
  const monthly = await waitBody(page, (t) => t.includes('Selected resource: klima-v2-1m') && t.includes('Parameter set') && t.includes(MONTHLY_CONTEXT), 'monthly source UI');
  await expandMonthly(monthly.frame);
  const mx = await waitBody(page, (t) => t.includes('Core variables') && t.includes('Core + additional statistics') && t.includes('All provider parameters') && occurrences(t, MONTHLY_CONTEXT) === 1 && occurrences(t, MONTHLY_SOURCE) === 1, 'expanded monthly source UI');
  if (mx.text.includes('Parameter catalogue')) throw new Error('Legacy monthly Parameter catalogue is still visible.');
  report.checks.monthly_context_count = occurrences(mx.text, MONTHLY_CONTEXT);
  report.checks.monthly_source_block_count = occurrences(mx.text, MONTHLY_SOURCE);

  await selectDataset(page, '1 h (long-term)', 'klima-v2-1h');
  await selectExactStation(page, fixture.station_name, fixture.station_id);
  const hx = await waitBody(page, (t) => t.includes('Selected resource: klima-v2-1h') && t.includes('Station metadata validity') && occurrences(t, HOURLY_INFO) === 1 && occurrences(t, HOURLY_SOURCE) === 1, 'hourly source UI', 90000, 3);
  if (hx.text.includes(MONTHLY_CONTEXT) || hx.text.includes('Parameter set')) throw new Error('Monthly-only controls remained visible for hourly resource.');
  report.checks.hourly_context_count = occurrences(hx.text, HOURLY_INFO);
  report.checks.hourly_source_block_count = occurrences(hx.text, HOURLY_SOURCE);

  if (report.page_errors.length) throw new Error(`Browser page error(s): ${report.page_errors.join(' | ')}`);
  report.success = true;
  await fs.mkdir('artifacts/pr83-contract-smoke', { recursive: true });
  await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  report.error = String(error?.stack || error);
  await fs.mkdir('artifacts/pr83-contract-smoke', { recursive: true });
  await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2));
  console.error(report.error); process.exitCode = 1;
} finally { if (browser) await browser.close().catch(() => {}); }
