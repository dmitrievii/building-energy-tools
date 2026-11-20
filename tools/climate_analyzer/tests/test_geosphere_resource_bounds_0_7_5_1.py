from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from epw_climate_analyzer.source_parity_resource_bounds import (
    hourly_request_date_bounds, hourly_station_validity_warning, resource_start_date,
)


class GeoSphereResourceBoundsTests(unittest.TestCase):
    def test_published_resource_start_dates(self) -> None:
        self.assertEqual(resource_start_date("klima-v2-1h"), date(1880, 4, 1))
        self.assertEqual(resource_start_date("klima-v2-10min"), date(1992, 5, 20))

    def test_hourly_request_extent_does_not_use_station_record_dates(self) -> None:
        station = SimpleNamespace(valid_from="1911-01-01", valid_to="2005-01-31")
        metadata = {
            "start_time": "1880-04-01T00:00:00Z",
            "stations": [{"valid_from": station.valid_from, "valid_to": station.valid_to}],
        }
        lower, upper = hourly_request_date_bounds(metadata, today=date(2026, 11, 20))
        self.assertEqual((lower, upper), (date(1880, 4, 1), date(2026, 11, 20)))
        self.assertTrue(lower <= date(2025, 1, 1) <= date(2025, 5, 31) <= upper)
        self.assertIn("2005-01-31", hourly_station_validity_warning(
            station, date(2025, 1, 1), date(2025, 5, 31)
        ))
        self.assertIsNone(hourly_station_validity_warning(
            station, date(2004, 1, 1), date(2004, 12, 31)
        ))

    def test_hourly_resource_extent_respects_actual_source_bounds_and_today(self) -> None:
        today = date(2026, 11, 20)
        self.assertEqual(hourly_request_date_bounds({
            "start_time": "1900-01-01T00:00:00Z", "end_time": "2025-12-31T23:00:00Z",
        }, today=today), (date(1900, 1, 1), date(2025, 12, 31)))
        self.assertEqual(hourly_request_date_bounds({
            "end_time": "2030-01-01T00:00:00Z",
        }, today=today)[1], today)
        self.assertEqual(hourly_request_date_bounds({}, today=today)[0], date(1880, 4, 1))

    def test_unknown_resource_has_no_invented_bound(self) -> None:
        self.assertIsNone(resource_start_date("future-resource"))


if __name__ == "__main__":
    unittest.main()
