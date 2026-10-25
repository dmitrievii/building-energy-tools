"""A1.3 execution registration; the A1.1 method and A1.2 failures stay frozen."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "research/ige_cmip6"
sys.path.insert(0, str(ROOT / "tools/climate_analyzer"))
from epw_climate_analyzer.engine.historical import json_bytes

BASE = "fe2cf4a92c89087f5ba0499d8fcf706edfdbff01"
PROTOCOL_SHA = "a8a5c3a5898f58058ce1fd2c86e85002fc46249a9e367d1d76e4f8a0fbd05ec4"
MODEL_URL = "https://archive-api.open-meteo.com/v1/archive"
SMN_ROOT = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn"
CODE = ["research/ige_cmip6/"+n for n in ("a13_prepare.py", "a13_acquire.py", "a13_run.py", "a13_verify.py")]
CODE += ["tools/climate_analyzer/tests/test_ige_a13_comparison.py"]
CODE += [".github/workflows/ige-a1-3-ch-temperature-20261025.yml"]
REGISTRATION = "a13_execution_registration_20261025.json"
SEAL = "a13_prediction_seal_20261025.json"
PREDICTIONS = "a13_predictions_20261025.csv"
LEDGER = "a13_case_ledger_20261025.json"
INPUTS = "a13_input_sources_20261025.zip"
CONTROLS = "a13_control_sources_20261025.zip"
RESULTS = "a13_comparison_20261025.json"


def parent_inputs():
    p = (R / "a1_1_protocol_20261025.json").read_bytes()
    if sha256(p).hexdigest() != PROTOCOL_SHA: raise ValueError("A13_PARENT_PROTOCOL_CHANGED")
    return json.loads(p), json.loads((R / "a12_history_admission_20261025.json").read_text())


def observation_spec(key, role):
    sid = key.split(":")[1].lower()
    return {"id": role+"_"+key.replace(":", "_"), "station_key": key,
        "kind": "station_observation", "role": role,
        "url": f"{SMN_ROOT}/{sid}/ogd-smn_{sid}_h_historical_2020-2029.csv",
        "member": role+"_"+key.replace(":", "_")+".csv", "max_body_bytes": 25_000_000}


def prepare():
    protocol, admission = parent_inputs()
    ready = [c for c in admission["cases"] if c["strict_T2m_metadata_ready"]]
    targets = sorted({c["target_key"] for c in ready})
    donors = sorted({s for c in ready for s in c["metadata_admitted_donors"]})
    if targets != ["CH:ALT", "CH:BAS"] or donors != ["CH:DEM", "CH:ENG", "CH:GES", "CH:MOE", "CH:RUE"]:
        raise ValueError("A13_UNREGISTERED_METADATA_READY_SUBSET")
    backgrounds = []
    for key in sorted(set(targets+donors)):
        geometry = [r["geometry"] for r in admission["station_windows"][key].values()]
        positions = {(r["latitude"], r["longitude"]) for r in geometry}
        if len(positions) != 1: raise ValueError("A13_SOURCE_LOCATION_CHANGE_REQUIRES_SEGMENTED_PLAN")
        latitude, longitude = next(iter(positions))
        params = {"latitude": f"{latitude:.6f}", "longitude": f"{longitude:.6f}",
            "start_date": "2025-01-01", "end_date": "2025-12-31", "hourly": "temperature_2m",
            "models": "era5", "elevation": "nan", "cell_selection": "nearest", "timezone": "GMT",
            "timeformat": "iso8601", "temperature_unit": "celsius"}
        backgrounds.append({"id": "background_"+key.replace(":", "_"), "station_key": key,
            "kind": "model_background", "role": "background", "parameters": params,
            "url": MODEL_URL+"?"+urlencode(params), "member": "background_"+key.replace(":", "_")+".json",
            "max_body_bytes": 2_000_000})
    return {"schema": "IGE_A13_CH_TEMPERATURE_EXECUTION_REGISTRATION_v1", "date": "2026-10-25", "parent_commit": BASE,
        "parent_protocol_sha256": PROTOCOL_SHA,
        "parent_admission_sha256": sha256((R / "a12_history_admission_20261025.json").read_bytes()).hexdigest(),
        "parent_exposure_sha256": sha256((R / "a12_exposure_audit_20261025.json").read_bytes()).hexdigest(),
        "all_frozen_cases": 24, "references_per_case": 168, "ready_cases": 8,
        "inputs": [*backgrounds, *[observation_spec(s, "donor") for s in donors]],
        "controls": [observation_spec(s, "control") for s in targets],
        "source_budget": {"max_decoded_body_bytes_all_attempts_inputs_plus_controls": 200_000_000,
            "max_distinct_background_assets": 24, "max_distinct_observation_assets": 24,
            "attempts_per_asset": 3, "timeout_seconds": 45, "parallel_downloads": 1,
            "no_alternate_station_model_year_operator_or_hidden_fallback": True},
        "operators": {"model": "instantaneous published hour nodes, Celsius, explicit ERA5-derived provider route",
            "CH": "mean_six_10min_nominal_nodes", "model_to_CH": "5/12 previous + 7/12 current, disclosed linear subhourly surrogate",
            "true_sensor_filter_or_subhourly_path_known": False, "grid_elevation_or_vertical_transfer_qualified": False},
        "selection": "fixed A1.1 slots; A1.2 blocked slots zero; min2 admitted primary-QC donors; no replacement or target-observation input",
        "source_subset": "validate station/schema; select frozen reference windows before numeric temperature extraction; no other variable reconstructed",
        "QC": "PUBLISHED_NO_ROW_QC; physical domain [-80,65] C from A1.1; not equivalent to DWD QN10",
        "scores": {"primary": "paired MAE R1 minus B0 on identical eligible reference hours, per frozen target/season",
            "also": ["RMSE", "bias", "all-reference B0", "coverage", "blocked cases", "per-target and pooled CH"],
            "bootstrap": {"unit": "complete 7-day target-season blocks", "draws": 10000, "seed": 20261025,
                "interval": "95% percentile, linear quantile", "pooled_weighting": "sum hourly error over resampled complete blocks / total matched hours",
                "maximum_CH_blocks": 8, "independent_replicates_claimed": False},
            "automatic_promotion_threshold_or_tuning": None},
        "seal_policy": "publish actual predictions, all24 case rows, input packet SHA and code/protocol/operator/QC hashes before any new control asset body",
        "source_exposure": "old wind provenance confirms CH containers already read; T2025 fitting/errors not demonstrated; exposed-source evaluation, no strict untouched-source certification",
        "retrospective_same_hour_donor_reconstruction_not_advance_weather_forecast": True,
        "strict_blindness_certified": False, "independent_accuracy_qualified": False,
        "full_weather_or_EPW_promotion_allowed": False, "production_ready": False,
        "IV1_observations_opened": False, "AT_DE_sources_opened": False}


def registered():
    raw = (R / REGISTRATION).read_bytes()
    plan = prepare()
    if raw != json_bytes(plan): raise ValueError("A13_EXECUTION_REGISTRATION_CHANGED")
    return plan


def code_hashes():
    names = [*CODE, "research/ige_cmip6/"+REGISTRATION,
        "tools/climate_analyzer/epw_climate_analyzer/station_reconstruction.py",
        "tools/climate_analyzer/epw_climate_analyzer/station_admission.py"]
    return {n: sha256((ROOT/n).read_bytes()).hexdigest() for n in names}


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
