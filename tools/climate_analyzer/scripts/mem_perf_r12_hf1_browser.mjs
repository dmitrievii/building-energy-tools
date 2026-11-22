import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import {performance} from 'node:perf_hooks';
const dir='artifacts/mem-perf-r12-hf1';
await fs.mkdir(dir,{recursive:true});
const source=await fs.readFile('../../research/ige_cmip6/at_graz2021_point_original_output_20261102.epw','utf8');
// Two distinct valid payloads: identical weather data, distinct location label.
// This isolates lifetime/cache ownership rather than comparing scientific outputs.
const a=Buffer.from(source);
const b=Buffer.from(source.replace(/^(LOCATION,)[^,\r\n]+/i,'$1HF1-second-source'));
if(a.equals(b))throw Error('Second EPW payload identical');
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
const url='http://127.0.0.1:8513';
const rows=[];
let error=null,completed=0,baseline=null,lastIdle=null,initial=null;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const cycles=Number(process.env.HF1_CYCLES||20);
async function assertNoError(p){
 const err=p.locator('[data-testid="stException"]');
 if(await err.count())throw Error('App exception: '+(await err.first().innerText()).slice(0,500));
}
async function open(ctx){
 const p=await ctx.newPage();
 await p.goto(url);
 await p.getByRole('heading',{name:'Upload an EPW weather file'}).waitFor({timeout:90000});
 await assertNoError(p);
 return p;
}
async function settle(p){
 await p.waitForTimeout(350);
 await p.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden',timeout:60000});
 await assertNoError(p);
}
async function snapshot(p,stage,cycle){
 const summary=p.locator('[data-testid="stSidebar"]').getByText('Memory management',{exact:true});
 const inspect=p.getByRole('button',{name:'Inspect retained resources (refresh snapshot)'});
 if(!(await inspect.isVisible()))await summary.click();
 const ts=p.getByText(/^Snapshot captured:/);
 const previous=await ts.count()?await ts.first().innerText():'';
 await inspect.click();
 await p.waitForFunction(old=>Array.from(document.querySelectorAll('[data-testid="stCaptionContainer"]')).some(e=>e.innerText.startsWith('Snapshot captured:')&&e.innerText!==old),previous,{timeout:60000});
 const download=await Promise.all([p.waitForEvent('download'),p.getByRole('button',{name:'Download memory inventory JSON'}).click()]);
 const filename=path.join(dir,String(cycle).padStart(2,'0')+'_'+stage+'.json');
 await download[0].saveAs(filename);
 const v=JSON.parse(await fs.readFile(filename,'utf8'));
 if(v.snapshot_schema!=='MEM-PERF-R12-HF1')throw Error('Wrong runtime schema');
 rows.push({cycle,stage,memory:v.memory,epw:v.epw_lifecycle,session:v.session_cache_summary,
            reaper:v.session_runtime.session_reaper,processes:v.container_processes,library:v.library_footprint});
 return v;
}
async function nav(p,label){
 await p.locator('[data-testid="stSidebar"]').getByText(label,{exact:true}).click();
 await settle(p);
}
async function upload(p,name,buffer){
 await p.locator('input[type=file]').first().setInputFiles({name,mimeType:'application/octet-stream',buffer});
 await p.getByRole('button',{name:'Analyze this EPW'}).click({timeout:60000});
 await p.locator('[data-testid="stSidebar"]').getByText('Climate — Temperature',{exact:true}).waitFor({timeout:90000});
 await settle(p);
}
async function graph(p,label){
 await nav(p,label);
 await p.locator('[data-testid="stPlotlyChart"]').first().waitFor({timeout:90000});
 await settle(p);
}
async function freshIdle(p,previous,cycle){
 const deadline=performance.now()+20000;
 let value;
 do{
   await pause(1200);
   value=await snapshot(p,'idle-observer',cycle);
   const idle=value.session_runtime.session_reaper.last_idle_server_sample;
   if(idle&&idle.captured_at_utc!==previous&&idle.session_caches.owners===0&&idle.session_caches.entries===0)return idle;
 }while(performance.now()<deadline);
 throw Error('No new zero-session idle sample');
}
try{
 let ctx=await browser.newContext({acceptDownloads:true});
 let p=await open(ctx);
 initial=await snapshot(p,'cold-start',0);
 for(let cycle=1;cycle<=cycles;cycle++){
   await upload(p,'hf1-a.epw',a);
   await snapshot(p,'epw-a',cycle);
   await graph(p,'Climate — Temperature');
   await graph(p,'Climate — Wind');
   await snapshot(p,'graphs-a',cycle);
   await nav(p,'Start — Climate source');
   await p.getByRole('button',{name:'Choose a different climate'}).click();
   await p.getByRole('heading',{name:'Upload an EPW weather file'}).waitFor({timeout:60000});
   await upload(p,'hf1-b.epw',b);
   await snapshot(p,'epw-b',cycle);
   await graph(p,'Climate — Temperature');
   await graph(p,'Climate — Solar radiation');
   const before=await snapshot(p,'graphs-b',cycle);
   const previous=before.session_runtime.session_reaper.last_idle_server_sample?.captured_at_utc;
   await p.reload();
   await p.getByRole('heading',{name:'Upload an EPW weather file'}).waitFor({timeout:90000});
   const reload=await snapshot(p,'reload',cycle);
   if(reload.session_resources.some(r=>r.resource==='active_climate_file'))throw Error('Reload retained EPW');
   await ctx.close();
   // No observer connected during native shutdown and recovery.
   await pause(3000);
   ctx=await browser.newContext({acceptDownloads:true});
   p=await open(ctx);
   lastIdle=await freshIdle(p,previous,cycle);
   if(!baseline)baseline=lastIdle;
   completed++;
 }
 await ctx.close();
}catch(e){error=String(e);console.error(error);}
finally{
 await browser.close();
 const idle=rows.filter(r=>r.stage==='idle-observer').map(r=>r.reaper.last_idle_server_sample).filter(Boolean);
 await fs.writeFile(path.join(dir,'summary.json'),JSON.stringify({schema:'R12-HF1',scope:'Real app.py, two EPW identities, no PDF or UTCI; second EPW changes location label only',completed,cycles,error,baseline,lastIdle,idle,rows},null,2));
}
if(error||completed!==cycles)process.exit(1);
