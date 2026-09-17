from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd
import requests

from epw_climate_analyzer.geosphere import (
    DEFAULT_BATCH_DATAPOINTS,
    GEOSPHERE_NATIVE_INTERVAL_MINUTES,
    MAX_REQUEST_DATAPOINTS,
    estimate_request_datapoints,
    fetch_station_provider_frame,
    plan_data_queries,
)


def payload(start_minute: int, values: list[float]) -> dict[str, object]:
    timestamps = [
        f"2025-01-01T00:{start_minute + 10 * i:02d}+00:00"
        for i in range(len(values))
    ]
    return {
        "timestamps": timestamps,
        "features": [
            {
                "properties": {
                    "station": 11240,
                    "parameters": {"tl": {"data": values}},
                }
            }
        ],
    }


def http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"HTTP {status}", response=response)


class GeoSphereTransport065Tests(unittest.TestCase):
    def test_default_planner_uses_conservative_batches_below_hard_cap(self) -> None:
        self.assertLess(DEFAULT_BATCH_DATAPOINTS, MAX_REQUEST_DATAPOINTS)
        start = pd.Timestamp("2020-01-01T00:00:00Z")
        steps = DEFAULT_BATCH_DATAPOINTS * 2 + 1
        end = start + pd.Timedelta(minutes=GEOSPHERE_NATIVE_INTERVAL_MINUTES * (steps - 1))
        queries = plan_data_queries("11240", start, end, ["tl"])
        self.assertEqual(len(queries), 3)
        for query in queries:
            q_start = pd.Timestamp(query["start"], tz="UTC")
            q_end = pd.Timestamp(query["end"], tz="UTC")
            self.assertLessEqual(
                estimate_request_datapoints(q_start, q_end, 1),
                DEFAULT_BATCH_DATAPOINTS,
            )

    def test_transient_timeout_retries_only_current_batch_then_succeeds(self) -> None:
        planned = [
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:00",
                "end": "2025-01-01T00:10",
            }
        ]
        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(
            "epw_climate_analyzer.geosphere._bounded_get_json",
            side_effect=[requests.ReadTimeout("slow provider"), payload(0, [1.0, 2.0])],
        ) as getter, patch("epw_climate_analyzer.geosphere.time.sleep") as sleeper:
            frame, references = fetch_station_provider_frame(
                station_id="11240",
                start=pd.Timestamp("2025-01-01T00:00:00Z"),
                end=pd.Timestamp("2025-01-01T00:10:00Z"),
                provider_parameters=["tl"],
            )
        self.assertEqual(getter.call_count, 2)
        sleeper.assert_called_once()
        self.assertEqual(frame["tl"].tolist(), [1.0, 2.0])
        self.assertEqual(len(references), 1)

    def test_repeated_timeout_splits_only_failed_batch_without_overlap(self) -> None:
        planned = [
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:00",
                "end": "2025-01-01T00:30",
            }
        ]
        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(
            "epw_climate_analyzer.geosphere._bounded_get_json",
            side_effect=[
                requests.ReadTimeout("slow provider"),
                requests.ReadTimeout("still slow"),
                payload(0, [1.0, 2.0]),
                payload(20, [3.0, 4.0]),
            ],
        ) as getter, patch("epw_climate_analyzer.geosphere.time.sleep"):
            frame, references = fetch_station_provider_frame(
                station_id="11240",
                start=pd.Timestamp("2025-01-01T00:00:00Z"),
                end=pd.Timestamp("2025-01-01T00:30:00Z"),
                provider_parameters=["tl"],
            )
        self.assertEqual(getter.call_count, 4)
        self.assertEqual(frame["tl"].tolist(), [1.0, 2.0, 3.0, 4.0])
        self.assertFalse(frame.index.has_duplicates)
        self.assertEqual(len(references), 2)
        self.assertIn("start=2025-01-01T00%3A00", references[0])
        self.assertIn("end=2025-01-01T00%3A10", references[0])
        self.assertIn("start=2025-01-01T00%3A20", references[1])
        self.assertIn("end=2025-01-01T00%3A30", references[1])

    def test_503_is_retryable_but_permanent_400_fails_immediately(self) -> None:
        planned = [
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:00",
                "end": "2025-01-01T00:10",
            }
        ]
        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(
            "epw_climate_analyzer.geosphere._bounded_get_json",
            side_effect=[http_error(503), payload(0, [1.0, 2.0])],
        ) as getter, patch("epw_climate_analyzer.geosphere.time.sleep"):
            frame, _ = fetch_station_provider_frame(
                station_id="11240",
                start=pd.Timestamp("2025-01-01T00:00:00Z"),
                end=pd.Timestamp("2025-01-01T00:10:00Z"),
                provider_parameters=["tl"],
            )
        self.assertEqual(getter.call_count, 2)
        self.assertEqual(frame["tl"].tolist(), [1.0, 2.0])

        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(
            "epw_climate_analyzer.geosphere._bounded_get_json",
            side_effect=http_error(400),
        ) as getter, patch("epw_climate_analyzer.geosphere.time.sleep") as sleeper:
            with self.assertRaises(requests.HTTPError):
                fetch_station_provider_frame(
                    station_id="11240",
                    start=pd.Timestamp("2025-01-01T00:00:00Z"),
                    end=pd.Timestamp("2025-01-01T00:10:00Z"),
                    provider_parameters=["tl"],
                )
        self.assertEqual(getter.call_count, 1)
        sleeper.assert_not_called()

    def test_response_size_failure_splits_directly_without_same_size_retry(self) -> None:
        planned = [
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:00",
                "end": "2025-01-01T00:30",
            }
        ]
        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(
            "epw_climate_analyzer.geosphere._bounded_get_json",
            side_effect=[
                ValueError("GeoSphere response exceeds the local response-size limit."),
                payload(0, [1.0, 2.0]),
                payload(20, [3.0, 4.0]),
            ],
        ) as getter, patch("epw_climate_analyzer.geosphere.time.sleep") as sleeper:
            frame, references = fetch_station_provider_frame(
                station_id="11240",
                start=pd.Timestamp("2025-01-01T00:00:00Z"),
                end=pd.Timestamp("2025-01-01T00:30:00Z"),
                provider_parameters=["tl"],
            )
        self.assertEqual(getter.call_count, 3)
        sleeper.assert_not_called()
        self.assertEqual(frame["tl"].tolist(), [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(len(references), 2)

    def test_single_interval_persistent_timeout_fails_closed(self) -> None:
        planned = [
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:00",
                "end": "2025-01-01T00:00",
            }
        ]
        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(
            "epw_climate_analyzer.geosphere._bounded_get_json",
            side_effect=requests.ReadTimeout("provider unavailable"),
        ) as getter, patch("epw_climate_analyzer.geosphere.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "single-interval batch failed"):
                fetch_station_provider_frame(
                    station_id="11240",
                    start=pd.Timestamp("2025-01-01T00:00:00Z"),
                    end=pd.Timestamp("2025-01-01T00:00:00Z"),
                    provider_parameters=["tl"],
                )
        self.assertEqual(getter.call_count, 2)


if __name__ == "__main__":
    unittest.main()
