// Read-only production allocator evidence. Does not set secrets or reload server.
import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const OUT='artifacts/r145a-cloud';
await fs.mkdir(OUT,{recursive:true});
const url='https://building-climate-analyzer.streamlit.app/';
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
const result={schema:'R145A',target:url,classification:'UNAVAILABLE',error:null};
try{
 const ctx=await browser.newContext({acceptDownloads:true});
 const page=await ctx.newPage();
 await page.goto(url,{waitUntil:'domcontentloaded',timeout:60000});
 let frame;
 for(let i=0;i<90&&!frame;i++){
  for(const f of page.frames())if(await f.getByText('Memory management',{exact:true}).count().catch(()=>0)){frame=f;break;}
  if(!frame)await page.waitForTimeout(1000);
 }
 if(!frame)throw Error('No public application memory UI');
 const marker=frame.locator('#climate-analyzer-runtime-build');
 result.runtime_build=await marker.getAttribute('data-runtime-build',{timeout:10000});
 const expected=process.env.EXPECTED_RUNTIME_BUILD;
 if(!expected||result.runtime_build!==expected)throw Error('Deployed runtime fingerprint differs from tested source');
 const inspect=frame.getByRole('button',{name:'Inspect retained resources (refresh snapshot)'});
 if(!await inspect.isVisible())await frame.getByText('Memory management',{exact:true}).click();
 await inspect.click();
 const downloadButton=frame.getByRole('button',{name:'Download memory inventory JSON'});
 await downloadButton.waitFor({timeout:90000});
 const [download]=await Promise.all([page.waitForEvent('download'),downloadButton.click()]);
 const file=OUT+'/inventory.json';await download.saveAs(file);
 const v=JSON.parse(await fs.readFile(file,'utf8'));
 const a=v.allocator;
 if(!a||!Object.hasOwn(a,'arena_max_exec_env')||!Object.hasOwn(a,'arena_tunable_exec'))throw Error('Cloud allocator startup evidence unavailable');
 result.allocator={status:a.status,arena_max_env:a.arena_max_env,arena_max_exec_env:a.arena_max_exec_env,arena_tunable_exec:a.arena_tunable_exec,arena_setting_origin:a.arena_setting_origin};
 result.memory=v.memory;
 result.classification=a.status==='sampled'&&a.arena_max_exec_env===2&&a.arena_tunable_exec===null?'A2_EXEC_REQUEST_OBSERVED':'A2_EXEC_REQUEST_NOT_VERIFIED';
 // Do not imply that exec environment alone establishes actual arena count.
 await ctx.close();
}catch(e){result.error=String(e);}
finally{await browser.close();await fs.writeFile(OUT+'/classification.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));}
if(result.classification!=='A2_EXEC_REQUEST_OBSERVED')process.exit(1);
