// R2.19 HF1: use the actual native details element. Streamlit inserts
// icon text inside summary; matching its entire text can miss an open group.
export async function expandSidebar(frame,group) {
  const sidebar=frame.locator('section[data-testid="stSidebar"]');
  const summary=sidebar.locator('summary').filter({
    has:frame.getByText(group,{exact:true})
  }).first();
  await summary.waitFor({state:'visible',timeout:15000});
  const details=summary.locator('..');
  if(!await details.evaluate(el=>el.open)) {
    await summary.click({timeout:10000});
  }
  // Await the actual state; never toggle an already expanded group.
  for(let i=0;i<40;i++) {
    if(await details.evaluate(el=>el.open))return details;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw new Error('Sidebar group did not expand: '+group);
}
export async function clickGroupedNavigation(frame,oldLabel) {
  const [group,short]=oldLabel.split(' — ');
  const sidebar=frame.locator('section[data-testid="stSidebar"]');
  const groups=['Climate','Design','Explore'];
  const name=group==='Start'?'Climate source':group==='Summary'?'Overview':group==='Compare'?'Compare Climates':group==='Data'?'Data Quality':group==='Report'?'Report':short||group;
  if(groups.includes(group)) {
    const details=await expandSidebar(frame,group);
    const target=details.locator('label').filter({has:frame.getByText(name,{exact:true})}).first();
    await target.waitFor({state:'visible',timeout:15000});
    await target.click({timeout:15000});
  } else {
    await sidebar.getByRole('button',{name,exact:true}).first().click({timeout:15000});
  }
}
