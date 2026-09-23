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
