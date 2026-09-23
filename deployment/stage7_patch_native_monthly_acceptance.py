from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Expected block not found: {label}")
    return text.replace(old, new, 1)


# 1) Native-monthly Plotly presentation semantics.
timeseries_path = Path("tools/climate_analyzer/epw_climate_analyzer/timeseries.py")
timeseries = timeseries_path.read_text(encoding="utf-8")
timeseries = replace_once(
    timeseries,
    ''') -> tuple[go.Figure, list[pd.DataFrame]]:\n    fig = go.Figure()\n    tables: list[pd.DataFrame] = []\n''',
    ''') -> tuple[go.Figure, list[pd.DataFrame]]:\n    fig = go.Figure()\n    native_monthly = str(df.attrs.get("canonical_native_resolution", "")).strip().lower() == "monthly"\n    tables: list[pd.DataFrame] = []\n''',
    "interannual native-monthly detection",
)
timeseries = replace_once(
    timeseries,
    '''            mode = "lines+markers" if spec.resolution == "Monthly" else "lines"\n''',
    '''            mode = (\n                "lines+markers"\n                if spec.resolution == "Monthly" or (spec.resolution == "Native" and native_monthly)\n                else "lines"\n            )\n''',
    "native monthly markers",
)
timeseries = replace_once(
    timeseries,
    '''    resolutions = {item.resolution for item in series}\n    if resolutions == {"Monthly"}:\n        tickformat = "%b"\n        dtick: object = "M1"\n    else:\n        tickformat = "%d %b"\n        dtick = None\n''',
    '''    monthly_calendar_axis = all(\n        item.resolution == "Monthly" or (item.resolution == "Native" and native_monthly)\n        for item in series\n    )\n    if monthly_calendar_axis:\n        tickformat = "%b"\n        dtick: object = "M1"\n    else:\n        tickformat = "%d %b"\n        dtick = None\n''',
    "native monthly calendar axis",
)
timeseries_path.write_text(timeseries, encoding="utf-8")


# 2) Focused unit contract for Native monthly presentation.
test_path = Path("tools/climate_analyzer/tests/test_interannual_overlay.py")
test_text = test_path.read_text(encoding="utf-8")
marker = '''        self.assertTrue(all("Year: %{customdata[0]}" in trace.hovertemplate for trace in fig.data))\n\n\nif __name__ == "__main__":\n'''
replacement = '''        self.assertTrue(all("Year: %{customdata[0]}" in trace.hovertemplate for trace in fig.data))\n\n    def test_native_monthly_interannual_uses_month_markers_and_month_axis(self) -> None:\n        index = pd.DatetimeIndex(\n            [pd.Timestamp(year, month, 1) for year in (2020, 2021) for month in range(1, 13)]\n        )\n        values = [float(year - 2020) * 100.0 + month for year in (2020, 2021) for month in range(1, 13)]\n        frame = pd.DataFrame({"dry_bulb_temperature_c": values}, index=index)\n        frame.attrs["canonical_native_resolution"] = "monthly"\n        frame = with_time_basis(frame, INTERANNUAL_OVERLAY)\n        fig, _tables = build_overlay_figure(\n            frame,\n            [OverlaySeries("Temperature", "dry_bulb_temperature_c", "°C", "Native")],\n            pd.Timestamp("2020-01-01"),\n            pd.Timestamp("2022-01-01"),\n        )\n        self.assertEqual([trace.name for trace in fig.data], ["Temperature — 2020", "Temperature — 2021"])\n        self.assertTrue(all(trace.mode == "lines+markers" for trace in fig.data))\n        self.assertTrue(all(len([value for value in trace.x if value is not None]) == 12 for trace in fig.data))\n        self.assertEqual(fig.layout.xaxis.tickformat, "%b")\n        self.assertEqual(fig.layout.xaxis.dtick, "M1")\n\n\nif __name__ == "__main__":\n'''
test_text = replace_once(test_text, marker, replacement, "native monthly unit test insertion")
test_path.write_text(test_text, encoding="utf-8")


# 3) Upgrade monthly live browser smoke from loader-only to 2020-2025 Interannual acceptance.
smoke_path = Path("deployment/pr83_monthly_selected_load_smoke.mjs")
smoke = smoke_path.read_text(encoding="utf-8")

smoke = replace_once(
    smoke,
    '''  return null;\n}\n\nasync function chooseSource(page) {\n''',
    '''  return null;\n}\n\nasync function selectComboOption(page, label, predicate) {\n  for (let attempt = 0; attempt < 3; attempt += 1) {\n    const frame = await appFrame(page);\n    const control = await combo(frame, label, 10000);\n    await control.click({ timeout: 5000 });\n    const option = await visibleOption(page, frame, predicate);\n    if (option) {\n      await option.click({ timeout: 5000 });\n      await sleep(700);\n      return appFrame(page);\n    }\n    await sleep(300);\n  }\n  throw new Error(`Could not select option for ${label}.`);\n}\n\nasync function chooseSource(page) {\n''',
    "generic combo selector",
)

station_marker = '''  throw new Error(`Could not commit station ${stationName} ID ${targetId}; observed=${observed}`);\n}\n\nasync function waitMonthlySurface(page, timeoutMs = 60000) {\n'''
date_helpers = '''  throw new Error(`Could not commit station ${stationName} ID ${targetId}; observed=${observed}`);\n}\n\nfunction dateValueMatches(value, iso) {\n  const [year, month, day] = iso.split('-').map(Number);\n  const parts = String(value).split(/\\D+/).filter(Boolean).map(Number);\n  return parts.includes(year) && parts.includes(month) && parts.includes(day);\n}\n\nasync function dateControl(frame, label, timeoutMs = 30000) {\n  const started = performance.now();\n  let current = frame;\n  while (performance.now() - started < timeoutMs) {\n    const labelled = current.getByLabel(label, { exact: true }).first();\n    if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) {\n      const tag = await labelled.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');\n      const role = await labelled.getAttribute('role').catch(() => null);\n      if (['input', 'textarea', 'select'].includes(tag)) return { kind: 'input', locator: labelled };\n      if (role === 'group' && await labelled.locator('[role="spinbutton"]').count().catch(() => 0) >= 3) {\n        return { kind: 'segmented', locator: labelled };\n      }\n    }\n    const aria = current.locator(`input[aria-label="${label}"]`).first();\n    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) return { kind: 'input', locator: aria };\n    await sleep(200);\n    current = await appFrame(current.page(), 'Measured variables to load', 5000).catch(() => current);\n  }\n  throw new Error(`Date control unavailable after ${timeoutMs} ms: ${label}`);\n}\n\nasync function segmentedDateValue(group) {\n  const segments = group.locator('[role="spinbutton"]');\n  const values = {};\n  for (let i = 0; i < await segments.count(); i += 1) {\n    const segment = segments.nth(i);\n    const label = String(await segment.getAttribute('aria-label').catch(() => '')).toLowerCase();\n    const value = Number(await segment.getAttribute('aria-valuenow').catch(() => NaN));\n    if (label.includes('year')) values.year = value;\n    else if (label.includes('month')) values.month = value;\n    else if (label.includes('day')) values.day = value;\n  }\n  if ([values.year, values.month, values.day].every(Number.isFinite)) {\n    return `${values.year}-${String(values.month).padStart(2, '0')}-${String(values.day).padStart(2, '0')}`;\n  }\n  return await group.innerText().catch(() => '');\n}\n\nasync function setSegmentedDate(frame, group, iso) {\n  const [year, month, day] = iso.split('-').map(Number);\n  const desired = { year, month, day };\n  const segments = group.locator('[role="spinbutton"]');\n  const byPart = {};\n  for (let index = 0; index < await segments.count(); index += 1) {\n    const segment = segments.nth(index);\n    const label = String(await segment.getAttribute('aria-label').catch(() => '')).toLowerCase();\n    if (label.includes('year')) byPart.year = segment;\n    else if (label.includes('month')) byPart.month = segment;\n    else if (label.includes('day')) byPart.day = segment;\n  }\n  for (const part of ['year', 'month', 'day']) {\n    const segment = byPart[part];\n    if (!segment) throw new Error(`Could not identify ${part} segment for ${iso}.`);\n    await segment.click({ timeout: 10000 });\n    const editable = await segment.getAttribute('contenteditable').catch(() => null);\n    if (editable === 'true') await segment.fill(String(desired[part]), { timeout: 10000 });\n    else {\n      await segment.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {});\n      await segment.press('Backspace').catch(() => {});\n      await frame.page().keyboard.type(String(desired[part]), { delay: 50 });\n    }\n    await sleep(160);\n  }\n  await frame.page().keyboard.press('Tab').catch(() => {});\n}\n\nasync function setDate(page, label, iso) {\n  let lastValue = null;\n  for (let attempt = 0; attempt < 3; attempt += 1) {\n    const frame = await appFrame(page, 'Measured variables to load', 20000);\n    const control = await dateControl(frame, label);\n    if (control.kind === 'input') {\n      const candidate = attempt === 0 ? iso.replaceAll('-', '/') : iso;\n      await control.locator.click({ timeout: 10000 });\n      await control.locator.fill(candidate, { timeout: 10000 });\n      await control.locator.press('Enter').catch(() => {});\n      await control.locator.press('Tab').catch(() => {});\n    } else {\n      await setSegmentedDate(frame, control.locator, iso);\n    }\n    await sleep(1000);\n    const refreshedFrame = await appFrame(page, 'Measured variables to load', 20000);\n    const refreshed = await dateControl(refreshedFrame, label);\n    lastValue = refreshed.kind === 'input'\n      ? await refreshed.locator.inputValue().catch(() => null)\n      : await segmentedDateValue(refreshed.locator);\n    if (dateValueMatches(lastValue, iso)) return lastValue;\n  }\n  throw new Error(`Date input ${label} did not accept ${iso}; observed ${lastValue}.`);\n}\n\nasync function waitMonthlySurface(page, timeoutMs = 60000) {\n'''
smoke = replace_once(smoke, station_marker, date_helpers, "monthly date controls")

presentation_helpers = r'''
async function chooseTimeBasis(page) {
  await selectComboOption(page, 'Time basis', (text) => text.trim() === 'Interannual overlay');
  const frame = await appFrame(page);
  const control = await combo(frame, 'Time basis');
  const value = `${await control.textContent().catch(() => '')} ${await control.inputValue().catch(() => '')}`;
  if (!value.includes('Interannual overlay')) throw new Error('Interannual overlay time basis did not commit.');
}

async function openOverlay(page) {
  const frame = await appFrame(page);
  const target = frame.getByText('Explore — Time series & overlay', { exact: true }).last();
  if (!(await target.count().catch(() => 0))) throw new Error('Time series & overlay navigation item missing.');
  await target.click({ force: true, timeout: 10000 });
  return appFrame(page, 'Time series and overlay', 30000);
}

async function setSeriesCountOne(page) {
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

async function setResolution(page, resolution) {
  await selectComboOption(page, 'Series 1 resolution', (text) => text.trim() === resolution);
  await appFrame(page, 'Time series and overlay');
  await sleep(700);
}

async function plotSnapshot(page) {
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

function assertNativeMonthlyInterannual(snapshot) {
  const expectedYears = [2020, 2021, 2022, 2023, 2024, 2025];
  if (snapshot.traces.length !== expectedYears.length) {
    throw new Error(`Expected 6 Native monthly yearly traces, got ${snapshot.traces.length}: ${snapshot.traces.map((trace) => trace.name).join(' | ')}`);
  }
  for (const year of expectedYears) {
    const matches = snapshot.traces.filter((trace) => trace.name.includes(String(year)));
    if (matches.length !== 1) throw new Error(`Expected exactly one Native monthly trace for ${year}, got ${matches.length}.`);
    const trace = matches[0];
    if (!trace.mode.includes('markers')) throw new Error(`Native monthly ${year} trace must expose markers; mode=${trace.mode}`);
    const positions = trace.x.filter(Boolean);
    if (positions.length !== 12) throw new Error(`Native monthly ${year} trace has ${positions.length} calendar positions, expected 12.`);
    const months = positions.map((value) => {
      const match = String(value).match(/2000-(\d{2})-/);
      return match ? Number(match[1]) : NaN;
    });
    if (months.join(',') !== '1,2,3,4,5,6,7,8,9,10,11,12') {
      throw new Error(`Native monthly ${year} calendar positions are not Jan-Dec: ${positions.join(' | ')}`);
    }
    const custom = trace.customdata.filter((row) => Array.isArray(row) && row[0] != null);
    if (custom.length !== 12) throw new Error(`Native monthly ${year} customdata has ${custom.length} rows, expected 12.`);
    for (const row of custom) {
      if (Number(row[0]) !== year) throw new Error(`Native monthly ${year} customdata lost real-year identity: ${JSON.stringify(row)}`);
      if (!String(row[1] || '').startsWith(`${year}-`)) throw new Error(`Native monthly ${year} source timestamp is not real-year provenance: ${JSON.stringify(row)}`);
      if (String(row[3] || '') !== 'Native') throw new Error(`Native monthly ${year} resolution provenance is not Native: ${JSON.stringify(row)}`);
    }
    if (!trace.hovertemplate.includes('Year:') || !trace.hovertemplate.includes('Source:') || !trace.hovertemplate.includes('Value:')) {
      throw new Error(`Native monthly ${year} hover template lost Year/Source/Value semantics.`);
    }
  }
  if (snapshot.tickformat !== '%b') throw new Error(`Native monthly x-axis tickformat must be %b, got ${snapshot.tickformat}.`);
  if (String(snapshot.dtick) !== 'M1') throw new Error(`Native monthly x-axis dtick must be M1, got ${snapshot.dtick}.`);
  if (snapshot.xaxisTitle !== 'Calendar position') throw new Error(`Native monthly x-axis title changed: ${snapshot.xaxisTitle}`);
  return expectedYears;
}

async function renderedHoverText(plot) {
  const labels = await plot.locator('.hoverlayer text').allTextContents().catch(() => []);
  return labels.join(' ').replace(/\s+/g, ' ').trim();
}

async function waitForHoverText(plot, timeoutMs = 5000) {
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
    throw new Error('No finite Native monthly point is available for hover exercise.');
  });
  const text = await waitForHoverText(plot, 5000);
  if (!text.includes('Year:') || !text.includes('Value:')) {
    throw new Error(`Native monthly hover did not expose Year and Value for curve ${target.curveNumber}, point ${target.pointNumber}: ${text}`);
  }
  return text;
}

'''
smoke = replace_once(smoke, "\nconst report = {\n", "\n" + presentation_helpers + "const report = {\n", "monthly interannual helpers")
smoke = smoke.replace(
    "climate-analyzer-monthly-selected-load-smoke-v7-proven-selector-minimal",
    "climate-analyzer-monthly-selected-load-smoke-v8-native-interannual",
    1,
)

smoke = replace_once(
    smoke,
    '''  await selectDataset(page);\n  await selectStation(page, fixture.station_name, fixture.station_id);\n\n  let frame = await waitMonthlySurface(page);\n''',
    '''  await selectDataset(page);\n  await selectStation(page, fixture.station_name, fixture.station_id);\n  await setDate(page, 'From date (UTC)', '2020-01-01');\n  await setDate(page, 'Through date (UTC)', '2025-12-31');\n  report.checks.requested_interval = ['2020-01-01', '2025-12-31'];\n\n  let frame = await waitMonthlySurface(page);\n''',
    "explicit 2020-2025 monthly interval",
)

old_post_load = '''  frame = await appFrame(page, 'Climate overview', 180000);\n  text = await bodyText(frame);\n  if (!text.includes('Climate overview')) throw new Error('Monthly canonical dataset did not activate Overview.');\n  report.checks.canonical_dataset_activated = true;\n  report.checks.summary_overview = true;\n  report.checks.dew_point_contract_from_fixture = true;\n  report.checks.measured_station_pressure_contract_from_fixture = true;\n\n  if (report.page_errors.length) {\n'''
new_post_load = '''  frame = await appFrame(page, 'Explore — Time series & overlay', 180000);\n  report.checks.canonical_dataset_activated = true;\n  report.checks.dew_point_contract_from_fixture = true;\n  report.checks.measured_station_pressure_contract_from_fixture = true;\n\n  await chooseTimeBasis(page);\n  await openOverlay(page);\n  await setSeriesCountOne(page);\n  await setResolution(page, 'Native');\n  const nativeMonthly = await plotSnapshot(page);\n  report.checks.native_monthly_years = assertNativeMonthlyInterannual(nativeMonthly);\n  report.checks.native_monthly_trace_names = nativeMonthly.traces.map((trace) => trace.name);\n  report.checks.native_monthly_positions_per_year = Object.fromEntries(\n    nativeMonthly.traces.map((trace) => [trace.legendgroup, trace.x.filter(Boolean).length]),\n  );\n  report.checks.native_monthly_axis = { tickformat: nativeMonthly.tickformat, dtick: nativeMonthly.dtick };\n  report.checks.native_monthly_hover = await exerciseHover(page);\n\n  if (report.page_errors.length) {\n'''
smoke = replace_once(smoke, old_post_load, new_post_load, "native monthly browser acceptance")
smoke_path.write_text(smoke, encoding="utf-8")
