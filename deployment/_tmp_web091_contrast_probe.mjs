import { chromium } from 'playwright-core';

const target = 'https://building-climate-analyzer.streamlit.app/';
const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 120000 });
await page.waitForTimeout(6000);
const frame = page.frames().find((item) => item.url().includes('/~/+/'));
if (!frame) throw new Error('Streamlit app frame not found');
const selector = '.st-emotion-cache-19loc4w';
const loc = frame.locator(selector);
const count = await loc.count();
console.log(`MATCH_COUNT=${count}`);
for (let i = 0; i < count; i += 1) {
  const el = loc.nth(i);
  const data = await el.evaluate((node) => {
    const style = getComputedStyle(node);
    const ancestors = [];
    let current = node;
    for (let depth = 0; current && depth < 6; depth += 1, current = current.parentElement) {
      ancestors.push({
        depth,
        tag: current.tagName,
        className: current.className,
        testid: current.getAttribute('data-testid'),
        role: current.getAttribute('role'),
        ariaLabel: current.getAttribute('aria-label'),
      });
    }
    return {
      text: node.textContent?.trim() ?? '',
      color: style.color,
      backgroundColor: style.backgroundColor,
      fontSize: style.fontSize,
      fontWeight: style.fontWeight,
      ancestors,
      parentOuterHTML: node.parentElement?.outerHTML.slice(0, 3500) ?? '',
    };
  });
  console.log(`NODE_${i}=${JSON.stringify(data)}`);
}
await browser.close();
