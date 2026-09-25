from __future__ import annotations

from types import SimpleNamespace
import unittest

import pandas as pd

from epw_climate_analyzer.geosphere import GEOSPHERE_RESOURCES
from epw_climate_analyzer.source_parity_contract_guidance_hotfix import (
    _english_measured_variable_table,
    _install_guidance_safe,
)


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeStreamlit:
    def __init__(self, resource_id: str) -> None:
        self.session_state = {
            "geosphere_resource_id": resource_id,
            "_geosphere_resource_selector_widget_v1": resource_id,
        }
        self.events: list[tuple[str, object]] = []

    def selectbox(self, label, options, *args, **kwargs):
        values = list(options)
        if label == "GeoSphere dataset":
            return self.session_state["_geosphere_resource_selector_widget_v1"]
        return values[int(kwargs.get("index", 0))]

    def info(self, body, *args, **kwargs):
        self.events.append(("info", str(body)))

    def caption(self, body, *args, **kwargs):
        self.events.append(("caption", str(body)))

    def write(self, body, *args, **kwargs):
        self.events.append(("write", str(body)))

    def markdown(self, body, *args, **kwargs):
        self.events.append(("markdown", str(body)))

    def expander(self, label, *args, **kwargs):
        self.events.append(("expander", str(label)))
        return _Context()

    def radio(self, label, options, *args, **kwargs):
        values = list(options)
        return values[int(kwargs.get("index", 0))]

    def data_editor(self, data, *args, **kwargs):
        self.events.append(("editor", data.copy() if isinstance(data, pd.DataFrame) else data))
        return data


class GeoSphereSubhourlyPresentationTests(unittest.TestCase):
    def test_english_labels_come_from_canonical_model_without_changing_identity(self) -> None:
        raw = pd.DataFrame(
            {
                "Selected": [False, True, False],
                "Provider": ["tl", "rf", "rr"],
                "Measured variable": ["Lufttemperatur 2m", "Relative Feuchte", "Niederschlagssumme"],
                "Canonical field": [
                    "dry_bulb_temperature_c",
                    "relative_humidity_pct",
                    "liquid_precipitation_depth_mm",
                ],
                "Unit": ["°C", "%", "mm"],
            }
        )

        for resource_id in ("klima-v2-10min", "klima-v2-1h"):
            translated = _english_measured_variable_table(raw, resource_id)
            self.assertEqual(translated["Provider"].tolist(), raw["Provider"].tolist())
            self.assertEqual(translated["Canonical field"].tolist(), raw["Canonical field"].tolist())
            self.assertEqual(translated["Selected"].tolist(), raw["Selected"].tolist())
            self.assertEqual(
                translated["Measured variable"].tolist(),
                [
                    "Outdoor dry-bulb air temperature",
                    "Outdoor relative humidity",
                    "Liquid precipitation depth per reported source interval",
                ],
            )

        # Presentation helper must not mutate its input frame.
        self.assertEqual(raw.loc[0, "Measured variable"], "Lufttemperatur 2m")

    def test_hourly_blue_context_moves_below_map_into_expander_and_editor_is_english(self) -> None:
        st = _FakeStreamlit("klima-v2-1h")
        raw = pd.DataFrame(
            {
                "Selected": [False, False],
                "Provider": ["tl", "rf"],
                "Measured variable": ["Lufttemperatur 2m", "Relative Feuchte"],
                "Canonical field": ["dry_bulb_temperature_c", "relative_humidity_pct"],
                "Unit": ["°C", "%"],
            }
        )
        context = (
            "Official GeoSphere Austria availability context (translated summary): "
            "the hourly dataset begins with Vienna sunshine-duration observations from 1880."
        )
        old_source = (
            "Authoritative source: GeoSphere Austria Stationsdaten-v2 (1 h) · "
            "https://doi.org/10.60669/9bdm-yq93"
        )

        def previous(_legacy, _original):
            st.info(context)
            st.caption(old_source)
            # This is the first normal block after the map/station-detail columns
            # in the mature source UI and therefore the required insertion point.
            st.markdown("#### Manual station selection")
            return st.data_editor(raw, key="geosphere_variable_editor")

        parity = SimpleNamespace(
            st=st,
            _render_geosphere_resource_selector=previous,
            available_resource_specs=lambda: tuple(GEOSPHERE_RESOURCES.values()),
            resource_spec=lambda resource_id: GEOSPHERE_RESOURCES[resource_id],
        )
        _install_guidance_safe(parity)
        parity._render_geosphere_resource_selector(object(), object())

        kinds = [kind for kind, _ in st.events]
        self.assertNotIn("info", kinds)
        self.assertIn(("expander", "About this GeoSphere hourly dataset"), st.events)
        self.assertIn(("write", context), st.events)
        self.assertTrue(
            any(
                kind == "caption"
                and str(value).startswith("Official source: GeoSphere Austria Station Data-v2 (1 h)")
                for kind, value in st.events
            )
        )

        expander_index = st.events.index(("expander", "About this GeoSphere hourly dataset"))
        manual_index = st.events.index(("markdown", "#### Manual station selection"))
        self.assertLess(expander_index, manual_index)

        editor_frames = [value for kind, value in st.events if kind == "editor"]
        self.assertEqual(len(editor_frames), 1)
        rendered = editor_frames[0]
        self.assertEqual(
            rendered["Measured variable"].tolist(),
            ["Outdoor dry-bulb air temperature", "Outdoor relative humidity"],
        )
        self.assertEqual(rendered["Provider"].tolist(), ["tl", "rf"])

    def test_ten_minute_editor_is_english_without_hourly_expander(self) -> None:
        st = _FakeStreamlit("klima-v2-10min")
        raw = pd.DataFrame(
            {
                "Selected": [False],
                "Provider": ["p"],
                "Measured variable": ["Luftdruck"],
                "Canonical field": ["atmospheric_station_pressure_pa"],
                "Unit": ["hPa"],
            }
        )

        def previous(_legacy, _original):
            return st.data_editor(raw, key="geosphere_variable_editor")

        parity = SimpleNamespace(
            st=st,
            _render_geosphere_resource_selector=previous,
            available_resource_specs=lambda: tuple(GEOSPHERE_RESOURCES.values()),
            resource_spec=lambda resource_id: GEOSPHERE_RESOURCES[resource_id],
        )
        _install_guidance_safe(parity)
        parity._render_geosphere_resource_selector(object(), object())

        self.assertNotIn(("expander", "About this GeoSphere hourly dataset"), st.events)
        editor_frames = [value for kind, value in st.events if kind == "editor"]
        self.assertEqual(editor_frames[0].loc[0, "Measured variable"], "Atmospheric station pressure")
        self.assertEqual(editor_frames[0].loc[0, "Provider"], "p")


if __name__ == "__main__":
    unittest.main()
