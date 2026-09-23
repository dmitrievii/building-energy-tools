from pathlib import Path

path = Path('deployment/interannual_overlay_browser_smoke.mjs')
text = path.read_text(encoding='utf-8')
anchor = "async function loadDataset(page) {\n"
if anchor not in text:
    raise SystemExit('loadDataset anchor not found')
insert = r'''async function allProviderStates(page) {
  let current = await resetEditor(page);
  let lastScrollTop = -1;
  const states = new Map();
  for (let scan = 0; scan < 40; scan += 1) {
    const rows = current.editor.locator('[role="grid"] tr[role="row"]');
    const count = await rows.count().catch(() => 0);
    for (let i = 0; i < count; i += 1) {
      const row = rows.nth(i);
      const provider = (await row.locator('[role="gridcell"][aria-colindex="4"]').textContent().catch(() => '')).trim();
      if (!provider) continue;
      const ariaRowIndex = Number(await row.getAttribute('aria-rowindex'));
      if (!Number.isFinite(ariaRowIndex) || ariaRowIndex < 2) continue;
      const load = String(await row.locator('[role="gridcell"][aria-colindex="1"]').first().textContent().catch(() => '')).trim().toLowerCase();
      states.set(provider, { provider, load, ariaRowIndex, dataIndex: ariaRowIndex - 2 });
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
    await sleep(300);
    current = await variableEditor(page);
  }
  return [...states.values()].sort((a, b) => a.dataIndex - b.dataIndex);
}

async function setProviderLoadState(page, providerName, expected) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const state = await providerState(page, providerName);
    if (state.load === expected) return state;
    if (!['true', 'false'].includes(state.load)) throw new Error(`Unexpected Load state for ${providerName}: ${state.load}`);
    await navigateToLoadCell(page, state, providerName);
    await page.keyboard.press('Space');
    await sleep(150);
    await page.keyboard.press('Tab').catch(() => {});
    const started = performance.now();
    while (performance.now() - started < 12000) {
      const after = await providerState(page, providerName).catch(() => null);
      if (after?.load === expected) return after;
      await sleep(300);
    }
  }
  throw new Error(`Could not set provider ${providerName} Load=${expected}.`);
}

async function selectOnlyProvider(page, providerName) {
  const initial = await allProviderStates(page);
  if (!initial.some((item) => item.provider === providerName)) {
    throw new Error(`Required provider ${providerName} is absent from measured-variable editor.`);
  }
  for (const item of initial) {
    if (item.provider !== providerName && item.load === 'true') {
      await setProviderLoadState(page, item.provider, 'false');
    }
  }
  await setProviderLoadState(page, providerName, 'true');
  const final = await allProviderStates(page);
  const selected = final.filter((item) => item.load === 'true').map((item) => item.provider);
  if (selected.length !== 1 || selected[0] !== providerName) {
    throw new Error(`Expected only ${providerName} selected before load, got: ${selected.join(', ')}`);
  }
  return final.find((item) => item.provider === providerName);
}

'''
text = text.replace(anchor, insert + anchor, 1)
old = "  await selectProvider(page, 'tl');\n  await loadDataset(page);"
new = "  await selectOnlyProvider(page, 'tl');\n  await loadDataset(page);"
if old not in text:
    raise SystemExit('provider selection callsite not found')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')
