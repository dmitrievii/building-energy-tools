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
    const parentStyle = node.parentElement ? getComputedStyle(node.parentElement) : null;
    return {
      text: node.textContent?.trim() ?? '',
      tag: node.tagName,
      className: node.className,
      color: style.color,
      backgroundColor: style.backgroundColor,
      fontSize: style.fontSize,
      fontWeight: style.fontWeight,
      opacity: style.opacity,
      parentTag: node.parentElement?.tagName ?? null,
      parentClass: node.parentElement?.className ?? null,
      parentBackgroundColor: parentStyle?.backgroundColor ?? null,
      outerHTML: node.outerHTML.slice(0, 1200),
    };
  });
  console.log(`NODE_${i}=${JSON.stringify(data)}`);
}
await browser.close();
