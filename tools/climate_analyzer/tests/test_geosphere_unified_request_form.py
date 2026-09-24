from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest

import pandas as pd

from epw_climate_analyzer.geosphere_request_form import (
    COMMITTED_REQUEST_KEY,
    STAGED_REQUEST_KEY,
    GeoSphereRequestForm,
    GeoSphereRequestState,
)


class GeoSphereUnifiedRequestStateTests(unittest.TestCase):
    def _form(self, resource_id: str, station_id: str = "105") -> tuple[SimpleNamespace, GeoSphereRequestForm]:
        st = SimpleNamespace(
            session_state={
                "geosphere_resource_id": resource_id,
                "geosphere_selected_station_id": station_id,
            }
        )
        return st, GeoSphereRequestForm(st)

    def test_same_request_schema_is_used_for_all_three_resources(self) -> None:
        for resource_id in ("klima-v2-10min", "klima-v2-1h", "klima-v2-1m"):
            with self.subTest(resource_id=resource_id):
                st, form = self._form(resource_id)
                form.capture_date("geosphere_start_date", date(2020, 1, 1))
                form.capture_date("geosphere_end_date", date(2020, 12, 31))
                state = form.capture_editor(
                    pd.DataFrame(
                        {
                            "Selected": [True, False],
                            "Quality flag": [True, True],
                            "Provider": ["tl", "rf"],
                            "Canonical field": ["dry_bulb_temperature_c", "relative_humidity_pct"],
                        }
                    )
                )
                self.assertEqual(state.resource_id, resource_id)
                self.assertEqual(state.station_id, "105")
                self.assertEqual(state.provider_parameters, ("tl",))
                self.assertEqual(state.quality_flags, ("tl_flag",))
                self.assertEqual(state.canonical_fields, ("dry_bulb_temperature_c",))
                self.assertTrue(state.is_loadable)
                self.assertIn(STAGED_REQUEST_KEY, st.session_state)

    def test_scope_change_does_not_reuse_previous_provider_selection(self) -> None:
        st, form = self._form("klima-v2-1h")
        form.capture_editor(pd.DataFrame({"Selected": [True], "Provider": ["tl"]}))
        self.assertEqual(form.staged().provider_parameters, ("tl",))

        st.session_state["geosphere_resource_id"] = "klima-v2-1m"
        self.assertEqual(form.staged().resource_id, "klima-v2-1m")
        self.assertEqual(form.staged().provider_parameters, ())

        st.session_state["geosphere_selected_station_id"] = "16412"
        self.assertEqual(form.staged().station_id, "16412")
        self.assertEqual(form.staged().provider_parameters, ())

    def test_committed_request_is_an_explicit_snapshot(self) -> None:
        st, form = self._form("klima-v2-1m")
        form.capture_date("geosphere_start_date", "2020-01-01")
        form.capture_date("geosphere_end_date", "2025-12-31")
        form.capture_editor(
            pd.DataFrame(
                {
                    "Selected": [True, True, True],
                    "Provider": ["rf_mittel", "p", "tl_mittel"],
                    "Canonical field": ["", "", ""],
                }
            )
        )
        committed = form.commit()
        restored = GeoSphereRequestState.from_mapping(st.session_state[COMMITTED_REQUEST_KEY])
        self.assertEqual(restored, committed)
        self.assertEqual(
            committed.provider_parameters,
            ("rf_mittel", "p", "tl_mittel"),
        )
        self.assertTrue(committed.is_loadable)

    def test_roundtrip_is_serializable_mapping_not_streamlit_widget_object(self) -> None:
        state = GeoSphereRequestState(
            resource_id="klima-v2-1h",
            station_id="105",
            start_date=date(1990, 1, 1),
            end_date=date(2025, 12, 31),
            provider_parameters=("tl", "rf"),
            quality_flags=("tl_flag",),
            canonical_fields=("dry_bulb_temperature_c", "relative_humidity_pct"),
            catalogue_view="",
        )
        payload = state.to_mapping()
        self.assertEqual(payload["start_date"], "1990-01-01")
        self.assertEqual(payload["provider_parameters"], ["tl", "rf"])
        self.assertEqual(GeoSphereRequestState.from_mapping(payload), state)


class GeoSphereFragmentRuntimeContractTests(unittest.TestCase):
    def test_runtime_installs_request_boundary_before_freeze_and_uses_fragment(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "epw_climate_analyzer"
            / "source_parity_runtime.py"
        ).read_text(encoding="utf-8")
        install_pos = source.index("install_geosphere_request_form(parity)")
        freeze_pos = source.index("_freeze_session_geosphere_selector(proxy, parity)")
        self.assertLess(install_pos, freeze_pos)
        self.assertIn('fragment_factory = getattr(proxy.st, "fragment", None)', source)
        self.assertIn("fragment_factory(execute_geosphere_selector)", source)
        self.assertIn('"geosphere_request_form"', source)


if __name__ == "__main__":
    unittest.main()
