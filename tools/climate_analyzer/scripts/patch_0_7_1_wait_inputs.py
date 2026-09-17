from pathlib import Path

root = Path(__file__).resolve().parents[3]
path = root / "deployment" / "geosphere_precip_snow_live_smoke.mjs"
text = path.read_text(encoding="utf-8")
old = '''async function labelledInput(frame, label) {
  const labelled = frame.getByLabel(label, { exact: true });
  if (await labelled.count()) return labelled.first();
  const aria = frame.locator(`input[aria-label="${label}"]`).first();
  if (await aria.count()) return aria;
  const text = frame.getByText(label, { exact: true }).first();
  if (await text.count()) {
    const container = text.locator('xpath=..');
    const input = container.locator('input').first();
    if (await input.count()) return input;
  }
  throw new Error(`Could not locate input: ${label}`);
}

async function fillInput(frame, label, value) {
  const input = await labelledInput(frame, label);
  await input.fill(String(value), { timeout: 15_000 });
  await input.press('Tab').catch(() => {});
}
'''
new = '''async function labelledInput(frame, label, timeoutMs = 60_000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const labelled = frame.getByLabel(label, { exact: true }).first();
    if (await labelled.count().catch(() => 0) && await labelled.isVisible().catch(() => false)) {
      return labelled;
    }

    const aria = frame.locator(`input[aria-label="${label}"]`).first();
    if (await aria.count().catch(() => 0) && await aria.isVisible().catch(() => false)) {
      return aria;
    }

    // Streamlit can briefly render a widget skeleton before the real input is
    // mounted after a source-mode rerun. Resolve the input structurally from
    // the visible label only after the descendant input itself is visible.
    const domLabels = frame.locator('label').filter({ hasText: label });
    const domLabelCount = await domLabels.count().catch(() => 0);
    for (let index = 0; index < domLabelCount; index += 1) {
      const input = domLabels.nth(index).locator('input').first();
      if (await input.count().catch(() => 0) && await input.isVisible().catch(() => false)) {
        return input;
      }
    }

    const text = frame.getByText(label, { exact: true }).first();
    if (await text.count().catch(() => 0)) {
      const containers = [
        text.locator('xpath=..'),
        text.locator('xpath=../..'),
        text.locator('xpath=../../..'),
      ];
      for (const container of containers) {
        const input = container.locator('input').first();
        if (await input.count().catch(() => 0) && await input.isVisible().catch(() => false)) {
          return input;
        }
      }
    }
    await sleep(300);
  }
  throw new Error(`Timed out waiting for visible input: ${label}`);
}

async function fillInput(frame, label, value) {
  const input = await labelledInput(frame, label, 60_000);
  await input.fill(String(value), { timeout: 15_000 });
  await input.press('Tab').catch(() => {});
  await sleep(800);
}
'''
if old not in text:
    raise SystemExit("labelledInput patch target not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
