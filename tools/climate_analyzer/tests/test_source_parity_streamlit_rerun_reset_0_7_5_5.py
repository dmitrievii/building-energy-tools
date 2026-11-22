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
