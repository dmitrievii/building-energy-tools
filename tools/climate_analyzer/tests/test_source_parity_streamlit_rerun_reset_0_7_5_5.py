from __future__ import annotations

import unittest
from unittest.mock import patch

from epw_climate_analyzer import source_parity_runtime


class SourceParityStreamlitRerunResetTests(unittest.TestCase):
    def test_fresh_source_parity_ui_drops_persistent_selector_wrappers(self) -> None:
        parity = source_parity_runtime._fresh_source_parity_ui()
        base_selector = parity._render_geosphere_resource_selector

        def stale_wrapper(*args, **kwargs):
            return base_selector(*args, **kwargs)

        parity._render_geosphere_resource_selector = stale_wrapper
        self.assertIs(parity._render_geosphere_resource_selector, stale_wrapper)

        fresh = source_parity_runtime._fresh_source_parity_ui()
        self.assertIsNot(fresh._render_geosphere_resource_selector, stale_wrapper)
        self.assertEqual(fresh._render_geosphere_resource_selector.__name__, "_render_geosphere_resource_selector")

    def test_fresh_source_parity_ui_drops_persistent_transport_wrappers(self) -> None:
        parity = source_parity_runtime._fresh_source_parity_ui()
        base_mapping = parity.supported_parameter_mapping

        def stale_mapping(*args, **kwargs):
            return base_mapping(*args, **kwargs)

        parity.supported_parameter_mapping = stale_mapping
        self.assertIs(parity.supported_parameter_mapping, stale_mapping)

        fresh = source_parity_runtime._fresh_source_parity_ui()
        self.assertIsNot(fresh.supported_parameter_mapping, stale_mapping)
        self.assertEqual(fresh.supported_parameter_mapping.__name__, "supported_parameter_mapping")

    def test_twenty_binding_resets_preserve_pristine_function_and_class_identity(self) -> None:
        from epw_climate_analyzer import charts,timeseries
        parity=source_parity_runtime._fresh_source_parity_ui()
        selector=parity._render_geosphere_resource_selector
        chart=charts.profile_ribbon_chart
        overlay=timeseries.build_overlay_figure
        before=source_parity_runtime.runtime_stats()
        with patch.object(source_parity_runtime.importlib,"reload",side_effect=AssertionError("unexpected warm reload")):
            for _ in range(20):
                parity._render_geosphere_resource_selector=lambda *a,**k:None
                charts.profile_ribbon_chart=lambda *a,**k:None
                charts._R6_TEST_PATCHED=True
                self.assertIs(source_parity_runtime._fresh_source_parity_ui(),parity)
                self.assertIs(parity._render_geosphere_resource_selector,selector)
                self.assertIs(charts.profile_ribbon_chart,chart)
                self.assertIs(timeseries.build_overlay_figure,overlay)
                self.assertFalse(hasattr(charts,"_R6_TEST_PATCHED"))
        after=source_parity_runtime.runtime_stats()
        self.assertEqual(after["module_reloads"],before["module_reloads"])
        self.assertEqual(after["binding_resets"]-before["binding_resets"],20)

    def test_binding_reset_releases_session_specific_wrapper_reference(self) -> None:
        import gc,weakref
        parity=source_parity_runtime._fresh_source_parity_ui()
        class SessionObject:pass
        payload=SessionObject()
        reference=weakref.ref(payload)
        parity._render_geosphere_resource_selector=lambda *args,_payload=payload: _payload
        del payload
        self.assertIsNotNone(reference())
        source_parity_runtime._fresh_source_parity_ui()
        gc.collect()
        self.assertIsNone(reference())

    def test_heatmap_compatibility_guard_does_not_invalidate_warm_baseline(self) -> None:
        from types import SimpleNamespace
        import pandas as pd
        from epw_climate_analyzer import charts, runtime_module_guard
        # Exercise the actual legacy installer, followed by the same runtime
        # guard used in app.py before its next compatibility composition.
        runtime_module_guard.ensure_current_heatmap_runtime()
        parity=source_parity_runtime._fresh_source_parity_ui()
        before=source_parity_runtime.runtime_stats()
        with patch.object(source_parity_runtime.importlib,"reload",side_effect=AssertionError("unexpected warm reload")):
            for _ in range(100):
                from epw_climate_analyzer.source_parity_longterm_hotfix import install_longterm_hourly_hotfix
                proxy=SimpleNamespace(temporal_heatmap_chart=charts.temporal_heatmap_chart)
                install_longterm_hourly_hotfix(proxy,parity)
                self.assertIs(runtime_module_guard.ensure_current_heatmap_runtime(),charts)
                self.assertIs(source_parity_runtime._fresh_source_parity_ui(),parity)
        after=source_parity_runtime.runtime_stats()
        self.assertEqual(after["baseline_builds"],before["baseline_builds"])
        self.assertEqual(after["module_reloads"],before["module_reloads"])
        self.assertEqual(after["binding_resets"]-before["binding_resets"],100)

    def test_heatmap_wrapper_forwards_matrix_override(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import Mock
        import pandas as pd
        from epw_climate_analyzer import charts
        parity=source_parity_runtime._fresh_source_parity_ui()
        from epw_climate_analyzer.source_parity_longterm_hotfix import install_longterm_hourly_hotfix
        frame=pd.DataFrame({"dry_bulb_temperature_c":[20.]},index=pd.date_range("2025-01-01",periods=1,freq="h"))
        matrix=pd.DataFrame([[99.]])
        try:
            with patch.object(charts,"temporal_heatmap_chart",return_value=Mock()) as original:
                proxy=SimpleNamespace(temporal_heatmap_chart=charts.temporal_heatmap_chart)
                install_longterm_hourly_hotfix(proxy,parity)
                proxy.temporal_heatmap_chart(frame,"dry_bulb_temperature_c","Day","Month","Mean","Test","°C",matrix_override=matrix)
                self.assertIs(original.call_args.kwargs["matrix_override"],matrix)
        finally:
            source_parity_runtime._fresh_source_parity_ui()

    def test_temporal_filtering_reloads_before_timeseries(self) -> None:
        imported: list[str] = []

        def fake_import(name: str):
            imported.append(name.rsplit(".", 1)[-1])
            return object()

        with (
            patch.object(source_parity_runtime.importlib, "import_module", side_effect=fake_import),
            patch.object(source_parity_runtime.importlib, "reload", side_effect=lambda module: module),
        ):
            source_parity_runtime._reset_persistent_source_parity_modules()

        self.assertIn("temporal_filtering", imported)
        self.assertIn("timeseries", imported)
        self.assertLess(imported.index("temporal_filtering"), imported.index("timeseries"))


if __name__ == "__main__":
    unittest.main()
