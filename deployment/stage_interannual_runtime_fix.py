from pathlib import Path

ui = Path('tools/climate_analyzer/epw_climate_analyzer/source_parity_ui.py')
text = ui.read_text(encoding='utf-8')
old = '        table = monthly.reindex(range(1, 13)).rename("value").reset_index(names="month")\n'
new = '        table = monthly.reindex(range(1, 13)).rename_axis("month").reset_index(name="value")\n'
if text.count(old) != 1:
    raise SystemExit(f'source_parity_ui.py: expected exactly one pandas reset_index target, got {text.count(old)}')
ui.write_text(text.replace(old, new, 1), encoding='utf-8')

smoke = Path('deployment/interannual_overlay_browser_smoke.mjs')
text = smoke.read_text(encoding='utf-8')
old = '''async function selectProvider(page, provider) {
  const state = await providerState(page, provider);
  if (state.load === 'true') return;
  const current = await resetEditor(page);
  const box = await current.canvas.boundingBox();
  if (!box) throw new Error('Variable editor canvas has no box.');
  await current.canvas.click({ position: { x: Math.min(box.width - 10, box.width * 0.55), y: 52 }, force: true });
  await current.canvas.focus();
  await page.keyboard.press('Control+Home');
  for (let row = 0; row < state.dataIndex; row += 1) await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Space');
  const started = performance.now();
  while (performance.now() - started < 12000) {
    const after = await providerState(page, provider).catch(() => null);
    if (after?.load === 'true') return;
    await sleep(300);
  }
  throw new Error(`Could not select provider ${provider}.`);
}
'''
new = '''async function selectProvider(page, provider) {
  let state = await providerState(page, provider);
  if (state.load === 'true') return;
  if (state.load !== 'false') throw new Error(`Unexpected Load state for ${provider}: ${state.load}`);
  const expectedTestId = `glide-cell-0-${state.dataIndex}`;
  let lastSelectedTestId = null;
  let lastHomeTestId = null;
  let lastFocused = false;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    state = await providerState(page, provider);
    if (state.load === 'true') return;
    const current = await resetEditor(page);
    const box = await current.canvas.boundingBox().catch(() => null);
    if (!box || box.width < 100 || box.height < 80) { await sleep(250); continue; }
    await current.canvas.click({
      position: { x: Math.min(box.width - 10, box.width * 0.55), y: Math.min(box.height - 10, 52) },
      force: true,
      timeout: 5000,
    }).catch(() => {});
    await sleep(180);
    await current.canvas.focus();
    lastFocused = await current.canvas.evaluate((node) => document.activeElement === node).catch(() => false);
    if (!lastFocused) { await sleep(250); continue; }
    await page.keyboard.press('Control+Home');
    await sleep(250);
    const homeSelected = current.editor.locator('[role="gridcell"][aria-selected="true"]').first();
    lastHomeTestId = await homeSelected.getAttribute('data-testid').catch(() => null);
    if (lastHomeTestId !== 'glide-cell-0-0') { await sleep(350); continue; }
    for (let row = 0; row < state.dataIndex; row += 1) {
      await page.keyboard.press('ArrowDown');
      await sleep(40);
    }
    await sleep(300);
    const selected = current.editor.locator('[role="gridcell"][aria-selected="true"]').first();
    lastSelectedTestId = await selected.getAttribute('data-testid').catch(() => null);
    if (lastSelectedTestId !== expectedTestId) { await sleep(350); continue; }
    await page.keyboard.press('Space');
    const started = performance.now();
    while (performance.now() - started < 10000) {
      const after = await providerState(page, provider).catch(() => null);
      if (after?.load === 'true') return;
      await sleep(300);
    }
  }
  throw new Error(`Could not select provider ${provider}; focused=${lastFocused}, home=${lastHomeTestId}, selected=${lastSelectedTestId}, expected=${expectedTestId}.`);
}
'''
if text.count(old) != 1:
    raise SystemExit(f'interannual_overlay_browser_smoke.mjs: expected exactly one provider selector target, got {text.count(old)}')
smoke.write_text(text.replace(old, new, 1), encoding='utf-8')
