import fs from 'node:fs/promises';
import { chromium } from 'playwright-core';
const url = process.env.TARGET_URL || 'http://127.0.0.1:8503/';
const dir = 'artifacts/sun-path-smoke';
await fs.mkdir(dir, { recursive: true });
const browser = await chromium.launch({
  executablePath: '/usr/bin/google-chrome', headless: true,
  args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
});
const page = await browser.newPage({viewport: {width: 1680, height: 1200}});
const report = {};
function assert(value, message) { if (!value) throw new Error(message); }
async function readState() {
  return page.locator('.js-plotly-plot').evaluate(node => {
    const groups = {};
    for (const t of node._fullData) {
      if (!t.legendgroup) continue;
      (groups[t.legendgroup] ||= []).push({
        name: t.name, visible: t.visible !== false && t.visible !== 'legendonly',
        color: t.line?.color || null, showlegend: Boolean(t.showlegend),
      });
    }
    return {groups, dragmode: node._fullLayout.scene?.dragmode || null};
  });
}
async function waitVisibility(group, expected) {
  await page.waitForFunction(({group, expected}) => {
    const el = document.querySelector('.js-plotly-plot');
    const traces = (el?._fullData || []).filter(t => t.legendgroup === group);
    return traces.length > 0 && traces.every(t => (t.visible !== false && t.visible !== 'legendonly') === expected);
  }, {group, expected}, {timeout: 12000});
}
try {
  for (const view of ['radiation','technical','polar','3d']) {
    await page.goto(url + '?view=' + view, {waitUntil: 'domcontentloaded'});
    await page.waitForFunction(() => {
      const e = document.querySelector('.js-plotly-plot');
      return e?._fullData?.some(t => t.legendgroup === 'month-12');
    }, undefined, {timeout: 60000});
    const before = await readState();
    for (let m=1; m<=12; m++) {
      const g = before.groups['month-'+m];
      assert(g?.length, view+': missing month '+m);
      assert(g.filter(t => t.showlegend).length === 1, view+': duplicate month legend');
      assert(g.every(t => t.visible), view+': initial month hidden');
    }
    const colors = new Set(Array.from({length:12}, (_,i) =>
      before.groups['month-'+(i+1)].find(t=>t.showlegend).color));
    assert(colors.size === 12 && !colors.has(null), view+': month palette is incomplete');
    if (view === '3d') assert(before.dragmode === 'turntable', '3d default drag mode');
    for (const [group,name] of [['month-1','Jan 21'],['month-6','Jun 21']]) {
      const toggle = page.locator('.js-plotly-plot g.legend g.traces').filter({hasText: name}).locator('rect.legendtoggle');
      await toggle.click({timeout:15000});
      await waitVisibility(group,false);
      const hidden = await readState();
      const others = Object.keys(hidden.groups).filter(k=>k.startsWith('month-') && k !== group);
      assert(others.every(k=>hidden.groups[k].every(t=>t.visible)), view+': unrelated month hidden');
      await toggle.click({timeout:15000});
      await waitVisibility(group,true);
    }
    if (view === 'technical') {
      const spacing = await page.locator('.js-plotly-plot').evaluate(node => {
        const ticks = [...node.querySelectorAll('.xtick text')];
        const cardinals = ticks.filter(t => /East|South|West/.test(t.textContent || ''));
        const title = node.querySelector('.g-xtitle text');
        const legend = node.querySelector('g.legend');
        return {
          cardinalCount: cardinals.length,
          tickBottom: Math.max(...ticks.map(t => t.getBoundingClientRect().bottom)),
          titleTop: title?.getBoundingClientRect().top,
          titleBottom: title?.getBoundingClientRect().bottom,
          legendTop: legend?.getBoundingClientRect().top,
        };
      });
      assert(spacing.cardinalCount === 3, 'technical compass labels missing');
      assert(spacing.titleTop >= spacing.tickBottom - 1, 'technical axis title overlaps ticks: '+JSON.stringify(spacing));
      assert(spacing.legendTop >= spacing.titleBottom - 1, 'technical legend overlaps axis title: '+JSON.stringify(spacing));
      report.technicalAxisSpacing = spacing;
    }
    report[view] = {monthlyColors: colors.size, legendHideRestore: true, dragmode: before.dragmode};
    await page.screenshot({path: dir+'/'+view+'.png', fullPage:true});
  }
  await fs.writeFile(dir+'/report.json', JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
} catch(e) {
  await fs.writeFile(dir+'/report.json', JSON.stringify({report,error:String(e.stack||e)},null,2));
  await page.screenshot({path:dir+'/failure.png',fullPage:true}).catch(()=>{});
  throw e;
} finally { await browser.close(); }
