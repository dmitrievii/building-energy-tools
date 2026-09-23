from pathlib import Path

path = Path("deployment/pr83_monthly_selected_load_smoke.mjs")
text = path.read_text(encoding="utf-8")

old_resolution = '''async function setResolution(page, resolution) {
  await selectComboOption(page, 'Series 1 resolution', (text) => text.trim() === resolution);
  await appFrame(page, 'Time series and overlay');
  await sleep(700);
}
'''
new_resolution = '''async function setResolution(page, resolution) {
  if (resolution !== 'Native') {
    throw new Error(`Stage7 native-monthly acceptance only supports Native resolution, got ${resolution}.`);
  }
  const frame = await appFrame(page, 'Time series and overlay');
  const control = await combo(frame, 'Series 1 resolution', 10000);
  if (!(await control.count().catch(() => 0)) || !(await control.isVisible().catch(() => false))) {
    throw new Error('Series 1 resolution control is unavailable.');
  }
  // A fresh Streamlit session defaults Series 1 to Native in product code.
  // Do not re-select the already-active value: BaseWeb may omit the current
  // option from the popup. The rendered Plotly contract below proves that the
  // active resolution is truly Native (markers, M1 month axis, 12 source
  // observations per real year and unmodified source timestamps).
}
'''
if old_resolution not in text:
    raise SystemExit("Expected staged setResolution block not found")
text = text.replace(old_resolution, new_resolution, 1)

old_snapshot = '''async function plotSnapshot(page) {
  const frame = await appFrame(page, 'Time series and overlay');
  const plots = frame.locator('.js-plotly-plot');
  if (!(await plots.count().catch(() => 0))) throw new Error('No Plotly chart found on monthly overlay page.');
  const plot = plots.last();
  return plot.evaluate((node) => ({
    traces: (node.data || []).map((trace) => ({
      name: String(trace.name || ''),
      legendgroup: String(trace.legendgroup || ''),
      mode: String(trace.mode || ''),
      x: Array.from(trace.x || []).map((value) => value == null ? null : String(value)),
      y: Array.from(trace.y || []).map((value) => value == null ? null : Number(value)),
      customdata: Array.from(trace.customdata || []),
      hovertemplate: String(trace.hovertemplate || ''),
    })),
    tickformat: String(node.layout?.xaxis?.tickformat || ''),
    dtick: node.layout?.xaxis?.dtick ?? null,
    xaxisTitle: String(node.layout?.xaxis?.title?.text || ''),
  }));
}
'''
new_snapshot = '''async function plotSnapshot(page, timeoutMs = 30000) {
  const started = performance.now();
  let lastBody = '';
  while (performance.now() - started < timeoutMs) {
    const frame = await appFrame(page, 'Time series and overlay', 10000);
    const plots = frame.locator('.js-plotly-plot');
    const count = await plots.count().catch(() => 0);
    if (count) {
      const plot = plots.last();
      const snapshot = await plot.evaluate((node) => ({
        traces: (node.data || []).map((trace) => ({
          name: String(trace.name || ''),
          legendgroup: String(trace.legendgroup || ''),
          mode: String(trace.mode || ''),
          x: Array.from(trace.x || []).map((value) => value == null ? null : String(value)),
          y: Array.from(trace.y || []).map((value) => value == null ? null : Number(value)),
          customdata: Array.from(trace.customdata || []),
          hovertemplate: String(trace.hovertemplate || ''),
        })),
        tickformat: String(node.layout?.xaxis?.tickformat || ''),
        dtick: node.layout?.xaxis?.dtick ?? null,
        xaxisTitle: String(node.layout?.xaxis?.title?.text || ''),
      })).catch(() => null);
      if (snapshot && snapshot.traces.length) return snapshot;
    }
    lastBody = (await bodyText(frame).catch(() => '')).replace(/\\s+/g, ' ').trim();
    await sleep(250);
  }
  throw new Error(`Native monthly Plotly chart did not render within ${timeoutMs} ms. Page text: ${lastBody.slice(-1200)}`);
}
'''
if old_snapshot not in text:
    raise SystemExit("Expected staged plotSnapshot block not found")
text = text.replace(old_snapshot, new_snapshot, 1)

path.write_text(text, encoding="utf-8")
