import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const file=process.env.R14_PROBE_FILE;
const out=process.env.R14_OUTPUT;
const mode=process.env.R14_MODE;
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
const rows=[];
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function read(){
 const v=JSON.parse(await fs.readFile(file,'utf8'));
 if(v.error)throw Error(v.error);
 return v;
}
async function until(pred,timeout=20000){
 const end=Date.now()+timeout;
 let last;
 do{
   try{last=await read();}catch(e){if(e.code!=='ENOENT')throw e;}
   if(last&&pred(last))return last;
   await pause(500);
 }while(Date.now()<end);
 throw Error('Probe timeout: '+JSON.stringify(last));
}
let error=null;
try{
 for(let cycle=1;cycle<=3;cycle++){
   const ctx=await browser.newContext();
   const page=await ctx.newPage();
   await page.goto('http://127.0.0.1:8516');
   await page.getByRole('heading',{name:'R14 lifecycle probe'}).waitFor({timeout:60000});
   const active=await until(v=>v.active_count===1&&v.payloads_alive>=1&&v.full_runs>=cycle);
   const slider=page.getByRole('slider');
   await slider.focus();
   await slider.press('ArrowRight');
   const fragment=await until(v=>v.fragment_runs>active.fragment_runs);
   if(fragment.full_runs!==active.full_runs)throw Error('Fragment caused full run');
   await ctx.close();
   const disconnected=await until(v=>v.active_count===0&&v.sample_ns>fragment.sample_ns);
   // TTL is set to 2 seconds. Keep zero connections while sampling the
   // upstream leak, and do not reconnect merely to fetch measurements.
   await pause(6500);
   const idle=await until(v=>v.active_count===0&&v.sample_ns>disconnected.sample_ns);
   const observation={cycle,active,fragment,disconnected,idle};
   rows.push(observation);
   console.log(JSON.stringify({cycle,mode,idle}));
   if(mode==='close-loop'){
     if(idle.storage_physical_count!==0||idle.sessions.some(s=>s.alive)||idle.payloads_alive!==0||idle.release_calls<cycle)
       throw Error('Mitigation failed: '+JSON.stringify(idle));
   }
 }
}catch(e){error=String(e);console.error(error);}
finally{
 await browser.close();
 await fs.writeFile(out,JSON.stringify({mode,rows,error},null,2));
}
if(error)process.exit(1);
