from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tools" / "climate_analyzer" / "app.py"
CHARTS = ROOT / "tools" / "climate_analyzer" / "epw_climate_analyzer" / "charts.py"
TEST = ROOT / "tools" / "climate_analyzer" / "tests" / "test_climate_0_10_3_regressions.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}; refusing blind patch")
    return text.replace(old, new, 1)


app = APP.read_text(encoding="utf-8")
app = replace_once(
    app,
    '''def _cached_station_catalog_by_identity(catalog_version: str, catalog_sha256: str) -> pd.DataFrame:\n    """Load one reviewed catalog snapshot under an immutable cache identity."""\n    catalog = load_production_station_catalog()\n''',
    '''def _cached_station_catalog_by_identity(catalog_version: str, catalog_sha256: str) -> pd.DataFrame:\n    """Load one reviewed catalog snapshot under an immutable cache identity."""\n    from epw_climate_analyzer.catalog_runtime import load_production_station_catalog\n\n    catalog = load_production_station_catalog()\n''',
    "catalog loader local import",
)
app = replace_once(
    app,
    '''    manifest = load_station_catalog_manifest()\n    return _cached_station_catalog_by_identity(manifest.catalog_version, manifest.csv_sha256)\n''',
    '''    from epw_climate_analyzer.catalog_runtime import load_station_catalog_manifest\n\n    manifest = load_station_catalog_manifest()\n    return _cached_station_catalog_by_identity(manifest.catalog_version, manifest.csv_sha256)\n''',
    "catalog manifest local import",
)
APP.write_text(app, encoding="utf-8")

charts = CHARTS.read_text(encoding="utf-8")
charts = replace_once(
    charts,
    '''    for zone_id in GIVONI_DRAW_ORDER\n]\n''',
    '''    for zone_id in sorted(GIVONI_ZONE_NAMES)\n]\n''',
    "Givoni public zone order",
)
charts = replace_once(
    charts,
    '''                name=f"{zone_id}. {zone_name}",\n                legendgroup=legend_group,\n                showlegend=True,\n''',
    '''                name=f"{zone_id}. {zone_name}",\n                legend="legend2",\n                legendgroup=legend_group,\n                legendrank=zone_id,\n                showlegend=True,\n''',
    "zone visible legend assignment",
)
charts = replace_once(
    charts,
    '''                name=f"{zone_id}. {short_label} label",\n                legendgroup=legend_group,\n                showlegend=False,\n''',
    '''                name=f"{zone_id}. {short_label} label",\n                legend="legend2",\n                legendgroup=legend_group,\n                legendrank=zone_id,\n                showlegend=False,\n''',
    "zone label legend assignment",
)
charts = replace_once(
    charts,
    '''                    name=f"Heat index {level:.0f} °C",\n                    legendgroup="Heat index",\n                    line=dict(width=1.1, color="rgba(185,28,28,0.75)", dash="dash"),\n''',
    '''                    name=f"Heat index {level:.0f} °C",\n                    legend="legend2",\n                    legendgroup="Heat index",\n                    legendrank=1000 + int(level),\n                    line=dict(width=1.1, color="rgba(185,28,28,0.75)", dash="dash"),\n''',
    "heat-index legend assignment",
)
charts = replace_once(
    charts,
    '''            for month in selected_months:\n                subset = data[data["month_index"] == month]\n''',
    '''            for month in sorted(set(selected_months)):\n                subset = data[data["month_index"] == month]\n''',
    "month stable order",
)
charts = replace_once(
    charts,
    '''                        name=MONTH_LABELS[month - 1],\n                        marker=dict(size=3.5, opacity=0.42, color=MONTH_COLORS[month - 1]),\n''',
    '''                        name=MONTH_LABELS[month - 1],\n                        legend="legend",\n                        legendgroup="months",\n                        legendrank=month,\n                        marker=dict(size=3.5, opacity=0.42, color=MONTH_COLORS[month - 1]),\n''',
    "month legend assignment",
)
charts = replace_once(
    charts,
    '''    fig.update_layout(\n        width=920,\n        height=920,\n        autosize=False,\n        hovermode="closest",\n        legend=dict(\n            orientation="h",\n            yanchor="top",\n            y=-0.22,\n            xanchor="center",\n            x=0.5,\n            itemsizing="constant",\n            font=dict(size=8),\n            groupclick="togglegroup",\n            traceorder="grouped",\n        ),\n        margin=dict(l=64, r=44, t=74, b=300),\n    )\n''',
    '''    fig.update_layout(\n        height=900,\n        autosize=True,\n        hovermode="closest",\n        legend=dict(\n            title=dict(text="Month", font=dict(size=13)),\n            orientation="h",\n            yanchor="top",\n            y=-0.12,\n            xanchor="left",\n            x=0.0,\n            itemsizing="constant",\n            font=dict(size=12),\n            groupclick="toggleitem",\n            traceorder="normal",\n        ),\n        legend2=dict(\n            title=dict(text="Zones", font=dict(size=13)),\n            orientation="h",\n            yanchor="top",\n            y=-0.28,\n            xanchor="left",\n            x=0.0,\n            itemsizing="constant",\n            font=dict(size=12),\n            groupclick="togglegroup",\n            traceorder="normal",\n        ),\n        margin=dict(l=64, r=44, t=74, b=340),\n    )\n''',
    "psychrometric responsive layout",
)
CHARTS.write_text(charts, encoding="utf-8")

TEST.write_text(
    '''from __future__ import annotations\n\nimport ast\nfrom pathlib import Path\nimport unittest\n\nimport pandas as pd\n\nfrom epw_climate_analyzer.charts import GIVONI_MILNE_ZONES, GIVONI_ZONE_NAMES, psychrometric_chart\n\n\nROOT = Path(__file__).resolve().parents[1]\nAPP_PATH = ROOT / "app.py"\n\n\nclass Climate0103RegressionTests(unittest.TestCase):\n    def test_catalog_cache_loaders_are_page_independent_local_imports(self) -> None:\n        source = APP_PATH.read_text(encoding="utf-8")\n        tree = ast.parse(source)\n        functions = {\n            node.name: node\n            for node in ast.walk(tree)\n            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))\n        }\n        expected = {\n            "_cached_station_catalog_by_identity": "load_production_station_catalog",\n            "cached_station_catalog": "load_station_catalog_manifest",\n        }\n        for function_name, imported_name in expected.items():\n            with self.subTest(function=function_name):\n                node = functions[function_name]\n                local_imports = {\n                    alias.name\n                    for child in ast.walk(node)\n                    if isinstance(child, ast.ImportFrom)\n                    and child.module == "epw_climate_analyzer.catalog_runtime"\n                    for alias in child.names\n                }\n                self.assertIn(imported_name, local_imports)\n\n    def test_psychrometric_chart_is_responsive_and_legend_is_split_and_sorted(self) -> None:\n        data = pd.DataFrame(\n            {\n                "dry_bulb_temperature_c": [8.0, 18.0, 28.0],\n                "humidity_ratio_g_kg": [3.0, 7.0, 11.0],\n                "month_index": [12, 1, 2],\n            }\n        )\n        fig = psychrometric_chart(\n            data,\n            chart_type="T-d",\n            show_rh_curves=False,\n            show_comfort_zone=True,\n            metric_layers=[],\n            shown_bioclimatic_zones=[GIVONI_ZONE_NAMES[3], GIVONI_ZONE_NAMES[1], GIVONI_ZONE_NAMES[2]],\n            selected_months=[12, 2, 1],\n            color_mode="Month",\n        )\n\n        self.assertTrue(fig.layout.autosize)\n        self.assertIsNone(fig.layout.width)\n        self.assertGreaterEqual(fig.layout.legend.font.size, 12)\n        self.assertGreaterEqual(fig.layout.legend2.font.size, 12)\n        self.assertEqual(fig.layout.legend.title.text, "Month")\n        self.assertEqual(fig.layout.legend2.title.text, "Zones")\n\n        month_traces = [\n            trace\n            for trace in fig.data\n            if getattr(trace, "legendgroup", None) == "months" and trace.showlegend is not False\n        ]\n        self.assertEqual([trace.name for trace in month_traces], ["Jan", "Feb", "Dec"])\n        self.assertTrue(all(getattr(trace, "legend", None) == "legend" for trace in month_traces))\n\n        zone_traces = [\n            trace\n            for trace in fig.data\n            if str(getattr(trace, "legendgroup", "")).startswith("givoni_zone_") and trace.showlegend is True\n        ]\n        self.assertTrue(all(getattr(trace, "legend", None) == "legend2" for trace in zone_traces))\n        ordered_zone_ids = [\n            int(trace.name.split(".", 1)[0])\n            for trace in sorted(zone_traces, key=lambda trace: float(trace.legendrank))\n        ]\n        self.assertEqual(ordered_zone_ids, [1, 2, 3])\n\n    def test_public_givoni_zone_options_are_numeric_order(self) -> None:\n        zone_ids = [int(zone["zone_id"]) for zone in GIVONI_MILNE_ZONES]\n        self.assertEqual(zone_ids, sorted(zone_ids))\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)

print("CLIMATE-0.10.3 remediation applied")
