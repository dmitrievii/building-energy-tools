"""R2.18 HF3: reject a mixed-release Streamlit worker before named imports."""
from __future__ import annotations

import ast
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

from epw_climate_analyzer import chart_theme, runtime_identity

APP = Path(__file__).resolve().parents[1] / "app.py"


class _Stopped(Exception):
    pass


class HotDeployStartupTests(unittest.TestCase):
    def test_build_guard_precedes_package_consumers(self):
        source=APP.read_text(encoding="utf-8")
        self.assertLess(source.index("if RUNTIME_BUILD_ID != runtime_build_id():"),
                        source.index("from epw_climate_analyzer import byte_cache"))
        self.assertLess(source.index("getattr(_startup_chart_theme"),
                        source.index("from epw_climate_analyzer.chart_theme import metric_color"))
        ast.parse(source)

    def _expect_safe_stop(self, message):
        with patch("streamlit.error") as error, patch("streamlit.stop",side_effect=_Stopped):
            with self.assertRaises(_Stopped):
                runpy.run_path(str(APP),run_name="hf3_hotdeploy_fixture")
            self.assertIn(message,error.call_args.args[0])
            self.assertIn("Reboot app",error.call_args.args[0])

    def test_old_process_build_stops_before_named_import(self):
        with patch.object(runtime_identity,"RUNTIME_BUILD_ID","previous-release"):
            self._expect_safe_stop("previous build")

    def test_stale_palette_source_hash_stops_even_with_current_identity(self):
        with patch.object(runtime_identity,"RUNTIME_BUILD_ID",runtime_identity.runtime_build_id()):
            with patch.object(chart_theme,"_RUNTIME_SOURCE_SHA256","previous-release"):
                self._expect_safe_stop("older Climate Analyzer colour module")

    def test_missing_palette_symbol_stops_before_import_error(self):
        old=chart_theme.PASSIVE_STRATEGY_COLORS
        try:
            del chart_theme.PASSIVE_STRATEGY_COLORS
            with patch.object(runtime_identity,"RUNTIME_BUILD_ID",runtime_identity.runtime_build_id()):
                self._expect_safe_stop("older Climate Analyzer colour module")
            self.assertFalse(hasattr(chart_theme,"PASSIVE_STRATEGY_COLORS"))
        finally:
            chart_theme.PASSIVE_STRATEGY_COLORS=old

    def test_current_worker_does_not_reload_palette(self):
        original=chart_theme.metric_color
        # Execute just the startup prefix. No heavy libraries or app main.
        source=APP.read_text(encoding="utf-8")
        prefix=source[:source.index("from epw_climate_analyzer import byte_cache")]
        with patch.object(runtime_identity,"RUNTIME_BUILD_ID",runtime_identity.runtime_build_id()):
            with patch("streamlit.error") as error,patch("streamlit.stop",side_effect=_Stopped):
                exec(compile(prefix,str(APP),"exec"),{})
                error.assert_not_called()
        self.assertIs(chart_theme.metric_color,original)
