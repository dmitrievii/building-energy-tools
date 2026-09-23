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
  await sleep(700);
}
'''
if old not in text:
    raise SystemExit("Expected staged setResolution block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
