from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tools" / "climate_analyzer" / "app.py"
TEST = ROOT / "tools" / "climate_analyzer" / "tests" / "test_global_catalog_map_contract.py"
LIVE = ROOT / "deployment" / "live_browser_audit.mjs"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


app = APP.read_text(encoding="utf-8")
app = replace_once(
    app,
    "    global catalog_runtime_summary, load_production_station_catalog, station_provenance_text\n",
    "    global catalog_runtime_summary, load_production_station_catalog, load_station_catalog_manifest, station_provenance_text\n",
    label="map dependency globals",
)
app = replace_once(
    app,
    "        catalog_runtime_summary,\n        load_production_station_catalog,\n        station_provenance_text,\n",
    "        catalog_runtime_summary,\n        load_production_station_catalog,\n        load_station_catalog_manifest,\n        station_provenance_text,\n",
    label="catalog runtime imports",
)
app = replace_once(
    app,
    '''@st.cache_data(show_spinner=False)\ndef cached_station_catalog() -> pd.DataFrame:\n    """Load and cache the reviewed, versioned station catalog for the OSM map."""\n    return load_production_station_catalog()\n''',
    '''@st.cache_data(show_spinner=False)\ndef cached_station_catalog(catalog_version: str, catalog_sha256: str) -> pd.DataFrame:\n    """Load the reviewed catalog using immutable manifest identity as the cache key.\n\n    Streamlit may preserve ``st.cache_data`` entries across a source redeploy. A\n    no-argument cache therefore allowed the previous 20-record bootstrap DataFrame\n    to survive after the global catalog files had changed. Binding the cache entry\n    to both the catalog version and byte-level SHA prevents stale catalog reuse.\n    """\n    catalog = load_production_station_catalog()\n    if catalog.empty:\n        return catalog\n\n    actual_version = str(catalog["catalog_version"].iloc[0])\n    actual_sha256 = str(catalog["catalog_sha256"].iloc[0])\n    if actual_version != catalog_version or actual_sha256 != catalog_sha256:\n        raise RuntimeError(\n            "Station catalog cache identity mismatch: "\n            f"expected {catalog_version}/{catalog_sha256}, "\n            f"loaded {actual_version}/{actual_sha256}."\n        )\n    return catalog\n''',
    label="station catalog cache",
)
app = replace_once(
    app,
    '''    try:\n        catalog = cached_station_catalog()\n    except Exception as exc:\n''',
    '''    try:\n        manifest = load_station_catalog_manifest()\n        catalog = cached_station_catalog(manifest.catalog_version, manifest.csv_sha256)\n    except Exception as exc:\n''',
    label="station catalog caller",
)
APP.write_text(app, encoding="utf-8")


test = TEST.read_text(encoding="utf-8")
needle = '''    def test_global_map_default_capacity_covers_snapshot(self) -> None:\n'''
new_test = '''    def test_station_catalog_cache_is_bound_to_manifest_identity(self) -> None:\n        app = APP_PATH.read_text(encoding="utf-8")\n        self.assertIn(\n            "def cached_station_catalog(catalog_version: str, catalog_sha256: str)",\n            app,\n        )\n        self.assertIn("manifest = load_station_catalog_manifest()", app)\n        self.assertIn(\n            "cached_station_catalog(manifest.catalog_version, manifest.csv_sha256)",\n            app,\n        )\n        self.assertNotIn("def cached_station_catalog()", app)\n\n'''
test = replace_once(test, needle, new_test + needle, label="cache regression test insertion")
TEST.write_text(test, encoding="utf-8")


live = LIVE.read_text(encoding="utf-8")
live = replace_once(
    live,
    "const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';\n\nawait fs.mkdir(OUT_DIR, { recursive: true });\n",
    "const CHROME_PATH = process.env.CHROME_PATH || '/usr/bin/google-chrome';\nconst CATALOG_MANIFEST_PATH = process.env.CATALOG_MANIFEST_PATH || 'tools/climate_analyzer/epw_climate_analyzer/data/station_catalog.meta.json';\nconst expectedCatalogManifest = JSON.parse(await fs.readFile(CATALOG_MANIFEST_PATH, 'utf8'));\n\nawait fs.mkdir(OUT_DIR, { recursive: true });\n",
    label="live manifest identity",
)
helper_anchor = '''function domainSet(urls) {\n  return [...new Set([...urls].map((url) => {\n    try {\n      return new URL(url).hostname;\n    } catch {\n      return null;\n    }\n  }).filter(Boolean))].sort();\n}\n\n'''
helpers = '''function parseIntegerText(value) {\n  if (value == null) return null;\n  const cleaned = String(value).replace(/,/g, '').trim();\n  const parsed = Number.parseInt(cleaned, 10);\n  return Number.isFinite(parsed) ? parsed : null;\n}\n\nfunction parseLiveCatalogIdentity(text) {\n  const summary = text.match(/Versioned station catalog:\\s*([^·\\n]+?)\\s*·\\s*([\\d,]+)\\s+records/i);\n  const visible = text.match(/Visible catalog records after filters:\\s*([\\d,]+)\\s+of\\s+([\\d,]+)/i);\n  const displayedVersion = summary ? summary[1].trim() : null;\n  const displayedRecords = summary ? parseIntegerText(summary[2]) : null;\n  const filteredVisible = visible ? parseIntegerText(visible[1]) : null;\n  const filteredTotal = visible ? parseIntegerText(visible[2]) : null;\n  const expectedVersion = String(expectedCatalogManifest.catalog_version);\n  const expectedRecords = Number(expectedCatalogManifest.station_count);\n  return {\n    expected_version: expectedVersion,\n    expected_records: expectedRecords,\n    displayed_version: displayedVersion,\n    displayed_records: displayedRecords,\n    filtered_visible: filteredVisible,\n    filtered_total: filteredTotal,\n    matches_manifest: displayedVersion === expectedVersion\n      && displayedRecords === expectedRecords\n      && filteredTotal === expectedRecords,\n  };\n}\n\nasync function leafletTileZoom(frame) {\n  const urls = await frame.locator('img.leaflet-tile').evaluateAll((nodes) =>\n    nodes.map((node) => node.src || '').filter(Boolean)\n  ).catch(() => []);\n  const levels = [];\n  for (const raw of urls) {\n    try {\n      const match = new URL(raw).pathname.match(/^\\/(\\d+)\\//);\n      if (match) levels.push(Number.parseInt(match[1], 10));\n    } catch {\n      // Ignore non-URL tile placeholders.\n    }\n  }\n  return levels.length ? Math.max(...levels) : null;\n}\n\nasync function exerciseLeafletZoom(page, timeoutMs = 15_000) {\n  const started = performance.now();\n  while (performance.now() - started < timeoutMs) {\n    for (const frame of page.frames()) {\n      const zoomIn = frame.locator('.leaflet-control-zoom-in').first();\n      if (!(await zoomIn.count().catch(() => 0))) continue;\n      try {\n        const levels = [];\n        levels.push(await leafletTileZoom(frame));\n        await zoomIn.click({ timeout: 5_000 });\n        await sleep(1_200);\n        levels.push(await leafletTileZoom(frame));\n        await zoomIn.click({ timeout: 5_000 });\n        await sleep(1_200);\n        levels.push(await leafletTileZoom(frame));\n        const monotonic = levels.every((value) => Number.isInteger(value))\n          && levels[1] > levels[0]\n          && levels[2] > levels[1];\n        return { attempted: true, frame_url: frame.url(), levels, monotonic };\n      } catch (error) {\n        return { attempted: true, frame_url: frame.url(), levels: [], monotonic: false, error: String(error) };\n      }\n    }\n    await sleep(500);\n  }\n  return { attempted: false, frame_url: null, levels: [], monotonic: false };\n}\n\n'''
live = replace_once(live, helper_anchor, helper_anchor + helpers, label="live helpers")
live = replace_once(
    live,
    '''  const findClimate = {\n    attempted: false,\n    clicked: false,\n    openstreetmap_visible: false,\n    frame_attribution: [],\n  };\n''',
    '''  const findClimate = {\n    attempted: false,\n    clicked: false,\n    openstreetmap_visible: false,\n    frame_attribution: [],\n    catalog: null,\n    zoom_sequence: null,\n  };\n''',
    label="find climate result contract",
)
live = replace_once(
    live,
    '''        findClimate.clicked = true;\n        await sleep(5_000);\n        findClimate.frame_attribution = await collectAttribution(page);\n''',
    '''        findClimate.clicked = true;\n        await sleep(5_000);\n        const liveCatalogText = await bodyText(appFrame);\n        findClimate.catalog = parseLiveCatalogIdentity(liveCatalogText);\n        findClimate.zoom_sequence = await exerciseLeafletZoom(page);\n        findClimate.frame_attribution = await collectAttribution(page);\n''',
    label="live catalog and zoom capture",
)
live = replace_once(
    live,
    '''  if (view.find_climate.clicked && !view.find_climate.openstreetmap_visible) {\n    critical.push(`${view.name}: OpenStreetMap attribution was not detected after opening Find climate.`);\n  }\n''',
    '''  if (view.find_climate.clicked && !view.find_climate.openstreetmap_visible) {\n    critical.push(`${view.name}: OpenStreetMap attribution was not detected after opening Find climate.`);\n  }\n  if (view.find_climate.clicked && !view.find_climate.catalog?.matches_manifest) {\n    critical.push(\n      `${view.name}: live catalog does not match checked-out manifest `\n      + `(expected ${view.find_climate.catalog?.expected_version}/${view.find_climate.catalog?.expected_records}, `\n      + `displayed ${view.find_climate.catalog?.displayed_version}/${view.find_climate.catalog?.displayed_records}).`\n    );\n  }\n  if (view.find_climate.clicked && !view.find_climate.zoom_sequence?.monotonic) {\n    critical.push(\n      `${view.name}: two consecutive Leaflet zoom-in actions were not monotonic `\n      + `(levels=${JSON.stringify(view.find_climate.zoom_sequence?.levels || [])}).`\n    );\n  }\n''',
    label="live critical gates",
)
live = replace_once(
    live,
    '''    `- Find climate clicked: ${view.find_climate.clicked}`,\n    `- OSM attribution detected after Find climate: ${view.find_climate.openstreetmap_visible}`,\n''',
    '''    `- Find climate clicked: ${view.find_climate.clicked}`,\n    `- Live catalog matches checked-out manifest: ${view.find_climate.catalog?.matches_manifest ?? false}`,\n    `- Live catalog records: ${view.find_climate.catalog?.displayed_records ?? 'n/a'} / expected ${view.find_climate.catalog?.expected_records ?? 'n/a'}`,\n    `- Consecutive zoom-in levels: ${JSON.stringify(view.find_climate.zoom_sequence?.levels || [])}`,\n    `- Consecutive zoom monotonic: ${view.find_climate.zoom_sequence?.monotonic ?? false}`,\n    `- OSM attribution detected after Find climate: ${view.find_climate.openstreetmap_visible}`,\n''',
    label="live markdown evidence",
)
live = replace_once(
    live,
    "  schema: 'building-energy-tools-live-audit-v2',\n",
    "  schema: 'building-energy-tools-live-audit-v3',\n  expected_catalog: { version: expectedCatalogManifest.catalog_version, records: expectedCatalogManifest.station_count, sha256: expectedCatalogManifest.csv_sha256 },\n",
    label="live audit schema",
)
LIVE.write_text(live, encoding="utf-8")

print("CLIMATE-0.10.1 runtime cache + live gate patch applied")
