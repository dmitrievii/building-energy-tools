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
const ROUTES={
  'Start — Climate source':['Climate source','Climate File Source'],
  'Summary — Overview':['Overview','Overview'],
  'Climate — Temperature':['Climate','Temperature'],
  'Climate — Moisture & psychrometrics':['Climate','Humidity and Psychrometrics'],
  'Climate — Solar radiation':['Climate','Solar and Radiation'],
  'Climate — Wind':['Climate','Wind and Ventilation'],
  'Climate — Sky & daylight':['Climate','Sky and Daylight'],
  'Climate — Precipitation & snow':['Climate','Precipitation and Snow'],
  'Explore — Time series & overlay':['Explore','Time Series and Overlay'],
  'Compare — Multiple climates':['Explore','Compare Climates'],
  'Data — Quality & metadata':['Explore','Data Quality'],
  'Design — Natural ventilation':['Design','Natural Ventilation'],
  'Design — Shading analysis':['Design','Shading analysis'],
  'Design — Passive strategies & HVAC':['Design','HVAC and Passive Design'],
  'Design — Outdoor thermal comfort':['Design','Outdoor Thermal Comfort'],
  'Report — Climate assessment':['Report','Report'],
};
const slug=s=>s.replaceAll(' ','_');
export async function clickGroupedNavigation(frame,oldLabel) {
  const sidebar=frame.locator('section[data-testid="stSidebar"]');
  const route=ROUTES[oldLabel];
  if(!route)throw new Error('Unregistered navigation label: '+oldLabel);
  const [group,page]=route;
  const grouped=['Climate','Design','Explore'].includes(group);
  const groupButton=sidebar.locator('.st-key-_r219_group_'+slug(group)+' button');
  const target=sidebar.locator(grouped?'.st-key-_r220_page_'+slug(page)+' button':'.st-key-_r219_nav_'+slug(group)+'_button button');
  if(process.env.R219_ALLOW_LEGACY_NAV==='1'){
    const legacy=sidebar.locator('label').filter({has:frame.getByText(oldLabel,{exact:true})}).first();
    if(await legacy.isVisible().catch(()=>false)){
      await legacy.click({timeout:15000});
      return 'legacy-flat';
    }
    // Previous HF2 deployment remains admissible only in public-site checks.
    const [oldGroup,short]=oldLabel.split(' — ');
    if(grouped&&await groupButton.isVisible().catch(()=>false)&&!(await target.isVisible().catch(()=>false))){
      const text=await groupButton.innerText();
      if(text.trim().endsWith('▸')){
        await groupButton.click({timeout:15000});
        await pause(500);
      }
      const oldRadio=sidebar.locator('label').filter({has:frame.getByText(short,{exact:true})}).first();
      if(await oldRadio.isVisible().catch(()=>false)){
        await oldRadio.click({timeout:15000});
        return 'r219-server-groups';
      }
    }
  }
  if(grouped){
    await groupButton.waitFor({state:'visible',timeout:30000});
    if(!(await target.isVisible().catch(()=>false))&&
        (await groupButton.innerText()).trim().endsWith('▸')){
      await groupButton.click({timeout:15000});
    }
  }
  await target.waitFor({state:'visible',timeout:60000});
  await target.click({timeout:30000});
  for(let i=0;i<120;i++){
    if(await target.getAttribute('data-testid').catch(()=>null)==='stBaseButton-primary'){
      await pause(300);
      if(await target.getAttribute('data-testid').catch(()=>null)==='stBaseButton-primary')return 'r220-icon-tree';
    }
    await pause(250);
  }
  throw new Error('Navigation selection did not commit: '+oldLabel);
}
