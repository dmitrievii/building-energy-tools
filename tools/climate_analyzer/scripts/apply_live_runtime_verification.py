"""One-shot patcher for VIS-0.1.1 live runtime verification.

The script is removed by its GitHub Actions runner after the patched production
sources and tests pass.  It exists only to safely edit large source files through
a reproducible CI gate.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "tools" / "climate_analyzer" / "app.py"
AUDIT = ROOT / "deployment" / "live_browser_audit.mjs"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"VIS-0.1.1 anchor missing: {label}")
    return text.replace(old, new, 1)


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")

    import_anchor = """    queue_navigation_reset,\n)\n\n\n_MAP_DEPENDENCIES_LOADED = False\n"""
    import_replacement = """    queue_navigation_reset,\n)\nfrom epw_climate_analyzer.chart_theme import metric_color\nfrom epw_climate_analyzer.runtime_identity import RUNTIME_BUILD_ID\n\n\n_MAP_DEPENDENCIES_LOADED = False\n"""
    if "from epw_climate_analyzer.runtime_identity import RUNTIME_BUILD_ID" not in text:
        text = replace_once(text, import_anchor, import_replacement, "app runtime imports")

    marker_anchor = 'st.set_page_config(page_title=APP_BROWSER_TITLE, layout="wide", page_icon="🌦️")\n\n'
    marker_block = '''st.set_page_config(page_title=APP_BROWSER_TITLE, layout="wide", page_icon="🌦️")\n\n# Hidden machine-readable deployment identity.  The live browser audit compares\n# this source-derived fingerprint with the exact checked-out source set before a\n# deployment is considered current.  The semantic GHI colour is included as a\n# direct visual-contract sentinel for VIS-0.1.\n_RUNTIME_GHI_COLOR = metric_color("global_horizontal_radiation_wh_m2")\nst.markdown(\n    (\n        '<span id="climate-analyzer-runtime-build" '\n        f'data-runtime-build="{html.escape(RUNTIME_BUILD_ID, quote=True)}" '\n        f'data-ghi-color="{html.escape(_RUNTIME_GHI_COLOR, quote=True)}" '\n        'aria-hidden="true" style="display:none"></span>'\n    ),\n    unsafe_allow_html=True,\n)\n\n'''
    if 'id="climate-analyzer-runtime-build"' not in text:
        text = replace_once(text, marker_anchor, marker_block, "app runtime DOM marker")

    APP.write_text(text, encoding="utf-8")


def patch_audit() -> None:
    text = AUDIT.read_text(encoding="utf-8")

    if "import crypto from 'node:crypto';" not in text:
        text = replace_once(
            text,
            "import fs from 'node:fs/promises';\n",
            "import fs from 'node:fs/promises';\nimport crypto from 'node:crypto';\n",
            "audit crypto import",
        )

    expected_anchor = "const expectedCatalogManifest = JSON.parse(await fs.readFile(CATALOG_MANIFEST_PATH, 'utf8'));\n\n"
    expected_block = """const expectedCatalogManifest = JSON.parse(await fs.readFile(CATALOG_MANIFEST_PATH, 'utf8'));\nconst TOOL_ROOT = 'tools/climate_analyzer';\nconst PACKAGE_ROOT = path.join(TOOL_ROOT, 'epw_climate_analyzer');\nconst EXPECTED_GHI_COLOR = '#F59E0B';\n\nasync function runtimeSourceFiles() {\n  const entries = await fs.readdir(PACKAGE_ROOT, { withFileTypes: true });\n  const packageFiles = entries\n    .filter((entry) => entry.isFile() && entry.name.endsWith('.py'))\n    .map((entry) => path.join(PACKAGE_ROOT, entry.name))\n    .sort();\n  return [\n    path.join(TOOL_ROOT, 'app.py'),\n    path.join(TOOL_ROOT, 'requirements.txt'),\n    ...packageFiles,\n  ];\n}\n\nasync function expectedRuntimeBuildId() {\n  const hash = crypto.createHash('sha256');\n  for (const file of await runtimeSourceFiles()) {\n    const relative = path.relative(TOOL_ROOT, file).split(path.sep).join('/');\n    hash.update(Buffer.from(relative, 'utf8'));\n    hash.update(Buffer.from([0]));\n    hash.update(await fs.readFile(file));\n    hash.update(Buffer.from([0]));\n  }\n  return hash.digest('hex');\n}\n\nconst EXPECTED_RUNTIME_BUILD_ID = await expectedRuntimeBuildId();\n\n"""
    if "const EXPECTED_RUNTIME_BUILD_ID" not in text:
        text = replace_once(text, expected_anchor, expected_block, "expected runtime fingerprint")

    marker_anchor = """async function leafletTileZoom(frame) {\n"""
    marker_functions = """async function readRuntimeMarker(page) {\n  for (const frame of page.frames()) {\n    const marker = frame.locator('#climate-analyzer-runtime-build').first();\n    if (!(await marker.count().catch(() => 0))) continue;\n    return {\n      frame_url: frame.url(),\n      build_id: await marker.getAttribute('data-runtime-build').catch(() => null),\n      ghi_color: await marker.getAttribute('data-ghi-color').catch(() => null),\n    };\n  }\n  return { frame_url: null, build_id: null, ghi_color: null };\n}\n\nfunction runtimeMatchesExpected(runtime) {\n  return runtime?.build_id === EXPECTED_RUNTIME_BUILD_ID\n    && String(runtime?.ghi_color || '').toUpperCase() === EXPECTED_GHI_COLOR;\n}\n\nasync function waitForExpectedRuntimeBuild(browser, timeoutMs = 480_000, intervalMs = 15_000) {\n  const started = performance.now();\n  const attempts = [];\n  while (performance.now() - started < timeoutMs) {\n    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });\n    const page = await context.newPage();\n    let runtime = { frame_url: null, build_id: null, ghi_color: null };\n    let error = null;\n    try {\n      await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });\n      await waitForFrameContaining(page, 'Climate Analyzer', 60_000);\n      await sleep(1_000);\n      runtime = await readRuntimeMarker(page);\n    } catch (exc) {\n      error = String(exc);\n    } finally {\n      await context.close();\n    }\n    const matchesExpected = runtimeMatchesExpected(runtime);\n    attempts.push({\n      elapsed_ms: Math.round(performance.now() - started),\n      build_id: runtime.build_id,\n      ghi_color: runtime.ghi_color,\n      matches_expected: matchesExpected,\n      error,\n    });\n    if (matchesExpected) {\n      return {\n        matches_expected: true,\n        elapsed_ms: Math.round(performance.now() - started),\n        attempts,\n        runtime,\n      };\n    }\n    await sleep(intervalMs);\n  }\n  const last = attempts.at(-1) || null;\n  return {\n    matches_expected: false,\n    elapsed_ms: Math.round(performance.now() - started),\n    attempts,\n    runtime: last ? { build_id: last.build_id, ghi_color: last.ghi_color } : null,\n  };\n}\n\nasync function leafletTileZoom(frame) {\n"""
    if "async function readRuntimeMarker(page)" not in text:
        text = replace_once(text, marker_anchor, marker_functions, "runtime marker reader and propagation wait")

    runtime_capture_anchor = """  const appText = await bodyText(appFrame);\n  const pageText = await bodyText(page.mainFrame());\n"""
    runtime_capture_replacement = """  const appText = await bodyText(appFrame);\n  const pageText = await bodyText(page.mainFrame());\n  const runtimeBuild = await readRuntimeMarker(page);\n"""
    if "const runtimeBuild = await readRuntimeMarker(page);" not in text:
        text = replace_once(text, runtime_capture_anchor, runtime_capture_replacement, "viewport runtime capture")

    result_anchor = """    resource_limit_visible: resourceLimitVisible,\n    viewport_metrics: viewportMetrics,\n"""
    result_replacement = """    resource_limit_visible: resourceLimitVisible,\n    runtime_build: runtimeBuild,\n    viewport_metrics: viewportMetrics,\n"""
    if "runtime_build: runtimeBuild" not in text:
        text = replace_once(text, result_anchor, result_replacement, "viewport runtime result")

    text = text.replace("schema: 'building-energy-tools-live-audit-v3'", "schema: 'building-energy-tools-live-audit-v4'", 1)

    report_anchor = """  expected_catalog: { version: expectedCatalogManifest.catalog_version, records: expectedCatalogManifest.station_count, sha256: expectedCatalogManifest.csv_sha256 },\n  target_url: TARGET_URL,\n"""
    report_replacement = """  expected_catalog: { version: expectedCatalogManifest.catalog_version, records: expectedCatalogManifest.station_count, sha256: expectedCatalogManifest.csv_sha256 },\n  expected_runtime: { build_id: EXPECTED_RUNTIME_BUILD_ID, ghi_color: EXPECTED_GHI_COLOR },\n  runtime_preflight: null,\n  target_url: TARGET_URL,\n"""
    if "expected_runtime: { build_id: EXPECTED_RUNTIME_BUILD_ID" not in text:
        text = replace_once(text, report_anchor, report_replacement, "report expected runtime")

    browser_anchor = """  report.browser = {\n    desktop: await runViewportAudit(browser, 'desktop', { width: 1440, height: 1000 }),\n    mobile: await runViewportAudit(browser, 'mobile', { width: 390, height: 844 }),\n  };\n"""
    browser_replacement = """  report.runtime_preflight = await waitForExpectedRuntimeBuild(browser);\n  report.browser = {\n    desktop: await runViewportAudit(browser, 'desktop', { width: 1440, height: 1000 }),\n    mobile: await runViewportAudit(browser, 'mobile', { width: 390, height: 844 }),\n  };\n"""
    if "report.runtime_preflight = await waitForExpectedRuntimeBuild(browser);" not in text:
        text = replace_once(text, browser_anchor, browser_replacement, "runtime propagation preflight invocation")

    critical_anchor = """const critical = [];\nconst findings = [];\nfor (const view of views) {\n"""
    critical_replacement = """const critical = [];\nconst findings = [];\nif (!report.runtime_preflight?.matches_expected) {\n  critical.push(\n    `live runtime build does not match checked-out source after propagation wait `\n    + `(expected ${EXPECTED_RUNTIME_BUILD_ID}/${EXPECTED_GHI_COLOR}, `\n    + `observed ${report.runtime_preflight?.runtime?.build_id ?? 'missing'}/${report.runtime_preflight?.runtime?.ghi_color ?? 'missing'}).`\n  );\n}\nfor (const view of views) {\n  if (!runtimeMatchesExpected(view.runtime_build)) {\n    critical.push(\n      `${view.name}: live runtime build does not match checked-out source `\n      + `(expected ${EXPECTED_RUNTIME_BUILD_ID}/${EXPECTED_GHI_COLOR}, `\n      + `observed ${view.runtime_build?.build_id ?? 'missing'}/${view.runtime_build?.ghi_color ?? 'missing'}).`\n    );\n  }\n"""
    if "live runtime build does not match checked-out source after propagation wait" not in text:
        text = replace_once(text, critical_anchor, critical_replacement, "critical runtime freshness gates")

    md_anchor = """  `- First unauthenticated HTTP response: ${report.first_http_response.status ?? 'ERROR'} (${report.first_http_response.elapsed_ms} ms)`,\n  '',\n  '## Browser summary',\n"""
    md_replacement = """  `- First unauthenticated HTTP response: ${report.first_http_response.status ?? 'ERROR'} (${report.first_http_response.elapsed_ms} ms)`,\n  `- Expected runtime build: ${EXPECTED_RUNTIME_BUILD_ID}`,\n  `- Expected GHI semantic colour: ${EXPECTED_GHI_COLOR}`,\n  `- Runtime propagation preflight matched: ${report.runtime_preflight?.matches_expected ?? false}`,\n  `- Runtime propagation wait: ${report.runtime_preflight?.elapsed_ms ?? 'n/a'} ms`,\n  '',\n  '## Browser summary',\n"""
    if "Expected runtime build:" not in text:
        text = replace_once(text, md_anchor, md_replacement, "markdown runtime preflight summary")

    view_md_anchor = """    `- UI detected: ${view.app_visible}`,\n    `- App frame: ${view.app_frame_url}`,\n"""
    view_md_replacement = """    `- UI detected: ${view.app_visible}`,\n    `- App frame: ${view.app_frame_url}`,\n    `- Runtime build: ${view.runtime_build?.build_id ?? 'missing'}`,\n    `- Runtime GHI semantic colour: ${view.runtime_build?.ghi_color ?? 'missing'}`,\n    `- Runtime matches checked-out source: ${runtimeMatchesExpected(view.runtime_build)}`,\n"""
    if "Runtime matches checked-out source:" not in text:
        text = replace_once(text, view_md_anchor, view_md_replacement, "markdown viewport runtime summary")

    AUDIT.write_text(text, encoding="utf-8")


def main() -> None:
    patch_app()
    patch_audit()
    print("VIS-0.1.1 live runtime verification patch applied")


if __name__ == "__main__":
    main()
