from pathlib import Path

path = Path("deployment/pr83_monthly_selected_load_smoke.mjs")
text = path.read_text(encoding="utf-8")

old_series_count = '''async function setSeriesCountOne(page) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const frame = await appFrame(page, 'Time series and overlay');
    const slider = frame.getByRole('slider', { name: 'Number of series', exact: true }).first();
    if (!(await slider.count().catch(() => 0))) return;
    const value = Number(await slider.getAttribute('aria-valuenow').catch(() => NaN));
    if (value === 1) return;
    await slider.focus();
    await slider.press('Home');
    await sleep(700);
  }
  const frame = await appFrame(page, 'Time series and overlay');
  const slider = frame.getByRole('slider', { name: 'Number of series', exact: true }).first();
  const value = Number(await slider.getAttribute('aria-valuenow').catch(() => NaN));
  if (value !== 1) throw new Error(`Could not set Number of series to 1; observed ${value}.`);
}
'''
new_series_count = '''async function seriesCountSlider(frame) {
  const labels = frame.getByText('Number of series', { exact: true });
  const labelCount = await labels.count().catch(() => 0);
  for (let index = 0; index < labelCount; index += 1) {
    const label = labels.nth(index);
    if (!(await label.isVisible().catch(() => false))) continue;
    const container = label.locator(
      'xpath=ancestor::*[descendant::*[@role="slider"] or descendant::input[@type="range"]][1]'
    );
    if (!(await container.count().catch(() => 0))) continue;
    let slider = container.locator('[role="slider"]').first();
    if (!(await slider.count().catch(() => 0))) slider = container.locator('input[type="range"]').first();
    if (await slider.count().catch(() => 0) && await slider.isVisible().catch(() => false)) return slider;
  }

  const candidates = frame.locator('[role="slider"], input[type="range"]');
  const candidateCount = await candidates.count().catch(() => 0);
  for (let index = 0; index < candidateCount; index += 1) {
    const candidate = candidates.nth(index);
    if (!(await candidate.isVisible().catch(() => false))) continue;
    const min = await candidate.getAttribute('aria-valuemin').catch(() => null) ?? await candidate.getAttribute('min').catch(() => null);
    const max = await candidate.getAttribute('aria-valuemax').catch(() => null) ?? await candidate.getAttribute('max').catch(() => null);
    if (String(min) === '1' && String(max) === '6') return candidate;
  }
  return null;
}

async function sliderNumericValue(slider) {
  const aria = await slider.getAttribute('aria-valuenow').catch(() => null);
  if (aria != null && aria !== '') return Number(aria);
  const raw = await slider.inputValue().catch(() => null);
  return raw == null || raw === '' ? NaN : Number(raw);
}

async function setSeriesCountOne(page) {
  let lastValue = NaN;
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const frame = await appFrame(page, 'Time series and overlay', 10000);
    const slider = await seriesCountSlider(frame);
    if (!slider) {
      const text = (await bodyText(frame).catch(() => '')).replace(/\\s+/g, ' ').trim();
      throw new Error(`Number of series slider is unavailable. Page text: ${text.slice(-900)}`);
    }
    lastValue = await sliderNumericValue(slider);
    if (lastValue === 1) {
      await sleep(700);
      return;
    }
    await slider.focus();
    await slider.press('Home', { timeout: 5000 }).catch(async () => {
      await slider.press('ArrowLeft', { timeout: 5000 });
    });
    await frame.page().keyboard.press('Tab').catch(() => {});
    await sleep(900);
  }
  const frame = await appFrame(page, 'Time series and overlay', 10000);
  const slider = await seriesCountSlider(frame);
  lastValue = slider ? await sliderNumericValue(slider) : NaN;
  if (lastValue !== 1) throw new Error(`Could not commit Number of series = 1; observed ${lastValue}.`);
}
'''
if old_series_count not in text:
    raise SystemExit("Expected staged setSeriesCountOne block not found")
text = text.replace(old_series_count, new_series_count, 1)

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
