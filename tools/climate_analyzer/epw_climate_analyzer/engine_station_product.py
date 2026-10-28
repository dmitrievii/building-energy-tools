"""Read-only A1.5 product service for the two SHA-pinned A1.4 research years.

No provider/generator call, resaturation, state repair, EPW rewrite or automatic
promotion is performed. Downloaded originals retain their original bytes.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
from typing import Callable
import zipfile

import pandas as pd

from .engine_application import EngineProduct
from .engine_analysis import (UI_CONTRACT, STATION_UI_CONTRACT, STATION_BUNDLE_SHA,
    prepare_engine_analysis_frame, monthly_engine_summary)
from .engine.contracts import FieldDefinition, QualityStatus
from .engine.epw import validate_epw_bytes, validate_weather
from .engine.historical import json_bytes
from .engine.station_year import StationYearRequest, StationYearResult, validate_station_state
from .climate_model import ClimateLocation

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / "research/ige_cmip6"
BUNDLE_NAME = "a14_CH_2025_research_years_20261026.zip"
PARENT = "fb1b77a12a1dd525506d14ffc546988dbc39efb7"
CATALOG = {
    "CH:BAS": {"label": "Basel / Binningen (BAS)", "latitude": 47.541064, "longitude": 7.58355,
        "nominal_elevation_m": 316., "EPW_sha256": "b7cc31ac7cf6a71329f85a7d60f41fe2ea43be86692f8f012cc2b02009c378e1"},
    "CH:ALT": {"label": "Altdorf (ALT)", "latitude": 46.887047, "longitude": 8.621797,
        "nominal_elevation_m": 438., "EPW_sha256": "53a0a904ec7141d26d9941e1ed5dbf473a8cd461c8bb86e5a6f091da450ff538"},
}
SNAPSHOT_FILES = ("weather.epw", "hourly_states.csv", "manifest.json",
    "R1_donor_admission_ledger.csv", "temperature_mean_inverse_ledger.csv",
    "humidity_pressure_adjustment_ledger.csv")


def _snapshot(raw: bytes, station_key: str):
    if len(raw) > 5_000_000 or sha256(raw).hexdigest() != STATION_BUNDLE_SHA:
        raise ValueError("IGE_A15_ORIGINAL_YEAR_BUNDLE_HASH_OR_SIZE")
    expected = {"a14_results_20261026.json"} | {
        key.replace(":", "_")+"_2025/"+name for key in CATALOG for name in SNAPSHOT_FILES}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist(); names = [e.filename for e in entries]
        if (len(names) != len(set(names)) or set(names) != expected
                or sum(e.file_size for e in entries) > 32_000_000):
            raise ValueError("IGE_A15_SNAPSHOT_MEMBER_CENSUS_OR_BUDGET")
        folder = station_key.replace(":", "_")+"_2025/"
        files = {name: archive.read(folder+name) for name in SNAPSHOT_FILES}
        census = json.loads(archive.read("a14_results_20261026.json"))
    manifest = json.loads(files["manifest.json"])
    if manifest != census["targets"][station_key] or manifest["station_key"] != station_key:
        raise ValueError("IGE_A15_CROSS_STATION_MANIFEST")
    if set(manifest["product_sha256"]) != set(SNAPSHOT_FILES)-{"manifest.json"}:
        raise ValueError("IGE_A15_SNAPSHOT_PRODUCT_CENSUS")
    for name, digest in manifest["product_sha256"].items():
        if sha256(files[name]).hexdigest() != digest:
            raise ValueError("IGE_A15_SNAPSHOT_PRODUCT_HASH_"+name)
    if sha256(files["weather.epw"]).hexdigest() != CATALOG[station_key]["EPW_sha256"]:
        raise ValueError("IGE_A15_ORIGINAL_STATION_EPW_CHANGED")
    return files, manifest, census


def load_station_year_product(station_key: str, *, bundle_path: Path | None = None,
        progress: Callable[[str], None] = lambda _: None) -> EngineProduct:
    if station_key not in CATALOG:
        raise ValueError("IGE_A15_ONLY_SAVED_BAS_ALT_2025_ADMITTED")
    progress("Verifying the saved 2025 year, original file hashes and station identity")
    original, snapshot, census = _snapshot((bundle_path or RESEARCH/BUNDLE_NAME).read_bytes(), station_key)
    site = CATALOG[station_key]
    request = StationYearRequest(site["latitude"], site["longitude"], 2025, 60,
        site["label"], "station_temperature_year", site["nominal_elevation_m"],
        "Frozen nominal station height; vertical datum/model-orography transfer unqualified", station_key)
    data = pd.read_csv(io.BytesIO(original["hourly_states.csv"]), index_col=0, float_precision="round_trip")
    data.index = pd.to_datetime(data.index, utc=True).rename("interval_start_utc")
    geometry = snapshot["geometry"]
    if (geometry["latitude"] != request.latitude or geometry["longitude"] != request.longitude
            or geometry["AGL_m"] != 2. or len(data) != 8760):
        raise ValueError("IGE_A15_DATED_T_SENSOR_OR_FULL_YEAR_MISMATCH")
    quality = QualityStatus("SAVED_HASH_CLOCK_EPW_AND_UI_ADAPTER_PASS",
        "CONDITIONAL_T_P_Q_RH_CLOSURE_ONLY", "NOT_INDEPENDENTLY_QUALIFIED",
        "RESEARCH_UI_SAVED_CH_BAS_ALT_2025; NOT_PRODUCTION")
    result = StationYearResult(request, data,
        ClimateLocation(request.latitude, request.longitude, site["nominal_elevation_m"],
            city=site["label"], country="CH", station_id=station_key.split(":")[1]),
        {k: FieldDefinition(**v) for k, v in snapshot["fields"].items()}, tuple(snapshot["sources"]),
        (), (), quality, {"original_A14_manifest": snapshot, "UI_scope": "read-only saved year"})
    validate_station_state(result)
    validate_weather(result)
    epw_check = validate_epw_bytes(original["weather.epw"], result)
    dataset = result.to_canonical()
    frame = dataset.data.copy(deep=True)
    frame.attrs.update({"ige_engine_ui_contract": UI_CONTRACT,
        "ige_station_ui_admission": {"contract": STATION_UI_CONTRACT,
            "bundle_sha256": STATION_BUNDLE_SHA, "station_key": station_key},
        "ige_existing_U1_display_adapter_supports_this_contract": True,
        "ige_UI_humidity_phase_adapter_required": True})
    dataset = replace(dataset, data=frame)
    progress("Checking saved q, water-phase psychrometrics, calendar and unchanged EPW download")
    analysis = prepare_engine_analysis_frame(dataset)
    background = snapshot["background_diagnostics"]
    geometry_report = {"requested_point": [request.latitude, request.longitude],
        "background_cell": background["background_cell"],
        "requested_to_background_distance_km": background["requested_to_background_distance_km"],
        "elevation_m_provider_response_proxy": background["elevation_m_provider_response_proxy"],
        "nominal_station_elevation_m": site["nominal_elevation_m"],
        "dated_T_sensor_geometry": geometry, "site_elevation_or_native_orography_verified": False,
        "local_height_correction_applied": False, "RH_or_pressure_sensor_height_certified": False}
    references = {"snapshot": {"file": BUNDLE_NAME, "sha256": STATION_BUNDLE_SHA},
        "new_A14_background_originals": {"file": "a14_original_sources_20261026.zip",
            "sha256": census["new_source_packet_sha256"]},
        "reused_A13_predictor_originals": {"file": "a13_input_sources_20261025.zip",
            "sha256": census["reused_predictor_packet_sha256"]}}
    for ref in references.values():
        ref["url"] = f"https://github.com/dmitrievii/building-energy-tools/blob/{PARENT}/research/ige_cmip6/{ref['file']}"
    report = {"schema": STATION_UI_CONTRACT, "product_kind": "SAVED_STATION_T_RECONSTRUCTION",
        "UI_connected": True, "station_key": station_key, "historical_year": 2025,
        "calendar_mode": "historical", "pattern_year": None, "future_request": None,
        "rows": 8760, "state_sample_offset_minutes": 60,
        "row_clock": "actual 2025; fixed CET UTC+1 interval start; states at right endpoint; no DST",
        "quality": {k:v for k,v in asdict(quality).items() if k != "production_ready"},
        "source_snapshot_quality": snapshot["quality"],
        "analysis_adapter": analysis.attrs["ige_ui_analysis"], "source_geometry": geometry_report,
        "diagnostics": {"temperature": snapshot["temperature"], "humidity_projection_hours": snapshot["q_projection_hours"],
            "pressure": "conditional source-surface plus 2m proxy; not verified pressure at station height",
            "source_snapshot_quality_is_archived_not_rewritten": True,
            "atmospheric_water_mass_latent_heat_or_precipitation_flux_conserved": False},
        "field_provenance": [{"field":k, **v} for k,v in snapshot["fields"].items()],
        "monthly_summary": json.loads(monthly_engine_summary(analysis).reset_index().to_json(orient="records")),
        "engine_EPW_sha256": sha256(original["weather.epw"]).hexdigest(),
        "engine_manifest_sha256": sha256(original["manifest.json"]).hexdigest(),
        "original_snapshot_product_sha256": snapshot["product_sha256"],
        "source_references": references, "original_snapshot_files_in_download": True,
        "raw_provider_bodies_in_UI_download": False,
        "weather_provider_requests_this_run": 0, "saved_snapshot_values_modified": False,
        "EPW_regenerated": False, "historical_station_or_terrain_correction_applied": True,
        "station_temperature_residual_correction_applied": True, "terrain_correction_applied": False,
        "correction_scope": "frozen station T residual plus explicit humidity policy; no terrain/pressure transfer",
        "NASA_hurs_signal_enforced": False, "IV1_station_observations_opened": False,
        "new_target_observations_opened": False, "instantaneous_T_accuracy_qualified": False,
        "local_pressure_accuracy_qualified": False, "independent_station_accuracy_qualified": False,
        "full_weather_cross_field_accuracy_qualified": False, "production_ready": False,
        "EnergyPlus_building_simulation_run": False, "public_deployment_changed": False}
    files = {"climate.epw": original["weather.epw"],
        "hourly.csv.gz": gzip.compress(original["hourly_states.csv"], mtime=0),
        "analysis_state.csv.gz": gzip.compress(analysis.to_csv(index_label="interval_start_local_standard", float_format="%.12g").encode(), mtime=0),
        "ui_report.json": json_bytes(report), "source_references.json": json_bytes(references),
        **{"a14_snapshot/"+name:body for name,body in original.items()}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2000,1,1,0,0,0)); entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, body)
    return EngineProduct(dataset, files, buffer.getvalue(), report,
        "IGE_"+station_key.replace(":", "_")+"_2025_R1_RESEARCH")
