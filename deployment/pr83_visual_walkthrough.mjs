import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const TARGET_URL = process.env.TARGET_URL || 'http://127.0.0.1:8501/';
const FIXTURE_PATH = process.env.PR83_MONTHLY_FIXTURE || 'artifacts/pr83-contract-smoke/monthly-provider.json';
const OUT_DIR = process.env.PR83_VISUAL_DIR || 'artifacts/pr83-visual-walkthrough';
const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const fixture = JSON.parse(await fs.readFile(FIXTURE_PATH, 'utf8'));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const REQUIRED_PROVIDERS = ['tl_mittel','tlmin','tlmax','rf_mittel','p','tp_mittel','tb10_mittel'];

await fs.mkdir(OUT_DIR, { recursive: true });

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
    for (const c of [frame.getByRole('combobox', { name: label, exact: true }).first(), frame.getByLabel(label, { exact: true }).first()]) {
      if (await c.count().catch(() => 0) && await c.isVisible().catch(() => false)) return c;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for combobox: ${label}`);
}
async function labelledInput(frame, label, timeoutMs = 60000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    for (const c of [frame.getByLabel(label, { exact: true }).first(), frame.locator(`input[aria-label="${label}"]`).first()]) {
      if (await c.count().catch(() => 0) && await c.isVisible().catch(() => false)) return c;
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for input: ${label}`);
}
async function rendered(control) {
  return [await control.innerText().catch(() => ''), await control.textContent().catch(() => ''), await control.inputValue().catch(() => '')].join(' ').replace(/\s+/g, ' ').trim();
}
async function visibleOption(page, frame, predicate) {
  for (const options of [frame.getByRole('option'), page.getByRole('option'), frame.locator('[data-baseweb="menu"] li'), page.locator('[data-baseweb="menu"] li')]) {
    const count = await options.count().catch(() => 0);
    for (let i=0;i<count;i++) {
      const option=options.nth(i); if (!(await option.isVisible().catch(() => false))) continue;
      const text=(await option.innerText().catch(()=>'')).replace(/\s+/g,' ').trim();
      if (predicate(text)) return option;
    }
  }
  return null;
}
async function chooseSource(page) {
  const started=performance.now();
  while (performance.now()-started<60000) {
    const frame=await appFrame(page,'Climate Analyzer',10000);
    for (const c of [frame.getByRole('radio',{name:'GeoSphere Austria',exact:true}).last(),frame.getByText('GeoSphere Austria',{exact:true}).last(),frame.locator('label').filter({hasText:'GeoSphere Austria'}).last()]) {
      if (!(await c.count().catch(()=>0))) continue;
      try { await c.click({force:true,timeout:5000}); return await appFrame(page,'GeoSphere Austria — measured historical station data',15000); } catch {}
    }
    await sleep(400);
  }
  throw new Error('Could not select GeoSphere Austria source.');
}
async function selectComboContains(page,label,needle,timeoutMs=60000) {
  const started=performance.now(); let last=[];
  while (performance.now()-started<timeoutMs) {
    const frame=await appFrame(page,'Climate Analyzer',5000); const control=await combo(frame,label,5000);
    if ((await rendered(control)).includes(needle)) return frame;
    await control.click({timeout:5000}).catch(()=>{});
    const optionStarted=performance.now();
    while (performance.now()-optionStarted<6000) {
      const option=await visibleOption(page,frame,(t)=>t.includes(needle));
      if (option) { await option.click({timeout:8000}); return await appFrame(page,'Climate Analyzer',10000); }
      await sleep(200);
    }
    await page.keyboard.press('Escape').catch(()=>{}); await sleep(300);
  }
  throw new Error(`Could not select ${label}: ${needle}; last=${last.join('|')}`);
}
async function selectDataset(page,needle,resourceId) {
  await selectComboContains(page,'GeoSphere dataset',needle);
  const started=performance.now();
  while (performance.now()-started<60000) {
    const frame=await appFrame(page,'Climate Analyzer',5000); const text=await bodyText(frame);
    if ((await rendered(await combo(frame,'GeoSphere dataset',5000))).includes(needle) && text.includes(`Selected resource: ${resourceId}`)) return frame;
    await sleep(300);
  }
  throw new Error(`Dataset did not commit: ${resourceId}`);
}
async function selectExactStation(page,name,id) {
  let frame=await appFrame(page,'Search GeoSphere station',60000); const input=await labelledInput(frame,'Search GeoSphere station');
  await input.fill(String(name),{timeout:15000}); await input.press('Tab').catch(()=>{});
  frame=await appFrame(page,'Manual station selection',60000);
  const control=await combo(frame,'Search-result stations',60000); await control.click({timeout:10000});
  const started=performance.now();
  while (performance.now()-started<30000) {
    const option=await visibleOption(page,frame,(t)=>t.includes(name)&&(t.includes(`ID ${id}`)||t.includes(String(id))));
    if (option) { await option.click({timeout:10000}); break; }
    await sleep(200);
  }
  const settled=performance.now();
  while (performance.now()-settled<30000) {
    frame=await appFrame(page,'Climate Analyzer',5000); const text=await bodyText(frame);
    if (text.includes('Selected station')&&text.includes(name)&&text.includes(String(id))) return frame;
    try { if ((await rendered(await combo(frame,'Search-result stations',3000))).includes(name)) return frame; } catch {}
    await sleep(250);
  }
  throw new Error(`Station did not settle: ${name} ${id}`);
}
async function clickTextChoice(page,text,timeoutMs=60000) {
  const started=performance.now();
  while (performance.now()-started<timeoutMs) {
    const frame=await appFrame(page,'Climate Analyzer',5000);
    for (const c of [frame.getByText(text,{exact:true}).last(),frame.locator('label').filter({hasText:text}).last(),frame.getByRole('radio',{name:text,exact:true}).last()]) {
      if (!(await c.count().catch(()=>0))||!(await c.isVisible().catch(()=>false))) continue;
      try { await c.click({force:true,timeout:5000}); await sleep(500); return await appFrame(page,'Climate Analyzer',10000); } catch {}
    }
    await sleep(250);
  }
  throw new Error(`Choice not found: ${text}`);
}
async function dateControl(frame,label,timeoutMs=60000) {
  const started=performance.now();
  while (performance.now()-started<timeoutMs) {
    const c=frame.getByLabel(label,{exact:true}).first(); if (await c.count().catch(()=>0)&&await c.isVisible().catch(()=>false)) return c;
    const a=frame.locator(`input[aria-label="${label}"]`).first(); if (await a.count().catch(()=>0)&&await a.isVisible().catch(()=>false)) return a;
    await sleep(250);
  }
  throw new Error(`Date control not found: ${label}`);
}
async function setDate(page,label,value) {
  for (let attempt=0;attempt<3;attempt++) {
    const frame=await appFrame(page,'Measured variables to load',30000); const control=await dateControl(frame,label);
    const tag=await control.evaluate(n=>n.tagName.toLowerCase()).catch(()=>'');
    if (tag==='input') { await control.fill(value,{timeout:10000}); await control.press('Enter').catch(()=>{}); await control.press('Tab').catch(()=>{}); }
    else {
      const spins=control.locator('[role="spinbutton"]'); const [y,m,d]=value.split('-').map(Number);
      const desired={year:y,month:m,day:d};
      for (let i=0;i<await spins.count();i++) {
        const s=spins.nth(i); const lab=String(await s.getAttribute('aria-label').catch(()=>'')).toLowerCase();
        const part=lab.includes('year')?'year':lab.includes('month')?'month':lab.includes('day')?'day':null; if(!part) continue;
        await s.click(); await s.press('Control+A').catch(()=>{}); await s.press('Backspace').catch(()=>{}); await page.keyboard.type(String(desired[part]),{delay:40});
      }
      await page.keyboard.press('Tab').catch(()=>{});
    }
    await sleep(900);
    const refreshed=await appFrame(page,'Measured variables to load',30000); const text=await bodyText(refreshed);
    if (text.includes(value.slice(0,4))) return;
  }
  throw new Error(`Date did not settle: ${label} ${value}`);
}
async function editorState(page) {
  const frame=await appFrame(page,'Measured variables to load',30000); const tables=frame.locator('[data-testid="stDataFrame"]');
  if (!(await tables.count())) throw new Error('No DataEditor/DataFrame found.');
  const editor=tables.last(); const canvas=editor.locator('canvas[data-testid="data-grid-canvas"]').first();
  if (!(await canvas.count())) throw new Error('Monthly variable editor canvas not found.');
  return {frame,editor,canvas};
}
async function scrollEditor(editor,fraction) {
  await editor.locator('.dvn-scroller').first().evaluate((node,f)=>{node.scrollTop=Math.max(0,(node.scrollHeight-node.clientHeight)*f);node.dispatchEvent(new Event('scroll',{bubbles:true}));},fraction);
}
async function findProviderRow(page,provider) {
  for (const fraction of [0,0.2,0.4,0.6,0.8,1]) {
    let s=await editorState(page); await scrollEditor(s.editor,fraction); await sleep(500); s=await editorState(page);
    const rows=s.editor.locator('[role="grid"] tr[role="row"]'); const count=await rows.count();
    for(let i=0;i<count;i++) {
      const row=rows.nth(i); const cells=row.locator('[role="gridcell"]'); const texts=[];
      for(let j=0;j<await cells.count();j++) texts.push((await cells.nth(j).textContent().catch(()=>'' )).trim());
      if (!texts.includes(provider)) continue;
      const ariaRowIndex=Number(await row.getAttribute('aria-rowindex')); const load=(texts[0]||'').toLowerCase();
      return {...s,ariaRowIndex,dataIndex:ariaRowIndex-2,load,texts};
    }
  }
  throw new Error(`Provider row not found: ${provider}`);
}
async function toggleProvider(page,provider) {
  let state=await findProviderRow(page,provider); if(state.load==='true') return;
  for(let attempt=0;attempt<3;attempt++) {
    state=await findProviderRow(page,provider); const box=await state.canvas.boundingBox();
    await state.canvas.click({position:{x:Math.min(box.width-10,box.width*0.55),y:Math.min(box.height-10,52)},force:true});
    await state.canvas.focus(); await page.keyboard.press('Control+Home'); await sleep(200);
    for(let i=0;i<state.dataIndex;i++) { await page.keyboard.press('ArrowDown'); await sleep(25); }
    await page.keyboard.press('Space'); await sleep(700);
    const check=await findProviderRow(page,provider); if(check.load==='true') return;
  }
  throw new Error(`Could not enable Load for ${provider}`);
}
async function screenshot(page,name) { await page.screenshot({path:path.join(OUT_DIR,name),fullPage:true}); }
async function nav(page,label,needle) {
  const frame=await appFrame(page,'Climate Analyzer',30000); const target=frame.getByText(label,{exact:true}).last();
  if (!(await target.count().catch(()=>0))) throw new Error(`Navigation item not found: ${label}`);
  await target.click({force:true,timeout:10000}); return await appFrame(page,needle,60000);
}
async function selectAnalysis(page,name) {
  const frame=await appFrame(page,'Analysis type',30000); const control=await combo(frame,'Analysis type',30000); await control.click({timeout:10000});
  const started=performance.now();
  while(performance.now()-started<10000) { const option=await visibleOption(page,frame,t=>t===name); if(option){await option.click({timeout:10000});await sleep(700);return;} await sleep(200); }
  throw new Error(`Analysis option not found: ${name}`);
}

const report={success:false,checks:{},error:null,page_errors:[],console_errors:[]}; let browser; let page;
try {
  browser=await chromium.launch({executablePath:CHROME_PATH,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const context=await browser.newContext({viewport:{width:1440,height:1100},locale:'en-US'}); page=await context.newPage();
  page.on('pageerror',e=>report.page_errors.push(String(e))); page.on('console',m=>{if(m.type()==='error')report.console_errors.push(m.text());});
  await page.goto(TARGET_URL,{waitUntil:'domcontentloaded',timeout:60000}); await chooseSource(page); await selectDataset(page,'1 month','klima-v2-1m'); await selectExactStation(page,fixture.station_name,fixture.station_id);
  await clickTextChoice(page,'All provider parameters');
  await setDate(page,'From date (UTC)','2020-01-01'); await setDate(page,'Through date (UTC)','2025-12-31');
  for (const provider of REQUIRED_PROVIDERS) await toggleProvider(page,provider);
  report.checks.loaded_providers=REQUIRED_PROVIDERS; await screenshot(page,'01-monthly-source-selection.png');
  let frame=await appFrame(page,'Measured variables to load',30000); const load=frame.getByRole('button',{name:'Load measured GeoSphere interval',exact:true}).first(); if(!(await load.count()))throw new Error('Load button missing'); await load.click({timeout:15000});
  await appFrame(page,'Summary — Overview',180000); await nav(page,'Summary — Overview','Climate overview'); await screenshot(page,'02-monthly-overview.png');
  await nav(page,'Climate — Temperature','Temperature and extremes'); await screenshot(page,'03-monthly-temperature.png');
  const tempText=await bodyText(await appFrame(page,'Temperature and extremes',30000)); report.checks.temperature_no_threshold_sliders=!tempText.includes('Heating threshold [°C]')&&!tempText.includes('Cooling threshold [°C]');
  if (tempText.includes('Ground temperature')) { await selectAnalysis(page,'Ground temperature'); await appFrame(page,'Ground temperature',30000); await screenshot(page,'04-monthly-ground-temperature.png'); }
  await nav(page,'Climate — Moisture & psychrometrics','Humidity and psychrometrics'); await selectAnalysis(page,'Psychrometric chart'); await appFrame(page,'Psychrometric axes',30000); await screenshot(page,'05-monthly-psychrometric.png');
  await nav(page,'Explore — Time series & overlay','Time series'); await screenshot(page,'06-monthly-overlay.png');
  if (report.page_errors.length) throw new Error(`Page errors: ${report.page_errors.join(' | ')}`);
  report.success=true;
} catch(error) { report.error=String(error?.stack||error); if(page) await screenshot(page,'99-failure.png').catch(()=>{}); process.exitCode=1; }
finally { await fs.writeFile(path.join(OUT_DIR,'visual-walkthrough.json'),JSON.stringify(report,null,2)); console.log(JSON.stringify(report,null,2)); if(browser) await browser.close().catch(()=>{}); }
