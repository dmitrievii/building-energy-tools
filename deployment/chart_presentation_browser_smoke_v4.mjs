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
  await frame.getByText('Appearance', { exact: true }).first().click({ timeout: 10000 });
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

  // Exercise the actual exported PNG alpha channel, not just CSS or layout.
  async function chooseBackground(index) {
    const f=await openPresentation(page);
    await f.getByRole('combobox',{name:'Chart background',exact:true}).click();
    await page.keyboard.press('Home');
    if(index===1) await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await waitForCharts(page);
    await page.waitForFunction(transparent=>[...document.querySelectorAll('.js-plotly-plot')].every(
      node=>{
        const c=document.createElement('canvas');c.width=c.height=1;
        const ctx=c.getContext('2d');ctx.fillStyle=node._fullLayout?.paper_bgcolor||'black';
        ctx.fillRect(0,0,1,1);const px=ctx.getImageData(0,0,1,1).data;
        return transparent?px[3]===0:(px[3]===255&&px[0]===255&&px[1]===255&&px[2]===255);
      }),
      index===1);
  }
  async function exportAlpha(chartIndex) {
    const f=await waitForCharts(page);
    const plot=f.locator('.js-plotly-plot').nth(chartIndex);
    await plot.hover();
    const pending=page.waitForEvent('download',{timeout:30000});
    await plot.locator('.modebar-btn[data-title*="Download plot"]').first().click();
    const download=await pending;
    const file=await download.path();
    const png=await fs.readFile(file);
    return await page.evaluate(async data=>{
      const im=new Image();
      im.src='data:image/png;base64,'+data;
      await im.decode();
      const canvas=document.createElement('canvas');
      canvas.width=im.width;canvas.height=im.height;
      const ctx=canvas.getContext('2d');
      ctx.drawImage(im,0,0);
      const pixels=ctx.getImageData(0,0,im.width,im.height).data;
      let clear=0,opaque=0;
      for(let i=3;i<pixels.length;i+=4){if(pixels[i]===0)clear++;if(pixels[i]===255)opaque++;}
      return {corner:pixels[3],clear,opaque,width:im.width,height:im.height};
    },png.toString('base64'));
  }
  await chooseBackground(1);
  const bgFrame=await waitForCharts(page);
  const backgrounds=await bgFrame.locator('.js-plotly-plot').evaluateAll(nodes=>nodes.map(node=>({
    paper:node._fullLayout.paper_bgcolor,plot:node._fullLayout.plot_bgcolor,
    polar:node._fullLayout.polar?.bgcolor||null
  })));
  const clearColor=v=>String(v).replace(/\s+/g,'')==='rgba(0,0,0,0)'||v==='transparent';
  if(backgrounds.some(x=>!clearColor(x.paper) || (x.polar && !clearColor(x.polar))))
    throw new Error('Global background failed: '+JSON.stringify(backgrounds));
  const transparentLine=await exportAlpha(0);
  const transparentWind=await exportAlpha(3);
  for(const a of [transparentLine,transparentWind]){
    if(a.corner!==0 || a.clear<1000 || a.opaque<100)
      throw new Error('PNG does not preserve both transparent background and foreground: '+JSON.stringify(a));
  }
  await chooseBackground(0);
  const whiteWind=await exportAlpha(3);
  if(whiteWind.corner!==255 || whiteWind.clear!==0)
    throw new Error('White background restoration failed: '+JSON.stringify(whiteWind));
  report.metrics.globalBackground={backgrounds,transparentLine,transparentWind,whiteWind};
  report.checks.globalBackgroundAndPngAlpha=true;

  // A separate harness route exercises the actual monthly chart factory.
  await page.goto(TARGET_URL + '?monthly=1', { waitUntil: 'domcontentloaded' });
  let monthlyFrame = await waitForCharts(page, 1);
  async function monthlySpacing() {
    monthlyFrame = await waitForCharts(page, 1);
    return monthlyFrame.locator('.js-plotly-plot').evaluate(node => {
      const ticks = [...node.querySelectorAll('.xtick text')];
      const title = node.querySelector('.g-xtitle text');
      const legend = node.querySelector('g.legend');
      return {tickBottom: Math.max(...ticks.map(t=>t.getBoundingClientRect().bottom)),
        titleTop:title?.getBoundingClientRect().top, titleBottom:title?.getBoundingClientRect().bottom,
        legendTop:legend?.getBoundingClientRect().top};
    });
  }
  function assertSpacing(s) {
    if (!(s.titleTop >= s.tickBottom-1 && s.legendTop >= s.titleBottom+3))
      throw new Error('Monthly chart axis or legend overlaps: '+JSON.stringify(s));
  }
  const monthlyBar = await monthlySpacing();
  assertSpacing(monthlyBar);
  report.metrics.monthlyBarSpacing=monthlyBar;
  await page.screenshot({path: OUT_DIR+'/07-monthly-bar.png',fullPage:true});
  async function chooseMonthlyStyle(index) {
    monthlyFrame = await waitForCharts(page,1);
    await monthlyFrame.getByRole('combobox',{name:'Chart type',exact:true}).click();
    await page.keyboard.press('Home');
    for (let i=0;i<index;i++) await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await sleep(400);
    await waitForCharts(page,1);
  }
  await chooseMonthlyStyle(1);
  await page.waitForFunction(()=>document.querySelector('.js-plotly-plot')?._fullData?.[0]?.type==='scatter');
  const monthlyLine=await monthlySpacing();
  assertSpacing(monthlyLine);
  report.metrics.monthlyLineSpacing=monthlyLine;
  await chooseMonthlyStyle(2);
  await page.waitForFunction(()=>document.querySelector('.js-plotly-plot')?._fullData?.[0]?.type==='barpolar');
  const rose=await monthlyFrame.locator('.js-plotly-plot').evaluate(node=>({
    sectors: Array.from(node._fullLayout.polar.angularaxis.ticktext),
    radii:node._fullData.map(t=>Array.from(t.r)),
    origins:node._fullData.map(t=>t.base),
    angles:node._fullData.map(t=>Array.from(t.theta)),
    widths:node._fullData.map(t=>t.width),
    opacity:node._fullData.map(t=>t.opacity),
    paths:node.querySelectorAll('.polarlayer .barlayer path').length,
  }));
  if (rose.sectors.length!==12 || rose.radii.length!==3 ||
      rose.radii.some(r=>r.length!==12) || rose.origins.some(b=>b!==0) ||
      rose.angles.some(a=>a.length!==12) || rose.paths!==36)
    throw new Error('Monthly rose geometry invalid: '+JSON.stringify(rose));
  if (rose.angles.some(a=>a.some((v,m)=>Math.abs(v-m*30)>1e-8)) ||
      rose.widths.some(w=>w!==26) || rose.opacity.some(o=>!(o>0 && o<1)))
    throw new Error('Monthly rose traces must overlap at the same month angles: '+JSON.stringify(rose));
  report.metrics.monthlyRose=rose;
  report.checks.monthlyAxisSpacingAndRose=true;
  await page.screenshot({path:OUT_DIR+'/08-monthly-rose.png',fullPage:true});
  monthlyFrame=await waitForCharts(page,1);
  await monthlyFrame.getByRole('combobox',{name:'Rose style',exact:true}).click();
  await page.keyboard.press('Home');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await page.waitForFunction(()=>document.querySelector('.js-plotly-plot')?._fullData?.[0]?.type==='scatterpolar');
  monthlyFrame=await waitForCharts(page,1);
  const lines=await monthlyFrame.locator('.js-plotly-plot').evaluate(node=>({
    sectors:Array.from(node._fullLayout.polar.angularaxis.ticktext),
    traces:node._fullData.map(t=>({type:t.type,r:Array.from(t.r),theta:Array.from(t.theta),
      mode:t.mode,fill:t.fill,connectgaps:t.connectgaps})),
    paths:node.querySelectorAll('.polarlayer .scatterlayer .js-line').length,
  }));
  if (JSON.stringify(lines.sectors)!==JSON.stringify(rose.sectors) ||
      lines.traces.length!==3 || lines.paths<3 ||
      lines.traces.some((t,i)=>t.type!=='scatterpolar' || t.mode!=='lines+markers' ||
        t.fill!=='none' || t.connectgaps!==false || t.theta.length!==13 ||
        t.theta.some((v,m)=>v!==m*30) || t.r.length!==13 ||
        t.r[12]!==t.r[0] || t.r.slice(0,12).some((v,m)=>v!==rose.radii[i][m])))
    throw new Error('Monthly rose lines differ from sector data: '+JSON.stringify(lines));
  report.metrics.monthlyRoseLines=lines;
  report.checks.monthlyRoseLines=true;
  await page.screenshot({path:OUT_DIR+'/09-monthly-rose-lines.png',fullPage:true});

  // Verify actual SVG tick labels, not just Python/Plotly layout metadata.
  await page.goto(TARGET_URL+'?duration=1',{waitUntil:'domcontentloaded'});
  const durationFrame=await waitForCharts(page,4);
  const durationPlots=durationFrame.locator('.js-plotly-plot');
  const tickReports=await durationPlots.evaluateAll(nodes=>nodes.slice(0,3).map(node=>{
    const box=node.getBoundingClientRect();
    return [...node.querySelectorAll('.xtick text')].map(t=>{
      const r=t.getBoundingClientRect();
      return {label:t.textContent,left:r.left>=box.left-1,right:r.right<=box.right+1,
        width:r.width,height:r.height,visibility:getComputedStyle(t).visibility};
    });
  }));
  const expectedTicks=[['0','1000','2000','3000','4000','5000','6000','7000','8000','8760'],
                       ['0','1000','2000','3000','4000','5000','6000','7000','8000','8784'],
                       ['0%','20%','40%','60%','80%','100%']];
  for(let i=0;i<expectedTicks.length;i++){
    const labels=tickReports[i].filter(t=>t.left&&t.right&&t.width>0&&t.height>0&&t.visibility!=='hidden').map(t=>t.label);
    if(expectedTicks[i].some(t=>!labels.includes(t)))
      throw new Error('Duration tick missing or clipped: '+JSON.stringify({expected:expectedTicks[i],actual:tickReports[i]}));
  }
  const amp=await durationPlots.nth(3).evaluate(node=>node._fullData.map(t=>({type:t.type,mode:t.mode})));
  if(!amp.length||amp.some(t=>t.type!=='scatter'||!t.mode.includes('lines')))
    throw new Error('Amplitude is not a line chart: '+JSON.stringify(amp));
  report.metrics.durationEndpoints=tickReports;
  report.checks.durationEndpointsAndAmplitude=true;
  await page.screenshot({path:OUT_DIR+'/10-duration-endpoints.png',fullPage:true});

  await page.goto(TARGET_URL+'?p2=1',{waitUntil:'domcontentloaded'});
  const p2Frame=await waitForCharts(page,6);
  const p2=await p2Frame.locator('.js-plotly-plot').evaluateAll(nodes=>nodes.map(node=>({
    types:node._fullData.map(t=>t.type),patches:node._fullData[0]?.r?.length||0,
    classStack:node._fullLayout.polar?.barmode||null,
    names:node._fullData.map(t=>t.name),
    radialSum:node._fullData.reduce((sum,t)=>sum+(t.type==='barpolar'?Array.from(t.r).reduce((a,b)=>a+Number(b||0),0):0),0),
    images:node.querySelectorAll('.imagelayer image').length,
    imageSource:node._fullLayout.images?.[0]?.source?.slice(0,22)||null,
    scaleStart:node._fullData[0]?.marker?.colorscale?.[0]?.[1]||node._fullData[0]?.colorscale?.[0]?.[1]||null,
    compass:node._fullData.find(t=>t.name==='Compass labels')?.text||null,
    annotationTexts:node._fullLayout.annotations?.map(a=>a.text)||[],
    maskClasses:node._fullData.filter(t=>t.meta?.direct_sun_shading_mask===true).map(t=>t.name)
  })));
  if(p2[0].types.length!==6||p2[0].types.some(t=>t!=='barpolar')||p2[0].classStack!=='stack'||Math.abs(p2[0].radialSum-8)>1e-8||p2[1].patches!==145||p2[2].types[0]!=='mesh3d'||
     p2[3].images<1||p2[3].imageSource!=='data:image/png;base64,')
    throw new Error('P2 chart rendering or underlay incomplete: '+JSON.stringify(p2));
  const white=v=>v==='#FFFFFF'||v==='#ffffff'||v==='rgb(255, 255, 255)'||v==='rgb(255,255,255)';
  if(!white(p2[1].scaleStart)||!white(p2[2].scaleStart)||JSON.stringify(p2[2].compass)!==JSON.stringify(['N','E','S','W'])||
      !p2[4].annotationTexts.includes('D = 0.60 m')||!p2[4].annotationTexts.includes('R = 0.80 m')||
      p2[5].maskClasses.length!==5)
    throw new Error('Shading sketch/mask or sky palette/compass incomplete: '+JSON.stringify(p2));
  report.metrics.p2Visuals=p2;
  report.checks.p2Visuals=true;
  await page.screenshot({path:OUT_DIR+'/11-p2-directional-graphics.png',fullPage:true});

  // Measure rendered label coordinates and row pitch, not just CSS strings.
  await page.goto(TARGET_URL+'?sidebar=1',{waitUntil:'domcontentloaded'});
  const sideFrame=await appFrame(page,'Sidebar geometry harness');
  const sidebar=sideFrame.locator('[data-testid="stSidebar"]');
  const overview=sidebar.locator('.st-key-_r219_nav_Overview_button button');
  try {
    await overview.waitFor({state:'visible'});
  } catch (error) {
    report.metrics.sidebarMountDiagnostic=await sidebar.innerText().catch(()=>'(sidebar unavailable)');
    throw error;
  }
  await page.evaluate(()=>document.fonts.ready);
  await page.mouse.move(900,400);
  const measureSidebar=()=>sidebar.evaluate(root=>{
    const nav=root.querySelector('.st-key-_r220_navigation_tree');
    const rows=[...nav.querySelectorAll('button'),...root.querySelectorAll('[data-testid="stExpander"] summary'),
      ...root.querySelectorAll('.st-key-_r219_service_button button')];
    return rows.filter(r=>r.getBoundingClientRect().height>0).map(r=>{
      const label=r.querySelector('[data-testid="stMarkdownContainer"] p')||r.querySelector('p');
      if(!label)throw new Error('Sidebar label not found: '+r.textContent);
      const b=r.getBoundingClientRect();
      const range=document.createRange();
      range.selectNodeContents(label);
      const p=range.getBoundingClientRect();
      return {text:label.textContent.trim(),x:p.left,top:b.top,height:b.height,
        left:b.left,padding:getComputedStyle(r).paddingLeft};
    }).sort((a,b)=>a.top-b.top);
  });
  const collapsed=await measureSidebar();
  report.metrics.sidebarCollapsed=collapsed;
  const topRows=collapsed.filter(r=>/^(Climate source|Overview|Climate|Explore|Design|Report|Appearance|Architectural background|Export settings|Data filters|Service & Diagnostics)(\s*[▸▾])?$/.test(r.text));
  if(topRows.length!==11) throw new Error('Missing sidebar rows: '+JSON.stringify(collapsed));
  const baseline=topRows[0].x;
  for(const row of topRows) assertNear(row.x,baseline,3,'Main label alignment '+row.text);
  const navPitch=topRows[1].top-topRows[0].top;
  for(let i=1;i<6;i++)assertNear(topRows[i].top-topRows[i-1].top,navPitch,2,'Navigation pitch '+topRows[i].text);
  for(let i=7;i<topRows.length;i++)assertNear(topRows[i].top-topRows[i-1].top,navPitch,3,'Settings pitch '+topRows[i].text);
  report.metrics.sidebarCollapsed=collapsed;
  await page.screenshot({path:OUT_DIR+'/12-sidebar-collapsed.png',fullPage:true});
  await sidebar.locator('.st-key-_r219_group_Design button').click();
  await sidebar.locator('.st-key-_r220_page_Natural_Ventilation button').waitFor({state:'visible'});
  await page.mouse.move(900,400);
  const expanded=await measureSidebar();
  report.metrics.sidebarExpanded=expanded;
  const child=expanded.find(r=>/^Natural Ventilation$/i.test(r.text));
  const parent=expanded.find(r=>/^Design/.test(r.text));
  if(!child||!parent)throw new Error('Missing Design submenu: '+JSON.stringify(expanded));
  const rem=await sideFrame.locator('html').evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
  assertNear(child.x-parent.x,0.7*rem,3,'Intentional submenu indentation');
  report.metrics.sidebarExpanded=expanded;
  report.checks.sidebarGeometry=true;
  await page.screenshot({path:OUT_DIR+'/13-sidebar-expanded.png',fullPage:true});

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
