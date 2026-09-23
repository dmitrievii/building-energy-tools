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
  const frame = await appFrame(page, 'Time series and overlay', 10000);
  const control = await combo(frame, 'Series 1 resolution', 10000);
  const current = await rendered(control);
  if (!current.includes('Native')) {
    throw new Error(`Series 1 resolution did not initialize to Native; observed ${current}.`);
  }
  await sleep(700);
}
'''

if old not in text:
    raise SystemExit("Expected Stage7 setResolution block not found for Native state assertion")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
