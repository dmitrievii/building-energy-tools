import { chromium } from 'playwright-core';
import fs from 'node:fs/promises';
const out=process.env.R11_OUTPUT || 'artifacts/mem-perf-r11/endurance.json';
const url='http://127.0.0.1:8511';
const cycles=50;
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
const rows=[];
let error=null;
try {
 const sentinel=await browser.newContext();
 const page=await sentinel.newPage();
 await page.goto(url);
 await page.getByText('Sentinel: preserved',{exact:true}).waitFor({timeout:60000});
 const sample=async()=>{
   await page.getByRole('button',{name:'Refresh measurement'}).click();
   await page.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden',timeout:30000});
   const text=await page.getByText(/^R11:/).innerText();
   return JSON.parse(text.slice(4));
 };
 const initial=await sample();
 for(let i=0;i<cycles;i++){
   const ctx=await browser.newContext();
   const p=await ctx.newPage();
   try {
     await p.goto(url);
     await p.getByRole('checkbox',{name:'Generate test chart'}).check({timeout:30000});
     await p.locator('[data-testid="stPlotlyChart"]').waitFor({timeout:30000});
   } finally {await ctx.close();}
   let observation;
   const deadline=Date.now()+15000;
   // Wait without rerunning the sentinel during the recovery window.
   do{
     await new Promise(r=>setTimeout(r,3000));
     observation=await sample();
     if(observation.reaper.expired_reaped>=initial.reaper.expired_reaped+i+1 &&
        observation.reaper.disconnected_sessions===0 &&
        !observation.reaper.allocator_recovery_pending)break;
   }while(Date.now()<deadline);
   rows.push({cycle:i+1,...observation});
   if(observation.reaper.expired_reaped<initial.reaper.expired_reaped+i+1 ||
      observation.reaper.disconnected_sessions!==0 ||
      observation.reaper.allocator_recovery_pending ||
      observation.reaper.shutdown_failures!==0)throw Error('Session recovery incomplete at cycle '+(i+1));
   await page.getByText('Sentinel: preserved',{exact:true}).waitFor();
 }
 await sentinel.close();
}catch(e){error=String(e);console.error(error);}
finally{
 await browser.close();
 const warm=rows.slice(10).map(x=>x.memory.process_anon).filter(Number.isFinite);
 await fs.mkdir(new URL('.', 'file://'+process.cwd()+'/'+out).pathname,{recursive:true});
 await fs.writeFile(out,JSON.stringify({scope:'Real local browser connections on fixture; accelerated TTL; not full app endurance',cycles,completed:rows.length,error,
   warmAnonymousRangeBytes:warm.length?Math.max(...warm)-Math.min(...warm):null,
   warmFirstToLastBytes:warm.length?warm.at(-1)-warm[0]:null,rows},null,2));
}
if(error||rows.length!==cycles)process.exit(1);
