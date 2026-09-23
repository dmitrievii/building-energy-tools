from pathlib import Path

path = Path('deployment/interannual_overlay_browser_smoke.mjs')
text = path.read_text()
start = text.index('async function variableEditor(page) {')
end = text.index('async function chooseTimeBasis(page) {')
replacement = r'''async function variableEditor(page) {
  const frame = await appFrame(page, 'Measured variables to load', 30000);
  const tables = frame.locator('[data-testid="stDataFrame"]');
  if (await tables.count() < 2) throw new Error('Measured-variable data editor not found.');
  const editor = tables.last();
  const canvas = editor.locator('canvas[data-testid="data-grid-canvas"]').first();
  if (!(await canvas.count())) throw new Error('Measured-variable Glide canvas not found.');
  return { frame, editor, canvas };
}

async function scrollEditorBottom(editor) {
  return await editor.locator('.dvn-scroller').first().evaluate((node) => {
    node.scrollTop = node.scrollHeight;
    node.dispatchEvent(new Event('scroll', { bubbles: true }));
    return { scrollTop: node.scrollTop, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight };
  });
}

async function settledVariableEditor(page) {
  let current = await variableEditor(page);
  await scrollEditorBottom(current.editor);
  await sleep(1200);
  current = await variableEditor(page);
  return current;
}

async function providerState(page, providerName) {
  const { frame, editor, canvas } = await settledVariableEditor(page);
  const rows = editor.locator('[role="grid"] tr[role="row"]');
  const count = await rows.count();
  for (let index = 0; index < count; index += 1) {
    const row = rows.nth(index);
    const provider = (await row.locator('[role="gridcell"][aria-colindex="4"]').textContent().catch(() => '')).trim();
    if (provider !== providerName) continue;
    const load = (await row.locator('[role="gridcell"][aria-colindex="1"]').textContent().catch(() => '')).trim().toLowerCase();
    const ariaRowIndex = Number(await row.getAttribute('aria-rowindex'));
    if (!Number.isFinite(ariaRowIndex) || ariaRowIndex < 2) throw new Error(`Invalid Glide row index for ${providerName}: ${ariaRowIndex}`);
    return { frame, editor, canvas, provider, load, ariaRowIndex, dataIndex: ariaRowIndex - 2 };
  }
  throw new Error(`Provider parameter ${providerName} is not visible after scrolling the measured-variable editor to the bottom.`);
}

async function waitProviderLoadState(page, providerName, expected, timeoutMs = 12000) {
  const started = performance.now();
  let last = null;
  while (performance.now() - started < timeoutMs) {
    try {
      last = await providerState(page, providerName);
      if (last.load === expected) return last;
    } catch { /* rerun in flight */ }
    await sleep(300);
  }
  throw new Error(`Provider ${providerName} Load did not become ${expected}; last=${last?.load ?? 'unavailable'}.`);
}

async function navigateToLoadCell(page, state, providerName) {
  const expectedTestId = `glide-cell-0-${state.dataIndex}`;
  let lastSelectedTestId = null;
  let lastHomeTestId = null;
  let lastFocused = false;
  let lastMouseInitialized = false;
  for (let navigationAttempt = 0; navigationAttempt < 3; navigationAttempt += 1) {
    const current = await settledVariableEditor(page);
    const box = await current.canvas.boundingBox().catch(() => null);
    if (!box || box.width < 100 || box.height < 80) { await sleep(250); continue; }
    await current.canvas.click({
      position: { x: Math.min(box.width - 10, box.width * 0.55), y: Math.min(box.height - 10, 52) },
      force: true,
      timeout: 5000,
    }).catch(() => {});
    await sleep(180);
    lastMouseInitialized = true;
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
    if (lastSelectedTestId === expectedTestId) return expectedTestId;
    await sleep(350);
  }
  throw new Error(`Glide navigation could not address ${expectedTestId} for ${providerName}; mouseInitialized=${lastMouseInitialized}, focused=${lastFocused}, home=${lastHomeTestId}, last selected=${lastSelectedTestId}.`);
}

async function selectProvider(page, providerName) {
  let state = await providerState(page, providerName);
  if (state.load === 'true') return state;
  if (state.load !== 'false') throw new Error(`Unexpected Load state for ${providerName}: ${state.load}`);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    state = await providerState(page, providerName);
    if (state.load === 'true') return state;
    await navigateToLoadCell(page, state, providerName);
    await page.keyboard.press('Space');
    try { return await waitProviderLoadState(page, providerName, 'true', 10000); }
    catch { await sleep(500); }
  }
  throw new Error(`Could not toggle Load for provider ${providerName}.`);
}

async function loadDataset(page) {
  const state = await waitProviderLoadState(page, 'tl', 'true', 12000);
  const frame = state.frame;
  const button = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
  if (!(await button.count().catch(() => 0))) {
    throw new Error(`GeoSphere load button not found after selecting tl; tl=${state.load}, row=${state.ariaRowIndex}.`);
  }
  await button.click({ timeout: 15000 });
  return appFrame(page, 'Climate overview', 120000);
}

'''
patched = text[:start] + replacement + text[end:]
if patched == text:
    raise SystemExit('patch produced no change')
path.write_text(patched)
