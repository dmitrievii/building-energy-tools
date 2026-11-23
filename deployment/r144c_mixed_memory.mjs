// R14.4B5/B6: real browser mixed source memory qualification.
// Performance run intentionally excludes scientific parity serialization.
import { chromium } from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
const output=process.env.R144C_OUTPUT;
if(!output)throw Error('R144C_OUTPUT required');
const target=process.env.TARGET_URL||'http://127.0.0.1:8513/';
const fixture=process.env.GEOSPHERE_SMOKE_FIXTURE;
if(!fixture)throw Error('GEOSPHERE_SMOKE_FIXTURE required');
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
const cycles=Number(process.env.R144C_CYCLES||6);
const arena=process.env.MALLOC_ARENA_MAX==='2'?2:null;
const epw=await fs.readFile('research/ige_cmip6/at_graz2021_point_original_output_20261102.epw');
const samples=[];let previous=null,minimumCloses=0,error=null;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function opened(ctx){
 const p=await ctx.newPage();await p.goto(target,{waitUntil:'domcontentloaded'});
 await p.getByRole('heading',{name:'Upload an EPW weather file'}).waitFor({timeout:90000});
 return p;
}
async function settle(p){
 await p.waitForTimeout(350);
 await p.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden',timeout:90000});
 if(await p.getByTestId('stException').count())throw Error('App exception: '+await p.getByTestId('stException').first().innerText());
 if(await p.getByTestId('stAlert').filter({has:p.locator('[data-testid="stException"]')}).count())throw Error('Application exception');
}
async function snapshot(p,name){
 const side=p.getByTestId('stSidebar');
 const inspect=p.getByRole('button',{name:'Inspect retained resources (refresh snapshot)'});
 if(!await inspect.isVisible())await side.getByText('Memory management',{exact:true}).click();
 const caption=p.getByText(/^Snapshot captured:/);
 const old=await caption.count()?await caption.first().innerText():'';
 await inspect.click();
 await p.waitForFunction(previous=>Array.from(document.querySelectorAll('[data-testid="stCaptionContainer"]')).some(e=>e.innerText.startsWith('Snapshot captured:')&&e.innerText!==previous),old,{timeout:60000});
 const [download]=await Promise.all([p.waitForEvent('download'),p.getByRole('button',{name:'Download memory inventory JSON'}).click()]);
 const file=path.join(output,name+'.json');await download.saveAs(file);
 const v=JSON.parse(await fs.readFile(file,'utf8'));
 if(v.snapshot_schema!=='MEM-PERF-R13-HF2')throw Error('Unexpected inventory schema');
 if(v.allocator?.status!=='sampled'||v.allocator.arena_max_exec_env!==arena||v.allocator.arena_tunable_exec!==null)throw Error('Wrong allocator startup evidence '+JSON.stringify(v.allocator));
 return v;
}
async function report(p){
 const count=p.getByText(/^Report: \d+ saved diagram\(s\)\.$/).first();
 const n=Number((await count.innerText()).match(/\d+/)[0]);
 await p.getByRole('button',{name:'Add to report',exact:true}).first().click();
 await settle(p);
 await p.waitForFunction(n=>Array.from(document.querySelectorAll('[data-testid="stCaptionContainer"]')).some(e=>{
  const m=e.innerText.match(/^Report: (\d+) saved diagram\(s\)\.$/);return m&&Number(m[1])===n+1;
 }),n,{timeout:30000});
}
async function epwRun(i){
 const ctx=await browser.newContext({acceptDownloads:true});
 try{
  const p=await opened(ctx);
  await p.getByTestId('stFileUploader').filter({hasText:'Choose EPW file'}).locator('input[type=file]').setInputFiles({name:'graz.epw',mimeType:'application/octet-stream',buffer:epw});
  await p.getByRole('button',{name:'Analyze this EPW'}).click({timeout:90000});
  for(const label of ['Climate — Temperature','Climate — Wind','Climate — Solar radiation']){
   await p.getByTestId('stSidebar').getByText(label,{exact:true}).click();
   await p.getByTestId('stPlotlyChart').first().waitFor({timeout:90000});
   await settle(p);await report(p);
  }
  const active=await snapshot(p,'cycle-'+i+'-epw-active');
  if(!active.session_resources.some(r=>r.resource==='active_climate_file'))throw Error('EPW activation not observed');
  if(!active.epw_lifecycle?.alive?.['active EPW payload'])throw Error('Missing EPW weak reference');
  return active;
 }finally{await ctx.close();}
}
function geoRun(i){
 const dest=path.join(output,'geo-'+i);
 return new Promise((resolve,reject)=>{
  // Reuse provider-validated existing UI test, not injected data or hidden routes.
  const child=spawn(process.execPath,['deployment/pr83_precip_snow_live_smoke.mjs'],{stdio:'inherit',env:{...process.env,TARGET_URL:target,GEOSPHERE_SMOKE_FIXTURE:fixture,AUDIT_OUTPUT_DIR:dest}});
  child.on('error',reject);child.on('exit',code=>code===0?resolve():reject(Error('GeoSphere browser exit '+code)));
 });
}
async function idle(i,kind){
 // Browser contexts are closed before observer attaches. The stored recovery
 // sample must belong to a new zero-session state, not the observer itself.
 await pause(3500);
 const ctx=await browser.newContext({acceptDownloads:true});
 try{
  const p=await opened(ctx);
  for(let attempt=0;attempt<10;attempt++){
   const v=await snapshot(p,'cycle-'+i+'-'+kind+'-observer-'+attempt);
   const r=v.session_runtime.session_reaper;
   const idle=r.last_idle_server_sample;
   if(idle&&idle.captured_at_utc!==previous&&idle.active_sessions===0&&idle.native_closes>minimumCloses){
    if(idle.session_caches.owners!==0||idle.session_caches.entries!==0||idle.closed_session_refs_alive!==0||Object.values(idle.epw_lifecycle?.alive||{}).some(n=>n>0))throw Error('Retained session ownership at idle '+JSON.stringify(idle));
    if(!Number.isFinite(idle.memory.process_anon)||idle.allocator?.arena_max_exec_env!==arena)throw Error('Missing idle/startup evidence');
    if(kind==='geo'&&(!idle.epw_lifecycle?.observations?.['active canonical dataset']||!idle.epw_lifecycle?.observations?.['active canonical source frame']))throw Error('No canonical dataset tracking evidence');
    if(kind==='geo'&&(idle.epw_lifecycle.observations['active canonical dataset']||0)<= (samples.at(-1)?.idle.epw_lifecycle?.observations?.['active canonical dataset']||0))throw Error('No new canonical dataset activation');
    previous=idle.captured_at_utc;minimumCloses=r.native_closes||idle.native_closes;
    samples.push({cycle:i,kind,idle});
    console.log('MIXED_IDLE',i,kind,idle.memory.process_anon,JSON.stringify(idle.epw_lifecycle?.alive||{}));
    return;
   }
   await pause(1200);
  }
  throw Error('No fresh zero-session recovery sample for '+kind);
 }finally{await ctx.close();}
}
try{
 await fs.mkdir(output,{recursive:true});
 for(let i=1;i<=cycles;i++){
  // The pair alternates order to reduce source-order confounding.
  for(const kind of i%2?['epw','geo']:['geo','epw']){
   if(kind==='epw')await epwRun(i);else await geoRun(i);
   await idle(i,kind);
  }
 }
}catch(e){error=String(e);console.error(error);}
finally{
 await browser.close();
 await fs.writeFile(path.join(output,'mixed.json'),JSON.stringify({schema:'R144C-MIXED',cycles,arena,samples,error},null,2));
}
if(error||samples.length!==cycles*2)process.exit(1);
