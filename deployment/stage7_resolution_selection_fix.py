from pathlib import Path

path = Path("deployment/pr83_monthly_selected_load_smoke.mjs")
text = path.read_text(encoding="utf-8")
old = '''async function setResolution(page, resolution) {
  await selectComboOption(page, 'Series 1 resolution', (text) => text.trim() === resolution);
  await appFrame(page, 'Time series and overlay');
  await sleep(700);
}
'''
new = '''async function setResolution(page, resolution) {
  let frame = await appFrame(page, 'Time series and overlay');
  let control = await combo(frame, 'Series 1 resolution', 10000);
  let current = `${await control.textContent().catch(() => '')} ${await control.inputValue().catch(() => '')}`.replace(/\\s+/g, ' ').trim();
  if (current.includes(resolution)) return;

  await selectComboOption(page, 'Series 1 resolution', (text) => text.trim() === resolution);
  frame = await appFrame(page, 'Time series and overlay');
  control = await combo(frame, 'Series 1 resolution', 10000);
  current = `${await control.textContent().catch(() => '')} ${await control.inputValue().catch(() => '')}`.replace(/\\s+/g, ' ').trim();
  if (!current.includes(resolution)) {
    throw new Error(`Series 1 resolution did not commit ${resolution}; observed ${current}`);
  }
  await sleep(700);
}
'''
if old not in text:
    raise SystemExit("Expected staged setResolution block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
