from pathlib import Path

root = Path(__file__).resolve().parents[3]
path = root / "deployment" / "geosphere_precip_snow_live_smoke.mjs"
text = path.read_text(encoding="utf-8")

old = r'''async function setSegmentedDate(frame, group, iso) {
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
'''
new = r'''async function setSegmentedDate(frame, group, iso) {
  const [year, month, day] = iso.split('-').map(Number);
  const desired = { year, month, day };
  const segments = group.locator('[role="spinbutton"]');
  const count = await segments.count();
  if (count < 3) throw new Error(`Segmented date control for ${iso} exposes only ${count} segment(s).`);

  const byPart = {};
  for (let index = 0; index < count; index += 1) {
    const segment = segments.nth(index);
    const ariaLabel = String(await segment.getAttribute('aria-label').catch(() => '')).toLowerCase();
    if (ariaLabel.includes('year')) byPart.year = segment;
    else if (ariaLabel.includes('month')) byPart.month = segment;
    else if (ariaLabel.includes('day')) byPart.day = segment;
  }
  const missingParts = ['year', 'month', 'day'].filter((part) => !byPart[part]);
  if (missingParts.length) {
    throw new Error(`Could not identify date segment(s) for ${iso}: ${missingParts.join(', ')}`);
  }

  // React-Aria date segments are contenteditable spinbuttons. Playwright fill()
  // dispatches the input events React expects; typing digit-by-digit can leave
  // the year unchanged because DateSegment applies partial-value semantics.
  // Set the year first, then month/day, and verify every aria-valuenow before
  // moving to the next segment.
  for (const part of ['year', 'month', 'day']) {
    const segment = byPart[part];
    const expected = desired[part];
    await segment.click({ timeout: 10_000 });
    const editable = await segment.getAttribute('contenteditable').catch(() => null);
    if (editable === 'true') {
      await segment.fill(String(expected), { timeout: 10_000 });
    } else {
      await segment.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {});
      await segment.press('Backspace').catch(() => {});
      await frame.page().keyboard.type(String(expected), { delay: 60 });
    }
    await sleep(180);
    const observed = Number(await segment.getAttribute('aria-valuenow').catch(() => NaN));
    if (Number.isFinite(observed) && observed !== expected) {
      // A second explicit keyboard replacement covers React-Aria variants that
      // expose contenteditable but defer normalization until a key event.
      await segment.click({ timeout: 10_000 });
      await segment.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {});
      await frame.page().keyboard.type(String(expected), { delay: 60 });
      await sleep(180);
    }
  }
  await frame.page().keyboard.press('Tab').catch(() => {});
}
'''
if old not in text:
    raise SystemExit("setSegmentedDate target not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

test_path = root / "tools" / "climate_analyzer" / "tests" / "test_geosphere_precip_snow_live_smoke_0_7_1.py"
test_text = test_path.read_text(encoding="utf-8")
needle = '        self.assertIn("aria-valuenow", self.browser)\n'
replacement = needle + '        self.assertIn("segment.fill(String(expected)", self.browser)\n        self.assertIn("for (const part of [\'year\', \'month\', \'day\'])", self.browser)\n'
if replacement not in test_text:
    if needle not in test_text:
        raise SystemExit("segmented-date test target not found")
    test_path.write_text(test_text.replace(needle, replacement, 1), encoding="utf-8")
