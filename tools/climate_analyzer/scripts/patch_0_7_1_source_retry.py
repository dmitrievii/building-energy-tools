from pathlib import Path

root = Path(__file__).resolve().parents[3]
path = root / "deployment" / "geosphere_precip_snow_live_smoke.mjs"
text = path.read_text(encoding="utf-8")

insert_before = "async function labelledInput(frame, label, timeoutMs = 60_000) {\n"
helper = r'''async function chooseAndWait(page, name, expectedText, timeoutMs = 45_000) {
  const started = performance.now();
  let attempts = 0;
  while (performance.now() - started < timeoutMs) {
    attempts += 1;
    let frame;
    try {
      frame = await waitForFrameContaining(page, 'Climate Analyzer', 10_000);
    } catch {
      await sleep(500);
      continue;
    }

    const candidates = [
      frame.locator('label').filter({ hasText: name }).last(),
      frame.getByText(name, { exact: true }).last(),
      frame.getByRole('radio', { name, exact: true }).last(),
    ];

    for (const candidate of candidates) {
      if (!(await candidate.count().catch(() => 0))) continue;
      try {
        await candidate.scrollIntoViewIfNeeded({ timeout: 5_000 }).catch(() => {});
        const tagName = await candidate.evaluate((node) => node.tagName.toLowerCase()).catch(() => '');
        const inputType = await candidate.getAttribute('type').catch(() => null);
        if (tagName === 'input' && inputType === 'radio') {
          await candidate.check({ force: true, timeout: 5_000 });
        } else {
          await candidate.click({ force: true, timeout: 5_000 });
        }
      } catch {
        continue;
      }

      const verifyStarted = performance.now();
      while (performance.now() - verifyStarted < 6_000) {
        for (const currentFrame of page.frames()) {
          const textContent = await bodyText(currentFrame);
          if (textContent.includes(expectedText)) {
            return { frame: currentFrame, attempts };
          }
        }
        await sleep(300);
      }
    }

    await sleep(700);
  }
  throw new Error(`Timed out selecting ${name} and waiting for: ${expectedText}`);
}

'''
if helper not in text:
    if insert_before not in text:
        raise SystemExit("helper insertion point not found")
    text = text.replace(insert_before, helper + insert_before, 1)

old = """  await clickChoice(appFrame, 'GeoSphere Austria');\n  appFrame = await waitForFrameContaining(page, 'GeoSphere Austria — measured historical station data');\n  report.checks.geosphere_source_opened = true;\n"""
new = """  const sourceOpen = await chooseAndWait(\n    page,\n    'GeoSphere Austria',\n    'GeoSphere Austria — measured historical station data',\n    45_000,\n  );\n  appFrame = sourceOpen.frame;\n  report.checks.geosphere_source_opened = true;\n  report.checks.geosphere_source_attempts = sourceOpen.attempts;\n"""
if old not in text:
    raise SystemExit("GeoSphere source block not found")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
