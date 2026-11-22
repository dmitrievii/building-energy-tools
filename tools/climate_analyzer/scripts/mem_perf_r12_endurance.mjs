import { chromium } from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
const out='artifacts/mem-perf-r12/endurance.json';
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
const url='http://127.0.0.1:8512';
const rows=[],parallel=[];
let error=null;
let reloadPassed=false,resetPassed=false,baseline=null;
const marker=p=>p.getByText(/^Sentinel: [a-f0-9]{32}$/);
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function open(){
 const ctx=await browser.newContext(),p=await ctx.newPage();
 await p.goto(url);
 await marker(p).waitFor({timeout:60000});
 return {ctx,p,identity:await marker(p).innerText(),measurement:0};
}
async function sample(s){
 const n=++s.measurement;
 await s.p.getByRole('button',{name:'Refresh measurement'}).click();
 await s.p.waitForFunction(n=>{
   return Array.from(document.querySelectorAll('[data-testid="stText"]')).some(el=>{
     try{return el.innerText.startsWith('R12:')&&JSON.parse(el.innerText.slice(4)).measurement===n;}catch{return false;}
   });
 },n,{timeout:30000});
 return JSON.parse((await s.p.getByText(/^R12:/).innerText()).slice(4));
}
async function generate(s){
 await s.p.getByRole('button',{name:'Generate test chart'}).click();
 await s.p.locator('[data-testid="stPlotlyChart"]').waitFor({timeout:30000});
 const v=await sample(s);
 if(v.private.reduce((n,r)=>n+r.entries,0)!==1)throw Error('private cache missing');
 return v;
}
async function recover(s,expected,owners){
 const start=performance.now();
 let v;
 do{
   await pause(1200);
   v=await sample(s);
   if((v.reaper.native_closes||0)>=expected && v.reaper.disconnected_sessions===0 &&
      !v.reaper.allocator_recovery_pending && v.aggregate.owners===owners &&
      v.reaper.shutdown_failures===0)return {latency_ms:performance.now()-start,...v};
 }while(performance.now()-start<20000);
 throw Error('Incomplete recovery: '+JSON.stringify({expected,owners,reaper:v?.reaper,aggregate:v?.aggregate}));
}
try{
 const sentinel=await open();
 await generate(sentinel);
 let state=await sample(sentinel);
 if(!state.reaper.disconnect_policy?.includes('native close'))throw Error('No disconnect policy');
 // One full warmup, then explicitly test manual reset and page reload.
 const sampleUser=await open();await generate(sampleUser);
 await Promise.all([
   sampleUser.p.waitForEvent('framenavigated',{predicate:frame=>frame===sampleUser.p.mainFrame(),timeout:60000}),
   sampleUser.p.getByRole('button',{name:'Reset test session'}).click()
 ]);
 await sampleUser.p.waitForFunction(old=>Array.from(document.querySelectorAll('[data-testid="stText"]')).some(e=>/^Sentinel: [a-f0-9]{32}$/.test(e.innerText)&&e.innerText!==old),sampleUser.identity,{timeout:60000});
 await marker(sampleUser.p).waitFor({timeout:60000});
 sampleUser.identity=await marker(sampleUser.p).innerText();sampleUser.measurement=0;
 const reset=await sample(sampleUser);
 if(reset.private.length||reset.aggregate.owners!==1)throw Error('Manual reset not isolated: '+JSON.stringify({private:reset.private,aggregate:reset.aggregate,reaper:reset.reaper}));
 if((reset.reaper.native_resets||0)<1)throw Error('No native reset recorded');
 resetPassed=true;
 const original=sampleUser.identity;
 await generate(sampleUser);
 await sampleUser.p.reload();
 await marker(sampleUser.p).waitFor({timeout:60000});
 sampleUser.identity=await marker(sampleUser.p).innerText();sampleUser.measurement=0;
 if(sampleUser.identity===original)throw Error('Old session restored on reload');
 reloadPassed=true;
 await sampleUser.ctx.close();
 state=await recover(sentinel,(state.reaper.native_closes||0)+3,1);
 // Qualify distinct simultaneous live private owners, plus sentinel.
 for(const n of [1,2,5,10]){
   const before=state.reaper.native_closes||0;
   const users=await Promise.all(Array.from({length:n},()=>open()));
   try{
     await Promise.all(users.map(generate));
     const peak=await sample(sentinel);
     if(peak.aggregate.owners!==n+1||peak.aggregate.entries!==n+1)throw Error('Parallel owner count mismatch');
     if(await marker(sentinel.p).innerText()!==sentinel.identity)throw Error('Sentinel changed');
     await Promise.all(users.map(u=>u.ctx.close()));
     state=await recover(sentinel,before+n,1);
     parallel.push({additional_sessions:n,peak,after:state});
   }finally{await Promise.all(users.map(u=>u.ctx.close()));}
 }
 for(let i=0;i<100;i++){
   const before=state.reaper.native_closes||0;
   const u=await open();
   try{await generate(u);}finally{await u.ctx.close();}
   state=await recover(sentinel,before+1,1);
   if(state.private.length!==1||state.aggregate.entries!==1||await marker(sentinel.p).innerText()!==sentinel.identity)
      throw Error('Active sentinel resources changed at cycle '+(i+1));
   rows.push({cycle:i+1,...state});
 }
 // Recover with no active sessions, then read the recorded zero-session snapshot
 // via a fresh observer (observer allocations do not enter the snapshot).
 const expected=(state.reaper.native_closes||0)+1;
 await sentinel.ctx.close();
 await pause(3000);
 const observer=await open();
 const last=await recover(observer,expected,0);
 baseline=last.reaper.last_idle_server_sample;
 if(!baseline||baseline.session_caches.entries!==0||baseline.session_caches.owners!==0)
     throw Error('No valid zero-session recovered snapshot');
 await observer.ctx.close();
}catch(e){error=String(e);console.error(error);}
finally{
 await browser.close();
 const warm=rows.slice(10).map(x=>x.memory.process_anon).filter(Number.isFinite);
 await fs.mkdir(path.dirname(out),{recursive:true});
 await fs.writeFile(out,JSON.stringify({schema:'MEM-PERF-R12',scope:'Real local connections on representative fixture, not full production app',completed:rows.length,parallel,resetPassed,reloadPassed,baseline,error,
    warmAnonymousRangeBytes:warm.length?Math.max(...warm)-Math.min(...warm):null,
    warmFirstToLastBytes:warm.length?warm.at(-1)-warm[0]:null,rows},null,2));
}
if(error||rows.length!==100||parallel.length!==4||!resetPassed||!reloadPassed)process.exit(1);
