// R2.19 browser navigation. Open collapsed groups explicitly rather than
// relying on labels from the retired flat radio menu.
export async function expandSidebar(frame,group) {
  const sidebar=frame.locator('section[data-testid="stSidebar"]');
  const summary=sidebar.locator('summary').filter({hasText:new RegExp('^'+group+'$')}).first();
  if (await summary.count()) {
    const open=await summary.evaluate(el=>el.closest('details')?.open ?? false);
    if(!open) await summary.click({timeout:10000});
  } else {
    const label=sidebar.getByText(group,{exact:true}).first();
    await label.click({timeout:10000});
  }
}
export async function clickGroupedNavigation(frame,oldLabel) {
  const [group,short]=oldLabel.split(' — ');
  const sidebar=frame.locator('section[data-testid="stSidebar"]');
  const groups=['Climate','Design','Explore'];
  const name=group==='Start'?'Climate source':group==='Summary'?'Overview':group==='Compare'?'Compare Climates':group==='Data'?'Data Quality':group==='Report'?'Report':short||group;
  if(groups.includes(group)) await expandSidebar(frame,group);
  const target=groups.includes(group)?sidebar.getByText(name,{exact:true}).last():sidebar.getByRole('button',{name,exact:true}).first();
  await target.click({timeout:10000});
}
