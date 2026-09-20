from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer import geosphere
from epw_climate_analyzer.geosphere_monthly import (
    MONTHLY_DOI,
    MONTHLY_RESOURCE_ID,
    build_monthly_dataset,
    ensure_monthly_resource_registered,
    estimate_monthly_datapoints,
    month_count,
    monthly_coverage_table,
    monthly_parameter_mapping,
    plan_monthly_queries,
    selected_monthly_query_parameters,
    trim_monthly_empty_edges,
)
from epw_climate_analyzer.source_parity_resource_bounds import resource_start_date


class GeoSphereMonthlyResourceTests(unittest.TestCase):
    @staticmethod
    def metadata() -> dict:
        return {
            "parameters": [
                {
                    "name": "tl_mittel",
                    "long_name": "Lufttemperatur Monatsmittel",
                    "unit": "°C",
                    "description": "Monatsmittel der Lufttemperatur",
                },
                {
                    "name": "tl_mittel_flag",
                    "long_name": "Qualitätsflag Lufttemperatur",
                    "unit": "code",
                    "code_list_ref": "q1",
                },
                {
                    "name": "so_h",
                    "long_name": "Sonnenscheindauer",
                    "unit": "h",
                    "description": "Monatssumme Sonnenscheindauer",
                },
                {
                    "name": "tage_frost",
                    "long_name": "Frosttage",
                    "unit": "d",
                    "description": "Anzahl Frosttage im Monat",
                },
            ],
            "code_lists": {
                "q1": [
                    {"key": 10, "value": "automatisch geprüft"},
                    {"key": 20, "value": "manuell geprüft"},
                ]
            },
            "stations": [
                {
                    "id": "105",
                    "name": "Wien Hohe Warte",
                    "lat": 48.2486,
                    "lon": 16.3564,
                    "altitude": 198,
                    "state": "Wien",
                    "valid_from": "1872-01-01T00:00+00:00",
                    "valid_to": "2026-09-01T00:00+00:00",
                }
            ],
        }

    def setUp(self) -> None:
        ensure_monthly_resource_registered()

    def test_monthly_resource_is_registered_with_official_identity(self) -> None:
        spec = geosphere.resource_spec(MONTHLY_RESOURCE_ID)
        self.assertEqual(spec.doi, MONTHLY_DOI)
        self.assertEqual(spec.resource_id, MONTHLY_RESOURCE_ID)
        self.assertIn("month", spec.label.lower())
        self.assertEqual(resource_start_date(MONTHLY_RESOURCE_ID), pd.Timestamp("1767-12-01").date())

    def test_live_metadata_mapping_exposes_all_physical_fields_but_not_flags(self) -> None:
        mapping = monthly_parameter_mapping(self.metadata())
        self.assertEqual(set(mapping), {"tl_mittel", "so_h", "tage_frost"})
        self.assertEqual(mapping["tl_mittel"].canonical_name, "tl_mittel")
        self.assertEqual(mapping["tage_frost"].expected_units, ("d",))

    def test_quality_flags_are_opt_in(self) -> None:
        metadata = self.metadata()
        without = selected_monthly_query_parameters(metadata, ["tl_mittel", "so_h"])
        self.assertEqual(without, ("tl_mittel", "so_h"))
        with_flag = selected_monthly_query_parameters(
            metadata,
            ["tl_mittel", "so_h"],
            selected_flag_names=["tl_mittel_flag"],
        )
        self.assertEqual(with_flag, ("tl_mittel", "so_h", "tl_mittel_flag"))

    def test_calendar_month_count_and_estimate_do_not_assume_30_day_steps(self) -> None:
        start = pd.Timestamp("1767-12-17T00:00:00Z")
        end = pd.Timestamp("1768-03-02T00:00:00Z")
        self.assertEqual(month_count(start, end), 4)
        self.assertEqual(estimate_monthly_datapoints(start, end, 3, 1), 12)

    def test_monthly_batch_planner_uses_calendar_boundaries(self) -> None:
        queries = plan_monthly_queries(
            "105",
            pd.Timestamp("2020-01-15T00:00:00Z"),
            pd.Timestamp("2020-06-20T23:50:00Z"),
            ["tl_mittel", "so_h"],
            max_datapoints=4,  # 2 parameters -> at most 2 calendar months per batch
        )
        self.assertEqual(len(queries), 3)
        self.assertTrue(queries[0]["start"].startswith("2020-01-01"))
        self.assertTrue(queries[1]["start"].startswith("2020-03-01"))
        self.assertTrue(queries[2]["start"].startswith("2020-05-01"))
        self.assertTrue(queries[-1]["end"].startswith("2020-06-20"))

    def test_outer_trim_uses_union_of_selected_variables(self) -> None:
        index = pd.date_range("1880-01-01", periods=7, freq="MS", tz="UTC")
        frame = pd.DataFrame(
            {
                "so_h": [np.nan, 12.0, 20.0, 30.0, 40.0, np.nan, np.nan],
                "tl_mittel": [np.nan, np.nan, np.nan, 5.0, 8.0, 10.0, np.nan],
            },
            index=index,
        )
        trimmed = trim_monthly_empty_edges(frame, ["so_h", "tl_mittel"])
        self.assertEqual(trimmed.index[0], index[1])
        self.assertEqual(trimmed.index[-1], index[5])
        # Early sunshine survives even though temperature is still empty.
        self.assertEqual(float(trimmed.loc[index[1], "so_h"]), 12.0)
        self.assertTrue(pd.isna(trimmed.loc[index[1], "tl_mittel"]))

    def test_dataset_keeps_provider_monthly_fields_and_independent_coverage(self) -> None:
        metadata = self.metadata()
        station = geosphere.parse_stations(metadata)[0]
        index = pd.date_range("1940-11-01", periods=5, freq="MS", tz="UTC")
        provider = pd.DataFrame(
            {
                "so_h": [60.0, 55.0, 50.0, 80.0, 100.0],
                "tl_mittel": [np.nan, np.nan, 0.5, 1.0, 4.0],
                "tl_mittel_flag": [np.nan, np.nan, 20, 20, 10],
            },
            index=index,
        )
        dataset = build_monthly_dataset(
            station=station,
            provider_frame=provider,
            metadata=metadata,
            physical_parameters=["so_h", "tl_mittel"],
            requested_start=index[0],
            requested_end=index[-1],
        )
        self.assertEqual(dataset.data.attrs["geosphere_resource_id"], MONTHLY_RESOURCE_ID)
        self.assertIn("so_h", dataset.data.columns)
        self.assertIn("tl_mittel", dataset.data.columns)
        self.assertIn("quality_flag__tl_mittel", dataset.data.columns)
        coverage = monthly_coverage_table(dataset.data).set_index("Provider")
        self.assertEqual(coverage.loc["so_h", "First available"], "1940-11")
        self.assertEqual(coverage.loc["tl_mittel", "First available"], "1941-01")
        self.assertEqual(int(coverage.loc["so_h", "Available months"]), 5)
        self.assertEqual(int(coverage.loc["tl_mittel", "Available months"]), 3)


if __name__ == "__main__":
    unittest.main()
