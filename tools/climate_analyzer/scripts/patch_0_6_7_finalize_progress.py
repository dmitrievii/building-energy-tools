from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GEOSPHERE = ROOT / "tools/climate_analyzer/epw_climate_analyzer/geosphere.py"
TEST = ROOT / "tools/climate_analyzer/tests/test_geosphere_progress_0_6_7.py"

source = GEOSPHERE.read_text(encoding="utf-8")
old = '''    if queries:\n        _emit_progress(\n            progress_callback,\n            event="load_complete",\n            completed_batches=total_batches,\n            total_batches=total_batches,\n            batch_number=total_batches,\n            query=queries[-1],\n        )\n\n    if not frames:\n        raise ValueError("GeoSphere batching produced no requests.")\n    combined = pd.concat(frames, axis=0)\n    if combined.empty:\n        raise ValueError("GeoSphere returned no timestamps for the selected interval.")\n    if combined.index.has_duplicates:\n        duplicate_count = int(combined.index.duplicated(keep=False).sum())\n        raise ValueError(f"GeoSphere batched response contains {duplicate_count} duplicate timestamps.")\n    combined = combined.sort_index(kind="mergesort")\n    return combined, tuple(references)\n'''
new = '''    if not frames:\n        raise ValueError("GeoSphere batching produced no requests.")\n    combined = pd.concat(frames, axis=0)\n    if combined.empty:\n        raise ValueError("GeoSphere returned no timestamps for the selected interval.")\n    if combined.index.has_duplicates:\n        duplicate_count = int(combined.index.duplicated(keep=False).sum())\n        raise ValueError(f"GeoSphere batched response contains {duplicate_count} duplicate timestamps.")\n    combined = combined.sort_index(kind="mergesort")\n    _emit_progress(\n        progress_callback,\n        event="load_complete",\n        completed_batches=total_batches,\n        total_batches=total_batches,\n        batch_number=total_batches,\n        query=queries[-1],\n    )\n    return combined, tuple(references)\n'''
if old not in source:
    raise SystemExit("expected geosphere load_complete block not found")
GEOSPHERE.write_text(source.replace(old, new, 1), encoding="utf-8")

test_source = TEST.read_text(encoding="utf-8")
anchor = '''    def test_public_ui_uses_determinate_progress_callback(self) -> None:\n'''
addition = '''    def test_load_complete_is_not_emitted_before_final_structural_validation(self) -> None:\n        planned = [\n            {\n                "parameters": "tl",\n                "station_ids": "11240",\n                "start": "2025-01-01T00:00",\n                "end": "2025-01-01T00:10",\n            },\n            {\n                "parameters": "tl",\n                "station_ids": "11240",\n                "start": "2025-01-01T00:10",\n                "end": "2025-01-01T00:20",\n            },\n        ]\n        events: list[dict[str, object]] = []\n        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(\n            "epw_climate_analyzer.geosphere._bounded_get_json",\n            side_effect=[payload(0, [1.0, 2.0]), payload(10, [3.0, 4.0])],\n        ):\n            with self.assertRaisesRegex(ValueError, "duplicate timestamps"):\n                fetch_station_provider_frame(\n                    station_id="11240",\n                    start=pd.Timestamp("2025-01-01T00:00:00Z"),\n                    end=pd.Timestamp("2025-01-01T00:20:00Z"),\n                    provider_parameters=["tl"],\n                    progress_callback=lambda event: events.append(dict(event)),\n                )\n        self.assertFalse(any(event["event"] == "load_complete" for event in events))\n        self.assertEqual(events[-1]["event"], "batch_complete")\n        self.assertEqual(int(events[-1]["completed_batches"]), 2)\n\n'''
if anchor not in test_source:
    raise SystemExit("expected test insertion anchor not found")
if "test_load_complete_is_not_emitted_before_final_structural_validation" not in test_source:
    TEST.write_text(test_source.replace(anchor, addition + anchor, 1), encoding="utf-8")
