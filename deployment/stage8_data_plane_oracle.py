from pathlib import Path
import re

path = Path("deployment/pr83_monthly_selected_load_smoke.mjs")
text = path.read_text(encoding="utf-8")

replacement = r'''async function inspectResolutionControl(page) {
  const frame = await appFrame(page, 'Time series and overlay', 10000);
  const control = await combo(frame, 'Series 1 resolution', 10000);
  const renderedValue = await rendered(control);
  const options = [];

  await control.click({ timeout: 5000 }).catch(() => {});
  await sleep(250);
  for (const candidates of [
    frame.getByRole('option'),
    page.getByRole('option'),
    frame.locator('[data-baseweb="menu"] li'),
    page.locator('[data-baseweb="menu"] li'),
  ]) {
    const count = await candidates.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const option = candidates.nth(index);
      if (!(await option.isVisible().catch(() => false))) continue;
      const value = (await option.innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
      if (value && !options.includes(value)) options.push(value);
    }
  }
  await page.keyboard.press('Escape').catch(() => {});
  return { rendered: renderedValue, visible_options: options };
}

async function plotSnapshot'''

pattern = re.compile(
    r"async function setResolution\(page, resolution\) \{.*?\n\}\n\nasync function plotSnapshot",
    flags=re.S,
)
matches = list(pattern.finditer(text))
if len(matches) != 1:
    raise SystemExit(f"Could not replace setResolution with observational oracle; matches={len(matches)}")
match = matches[0]
text = text[:match.start()] + replacement + text[match.end():]

old_call = "  await setResolution(page, 'Native');\n"
new_call = "  report.checks.resolution_ui = await inspectResolutionControl(page);\n"
if old_call not in text:
    raise SystemExit("Could not replace resolution interaction call")
text = text.replace(old_call, new_call, 1)

if "setResolution(" in text:
    raise SystemExit("Resolution-mutating browser interaction still present")
if "inspectResolutionControl(page)" not in text:
    raise SystemExit("Resolution observational oracle missing")

path.write_text(text, encoding="utf-8")
