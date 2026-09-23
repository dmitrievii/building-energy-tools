from pathlib import Path

path = Path("deployment/pr83_monthly_selected_load_smoke.mjs")
text = path.read_text(encoding="utf-8")

old = '''async function setResolution(page, resolution) {
  if (resolution !== 'Native') {
    throw new Error(`Stage7 native-monthly acceptance only supports Native resolution, got ${resolution}.`);
  }
  for (let attempt = 0; attempt < 4; attempt += 1) {
    let frame = await appFrame(page, 'Time series and overlay', 10000);
    let control = await combo(frame, 'Series 1 resolution', 10000);
    let current = await rendered(control);
    if (current.includes('Native')) {
      await sleep(700);
      return;
    }

    await control.click({ timeout: 5000 }).catch(() => {});
    await control.press('Home', { timeout: 5000 }).catch(() => {});
    await control.press('Enter', { timeout: 5000 }).catch(() => {});
    await sleep(800);

    frame = await appFrame(page, 'Time series and overlay', 10000);
    control = await combo(frame, 'Series 1 resolution', 10000);
    current = await rendered(control);
    if (current.includes('Native')) {
      await sleep(700);
      return;
    }

    await control.click({ timeout: 5000 }).catch(() => {});
    const option = await visibleOption(page, frame, (text) => text.trim() === 'Native');
    if (option) {
      await option.click({ timeout: 5000 });
      await sleep(800);
    }
  }

  const frame = await appFrame(page, 'Time series and overlay', 10000);
  const control = await combo(frame, 'Series 1 resolution', 10000);
  const current = await rendered(control);
  throw new Error(`Could not commit Series 1 resolution = Native; observed ${current}.`);
}
'''

new = '''async function setResolution(page, resolution) {
  if (resolution !== 'Native') {
    throw new Error(`Stage7 native-monthly acceptance only supports Native resolution, got ${resolution}.`);
  }

  let lastValue = '';
  for (let attempt = 0; attempt < 5; attempt += 1) {
    let frame = await appFrame(page, 'Time series and overlay', 10000);
    let control = await combo(frame, 'Series 1 resolution', 10000);
    lastValue = await rendered(control);
    if (lastValue.includes('Native')) {
      await sleep(700);
      return;
    }

    // Prefer an explicit visible Native option.  This is stronger than relying
    // on BaseWeb's Home-key behaviour, which did not commit under headless CI.
    await control.click({ timeout: 5000 });
    await sleep(250);
    const option = await visibleOption(page, frame, (text) => text.trim() === 'Native');
    if (option) {
      await option.click({ timeout: 5000 });
    } else if (lastValue.includes('Monthly')) {
      // Monthly immediately follows Native in available_resolution_labels().
      // Move one item upward in the open BaseWeb list and commit it.
      await page.keyboard.press('ArrowUp').catch(() => {});
      await page.keyboard.press('Enter').catch(() => {});
    } else {
      await page.keyboard.press('Home').catch(() => {});
      await page.keyboard.press('Enter').catch(() => {});
    }
    await sleep(1000);

    frame = await appFrame(page, 'Time series and overlay', 10000);
    control = await combo(frame, 'Series 1 resolution', 10000);
    lastValue = await rendered(control);
    if (lastValue.includes('Native')) {
      await sleep(700);
      return;
    }
  }

  throw new Error(`Could not commit Series 1 resolution = Native; observed ${lastValue}.`);
}
'''

if old not in text:
    raise SystemExit("Expected Stage7 setResolution block not found for Native option fix")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
