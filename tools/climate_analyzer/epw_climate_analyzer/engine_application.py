"""Transactional UI service around the unchanged I1/A0 and B-M1 engines.

Only complete, hash-checked products become downloadable. Temporary runs are
isolated and removed after packaging; rerendering the UI never fetches weather.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
from typing import Callable
import zipfile

from .climate_model import CanonicalClimateDataset
from .engine import HistoricalRequest, FutureRequest, run_historical, run_future
from .engine.contracts import ClimateResult
from .engine.future import PATTERN_SOURCE_SHA
from .engine.historical import json_bytes, _haversine
from .engine.model_sources import SEMANTICS_VERSION, NEX_PACKET_SHA, REFERENCE_PACKET_SHA
from .engine_analysis import UI_CONTRACT, prepare_engine_analysis_frame, monthly_engine_summary

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / "research/ige_cmip6"
HISTORICAL_EPW_SHA = "acf8e7d82be69de5fa19f76c599143559d477aa01cdb7c56414fc23c93796635"
PATTERN = "i1_a0_graz2023_original_sources_20261025.zip"
REFERENCE = "bm1_reference_sources_2002_2014_20261025.zip"
NEX = "e2e_original_replay_inputs_20261025.zip"
PROTOCOL = "bm1_protocol_20261025.json"


@dataclass(frozen=True)
class EngineProduct:
    dataset: CanonicalClimateDataset
    files: dict[str, bytes]
    archive: bytes
    report: dict
    download_stem: str


def pilot_historical_request() -> HistoricalRequest:
    return HistoricalRequest(47.0707, 15.4395, 2023, 60, label="Graz")


def pilot_future_request() -> FutureRequest:
    return FutureRequest(HISTORICAL_EPW_SHA, "CanESM5", "r1i1p1f1", "ssp245", (2002, 2014),
        (2040, 2059), SEMANTICS_VERSION, 2023)


def _complete_product(result: ClimateResult, output: Path, source_packets: dict[str, bytes]) -> EngineProduct:
    """Validate disk output before publishing any success state to the UI."""
    if (output / "failed.json").exists() or not (output / "manifest.json").is_file():
        raise ValueError("IGE_U1_INCOMPLETE_OUTPUT_NOT_DOWNLOADABLE")
    manifest = json.loads((output / "manifest.json").read_bytes())
    files = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
    expected = set(manifest["files"]) | {"manifest.json"}
    if set(files) != expected:
        raise ValueError("IGE_U1_UNMANIFESTED_OR_MISSING_OUTPUT")
    for name, entry in manifest["files"].items():
        if sha256(files[name]).hexdigest() != entry["sha256"] or len(files[name]) != entry["bytes"]:
            raise ValueError("IGE_U1_OUTPUT_HASH_MISMATCH_" + name)
    if sha256(files["climate.epw"]).hexdigest() != manifest["EPW"]["sha256"]:
        raise ValueError("IGE_U1_EPW_MANIFEST_HASH_MISMATCH")
    dataset = result.to_canonical()
    frame = dataset.data.copy(deep=True)
    frame.attrs["ige_engine_ui_contract"] = UI_CONTRACT
    frame.attrs["ige_engine_diagnostics"] = result.diagnostics
    frame.attrs["ige_UI_humidity_phase_adapter_required"] = True
    dataset = replace(dataset, data=frame)
    analysis = prepare_engine_analysis_frame(dataset)
    adapter_report = analysis.attrs["ige_ui_analysis"]
    source_hashes = {name: sha256(body).hexdigest() for name, body in source_packets.items()}
    future = result.future_request is not None
    location, request = dataset.location, result.request
    geometry = {"requested_point": [request.latitude, request.longitude],
        "background_cell": [location.latitude, location.longitude],
        "requested_to_background_distance_km": _haversine(request.latitude, request.longitude, location.latitude, location.longitude),
        "elevation_m_provider_response_proxy": location.elevation_m,
        "site_elevation_or_native_orography_verified": False, "local_height_correction_applied": False}
    report = {"schema": UI_CONTRACT, "UI_connected": True,
        "calendar_mode": dataset.temporal.calendar_mode,
        "pattern_year": result.request.year if future else None,
        "historical_year": None if future else result.request.year,
        "future_request": manifest.get("future_request"),
        "rows": len(dataset.data), "state_sample_offset_minutes": 60,
        "row_clock": "fixed local standard interval start; states at right endpoint; no DST",
        "quality": {"execution_correctness": "COMPLETE_ENGINE_OUTPUT_HASHES_AND_UI_ADAPTER_PASS",
            "physical_admissibility": "CONDITIONAL_WATER_T_P_Q_RH_CLOSURE_PASS" if future else "BOUNDS_AND_SOURCE_ROUNDING_PASS_NO_COMMON_HEIGHT_CLOSURE",
            "independent_accuracy": "NOT_INDEPENDENTLY_VALIDATED",
            "operational_and_application_scope": "RESEARCH_UI_SINGLE_PILOT" if future else "RESEARCH_UI_GRID_BACKGROUND_YEAR"},
        "analysis_adapter": adapter_report, "diagnostics": result.diagnostics, "source_geometry": geometry,
        "monthly_summary": json.loads(monthly_engine_summary(analysis).reset_index().to_json(orient="records")),
        "engine_manifest_sha256": sha256(files["manifest.json"]).hexdigest(),
        "engine_EPW_sha256": sha256(files["climate.epw"]).hexdigest(),
        "engine_output_files": manifest["files"], "retained_source_packets_sha256": source_hashes,
        "weather_provider_requests_this_run": manifest["weather_provider_requests_this_run"],
        "historical_station_or_terrain_correction_applied": False,
        "NASA_hurs_signal_enforced": False, "IV1_station_observations_opened": False,
        "production_ready": False, "EnergyPlus_building_simulation_run": False}
    files["ui_report.json"] = json_bytes(report)
    files["analysis_state.csv.gz"] = gzip.compress(analysis.to_csv(index_label="interval_start_local_standard", float_format="%.12g").encode(), mtime=0)
    for name, body in source_packets.items():
        if Path(name).name != name:
            raise ValueError("IGE_U1_INVALID_SOURCE_PACKET_NAME")
        files["source_packets/" + name] = body
    # A fixed ZIP header makes archive packaging deterministic for equal files.
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0)); entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, body)
    stem = ("IGE_Graz_CanESM5_ssp245_2040-2059_pattern2023_RESEARCH" if future
        else f"IGE_{result.request.latitude:.4f}_{result.request.longitude:.4f}_{result.request.year}_BACKGROUND")
    return EngineProduct(dataset, files, archive_buffer.getvalue(), report, stem)


def run_historical_product(request: HistoricalRequest, *, use_saved_pilot: bool = True,
        progress: Callable[[str], None] = lambda _: None) -> EngineProduct:
    if use_saved_pilot and request != pilot_historical_request():
        raise ValueError("IGE_U1_SAVED_PILOT_IDENTITY_MISMATCH")
    progress("Validating the annual request and original sources")
    with tempfile.TemporaryDirectory(prefix="ige-u1-historical-") as temporary:
        output = Path(temporary) / "year"
        progress("Assembling the historical year" if use_saved_pilot else "Requesting ERA5-derived and POWER data; provider retries may take several minutes")
        result = run_historical(request, output,
            source_bundle=RESEARCH / PATTERN if use_saved_pilot else None,
            source_bundle_sha256=PATTERN_SOURCE_SHA if use_saved_pilot else None)
        progress("Checking the saved EPW, calendar, humidity convention and downloads")
        # sources.zip already contains the exact original responses and receipts.
        return _complete_product(result, output, {})


def run_future_pilot_product(*, progress: Callable[[str], None] = lambda _: None) -> EngineProduct:
    """Only the admitted model/member/location/windows; no silent substitution."""
    sources = {name: (RESEARCH / name).read_bytes() for name in (PATTERN, REFERENCE, NEX, PROTOCOL)}
    for name, expected in ((PATTERN, PATTERN_SOURCE_SHA), (REFERENCE, REFERENCE_PACKET_SHA), (NEX, NEX_PACKET_SHA)):
        if sha256(sources[name]).hexdigest() != expected:
            raise ValueError("IGE_U1_PILOT_SOURCE_HASH_MISMATCH_" + name)
    with tempfile.TemporaryDirectory(prefix="ige-u1-future-") as temporary:
        progress("Verifying the original historical pattern and its EPW")
        historical_output = Path(temporary) / "historical"
        run_historical(pilot_historical_request(), historical_output,
            source_bundle=RESEARCH / PATTERN, source_bundle_sha256=PATTERN_SOURCE_SHA)
        if sha256((historical_output / "climate.epw").read_bytes()).hexdigest() != HISTORICAL_EPW_SHA:
            raise ValueError("IGE_U1_FUTURE_HISTORICAL_BASE_CHANGED")
        progress("Applying CanESM5 SSP245 changes with the common 2002–2014 reference")
        output = Path(temporary) / "future"
        result = run_future(pilot_historical_request(), pilot_future_request(),
            pattern_sources=RESEARCH / PATTERN, reference_sources=RESEARCH / REFERENCE,
            nex_sources=RESEARCH / NEX, protocol=RESEARCH / PROTOCOL, output=output)
        progress("Checking monthly signals, physical states and complete downloads")
        return _complete_product(result, output, sources)
