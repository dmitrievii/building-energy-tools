from pathlib import Path

path = Path("deployment/interannual_overlay_browser_smoke.mjs")
text = path.read_text(encoding="utf-8")
old = '''async function exerciseHover(page) {
  const frame = await appFrame(page, 'Time series and overlay');
  const plot = frame.locator('.js-plotly-plot').last();
  await plot.evaluate((node) => {
    if (!window.Plotly) throw new Error('Plotly global unavailable');
    window.Plotly.Fx.hover(node, [{ curveNumber: 0, pointNumber: 0 }]);
  });
  await sleep(250);
  const hover = frame.locator('.hoverlayer').last();
  const text = await hover.innerText().catch(() => '');
  if (!text.includes('Year:') || !text.includes('Value:')) throw new Error(`Hover did not expose Year and Value: ${text}`);
  return text.replace(/\\s+/g, ' ').trim();
}
'''
new = '''async function renderedHoverText(plot) {
  const labels = await plot.locator('.hoverlayer text').allTextContents().catch(() => []);
  return labels.join(' ').replace(/\\s+/g, ' ').trim();
}

async function waitForHoverText(plot, timeoutMs = 4000) {
  const started = performance.now();
  let text = '';
  while (performance.now() - started < timeoutMs) {
    text = await renderedHoverText(plot);
    if (text.includes('Year:') && text.includes('Value:')) return text;
    await sleep(100);
  }
  return text;
}

async function exerciseHover(page) {
  const frame = await appFrame(page, 'Time series and overlay');
  const plot = frame.locator('.js-plotly-plot').last();

  const target = await plot.evaluate((node) => {
    if (!window.Plotly) throw new Error('Plotly global unavailable');
    const traces = Array.from(node.data || []);
    for (let curveNumber = 0; curveNumber < traces.length; curveNumber += 1) {
      const values = Array.from(traces[curveNumber].y || []);
      const pointNumber = values.findIndex((value) => value != null && Number.isFinite(Number(value)));
      if (pointNumber >= 0) {
        window.Plotly.Fx.hover(node, [{ curveNumber, pointNumber }]);
        return { curveNumber, pointNumber };
      }
    }
    throw new Error('No finite interannual point is available for hover exercise.');
  });

  let text = await waitForHoverText(plot, 4000);
  if (text.includes('Year:') && text.includes('Value:')) return text;

  const lines = plot.locator('.scatterlayer .trace.scatter path.js-line');
  const lineCount = await lines.count().catch(() => 0);
  for (let index = 0; index < lineCount; index += 1) {
    const box = await lines.nth(index).boundingBox().catch(() => null);
    if (!box || box.width < 4) continue;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    text = await waitForHoverText(plot, 2500);
    if (text.includes('Year:') && text.includes('Value:')) return text;
  }

  throw new Error(`Hover did not expose Year and Value for curve ${target.curveNumber}, point ${target.pointNumber}: ${text}`);
}
'''
if old not in text:
    raise SystemExit("Expected exerciseHover block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
