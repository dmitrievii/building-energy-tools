// R2.19 HF2: the analysis groups are server-owned buttons, independent of
// the lifecycle of the browser's native details elements. Data filters still
// use a regular expander. A public-site smoke can explicitly admit the old
// flat navigation while deployment catches up; candidate tests cannot.
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
export async function expandSidebar(frame,group) {
  const sidebar=frame.locator('section[data-testid="stSidebar"]');
  const summary=sidebar.locator('summary').filter({
    has:frame.getByText(group,{exact:true})
  }).first();
  await summary.waitFor({state:'visible',timeout:15000});
  const details=summary.locator('..');
  for(let i=0;i<5;i++){
    if(!await details.evaluate(el=>el.open))await summary.click({timeout:10000});
    await pause(350);
    if(await details.evaluate(el=>el.open))return details;
  }
  throw new Error('Sidebar expander did not remain open: '+group);
}
export async function clickGroupedNavigation(frame,oldLabel) {
  const [group,short]=oldLabel.split(' — ');
  const sidebar=frame.locator('section[data-testid="stSidebar"]');
  const groups=['Climate','Design','Explore'];
  const name=group==='Start'?'Climate source':group==='Summary'?'Overview':group==='Compare'?'Compare Climates':group==='Data'?'Data Quality':group==='Report'?'Report':short||group;
  if(process.env.R219_ALLOW_LEGACY_NAV==='1'){
    const legacy=sidebar.locator('label').filter({has:frame.getByText(oldLabel,{exact:true})}).first();
    if(await legacy.isVisible().catch(()=>false)){
      await legacy.click({timeout:15000});
      return 'legacy-flat';
    }
  }
  if(groups.includes(group)){
    const target=sidebar.locator('label').filter({has:frame.getByText(name,{exact:true})}).first();
    const closed=sidebar.getByRole('button',{name:group+' ▸',exact:true});
    const opened=sidebar.getByRole('button',{name:group+' ▾',exact:true});
    await sidebar.getByRole('button',{name:new RegExp('^'+group+' [▾▸]$')}).waitFor({state:'visible',timeout:30000});
    if(await closed.isVisible()){
      await closed.click({timeout:15000});
      await opened.waitFor({state:'visible',timeout:60000});
    }
    await target.waitFor({state:'visible',timeout:60000});
    await target.click({timeout:30000});
    // Native radio selection must commit; a group cannot silently close.
    await target.locator('input').waitFor({state:'attached',timeout:15000});
    for(let i=0;i<120;i++){
      if(await target.locator('input').isChecked().catch(()=>false)){
        await pause(300);
        if(await opened.isVisible().catch(()=>false)&&await target.locator('input').isChecked().catch(()=>false))return 'r219-server-groups';
      }
      await pause(250);
    }
    throw new Error('Grouped navigation did not commit: '+oldLabel);
  }
  await sidebar.getByRole('button',{name,exact:true}).first().click({timeout:15000});
  return 'r219-server-groups';
}
