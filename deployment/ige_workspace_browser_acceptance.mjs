// Software acceptance test against the local offline harness, never a live
// production-data substitute. Actual widgets, solvers and HTTP downloads run.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright-core');
const URL = process.env.TARGET_URL;
const OUT = process.env.IGE_VISUAL_OUT;
if (!URL || !OUT || !process.env.CHROME_PATH) throw new Error('Explicit local target/output/browser required');
await fs.mkdir(path.join(OUT, 'downloads'), { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const uploadResponses = [];
page.on('response', r=>{if(r.url().includes('_stcore/upload_file'))uploadResponses.push({upload_response_status:r.status()});});
const evidence = { schema: 'IGE_WORKSPACE_BROWSER_ACCEPTANCE_v1', base_commit: 'b4647b232439faf8c04c86cadfde14962d2cb62f',
  browser: browser.version(), fixture_mode: 'ORIGINAL_SOURCE_OFFLINE_ACQUISITION_ONLY', screenshots: [], downloads: [], checks: [],
  independent_accuracy_qualified: false, actual_public_deployment_verified: false };
function note(check) { evidence.checks.push(check); console.log('PASS '+check); }
async function settle(p = page) {
  await p.waitForTimeout(200); // allow the submitted widget event to reach the WebSocket
  await p.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').waitFor({ timeout: 90000 });
  assert.equal(await p.getByTestId('stException').count(), 0, 'No Streamlit exception');
}
async function select(label, value, p = page) {
  const widget = p.getByTestId('stSelectbox').filter({ has: p.getByText(label, { exact: true }) });
  if (await widget.getByRole('combobox').inputValue() === value) return;
  await widget.getByRole('combobox').click();
  await widget.getByRole('combobox').press('ArrowDown');
  await p.getByRole('option').filter({ hasText: value }).click(); await settle(p);
}
async function number(label, value) {
  const field = page.getByLabel(label, { exact: true });
  await field.fill(String(value)); await field.press('Enter'); await settle();
  assert.equal(Number(await field.inputValue()), value, 'Numeric edit retained: '+label);
}
async function shot(name, p = page) {
  await settle(p);
  const width = await p.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
  assert.ok(width.document <= width.viewport+1, 'No document horizontal overflow: '+JSON.stringify(width));
  await p.screenshot({ path: path.join(OUT, name+'.png') });
  await fs.writeFile(path.join(OUT, name+'.txt'), await p.locator('body').innerText());
  evidence.screenshots.push({ file: name+'.png', ...width });
}
async function download(label, save, p = page) {
  const ready = p.waitForEvent('download', { timeout: 30000 });
  await p.getByRole('button', { name: label, exact: true }).click();
  const file = await ready; assert.equal(await file.failure(), null);
  await file.saveAs(path.join(OUT, 'downloads', save));
  const raw = await fs.readFile(path.join(OUT, 'downloads', save)); assert.ok(raw.length > 100);
  evidence.downloads.push({ button: label, file: 'downloads/'+save, bytes: raw.length,
    sha256: createHash('sha256').update(raw).digest('hex') });
  await settle(p);
}
try {
  await page.goto(URL);
  await page.getByText('Generate climate', { exact: true }).click(); await settle();
  await page.getByRole('heading', { name: 'Generate a climate year', exact: true }).waitFor();
  await shot('01-background-map-desktop'); note('Actual public generation router and linked map render');
  await page.setViewportSize({ width: 412, height: 915 }); await shot('02-background-map-mobile');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByText('Station / EPW interpolation', { exact: true }).click(); await settle();
  await number('Latitude [°]', 47.0707); await number('Longitude [°]', 15.4395);
  assert.equal(Number(await page.getByLabel('Site elevation [m]', {exact:true}).inputValue()),363.0);
  assert.equal(await page.getByLabel('Elevation source / vertical datum', {exact:true}).count(),0);
  await number('Site elevation [m]',375.0);
  note('Original terrain lookup fills 363 m at Graz; manual override works without a datum field');
  await select('Interpolation inputs', 'Upload synchronous actual-year EPWs');
  await page.getByLabel('Point label', { exact: true }).fill('Graz S1 grid EPW integration');
  await page.getByLabel('Point label', { exact: true }).press('Tab'); await settle();
  await page.getByText(/Use Buck liquid-water moisture/).click(); await settle();
  await page.getByText(/Use published station/).click(); await settle();
  await page.getByText(/These are synchronous actual-year/).click(); await settle();
  await page.getByText(/Add ERA5-derived/).click(); await settle();
  await page.locator('input[type=file]').setInputFiles([0,1,2,3].map(i=>path.join(OUT,'inputs',`donor_0${i}.epw`)));
  await settle();
  const build = page.getByRole('button', { name: 'Check donors and interpolate year', exact: true });
  await build.and(page.locator(':enabled')).waitFor({ timeout: 60000 });
  assert.ok(await build.isEnabled()); await build.click();
  await page.getByText('Complete mixed-source research EPW passed the existing format and bounds screen.', { exact: true }).waitFor({ timeout: 90000 });
  await page.getByRole('heading', { name: 'Point-year result', exact: true }).scrollIntoViewIfNeeded();
  await shot('03-s1-complete-result-desktop');
  await download('Download interpolated research EPW', 's1-point.epw');
  await download('Download point year, sources and correction ledgers', 's1-point.zip');
  note('Four original donor EPWs build 8760-hour S1 through actual widgets; EPW and source ZIP download');
  await page.getByText('Future climate from selected base', { exact: true }).click(); await settle();
  const baseBox = page.getByTestId('stSelectbox').filter({ has: page.getByText('Selected annual base', { exact: true }) });
  await baseBox.getByRole('combobox').click();
  await page.getByRole('option', { name: /Interpolated point/ }).click(); await settle();
  await page.getByText('A compatible local reference EPW is required.', { exact: true }).waitFor();
  await settle();
  assert.equal(await page.getByRole('button', { name: 'Build future climate from this base', exact: true }).isEnabled(), false);
  await shot('04-f1-s1-missing-reference-blocked'); note('S1 actual-year base cannot bypass local reference requirement');
  await baseBox.getByRole('combobox').click();
  await page.getByRole('option', { name: /Grid background/ }).click(); await settle();
  await page.getByText('Selected base: 47.00000°, 15.50000° · 467 m · 8,760 hours', { exact: true }).waitFor();
  await settle();
  await select('Local climate reference', 'Same-chain multi-year background reference');
  await page.getByRole('heading', { name: 'Future climate from a selected base', exact: true }).scrollIntoViewIfNeeded();
  await shot('05-f1-selected-base-form-desktop');
  await page.setViewportSize({ width: 412, height: 915 }); await shot('06-f1-selected-base-form-mobile');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: 'Build future climate from this base', exact: true }).click();
  await page.getByText('8,760 hourly records; full future research year verified', { exact: true }).waitFor({ timeout: 90000 });
  await page.getByRole('button', { name: 'Download EPW', exact: true }).scrollIntoViewIfNeeded();
  await shot('07-f1-complete-result-and-downloads');
  await download('Download EPW', 'f1-future.epw');
  await download('Download data and report ZIP', 'f1-future.zip');
  await download('Download quality report', 'f1-quality.json');
  await download('Download hourly CSV (gzip)', 'f1-hourly.csv.gz');
  await download('Download all hourly adjustments', 'f1-adjustments.csv.gz');
  note('F1 actual Build runs reference/source admission and monthly solvers; five HTTP downloads complete');
  await page.getByRole('button', { name: 'Explore this future climate', exact: true }).click();
  await page.getByRole('heading', { name: 'EPW Climate Analyzer', exact: true }).waitFor({ timeout: 60000 });
  await settle();
  note('Future Explore opens the established overview and statistics panels');
  await shot('08-f1-overview-desktop');
  await page.setViewportSize({ width: 412, height: 915 }); await shot('09-f1-overview-mobile');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByText('Climate — Temperature', {exact:true}).click(); await settle();
  await page.getByRole('heading',{name:'Temperature and extremes',exact:true}).waitFor();
  await shot('10-canonical-temperature');
  await page.getByText('Climate — Moisture & psychrometrics', {exact:true}).click(); await settle();
  await select('Analysis type','Psychrometric chart');
  await page.getByText('Points',{exact:true}).waitFor();
  await page.getByTestId('stPlotlyChart').last().scrollIntoViewIfNeeded();
  await shot('11-canonical-psychrometric-points');
  await page.getByText('Distribution grid',{exact:true}).click(); await settle();
  await page.getByTestId('stPlotlyChart').last().scrollIntoViewIfNeeded();
  await shot('12-canonical-psychrometric-grid');
  await page.getByText('Climate contour',{exact:true}).click(); await settle();
  await page.getByTestId('stPlotlyChart').last().scrollIntoViewIfNeeded();
  await shot('13-canonical-psychrometric-contour');
  note('Established temperature panel and all three psychrometric representations render without an exception');
  const h1page = await context.newPage(); await h1page.goto(URL+'?visual=h1');
  await h1page.getByLabel('Station calendar year', { exact: true }).fill('2023');
  await h1page.getByLabel('Station calendar year', { exact: true }).press('Enter'); await settle(h1page);
  await h1page.getByRole('button', { name: 'Load station year and check EPW', exact: true }).click();
  await h1page.getByText('A complete EPW cannot be formed under this input contract. The table and gap ledger identify the missing data, QC and definition constraints.', { exact: true }).waitFor({ timeout: 60000 });
  assert.equal(await h1page.getByRole('button', { name: 'Download station-year EPW', exact: true }).count(), 0);
  await shot('10-h1-real-source-blocked-year', h1page);
  await download('Download station-year data and admission ZIP', 'h1-admission.zip', h1page);
  await download('Download station-year admission JSON', 'h1-admission.json', h1page);
  await download('Download missing-hour ledger (CSV gzip)', 'h1-gaps.csv.gz', h1page);
  note('H1 real source correctly refuses incomplete EPW and downloads all admission/gap evidence');
  evidence.status = 'PASS';
} catch (error) {
  evidence.status = 'FAIL'; evidence.error = String(error.stack ?? error);
  evidence.upload_responses = uploadResponses;
  evidence.visible_options = await page.getByRole('option').allTextContents();
  await page.screenshot({ path: path.join(OUT, 'failure.png'), fullPage: true }).catch(()=>{});
  await fs.writeFile(path.join(OUT, 'failure-dom.txt'), await page.locator('body').innerText().catch(()=>''));
  await fs.writeFile(path.join(OUT, 'failure-inputs.json'), JSON.stringify(await page.locator('input').evaluateAll(inputs=>inputs.map(x=>({type:x.type,label:x.getAttribute('aria-label'),value:x.value,checked:x.checked}))),null,2));
  throw error;
} finally {
  await fs.writeFile(path.join(OUT, 'browser-acceptance.json'), JSON.stringify(evidence, null, 2)+'\n');
  await browser.close();
}
