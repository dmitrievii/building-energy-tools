from pathlib import Path

root = Path(__file__).resolve().parents[3]
path = root / "deployment" / "geosphere_precip_snow_live_smoke.mjs"
text = path.read_text(encoding="utf-8")

old = r'''function dateValueMatches(value, iso) {
  const [year, month, day] = iso.split('-').map(Number);
  const parts = String(value).split(/\D+/).filter(Boolean).map(Number);
  return parts.includes(year) && parts.includes(month) && parts.includes(day);
}

async function setDateInput(frame, label, iso) {
  const displayCandidates = [iso.replaceAll('-', '/'), iso];
  let lastValue = null;
  for (const candidate of displayCandidates) {
    const input = await labelledInput(frame, label);
    await input.click({ timeout: 15_000 });
    await input.fill(candidate, { timeout: 15_000 });
    await input.press('Enter').catch(() => {});
    await input.press('Tab').catch(() => {});
    await sleep(1_200);
    const refreshed = await labelledInput(frame, label);
    lastValue = await refreshed.inputValue().catch(() => null);
    if (dateValueMatches(lastValue, iso)) return lastValue;
  }
  throw new Error(`Date input ${label} did not accept ${iso}; observed value=${lastValue}`);
}
'''
new = r'''function dateValueMatches(value, iso) {
  const [year, month, day] = iso.split('-').map(Number);
  const parts = String(value).split(/\D+/).filter(Boolean).map(Number);
  return parts.includes(year) && parts.includes(month) && parts.includes(day);
}

async function dateControl(frame, label, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const labelled = frame.getByLabel(label, { exact: true }).first();
    if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) {
      const tagName = await labelled.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
      const role = await labelled.getAttribute('role').catch(() => null);
      if (['input', 'textarea', 'select'].includes(tagName)) {
        return { kind: 'input', locator: labelled };
      }
      if (role === 'group') {
        const segmentCount = await labelled.locator('[role="spinbutton"]').count().catch(() => 0);
        if (segmentCount >= 3) return { kind: 'segmented', locator: labelled };
      }
    }

    const input = frame.locator(`input[aria-label="${label}"]`).first();
    if (await input.count().catch(() => 0) && await input.isVisible().catch(() => false)) {
      return { kind: 'input', locator: input };
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for date control: ${label}`);
}

async function segmentedDateValue(group) {
  const segments = group.locator('[role="spinbutton"]');
  const count = await segments.count();
  const values = {};
  for (let index = 0; index < count; index += 1) {
    const segment = segments.nth(index);
    const ariaLabel = String(await segment.getAttribute('aria-label').catch(() => '')).toLowerCase();
    const value = Number(await segment.getAttribute('aria-valuenow').catch(() => NaN));
    if (!Number.isFinite(value)) continue;
    if (ariaLabel.includes('month')) values.month = value;
    else if (ariaLabel.includes('day')) values.day = value;
    else if (ariaLabel.includes('year')) values.year = value;
  }
  if ([values.year, values.month, values.day].every(Number.isFinite)) {
    return `${values.year}-${String(values.month).padStart(2, '0')}-${String(values.day).padStart(2, '0')}`;
  }
  return (await group.innerText().catch(() => '')).trim();
}

async function setSegmentedDate(frame, group, iso) {
  const [year, month, day] = iso.split('-').map(Number);
  const desired = { year, month, day };
  const segments = group.locator('[role="spinbutton"]');
  const count = await segments.count();
  if (count < 3) throw new Error(`Segmented date control for ${iso} exposes only ${count} segment(s).`);

  let assigned = 0;
  for (let index = 0; index < count; index += 1) {
    const segment = segments.nth(index);
    const ariaLabel = String(await segment.getAttribute('aria-label').catch(() => '')).toLowerCase();
    let part = null;
    if (ariaLabel.includes('month')) part = 'month';
    else if (ariaLabel.includes('day')) part = 'day';
    else if (ariaLabel.includes('year')) part = 'year';
    if (!part) continue;

    await segment.click({ timeout: 10_000 });
    await segment.press('Backspace').catch(() => {});
    await frame.page().keyboard.type(String(desired[part]), { delay: 40 });
    assigned += 1;
    await sleep(120);
  }
  if (assigned < 3) {
    throw new Error(`Could not identify month/day/year segments for ${iso}.`);
  }
  await frame.page().keyboard.press('Tab').catch(() => {});
}

async function setDateInput(frame, label, iso) {
  let lastValue = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const control = await dateControl(frame, label);
    if (control.kind === 'input') {
      const candidate = attempt === 0 ? iso.replaceAll('-', '/') : iso;
      await control.locator.click({ timeout: 15_000 });
      await control.locator.fill(candidate, { timeout: 15_000 });
      await control.locator.press('Enter').catch(() => {});
      await control.locator.press('Tab').catch(() => {});
    } else {
      await setSegmentedDate(frame, control.locator, iso);
    }

    await sleep(1_500);
    const refreshed = await dateControl(frame, label);
    if (refreshed.kind === 'input') {
      lastValue = await refreshed.locator.inputValue().catch(() => null);
    } else {
      lastValue = await segmentedDateValue(refreshed.locator);
    }
    if (dateValueMatches(lastValue, iso)) return lastValue;
  }
  throw new Error(`Date input ${label} did not accept ${iso}; observed value=${lastValue}`);
}
'''
if old not in text:
    raise SystemExit("date helper block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

test_path = root / "tools" / "climate_analyzer" / "tests" / "test_geosphere_precip_snow_live_smoke_0_7_1.py"
test_text = test_path.read_text(encoding="utf-8")
anchor = "    def test_browser_smoke_explicitly_selects_filtered_station(self) -> None:\n"
test_method = '''    def test_browser_smoke_supports_streamlit_segmented_date_fields(self) -> None:\n        self.assertIn("async function dateControl", self.browser)\n        self.assertIn("role === 'group'", self.browser)\n        self.assertIn("[role=\\\"spinbutton\\\"]", self.browser)\n        self.assertIn("async function setSegmentedDate", self.browser)\n        self.assertIn("aria-valuenow", self.browser)\n\n'''
if test_method not in test_text:
    if anchor not in test_text:
        raise SystemExit("test anchor not found")
    test_path.write_text(test_text.replace(anchor, test_method + anchor, 1), encoding="utf-8")
