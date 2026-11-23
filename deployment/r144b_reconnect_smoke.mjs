// Real browser: sequential fresh contexts after immediate disconnect.
import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const url=process.env.TARGET_URL||'http://127.0.0.1:8513/';
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
const results=[];
try{
  for(let i=0;i<6;i++){
    const context=await browser.newContext();
    try{
      const page=await context.newPage();
      await page.goto(url,{waitUntil:'domcontentloaded',timeout:30000});
      await page.getByRole('heading',{name:'Upload an EPW weather file'}).waitFor({timeout:45000});
      const marker=page.locator('#climate-analyzer-runtime-build');
      await marker.waitFor({state:'attached',timeout:10000});
      const fingerprint=await marker.getAttribute('data-runtime-build');
      if(!fingerprint||fingerprint.length!==64)throw Error('Absent runtime fingerprint');
      if(results.length&&results[0].fingerprint!==fingerprint)throw Error('Runtime changed');
      if(await page.locator('[data-testid="stException"]').count())throw Error('App exception');
      results.push({cycle:i+1,fingerprint});console.log('Reconnect startup PASS',i+1);
    }finally{await context.close();}
  }
}finally{
  await fs.mkdir('artifacts/r144b-browser',{recursive:true});
  await fs.writeFile('artifacts/r144b-browser/reconnect.json',JSON.stringify(results,null,2));
  await browser.close();
}
