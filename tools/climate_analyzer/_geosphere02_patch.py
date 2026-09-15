from pathlib import Path

root = Path(__file__).resolve().parents[2]
geosphere_path = root / "tools/climate_analyzer/epw_climate_analyzer/geosphere.py"
test_path = root / "tools/climate_analyzer/tests/test_geosphere_adapter.py"
doc_path = root / "tools/climate_analyzer/CLIMATE_GEOSPHERE_0_1.md"

text = geosphere_path.read_text(encoding="utf-8")

anchor = '''def _feature_station_id(feature: Mapping[str, Any]) -> str:\n'''
insert = '''def plan_data_queries(\n    station_id: str,\n    start: pd.Timestamp,\n    end: pd.Timestamp,\n    provider_parameters: Iterable[str],\n    *,\n    max_datapoints: int = MAX_REQUEST_DATAPOINTS,\n) -> list[dict[str, str]]:\n    \"\"\"Split one inclusive station interval into bounded 10-minute requests.\n\n    GeoSphere request size scales with ``timestamps × parameters × stations``.\n    The public app requests one station at a time, so this planner partitions a\n    long interval along the time axis. Adjacent batches are separated by exactly\n    one native 10-minute interval: the first timestamp of a new batch is the\n    timestamp after the previous batch's inclusive end. No overlap or synthetic\n    interpolation is introduced.\n    \"\"\"\n    station_id = str(station_id).strip()\n    if not station_id:\n        raise ValueError("GeoSphere station_id must not be empty.")\n    parameters = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))\n    if not parameters:\n        raise ValueError("At least one GeoSphere parameter is required.")\n    unknown = sorted(set(parameters) - set(FIELD_SPEC_BY_PROVIDER))\n    if unknown:\n        raise ValueError(f"Unsupported GeoSphere parameters: {', '.join(unknown)}")\n    if int(max_datapoints) <= 0:\n        raise ValueError("GeoSphere batch datapoint limit must be positive.")\n\n    start_ts = pd.Timestamp(start)\n    end_ts = pd.Timestamp(end)\n    if end_ts < start_ts:\n        raise ValueError("GeoSphere request end must not be earlier than start.")\n\n    max_steps = int(max_datapoints) // len(parameters)\n    if max_steps < 1:\n        raise ValueError("GeoSphere batch datapoint limit is too small for the selected parameter set.")\n\n    interval = pd.Timedelta(minutes=GEOSPHERE_NATIVE_INTERVAL_MINUTES)\n    queries: list[dict[str, str]] = []\n    cursor = start_ts\n    while cursor <= end_ts:\n        batch_end = min(end_ts, cursor + interval * (max_steps - 1))\n        query = build_data_query(station_id, cursor, batch_end, parameters)\n        if estimate_request_datapoints(cursor, batch_end, len(parameters), 1) > int(max_datapoints):\n            raise RuntimeError("Internal GeoSphere batch planner exceeded its datapoint limit.")\n        queries.append(query)\n        cursor = batch_end + interval\n    return queries\n\n\ndef _query_reference(query: Mapping[str, str]) -> str:\n    return f"{GEOSPHERE_ENDPOINT}?{urlencode(dict(query))}"\n\n\ndef fetch_station_provider_frame(\n    *,\n    station_id: str,\n    start: pd.Timestamp,\n    end: pd.Timestamp,\n    provider_parameters: Iterable[str],\n    timeout_s: int = DEFAULT_TIMEOUT_SECONDS,\n) -> tuple[pd.DataFrame, tuple[str, ...]]:\n    \"\"\"Fetch and concatenate all bounded batches for one historical interval.\n\n    Missing observations remain missing. Only structural corruption is rejected:\n    duplicate timestamps across batches, an empty aggregate response, or malformed\n    provider payloads. Historical gaps are not fabricated or interpolated.\n    \"\"\"\n    parameters = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))\n    queries = plan_data_queries(station_id, start, end, parameters)\n    frames: list[pd.DataFrame] = []\n    references: list[str] = []\n    for query in queries:\n        payload = _bounded_get_json(GEOSPHERE_ENDPOINT, params=query, timeout_s=timeout_s)\n        frames.append(parse_station_data_response(payload, station_id, parameters))\n        references.append(_query_reference(query))\n\n    if not frames:\n        raise ValueError("GeoSphere batching produced no requests.")\n    combined = pd.concat(frames, axis=0)\n    if combined.empty:\n        raise ValueError("GeoSphere returned no timestamps for the selected interval.")\n    if combined.index.has_duplicates:\n        duplicate_count = int(combined.index.duplicated(keep=False).sum())\n        raise ValueError(f"GeoSphere batched response contains {duplicate_count} duplicate timestamps.")\n    combined = combined.sort_index(kind="mergesort")\n    return combined, tuple(references)\n\n\n'''
if anchor not in text:
    raise SystemExit("geosphere insertion anchor not found")
text = text.replace(anchor, insert + anchor, 1)

old_sig = '''    request_reference: str = "",\n    retrieval_time_utc: str | None = None,\n) -> CanonicalClimateDataset:\n'''
new_sig = '''    request_reference: str = "",\n    retrieval_time_utc: str | None = None,\n    request_count: int = 1,\n) -> CanonicalClimateDataset:\n'''
if old_sig not in text:
    raise SystemExit("canonical builder signature anchor not found")
text = text.replace(old_sig, new_sig, 1)

old_notes = '''            "Provider timestamps are retained as real UTC historical timestamps.",\n            "10-minute mean radiation in W/m² is converted to interval irradiation in Wh/m².",\n        ),\n'''
new_notes = '''            "Provider timestamps are retained as real UTC historical timestamps.",\n            "10-minute mean radiation in W/m² is converted to interval irradiation in Wh/m².",\n            f"Historical interval retrieved in {int(request_count)} bounded Dataset API request batch(es).",\n        ),\n'''
if old_notes not in text:
    raise SystemExit("provenance notes anchor not found")
text = text.replace(old_notes, new_notes, 1)

old_fetch = '''    query = build_data_query(station.station_id, start, end, selected.keys())\n    payload = _bounded_get_json(GEOSPHERE_ENDPOINT, params=query, timeout_s=timeout_s)\n    provider_frame = parse_station_data_response(payload, station.station_id, selected.keys())\n    request_reference = f"{GEOSPHERE_ENDPOINT}?{urlencode(query)}"\n    return build_canonical_station_dataset(\n        station=station,\n        provider_frame=provider_frame,\n        mapping=selected,\n        request_reference=request_reference,\n    )\n'''
new_fetch = '''    provider_frame, request_references = fetch_station_provider_frame(\n        station_id=station.station_id,\n        start=start,\n        end=end,\n        provider_parameters=selected.keys(),\n        timeout_s=timeout_s,\n    )\n    return build_canonical_station_dataset(\n        station=station,\n        provider_frame=provider_frame,\n        mapping=selected,\n        request_reference="\\n".join(request_references),\n        request_count=len(request_references),\n    )\n'''
if old_fetch not in text:
    raise SystemExit("fetch_station_dataset body anchor not found")
text = text.replace(old_fetch, new_fetch, 1)
geosphere_path.write_text(text, encoding="utf-8")

# Extend adapter tests with deterministic batching coverage and a mocked multi-batch fetch.
tests = test_path.read_text(encoding="utf-8")
tests = tests.replace(
    '''import unittest\n\nimport pandas as pd\n''',
    '''import unittest\nfrom unittest.mock import patch\n\nimport pandas as pd\n''',
    1,
)
tests = tests.replace(
    '''    parse_parameters,\n    parse_station_data_response,\n''',
    '''    parse_parameters,\n    parse_station_data_response,\n    plan_data_queries,\n    fetch_station_provider_frame,\n''',
    1,
)

method_anchor = '''    def test_station_json_parser_retains_real_utc_timestamps_and_nulls(self) -> None:\n'''
new_methods = '''    def test_year_scale_request_is_partitioned_without_boundary_overlap(self) -> None:\n        start = pd.Timestamp("2025-01-01T00:00:00Z")\n        end = pd.Timestamp("2025-12-31T23:50:00Z")\n        parameters = [item["name"] for item in PARAMETERS if item["name"] != "tl_flag"]\n        queries = plan_data_queries("11240", start, end, parameters)\n        self.assertGreater(len(queries), 1)\n        previous_end = None\n        for query in queries:\n            q_start = pd.Timestamp(query["start"], tz="UTC")\n            q_end = pd.Timestamp(query["end"], tz="UTC")\n            self.assertLessEqual(estimate_request_datapoints(q_start, q_end, len(parameters)), MAX_REQUEST_DATAPOINTS)\n            if previous_end is not None:\n                self.assertEqual(q_start, previous_end + pd.Timedelta(minutes=10))\n            previous_end = q_end\n        self.assertEqual(pd.Timestamp(queries[0]["start"], tz="UTC"), start)\n        self.assertEqual(pd.Timestamp(queries[-1]["end"], tz="UTC"), end)\n\n    def test_batched_fetch_concatenates_non_overlapping_responses_and_records_references(self) -> None:\n        start = pd.Timestamp("2025-01-01T00:00:00Z")\n        end = pd.Timestamp("2025-01-01T00:30:00Z")\n        payloads = [\n            {\n                "timestamps": ["2025-01-01T00:00+00:00", "2025-01-01T00:10+00:00"],\n                "features": [{"properties": {"station": 11240, "parameters": {"tl": {"data": [1.0, 2.0]}}}}],\n            },\n            {\n                "timestamps": ["2025-01-01T00:20+00:00", "2025-01-01T00:30+00:00"],\n                "features": [{"properties": {"station": 11240, "parameters": {"tl": {"data": [3.0, 4.0]}}}}],\n            },\n        ]\n        planned = [\n            {"parameters": "tl", "station_ids": "11240", "start": "2025-01-01T00:00", "end": "2025-01-01T00:10"},\n            {"parameters": "tl", "station_ids": "11240", "start": "2025-01-01T00:20", "end": "2025-01-01T00:30"},\n        ]\n        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(\n            "epw_climate_analyzer.geosphere._bounded_get_json", side_effect=payloads\n        ):\n            frame, references = fetch_station_provider_frame(\n                station_id="11240", start=start, end=end, provider_parameters=["tl"]\n            )\n        self.assertEqual(frame["tl"].tolist(), [1.0, 2.0, 3.0, 4.0])\n        self.assertFalse(frame.index.has_duplicates)\n        self.assertEqual(len(references), 2)\n        self.assertTrue(all("station_ids=11240" in ref for ref in references))\n\n    def test_batched_fetch_fails_closed_on_duplicate_boundary_timestamp(self) -> None:\n        payloads = [\n            {\n                "timestamps": ["2025-01-01T00:00+00:00", "2025-01-01T00:10+00:00"],\n                "features": [{"properties": {"station": 11240, "parameters": {"tl": {"data": [1.0, 2.0]}}}}],\n            },\n            {\n                "timestamps": ["2025-01-01T00:10+00:00", "2025-01-01T00:20+00:00"],\n                "features": [{"properties": {"station": 11240, "parameters": {"tl": {"data": [2.0, 3.0]}}}}],\n            },\n        ]\n        planned = [\n            {"parameters": "tl", "station_ids": "11240", "start": "2025-01-01T00:00", "end": "2025-01-01T00:10"},\n            {"parameters": "tl", "station_ids": "11240", "start": "2025-01-01T00:10", "end": "2025-01-01T00:20"},\n        ]\n        with patch("epw_climate_analyzer.geosphere.plan_data_queries", return_value=planned), patch(\n            "epw_climate_analyzer.geosphere._bounded_get_json", side_effect=payloads\n        ):\n            with self.assertRaisesRegex(ValueError, "duplicate timestamps"):\n                fetch_station_provider_frame(\n                    station_id="11240",\n                    start=pd.Timestamp("2025-01-01T00:00:00Z"),\n                    end=pd.Timestamp("2025-01-01T00:20:00Z"),\n                    provider_parameters=["tl"],\n                )\n\n'''
if method_anchor not in tests:
    raise SystemExit("test insertion anchor not found")
tests = tests.replace(method_anchor, new_methods + method_anchor, 1)
test_path.write_text(tests, encoding="utf-8")

# Advance the documented adapter stage without claiming UI work that is not in this patch.
doc = doc_path.read_text(encoding="utf-8")
doc = doc.replace(
    "# CLIMATE-GEOSPHERE-0.1 — GeoSphere Austria historical station adapter",
    "# CLIMATE-GEOSPHERE-0.2 — GeoSphere Austria batched historical station adapter",
    1,
)
doc = doc.replace(
    "This is an **adapter stage**, not yet a public UI/map stage.",
    "This stage extends the qualified adapter with deterministic bounded batching for long historical ranges. It is still not a public station-selection UI stage.",
    1,
)
doc = doc.replace(
    "- currently requests one station per canonical dataset;\n- preserves missing values rather than treating them as zero.\n\nThe official API's request-size accounting is based on parameters × time steps × stations. A later UI stage may batch long ranges, but batching must preserve these same limits and provider rate limits.",
    "- requests one station per canonical dataset;\n- partitions year-scale ranges into deterministic non-overlapping 10-minute batches under the same 200,000-datapoint local cap;\n- rejects duplicate timestamps across returned batches;\n- preserves historical gaps and missing values rather than interpolating or treating them as zero.\n\nThe official API's request-size accounting is based on parameters × time steps × stations. Batch boundaries are inclusive and the next batch starts exactly one native 10-minute interval after the previous end, so request windows neither overlap nor leave a planner-created gap.",
    1,
)
doc = doc.replace(
    "- exact request reference when data were downloaded;",
    "- exact request reference for every bounded batch when data were downloaded;",
    1,
)
doc = doc.replace(
    "After this adapter is qualified, the next stage can add a GeoSphere station-selection experience and request batching for year-scale ranges. Detailed Year and Historical Comparison should consume the canonical dataset rather than introduce a second provider-specific analysis path.",
    "After this batched adapter is qualified, the next stage can add a GeoSphere station-selection experience. Detailed Year and Historical Comparison should consume the canonical dataset rather than introduce a second provider-specific analysis path.",
    1,
)
doc_path.write_text(doc, encoding="utf-8")

print("CLIMATE-GEOSPHERE-0.2 batching patch applied")
