from pathlib import Path

path = Path("deployment/interannual_overlay_browser_smoke.mjs")
text = path.read_text(encoding="utf-8")

old_date = '''async function dateControl(frame, label) {
  const labelled = frame.getByLabel(label, { exact: true }).first();
  if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) {
    const tag = await labelled.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
    const role = await labelled.getAttribute('role').catch(() => null);
    if (['input', 'textarea', 'select'].includes(tag)) return { kind: 'input', locator: labelled };
    if (role === 'group' && await labelled.locator('[role="spinbutton"]').count().catch(() => 0) >= 3) {
      return { kind: 'segmented', locator: labelled };
    }
  }
  const aria = frame.locator(`input[aria-label="${label}"]`).first();
  if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return { kind: 'input', locator: aria };
  throw new Error(`Date control unavailable: ${label}`);
}
'''
new_date = '''async function dateControl(frame, label, timeoutMs = 30000) {
  const started = performance.now();
  let current = frame;
  while (performance.now() - started < timeoutMs) {
    const labelled = current.getByLabel(label, { exact: true }).first();
    if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) {
      const tag = await labelled.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
      const role = await labelled.getAttribute('role').catch(() => null);
      if (['input', 'textarea', 'select'].includes(tag)) return { kind: 'input', locator: labelled };
      if (role === 'group' && await labelled.locator('[role="spinbutton"]').count().catch(() => 0) >= 3) {
        return { kind: 'segmented', locator: labelled };
      }
    }
    const aria = current.locator(`input[aria-label="${label}"]`).first();
    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return { kind: 'input', locator: aria };
    await sleep(200);
    current = await appFrame(current.page(), 'Measured variables to load', 5000).catch(() => current);
  }
  throw new Error(`Date control unavailable after ${timeoutMs} ms: ${label}`);
}
'''
if old_date not in text:
    raise SystemExit("Expected dateControl block not found")
text = text.replace(old_date, new_date, 1)

old_hover = '''async function exerciseHover(page) {
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
new_hover = '''async function renderedHoverText(plot) {
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
    await page.mouse.move(box.x + box.width / 2, box.y + Math.max(1, box.height / 2));
    text = await waitForHoverText(plot, 2500);
    if (text.includes('Year:') && text.includes('Value:')) return text;
  }

  throw new Error(`Hover did not expose Year and Value for curve ${target.curveNumber}, point ${target.pointNumber}: ${text}`);
}
'''
if old_hover not in text:
    raise SystemExit("Expected exerciseHover block not found")
text = text.replace(old_hover, new_hover, 1)
path.write_text(text, encoding="utf-8")
