from pathlib import Path

root = Path(__file__).resolve().parents[3]
path = root / "deployment" / "geosphere_precip_snow_live_smoke.mjs"
text = path.read_text(encoding="utf-8")

insert_before = "async function analysisCombo(frame) {\n"
helper = r'''async function selectStationFromList(page, frame, fixture, timeoutMs = 60_000) {
  await waitForText(frame, 'Manual station selection', timeoutMs);

  let combo = frame.getByRole('combobox', { name: 'Search-result stations', exact: true }).first();
  if (!(await combo.count().catch(() => 0))) {
    combo = frame.getByLabel('Search-result stations', { exact: true }).first();
  }
  if (!(await combo.count().catch(() => 0))) {
    throw new Error('Could not locate Search-result stations selectbox.');
  }

  await combo.click({ timeout: 15_000 });
  await sleep(300);
  const targetText = `ID ${fixture.station_id}`;
  let option = frame.getByRole('option').filter({ hasText: targetText }).last();
  if (!(await option.count().catch(() => 0))) {
    option = frame.locator('[data-baseweb="menu"] li').filter({ hasText: targetText }).last();
  }
  if (!(await option.count().catch(() => 0))) {
    throw new Error(`Search-result stations contains no option for ${targetText}.`);
  }
  const selectedLabel = (await option.innerText().catch(() => '')).trim();
  await option.click({ timeout: 15_000 });
  await sleep(500);

  const useButton = frame.getByRole('button', { name: 'Use station from list', exact: true }).first();
  if (!(await useButton.count().catch(() => 0))) {
    throw new Error('Could not locate Use station from list button.');
  }
  await useButton.click({ timeout: 15_000 });

  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    let currentFrame;
    try {
      currentFrame = await waitForFrameContaining(page, 'Selected station', 5_000);
    } catch {
      await sleep(300);
      continue;
    }
    let currentCombo = currentFrame.getByRole('combobox', { name: 'Search-result stations', exact: true }).first();
    if (!(await currentCombo.count().catch(() => 0))) {
      currentCombo = currentFrame.getByLabel('Search-result stations', { exact: true }).first();
    }
    if (await currentCombo.count().catch(() => 0)) {
      const rendered = [
        await currentCombo.innerText().catch(() => ''),
        await currentCombo.textContent().catch(() => ''),
        await currentCombo.inputValue().catch(() => ''),
      ].join(' ');
      if (rendered.includes(targetText) || rendered.includes(fixture.station_name)) {
        return { frame: currentFrame, selectedLabel, rendered: rendered.trim() };
      }
    }
    const selectedText = await bodyText(currentFrame);
    if (selectedText.includes('Selected station') && selectedText.includes(fixture.station_name)) {
      return { frame: currentFrame, selectedLabel, rendered: fixture.station_name };
    }
    await sleep(400);
  }
  throw new Error(`Station selection did not settle on ${fixture.station_name} (${targetText}).`);
}

'''
if helper not in text:
    if insert_before not in text:
        raise SystemExit("station helper insertion point not found")
    text = text.replace(insert_before, helper + insert_before, 1)

old = """  await fillInput(appFrame, 'Search GeoSphere station', fixture.station_id);\n  await waitForText(appFrame, 'Visible GeoSphere stations after filters:');\n  await waitForText(appFrame, `ID ${fixture.station_id}`);\n  report.checks.station_selected = `${fixture.station_name} (${fixture.station_id})`;\n"""
new = """  await fillInput(appFrame, 'Search GeoSphere station', fixture.station_id);\n  await waitForText(appFrame, 'Visible GeoSphere stations after filters:');\n  const stationSelection = await selectStationFromList(page, appFrame, fixture);\n  appFrame = stationSelection.frame;\n  report.checks.station_selected = `${fixture.station_name} (${fixture.station_id})`;\n  report.checks.station_selection_option = stationSelection.selectedLabel;\n  report.checks.station_selection_rendered = stationSelection.rendered;\n"""
if old not in text:
    raise SystemExit("old station filtering block not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

# Strengthen the source contract so future smoke changes cannot regress to
# treating a text filter as an actual GeoSphere station selection.
test_path = root / "tools" / "climate_analyzer" / "tests" / "test_geosphere_precip_snow_live_smoke_0_7_1.py"
test_text = test_path.read_text(encoding="utf-8")
anchor = "    def test_browser_smoke_drives_exact_fixture_dates(self) -> None:\n"
test_method = '''    def test_browser_smoke_explicitly_selects_filtered_station(self) -> None:\n        self.assertIn("async function selectStationFromList", self.browser)\n        self.assertIn("Search-result stations", self.browser)\n        self.assertIn("Use station from list", self.browser)\n        self.assertIn("station_selection_option", self.browser)\n        self.assertNotIn("await waitForText(appFrame, `ID ${fixture.station_id}`);", self.browser)\n\n'''
if test_method not in test_text:
    if anchor not in test_text:
        raise SystemExit("test insertion anchor not found")
    test_text = test_text.replace(anchor, test_method + anchor, 1)
    test_path.write_text(test_text, encoding="utf-8")
