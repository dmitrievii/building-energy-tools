from __future__ import annotations

from pathlib import Path
import unittest

from epw_climate_analyzer.geosphere import (
    CAPABILITY_RESOURCE_SUPPORTED,
    CAPABILITY_STATION_CONFIRMED,
    CAPABILITY_STATION_UNAVAILABLE,
    parse_stations,
    station_parameter_capability_index,
    station_parameter_capability_table,
)


PARAMETERS = [
    {"name": "tl", "long_name": "Lufttemperatur 2m", "unit": "°C", "description": ""},
    {"name": "rf", "long_name": "Relative Feuchte", "unit": "%", "description": ""},
    {"name": "cglo", "long_name": "Globalstrahlung Mittelwert", "unit": "W/m²", "description": ""},
    {"name": "chim", "long_name": "Himmelsstrahlung Mittelwert", "unit": "W/m²", "description": ""},
]

METADATA = {
    "parameters": PARAMETERS,
    "stations": [
        {
            "id": 1, "name": "Aflenz", "state": "Steiermark", "altitude": 783.2,
            "lat": 47.54594, "lon": 15.24069, "valid_from": "1983-05-01T00:00:00+00:00",
            "valid_to": "2100-12-31T00:00:00+00:00", "type": "COMBINED", "is_active": True,
            "has_global_radiation": True, "has_sunshine": True,
        },
        {
            "id": 2, "name": "NoRadiation", "state": "Test", "altitude": 500.0,
            "lat": 47.0, "lon": 14.0, "valid_from": "2000-01-01T00:00:00+00:00",
            "valid_to": "2100-12-31T00:00:00+00:00", "type": "CLIMATE", "is_active": False,
            "has_global_radiation": False, "has_sunshine": False,
        },
    ],
}


class GeoSphereMetadataCapabilityTests(unittest.TestCase):
    def test_station_metadata_fields_are_preserved(self) -> None:
        stations = parse_stations(METADATA)
        self.assertEqual(stations[0].station_type, "COMBINED")
        self.assertIs(stations[0].is_active, True)
        self.assertIs(stations[0].has_global_radiation, True)
        self.assertIs(stations[0].has_sunshine, True)

    def test_capability_index_is_station_keyed_and_conservative(self) -> None:
        index = station_parameter_capability_index(METADATA)
        self.assertEqual(index["1"]["cglo"], CAPABILITY_STATION_CONFIRMED)
        self.assertEqual(index["2"]["cglo"], CAPABILITY_STATION_UNAVAILABLE)
        self.assertEqual(index["2"]["tl"], CAPABILITY_RESOURCE_SUPPORTED)
        # No station-level diffuse-radiation flag exists; do not infer chim from cglo.
        self.assertEqual(index["2"]["chim"], CAPABILITY_RESOURCE_SUPPORTED)

    def test_capability_table_disables_only_authoritative_station_unavailability(self) -> None:
        table = station_parameter_capability_table(METADATA, "2").set_index("provider")
        self.assertFalse(bool(table.loc["cglo", "available"]))
        self.assertTrue(bool(table.loc["chim", "available"]))
        self.assertIn("station metadata", str(table.loc["cglo", "basis"]).lower())
        self.assertIn("period coverage", str(table.loc["tl", "basis"]).lower())


class GeoSphereMetadataPreviewUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.source = (root / "app.py").read_text(encoding="utf-8")

    def test_metadata_cache_is_resource_keyed_and_long_lived(self) -> None:
        self.assertIn("GEOSPHERE_METADATA_CACHE_TTL_SECONDS = 18 * 60 * 60", self.source)
        self.assertIn("def _cached_geosphere_metadata_bundle(resource_id: str)", self.source)
        self.assertIn("station_parameter_capability_index(metadata)", self.source)
        self.assertIn("return _cached_geosphere_metadata_bundle(GEOSPHERE_RESOURCE_ID)", self.source)

    def test_preview_does_not_issue_measurement_request(self) -> None:
        preview_pos = self.source.index('with st.expander("Measured-variable metadata"')
        load_button_pos = self.source.index('if st.button("Load measured GeoSphere interval"')
        fetch_pos = self.source.index("dataset = fetch_geosphere_station_dataset(")
        self.assertLess(preview_pos, load_button_pos)
        self.assertGreater(fetch_pos, load_button_pos)

    def test_unavailable_station_capability_is_not_in_checkbox_source(self) -> None:
        self.assertIn("selectable_supported = {", self.source)
        self.assertIn('!= "station-unavailable"', self.source)
        self.assertIn('st.column_config.CheckboxColumn("Load"', self.source)
        self.assertNotIn('key="geosphere_provider_parameters"', self.source)

    def test_map_hover_contains_metadata_without_changing_map_engine(self) -> None:
        self.assertIn("def geosphere_hover_name", self.source)
        self.assertIn("validity {valid_from} → {valid_to}", self.source)
        self.assertIn("station_catalog_persistent_map_layers(", self.source)
        self.assertIn('returned_objects=["last_object_clicked_tooltip"]', self.source)

    def test_ui_explains_station_vs_resource_level_capability(self) -> None:
        self.assertIn("No per-parameter validity dates are inferred.", self.source)
        self.assertIn("actual numeric coverage for the selected period is verified only after load", self.source)


if __name__ == "__main__":
    unittest.main()
