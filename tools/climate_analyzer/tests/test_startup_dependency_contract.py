from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = TOOL_ROOT / "app.py"


class StartupDependencyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = APP_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_heavy_dependencies_are_not_imported_at_module_scope(self) -> None:
        imported: set[str] = set()
        for node in self.tree.body:
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        forbidden = {
            "folium",
            "pandas",
            "plotly.express",
            "streamlit_folium",
            "epw_climate_analyzer.aggregations",
            "epw_climate_analyzer.catalog_runtime",
            "epw_climate_analyzer.charts",
            "epw_climate_analyzer.climate_sources",
            "epw_climate_analyzer.comparison",
            "epw_climate_analyzer.decisions",
            "epw_climate_analyzer.epw_parser",
            "epw_climate_analyzer.interpretations",
            "epw_climate_analyzer.psychrometrics",
            "epw_climate_analyzer.solar",
            "epw_climate_analyzer.statistics",
        }
        self.assertFalse(forbidden & imported, sorted(forbidden & imported))
        self.assertIn("streamlit", imported)
        self.assertIn("epw_climate_analyzer.ui_contract", imported)

    def test_map_dependencies_are_loaded_only_after_upload_path_returns(self) -> None:
        upload_branch = self.source.index('if source_mode == "Upload EPW":')
        upload_return = self.source.index("        return", upload_branch)
        map_gate = self.source.index("    _ensure_map_dependencies()", upload_return)
        find_heading = self.source.index('    st.subheader("Find a climate from Climate.OneBuilding")', map_gate)
        self.assertLess(upload_branch, upload_return)
        self.assertLess(upload_return, map_gate)
        self.assertLess(map_gate, find_heading)

    def test_analysis_dependencies_are_loaded_before_epw_derivation(self) -> None:
        main_start = self.source.index("def main() -> None:")
        source_return = self.source.index('    if page == "Climate File Source":', main_start)
        analysis_gate = self.source.index("    _ensure_analysis_dependencies(", source_return)
        load_call = self.source.index("    epw, full_df, issues = load_epw_from_bytes(", analysis_gate)
        self.assertLess(source_return, analysis_gate)
        self.assertLess(analysis_gate, load_call)

    def test_solar_and_comparison_are_explicit_optional_dependency_layers(self) -> None:
        self.assertIn("if include_solar and not _SOLAR_DEPENDENCIES_LOADED:", self.source)
        self.assertIn("if include_comparison and not _COMPARISON_DEPENDENCIES_LOADED:", self.source)
        self.assertIn('include_comparison=(page == "Compare Climates")', self.source)

    def test_lazy_dependency_gates_resolve_full_runtime_symbol_sets(self) -> None:
        code = textwrap.dedent(
            f"""
            import importlib.util
            from pathlib import Path

            app_path = Path({str(APP_PATH)!r})
            spec = importlib.util.spec_from_file_location("climate_analyzer_lazy_gate_test", app_path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)

            module._ensure_map_dependencies()
            assert module._MAP_DEPENDENCIES_LOADED
            for name in (
                "pd", "folium", "FastMarkerCluster", "MarkerCluster", "st_folium",
                "download_station_epw", "filter_station_catalog", "load_production_station_catalog",
            ):
                assert hasattr(module, name), name

            module._ensure_analysis_dependencies(include_solar=True, include_comparison=True)
            assert module._ANALYSIS_DEPENDENCIES_LOADED
            assert module._SOLAR_DEPENDENCIES_LOADED
            assert module._COMPARISON_DEPENDENCIES_LOADED
            for name in (
                "parse_epw", "add_degree_metrics", "add_psychrometric_properties",
                "heatmap_chart", "wind_rose_chart", "add_solar_position",
                "ClimateDataset", "psychrometric_comparison_chart", "px",
            ):
                assert hasattr(module, name), name
            print("LAZY_DEPENDENCY_RUNTIME_GATE=PASS")
            """
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(TOOL_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=TOOL_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + "\n" + result.stdout)
        self.assertIn("LAZY_DEPENDENCY_RUNTIME_GATE=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
