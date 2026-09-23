from pathlib import Path

path = Path('deployment/interannual_overlay_browser_smoke.mjs')
text = path.read_text()
start = text.index('async function variableEditor(page) {')
end = text.index('async function chooseTimeBasis(page) {')
replacement = r'''async function variableEditor(page) {
  const frame = await appFrame(page, 'Measured variables to load', 30000);
  const tables = frame.locator('[data-testid="stDataFrame"]');
  if (await tables.count() < 2) throw new Error('Measured-variable editor not found.');
  const editor = tables.last();
  const canvas = editor.locator('canvas[data-testid="data-grid-canvas"]').first();
  if (!(await canvas.count())) throw new Error('Measured-variable Glide canvas not found.');
  return { frame, editor, canvas };
}

async function resetEditor(page) {
  let current = await variableEditor(page);
  await current.editor.locator('.dvn-scroller').first().evaluate((node) => {
    node.scrollLeft = 0;
    node.scrollTop = 0;
    node.dispatchEvent(new Event('scroll', { bubbles: true }));
  }).catch(() => {});
  await sleep(450);
  return variableEditor(page);
}

async function providerState(page, providerName) {
  let current = await resetEditor(page);
  let lastScrollTop = -1;
  for (let scan = 0; scan < 40; scan += 1) {
    const rows = current.editor.locator('[role="grid"] tr[role="row"]');
    const count = await rows.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const row = rows.nth(i);
      const provider = (await row.locator('[role="gridcell"][aria-colindex="4"]').textContent().catch(() => '')).trim();
      if (provider !== providerName) continue;
      const ariaRowIndex = Number(await row.getAttribute('aria-rowindex'));
      if (!Number.isFinite(ariaRowIndex) || ariaRowIndex < 2) throw new Error(`Invalid row index for ${providerName}: ${ariaRowIndex}`);
      const load = String(await row.locator('[role="gridcell"][aria-colindex="1"]').first().textContent().catch(() => '')).trim().toLowerCase();
      return { ...current, load, ariaRowIndex, dataIndex: ariaRowIndex - 2 };
    }
    const scroll = await current.editor.locator('.dvn-scroller').first().evaluate((node) => {
      const before = node.scrollTop;
      const max = Math.max(0, node.scrollHeight - node.clientHeight);
      const step = Math.max(80, Math.floor(node.clientHeight * 0.75));
      node.scrollTop = Math.min(max, before + step);
      node.dispatchEvent(new Event('scroll', { bubbles: true }));
      return { before, after: node.scrollTop };
    }).catch(() => null);
    if (!scroll || scroll.after <= scroll.before || scroll.after === lastScrollTop) break;
    lastScrollTop = scroll.after;
    await sleep(350);
    current = await variableEditor(page);
  }
  throw new Error(`Provider parameter ${providerName} not visible while scanning the measured-variable editor.`);
}

async function navigateToLoadCell(page, state, providerName) {
  const expected = `glide-cell-0-${state.dataIndex}`;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const current = await resetEditor(page);
    const box = await current.canvas.boundingBox().catch(() => null);
    if (!box || box.width < 100 || box.height < 80) continue;
    await current.canvas.click({ position: { x: Math.min(box.width - 10, box.width * 0.55), y: Math.min(box.height - 10, 52) }, force: true, timeout: 5000 }).catch(() => {});
    await current.canvas.focus();
    await page.keyboard.press('Control+Home');
    await sleep(220);
    const selected = current.editor.locator('[role="gridcell"][aria-selected="true"]').first();
    if (await selected.getAttribute('data-testid').catch(() => null) !== 'glide-cell-0-0') continue;
    for (let row = 0; row < state.dataIndex; row += 1) {
      await page.keyboard.press('ArrowDown');
      await sleep(35);
    }
    await sleep(220);
    if (await selected.getAttribute('data-testid').catch(() => null) === expected) return;
  }
  throw new Error(`Could not address Load cell for ${providerName}.`);
}

async function selectProvider(page, providerName) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const state = await providerState(page, providerName);
    if (state.load === 'true') return state;
    if (state.load !== 'false') throw new Error(`Unexpected Load state for ${providerName}: ${state.load}`);
    await navigateToLoadCell(page, state, providerName);
    await page.keyboard.press('Space');
    await sleep(150);
    await page.keyboard.press('Tab').catch(() => {});
    const started = performance.now();
    while (performance.now() - started < 15000) {
      const frame = await appFrame(page, 'Measured variables to load', 10000).catch(() => null);
      if (frame) {
        const button = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
        if (await button.count().catch(() => 0)) {
          const committed = await providerState(page, providerName).catch(() => null);
          if (committed?.load === 'true') return committed;
        }
      }
      await sleep(300);
    }
  }
  throw new Error(`Could not commit Load selection for provider ${providerName}.`);
}

async function loadDataset(page) {
  const started = performance.now();
  while (performance.now() - started < 30000) {
    const frame = await appFrame(page, 'Measured variables to load', 10000);
    const button = frame.getByRole('button', { name: 'Load measured GeoSphere interval', exact: true }).first();
    if (await button.count().catch(() => 0)) {
      await button.click({ timeout: 15000 });
      return appFrame(page, 'Climate overview', 120000);
    }
    await sleep(300);
  }
  const state = await providerState(page, 'tl').catch(() => null);
  throw new Error(`GeoSphere load button did not appear after committed tl selection; tl=${state?.load ?? 'unavailable'}.`);
}

'''
patched = text[:start] + replacement + text[end:]
if patched == text:
    raise SystemExit('patch produced no change')
path.write_text(patched)
