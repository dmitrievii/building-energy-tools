from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd
import requests

from epw_climate_analyzer.geosphere import fetch_station_provider_frame

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


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


class GeoSphereProgress067Tests(unittest.TestCase):
    def test_root_batch_progress_is_monotonic_and_denominator_is_stable(self) -> None:
        planned = [
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:00",
                "end": "2025-01-01T00:10",
            },
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:20",
                "end": "2025-01-01T00:30",
            },
        ]
        events: list[dict[str, object]] = []
        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(
            "epw_climate_analyzer.geosphere._bounded_get_json",
            side_effect=[payload(0, [1.0, 2.0]), payload(20, [3.0, 4.0])],
        ):
            frame, _ = fetch_station_provider_frame(
                station_id="11240",
                start=pd.Timestamp("2025-01-01T00:00:00Z"),
                end=pd.Timestamp("2025-01-01T00:30:00Z"),
                provider_parameters=["tl"],
                progress_callback=lambda event: events.append(dict(event)),
            )
        self.assertEqual(frame["tl"].tolist(), [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(
            [event["event"] for event in events],
            ["batch_start", "batch_complete", "batch_start", "batch_complete", "load_complete"],
        )
        self.assertEqual([int(event["total_batches"]) for event in events], [2, 2, 2, 2, 2])
        self.assertEqual([int(event["completed_batches"]) for event in events], [0, 1, 1, 2, 2])

    def test_retry_and_split_stay_inside_current_root_batch(self) -> None:
        planned = [
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:00",
                "end": "2025-01-01T00:30",
            }
        ]
        events: list[dict[str, object]] = []
        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(
            "epw_climate_analyzer.geosphere._bounded_get_json",
            side_effect=[
                requests.ReadTimeout("slow provider"),
                requests.ReadTimeout("still slow"),
                payload(0, [1.0, 2.0]),
                payload(20, [3.0, 4.0]),
            ],
        ), patch("epw_climate_analyzer.geosphere.time.sleep"):
            frame, _ = fetch_station_provider_frame(
                station_id="11240",
                start=pd.Timestamp("2025-01-01T00:00:00Z"),
                end=pd.Timestamp("2025-01-01T00:30:00Z"),
                provider_parameters=["tl"],
                progress_callback=lambda event: events.append(dict(event)),
            )
        self.assertEqual(frame["tl"].tolist(), [1.0, 2.0, 3.0, 4.0])
        retry = next(event for event in events if event["event"] == "retry")
        split = next(event for event in events if event["event"] == "split")
        self.assertEqual((retry["completed_batches"], retry["total_batches"], retry["batch_number"]), (0, 1, 1))
        self.assertEqual(int(retry["attempt"]), 2)
        self.assertEqual((split["completed_batches"], split["total_batches"], split["batch_number"]), (0, 1, 1))
        self.assertEqual(int(split["split_depth"]), 1)
        self.assertEqual(events[-1]["event"], "load_complete")
        self.assertEqual(int(events[-1]["completed_batches"]), 1)

    def test_progress_callback_failure_never_breaks_provider_load(self) -> None:
        planned = [
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:00",
                "end": "2025-01-01T00:10",
            }
        ]

        def broken_callback(_event) -> None:
            raise RuntimeError("UI renderer unavailable")

        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(
            "epw_climate_analyzer.geosphere._bounded_get_json",
            return_value=payload(0, [1.0, 2.0]),
        ):
            frame, _ = fetch_station_provider_frame(
                station_id="11240",
                start=pd.Timestamp("2025-01-01T00:00:00Z"),
                end=pd.Timestamp("2025-01-01T00:10:00Z"),
                provider_parameters=["tl"],
                progress_callback=broken_callback,
            )
        self.assertEqual(frame["tl"].tolist(), [1.0, 2.0])

    def test_load_complete_is_not_emitted_before_final_structural_validation(self) -> None:
        planned = [
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:00",
                "end": "2025-01-01T00:10",
            },
            {
                "parameters": "tl",
                "station_ids": "11240",
                "start": "2025-01-01T00:10",
                "end": "2025-01-01T00:20",
            },
        ]
        events: list[dict[str, object]] = []
        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(
            "epw_climate_analyzer.geosphere._bounded_get_json",
            side_effect=[payload(0, [1.0, 2.0]), payload(10, [3.0, 4.0])],
        ):
            with self.assertRaisesRegex(ValueError, "duplicate timestamps"):
                fetch_station_provider_frame(
                    station_id="11240",
                    start=pd.Timestamp("2025-01-01T00:00:00Z"),
                    end=pd.Timestamp("2025-01-01T00:20:00Z"),
                    provider_parameters=["tl"],
                    progress_callback=lambda event: events.append(dict(event)),
                )
        self.assertFalse(any(event["event"] == "load_complete" for event in events))
        self.assertEqual(events[-1]["event"], "batch_complete")
        self.assertEqual(int(events[-1]["completed_batches"]), 2)

    def test_public_ui_uses_determinate_progress_callback(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("progress_bar = st.progress(", source)
        self.assertIn("progress_callback=update_geosphere_progress", source)
        self.assertIn("planned batch(es) complete", source)
        self.assertIn("transient provider error", source)
        self.assertIn("splitting this batch", source)
        self.assertNotIn("Loading {len(batches)} bounded GeoSphere request batch(es)...", source)


if __name__ == "__main__":
    unittest.main()
