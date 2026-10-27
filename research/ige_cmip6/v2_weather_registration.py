"""V2-M2 executable 2019 registration. Pure, metadata-only construction.

The V2-M1 cohort and every previous scientific file remain immutable.
Missing archives retain the original donor identity and a source block.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode

from v1_prepare import ROOT, R, metadata, DE_ROOT, SMN, FROZEN_CORE
from epw_climate_analyzer.engine.historical import json_bytes

BASE = "940e6664731e0bae6c0057608aa9ad70d604f6f2"
BRANCH = "research/ige-v2-executable-preregistration-20261027"
REG = "v2_weather_registration_20261027.json"
ADMISSION = "v2_metadata_admission_20261027.json"
PREDICTIONS = "v2_weather_predictions_20261027.csv"
LEDGER = "v2_weather_prediction_ledger_20261027.json"
SEAL = "v2_weather_prediction_seal_20261027.json"
RESULTS = "v2_weather_results_20261027.json"
INPUTS = "v2_weather_inputs_20261027.zip"
CONTROLS = "v2_weather_controls_20261027.zip"
WINDOWS = tuple({"season": s, "start_UTC": f"2019-{m:02d}-10T00:00:00Z",
                 "end_UTC": f"2019-{m:02d}-16T23:00:00Z"}
                for s, m in (("winter", 1), ("spring", 4), ("summer", 7), ("autumn", 10)))
CODE = ["research/ige_cmip6/" + n for n in (
    "v2_weather_registration.py", "v2_weather_io.py", "v2_weather_run.py", "v2_weather_verify.py")]
CODE += ["tools/climate_analyzer/tests/test_ige_v2_weather.py",
         ".github/workflows/ige-v2-weather-registration-20261027.yml"]
# Include imported scientific/serialization dependencies, not just the wrapper.
DEPENDENCIES = FROZEN_CORE + ["research/ige_cmip6/" + n for n in (
    "v1_prepare.py", "v1_time_admission.py", "a1_prepare.py", "a12_prepare_history.py",
    "p9_3b3_native_heights.py")]
DEPENDENCIES += ["tools/climate_analyzer/epw_climate_analyzer/" + n for n in (
    "engine/historical.py", "engine/epw.py", "engine/contracts.py", "climate_model.py")]
DEPENDENCIES += ["tools/climate_analyzer/requirements.txt"]
# Freeze the complete inherited Python scientific/application tree, including
# transitive imports used only by legacy metadata helpers. New V2 wrappers are
# listed separately in CODE, avoiding any self-referential registration hash.
DEPENDENCIES = sorted(set(DEPENDENCIES) | {
    p for p in subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE,
        "research/ige_cmip6", "tools/climate_analyzer/epw_climate_analyzer"], cwd=ROOT, text=True).splitlines()
    if p.endswith(".py")})
PROTOCOL = ["research/ige_cmip6/" + n for n in (
    ADMISSION, "v2_metadata_frame_20261027.json", "v2_exposure_audit_20261027.json",
    "v2_metadata_discovery_amendment_20261027.json", "v1a_next_validation_design_20261027.json",
    "v2_dated_metadata_sources_20261027.zip.storage.json", "v2_dated_metadata_sources_20261027.zip.part001",
    "v1_metadata_sources_20261026.zip", "a1_1_metadata_sources_20261025.zip",
    "a1_1_DWD_description_recovery_20261025.zip")]
RESERVED = {"AT:16412", "AT:5609", "AT:20123", "DE:00399", "CH:DAV"}


def hashes(paths):
    return {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}


def admission():
    raw = (R / ADMISSION).read_bytes()
    if sha256(raw).hexdigest() != "570acc5eefe1b9ef6e2b32cf1c17619d02eff7d79eba3aa70c6b25d3b5cd4ea6":
        raise ValueError("V2_M1_ORIGINAL_ADMISSION_CHANGED")
    obj = json.loads(raw)
    if len(obj["metadata_target_keys"]) != 18 or len(obj["groups"]) != 18 or obj["metadata_ready_cases"] != 72:
        raise ValueError("V2_M1_COHORT_CENSUS")
    return obj


def source_specs(a):
    targets = a["metadata_target_keys"]
    donors = sorted({d for g in a["groups"] for d in g["donors"]})
    all_keys = sorted(set(targets + donors))
    identities = {a["records"][k]["resolved_identity_group"] for k in targets}
    if set(donors) & (set(targets) | RESERVED) or any(a["records"][d]["resolved_identity_group"] in identities for d in donors):
        raise ValueError("V2_TARGET_OR_RESERVED_ALIAS_IN_DONORS")
    bodies, _ = metadata()
    index = bodies["DE_10min_historical_index.html"].decode()
    background, donor_specs, controls = [], [], []
    for key in all_keys:
        g = a["records"][key]["geometry"]
        p = {"latitude": f"{g['latitude']:.6f}", "longitude": f"{g['longitude']:.6f}",
             "start_date": "2019-01-01", "end_date": "2019-12-31", "hourly": "temperature_2m",
             "models": "era5", "elevation": "nan", "cell_selection": "nearest", "timezone": "GMT",
             "timeformat": "iso8601", "temperature_unit": "celsius"}
        name = "background_" + key.replace(":", "_")
        background.append({"id": name, "station_key": key, "role": "background", "kind": "model_background",
            "url": "https://archive-api.open-meteo.com/v1/archive?" + urlencode(p), "parameters": p,
            "member": name + ".json", "max_body_bytes": 2_000_000, "source_block": None,
            "raw_container_support": "2019 calendar year; model, no station measurements", "raw_other_variables": False})
    for role, keys, output in (("donor", donors, donor_specs), ("control", targets, controls)):
        for key in keys:
            c, sid = key.split(":"); reason = None
            if c == "AT":
                p = {"station_ids": sid, "parameters": "tl,tl_flag", "output_format": "geojson",
                     "start": WINDOWS[0]["start_UTC"], "end": WINDOWS[-1]["end_UTC"]}
                url = "https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h?" + urlencode(p)
                suffix, cap = ".json", 2_000_000
                support = "2019-01-10T00:00Z/2019-10-16T23:00Z, one individual station; intervening days exposed"
                evidence = "frozen GeoSphere v2 individual catalog/product request contract"
            elif c == "DE":
                matches = sorted(set(re.findall("10minutenwerte_TU_" + sid + r"_(\d{8})_(\d{8})_hist.zip", index)))
                matches = [(x, y) for x, y in matches if x <= "20190110" and y >= "20191016"]
                if len(matches) == 1:
                    x, y = matches[0]
                    url = DE_ROOT + "historical/" + f"10minutenwerte_TU_{sid}_{x}_{y}_hist.zip"
                    support = x + "/" + y + "; entire station ZIP including all variables and years counts as exposure"
                else:
                    url = None; support = None
                    reason = "NO_UNIQUE_2019_ARCHIVE_IN_PINNED_DWD_INDEX; retained identity, no replacement or new discovery"
                suffix, cap = ".zip", 10_000_000
                evidence = "v1_metadata_sources_20261026.zip:DE_10min_historical_index.html; SHA256=" + sha256(bodies["DE_10min_historical_index.html"]).hexdigest()
            else:
                url = f"{SMN}/{sid.lower()}/ogd-smn_{sid.lower()}_h_historical_2010-2019.csv"
                suffix, cap = ".csv", 45_000_000
                support = "2010/2019; all variables/years in whole original station h CSV count as exposure"
                evidence = "frozen provider h inventory and verified SCU/STG decade naming pattern; individual URL availability unverified, failure retained"
            name = role + "_" + key.replace(":", "_")
            output.append({"id": name, "station_key": key, "kind": "station_temperature", "role": role,
                "url": url, "member": name + suffix, "max_body_bytes": cap, "source_block": reason,
                "raw_container_support": support, "raw_other_variables": c in ("DE", "CH"), "inventory_evidence": evidence})
    return background + donor_specs, controls


def build_registration():
    a = admission(); inputs, controls = source_specs(a)
    live = [s for s in inputs + controls if s["url"]]
    if len({s["url"] for s in live}) != len(live) or len(live) > 240 or sum(s["max_body_bytes"] for s in live) > 2_000_000_000:
        raise ValueError("V2_SOURCE_INVENTORY_CANNOT_FIT_BUDGET")
    return {"schema": "IGE_V2_EXECUTABLE_2019_TEMPERATURE_PREREGISTRATION_v1", "date": "2026-10-27",
        "parent_commit": BASE, "branch": BRANCH, "stage": "V2-M2", "product_functions": ["A", "B-M historical reference only"],
        "target_keys": a["metadata_target_keys"], "groups": a["groups"], "windows": list(WINDOWS),
        "registered_cases": 72, "requested_reference_hours": 12096, "cohort_or_donor_replacement_allowed": False,
        "original_M1_admission_sha256": sha256((R / ADMISSION).read_bytes()).hexdigest(),
        "code_sha256": hashes(CODE + DEPENDENCIES), "protocol_sha256": hashes(PROTOCOL),
        "operators": {c: next(r["time_contract"] for k, r in a["records"].items() if k.startswith(c) and r["temperature_source_eligible"]) for c in ("AT", "DE", "CH")},
        "QC": {"AT": {"primary": [10], "label": "AUTO_CHECKED_ORIGINALITY_UNKNOWN_PROVIDER_PRODUCT", "original_sensor_accuracy_claim": False},
               "DE": {"primary": [3], "field": "TT_10", "not_hourly_QN10": True},
               "CH": {"primary": "PUBLISHED_HISTORICAL_NO_ROW_QC", "field": "tre200h0"}},
        "estimator": {"B0": "Open-Meteo ERA5-derived, elevation=nan nearest; same reference operator as R1",
            "R1": "unchanged A1 reconstruct_temperature: IDW2 accepted donor residuals, 2-3 fixed donors, min2 per hour",
            "formula": "R1_x=A B_x + sum_i I_i d_i^-2 (y_i-A B_i) / sum_i I_i d_i^-2",
            "CH_A_B_h": "(5 B_(h-1)+7 B_h)/12; surrogate for six nominal nodes, not certified sensor filter",
            "native_value_domain_C": [-80, 65], "R1_candidate_domain_C": [-70, 70],
            "missing": "R1 NaN retained; no B0 fill; no lapse fit, G1, calibration or error-dependent selection",
            "CH_endpoint_generation_or_validation": False},
        "inputs": inputs, "controls": controls,
        "source_inventory": {"model_assets": 70, "fixed_donor_identities": 52, "control_assets": 18,
            "total_registered_assets_including_blocks": len(inputs + controls), "requestable_assets": len(live),
            "known_blocked_assets": [{"id": s["id"], "reason": s["source_block"]} for s in inputs + controls if s["source_block"]],
            "sum_one_complete_body_cap_bytes": sum(s["max_body_bytes"] for s in live), "new_metadata_HTTP_requests": 0},
        "budget": {"HTTP_attempts_inputs_plus_controls_max": 240, "attempts_per_asset_max": 3,
            "body_bytes_all_attempts_inputs_plus_controls_max": 2_000_000_000,
            "maximum_original_body_per_asset": 150_000_000, "attempt_total_deadline_seconds": 45,
            "reserved_control_first_attempt_slots": len(controls),
            "reserved_control_first_body_caps_bytes": sum(s["max_body_bytes"] for s in controls if s["url"]),
            "workflow_job_deadline_minutes": 210, "parallel_downloads": 1,
            "retry_delays_seconds": [2, 4], "retry_only": ["transport error", "total deadline", "HTTP429", "HTTP500", "HTTP502", "HTTP503", "HTTP504"],
            "partial_failed_and_HTTP_error_bodies_preserved_and_counted": True,
            "DWD_product_uncompressed_member_max": 150_000_000,
            "transport_attempt_bound_seconds": 10800, "backoff_bound_seconds": 480,
            "CPU_estimate_minutes": [2, 10], "network_estimate_minutes": [10, 45], "estimates_not_measured_run": True,
            "first_pass_prioritized_over_retries": True, "budget_exhaustion": "retain every remaining asset/case as SOURCE_BLOCKED; no extension"},
        "control_admission": {"frozen_before_predictors": True, "target_gate": "open target archive only if at least one of its 4 cases has >=160 finite paired B0/R1 forecasts",
            "prediction_gate_counts_no_observed_values": True, "all72_cases_retained": True,
            "whole_archive_exposure": "opening any target archive reveals all its years/variables, including unscored dates; record entire extent",
            "actual_predictions_weights_NaNs_ledger_code_sources_seal_must_be_published_first": True,
            "remote_exact_commit_and_byte_identity_required": True},
        "scoring": {"minimum_pairs_per_case": 160, "requested_hours_per_case": 168,
            "primary": "MAE_R1 minus MAE_B0 on exactly the same native-primary-QC reference hours",
            "report": ["all72 cases", "per station/season", "country/QC stratum", "MAE", "RMSE", "bias", "centred RMSE", "B0 all reference", "coverage", "all source blocks", "worst station delta"],
            "partial_cases": "descriptive metrics retained; excluded from admitted-case estimate; report all-pair aggregate too",
            "pilot_benefit": "country has24/24 cases >=160 pairs, country admitted paired deltaMAE<0 and each6 station paired deltaMAE<=0",
            "zero_margin": "observed pilot score rule, not equivalence/significance or no-harm guarantee",
            "resampling": {"unit": "4 synchronous season weeks, all6 country stations together", "draws": 10000, "PCG64_seed": 20261027,
                "percentiles": [2.5, 97.5], "descriptive_only": True, "population_CI_or_p_value": False},
            "pooled_country_winner": False, "AT_DE_CH_QC_not_pooled": True},
        "diagnostics": ["native per-code counts including unknown/missing", "weights and effective weight count, not independent sample size",
            "shared returned grid cells and identical full-year arrays", "nominal/datum height proxies and distances, not qualified terrain rule",
            "LOO with3 donors only and unchanged min2; no accuracy gate from donor coherence"],
        "serialization": {"CSV_decimals": 10, "replay_numeric_absolute_tolerance": 1.1e-10,
            "all_source_ledger_and_seal_original_bytes": "exact SHA256",
            "recomputed_derived_ledger_JSON_floats": "absolute1.1e-10; all integers/categories exact",
            "JSON_floats": "full float, score replay absolute1.1e-8"},
        "exposure": {"old_AT_2018_and_IV1_2022_controls_unopened": True, "global_raw_byte_blindness_certified": False,
            "provider_spatial_QC_or_ERA5_assimilation_independence_certified": False,
            "new_prior_exposure_found": "retain target, disclose downgrade to revealed; no replacement",
            "AT_identity": "inferred WMO name and dated <=500m geometry, not provider-ID crosswalk"},
        "four_status_axes": {"code_correctness": "offline tests/source replay, no weather accuracy inference",
            "physical_admissibility": "dated nominal2m and time support only; no full EPW physics qualification",
            "independent_accuracy": "unmeasured until published prediction seal then new target scoring; upstream dependence disclosed",
            "operational_readiness": "research-only, no default/EPW/deployment promotion"},
        "B4_P2_or_NASA_closure_qualified": False, "production_ready": False, "merge_or_deployment_allowed": False}


def registered():
    plan = build_registration()
    if (R / REG).read_bytes() != json_bytes(plan):
        raise ValueError("V2_REGISTRATION_CODE_PROTOCOL_OR_INVENTORY_CHANGED")
    return plan


def publication_gate(commit, *, predictions=False):
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise ValueError("V2_EXACT_PUBLISHED_COMMIT_REQUIRED")
    plan = registered()
    living = {"docs/IGE_CLIMATE_ENGINE_TWO_PRODUCT_ROADMAP_RU_20261025.md", "research/ige_cmip6/e2e_two_product_roadmap_20261025.json"}
    for row in subprocess.check_output(["git", "diff", "--name-status", BASE], cwd=ROOT, text=True).splitlines():
        status, path = row.split("\t", 1)
        if status != "A" and path not in living:
            raise ValueError("V2_PRIOR_SCIENTIFIC_FILE_CHANGED:" + path)
    subprocess.run(["git", "merge-base", "--is-ancestor", commit, "refs/remotes/origin/" + BRANCH], cwd=ROOT, check=True, capture_output=True)
    paths = CODE + DEPENDENCIES + PROTOCOL + ["research/ige_cmip6/" + REG]
    if predictions:
        seal_raw = subprocess.check_output(["git", "show", commit + ":research/ige_cmip6/" + SEAL], cwd=ROOT)
        seal = json.loads(seal_raw)
        if seal_raw != (R / SEAL).read_bytes() or seal["control_bodies_opened"] is not False or seal["code_sha256"] != plan["code_sha256"]:
            raise ValueError("V2_CHANGED_OR_NON_PRECONTROL_SEAL")
        paths += ["research/ige_cmip6/" + n for n in seal["frozen_files_sha256"]] + ["research/ige_cmip6/" + SEAL]
        for name, digest in seal["frozen_files_sha256"].items():
            if sha256((R / name).read_bytes()).hexdigest() != digest:
                raise ValueError("V2_CHANGED_SEALED_FILE:" + name)
    for p in paths:
        if subprocess.check_output(["git", "show", commit + ":" + p], cwd=ROOT) != (ROOT / p).read_bytes():
            raise ValueError("V2_UNPUBLISHED_OR_CHANGED_BYTES:" + p)
    return {"commit": commit, "remote_tracking_ancestry_and_bytes_verified": True,
            "phase": "predictions" if predictions else "registration", "API_publication_receipt_required_separately": True,
            "local_wallclock_is_not_trusted_external_time": True}
