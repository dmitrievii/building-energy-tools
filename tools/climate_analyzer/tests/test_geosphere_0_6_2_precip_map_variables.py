from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.historical_capabilities import available_historical_pages
from epw_climate_analyzer.precipitation import occurrence_hours, occurrence_records, precipitation_summary

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class GeoSphere062PrecipitationSnowTests(unittest.TestCase):
    @staticmethod
    def frame(freq: str, periods: int = 6) -> pd.DataFrame:
        idx = pd.date_range("2026-01-01T00:00:00Z", periods=periods, freq=freq)
        frame = pd.DataFrame(
            {
                "liquid_precipitation_depth_mm": [0.2] * periods,
                "snow_depth_cm": [2.0] * periods,
                "season": ["Winter"] * periods,
            },
            index=idx,
        )
        return frame

    def test_snow_cover_duration_is_cadence_aware(self) -> None:
        ten = self.frame("10min")
        ten.attrs["canonical_native_interval_minutes"] = 10
        hourly = self.frame("1h")
        hourly.attrs["canonical_native_interval_minutes"] = 60
        self.assertAlmostEqual(float(occurrence_hours(ten, "snow_depth_cm", 0.0, "Daily", inclusive=False).iloc[0, 0]), 1.0)
        self.assertAlmostEqual(float(occurrence_hours(hourly, "snow_depth_cm", 0.0, "Daily", inclusive=False).iloc[0, 0]), 6.0)
        self.assertAlmostEqual(float(precipitation_summary(ten)["snow_cover_hours"]), 1.0)
        self.assertAlmostEqual(float(precipitation_summary(hourly)["snow_cover_hours"]), 6.0)

    def test_precipitation_occurrence_remains_record_count_not_duration(self) -> None:
        ten = self.frame("10min")
        ten.attrs["canonical_native_interval_minutes"] = 10
        counts = occurrence_records(ten, "liquid_precipitation_depth_mm", 0.1, "Daily")
        self.assertEqual(float(counts.iloc[0, 0]), 6.0)
        self.assertEqual(counts.columns.tolist(), ["records"])

    def test_missing_timestamp_gap_adds_no_snow_duration(self) -> None:
        idx = pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:10:00Z",
            "2026-01-01T01:00:00Z",
        ])
        frame = pd.DataFrame({"snow_depth_cm": [1.0, 1.0, 1.0], "season": ["Winter"] * 3}, index=idx)
        frame.attrs["canonical_native_interval_minutes"] = 10
        hours = occurrence_hours(frame, "snow_depth_cm", 0.0, "Daily", inclusive=False)
        self.assertAlmostEqual(float(hours.iloc[0, 0]), 0.5)

    def test_historical_precipitation_page_is_observation_gated(self) -> None:
        rr = pd.DataFrame({"liquid_precipitation_depth_mm": [0.0, 0.2]}, index=pd.date_range("2026-01-01", periods=2, freq="10min", tz="UTC"))
        sh = pd.DataFrame({"snow_depth_cm": [0.0, 1.0]}, index=rr.index)
        empty = pd.DataFrame({"liquid_precipitation_depth_mm": [pd.NA, pd.NA]}, index=rr.index)
        self.assertIn("Precipitation and Snow", available_historical_pages(rr))
        self.assertIn("Precipitation and Snow", available_historical_pages(sh))
        self.assertNotIn("Precipitation and Snow", available_historical_pages(empty))


class GeoSphere062UiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_variable_selection_is_one_editable_checkbox_table(self) -> None:
        self.assertIn('st.markdown("#### Measured variables to load")', self.source)
        self.assertIn("edited_variables = st.data_editor(", self.source)
        self.assertIn('st.column_config.CheckboxColumn("Load"', self.source)
        self.assertNotIn('key="geosphere_provider_parameters"', self.source)
        self.assertNotIn('with st.expander("Measured variables and provenance"', self.source)

    def test_geosphere_map_reuses_find_climate_persistent_map_engine(self) -> None:
        self.assertIn("GeoSphere uses the same persistent clustered Leaflet engine as Find climate", self.source)
        self.assertIn("station_catalog_persistent_map_layers(", self.source)
        self.assertIn("marker_payload=marker_payload", self.source)
        self.assertIn('returned_objects=["last_object_clicked_tooltip"]', self.source)
        self.assertIn('key=f"geosphere_selectable_cluster_map_', self.source)
        self.assertIn('tiles="OpenStreetMap"', self.source)

    def test_precipitation_ui_keeps_source_occurrence_and_duration_semantically_separate(self) -> None:
        # 0.7 deliberately routes occurrence and thresholded snow-state duration
        # through the provider-native frame. Conserved totals/duration stay on
        # the canonical hourly analysis frame.
        self.assertIn("counts = occurrence_records(", self.source)
        self.assertIn('source_df,\n            "liquid_precipitation_depth_mm"', self.source)
        self.assertIn('y="records"', self.source)
        self.assertIn('counts = occurrence_hours(source_df, "snow_depth_cm"', self.source)
        self.assertIn("Precipitation-record occurrence", self.source)
        self.assertIn("Source records meeting threshold", self.source)
        self.assertIn("active native cadence", self.source)
        self.assertIn("record-occurrence metric, not rainfall duration", self.source)
        self.assertIn("source-state cadence", self.source)
        self.assertIn('elif page == "Precipitation and Snow":', self.source)
        self.assertNotIn("Precipitation-interval occurrence", self.source)
        self.assertNotIn("Analysis intervals meeting threshold", self.source)


if __name__ == "__main__":
    unittest.main()
