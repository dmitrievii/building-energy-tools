"""F1 transactional application service, original inputs and offline replay."""
from __future__ import annotations

from dataclasses import asdict, replace
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import time

import pandas as pd

from .climate_model import CanonicalClimateDataset, ClimateProvenance, ClimateTemporalMetadata
from .engine.contracts import HistoricalRequest
from .engine.epw import serialize_epw
from .engine.f1 import CONTRACT, morph_selected
from .engine.f1_base import (BaseYear, admit_base, climatology, epw_reference, SURFACE,
    COLLOCATED, MK, BUCK, PROVIDER_ROUNDING)
from .engine.f1_sources import SignalRequest, acquire_nex, admit_nex_packet, matching_saved_nex_packet
from .engine.source_cache import OriginalSourceCache
from .engine.historical import (json_bytes, read_source_bundle, assemble_historical,
    source_plan, fetch_original, make_source_bundle)
from .engine.model_sources import bounded_zip, REFERENCE_PACKET_SHA
from .engine_application import EngineProduct, RESEARCH, REFERENCE
from .engine_analysis import UI_CONTRACT, prepare_engine_analysis_frame, monthly_engine_summary
from .geosphere_station_year import _zip


def base_from_engine(product):
    if product.report.get("calendar_mode") != "historical" or product.report.get("product_kind"):
        raise ValueError("F1_ENGINE_BASE_MUST_BE_AN_ADMITTED_HISTORICAL_BACKGROUND")
    manifest = json.loads(product.files["manifest.json"])
    req = manifest["request"]
    return admit_base(product.files["climate.epw"], calendar_kind="ACTUAL_YEAR", pressure_contract=SURFACE,
        water_curve=MK, vapour_authority="DEW_POINT", source_kind="IGE_B0_BACKGROUND",
        rounding_policy=PROVIDER_ROUNDING,
        signal_site=[req["latitude"], req["longitude"]], extras=product.dataset.data,
        provenance={"historical_request": req, "geometry": product.report["source_geometry"],
            "source_bundle_sha256": sha256(product.files["sources.zip"]).hexdigest()})


def base_from_point(product):
    if product.report.get("EPW_status") != "ADMITTED_MIXED_SOURCE_RESEARCH" or "climate.epw" not in product.files:
        raise ValueError("F1_S1_THERMODYNAMIC_ONLY_YEAR_HAS_NO_COMPLETE_EPW")
    return admit_base(product.files["climate.epw"], calendar_kind="ACTUAL_YEAR", pressure_contract=COLLOCATED,
        water_curve=BUCK, source_kind="IGE_S1_INTERPOLATED_POINT",
        provenance={"point_request": product.request.to_dict(), "field_sources": product.report["field_sources"],
            "donor_admission": product.report["donor_admission"],
            "background_geometry": product.report["background_source_geometry"],
            "source_report_sha256": sha256(product.files["report.json"]).hexdigest()})


def background_reference(base, window, *, packet=None, expected_sha256=None, progress=lambda message: None):
    if base.identity["source_kind"] != "IGE_B0_BACKGROUND" or base.pressure_contract != SURFACE:
        raise ValueError("F1_BACKGROUND_REFERENCE_CANNOT_REPLACE_STATION_OR_POINT_CLIMATOLOGY")
    if not 2002 <= window[0] <= window[1] <= 2025:
        raise ValueError("F1_BACKGROUND_REFERENCE_SOURCE_WINDOW_2002_TO_2025")
    original = HistoricalRequest(**base.identity["source_provenance"]["historical_request"])
    stored = None
    if packet is not None:
        if not expected_sha256 or sha256(packet).hexdigest() != expected_sha256:
            raise ValueError("F1_REFERENCE_PACKET_SHA_CHANGED")
        stored = bounded_zip(packet, byte_limit=128*1024**2, member_limit=40)
        manifest = json.loads(stored["manifest.json"])
        if manifest.get("reference_window") != list(window): raise ValueError("F1_REFERENCE_PACKET_WINDOW_MISMATCH")
        if expected_sha256 == REFERENCE_PACKET_SHA:
            names = {f"Graz_{y}_original_sources.zip" for y in range(window[0], window[1]+1)}
            if set(stored) != names | {"manifest.json", "registered_protocol.json"}:
                raise ValueError("F1_LEGACY_REFERENCE_CENSUS")
        else:
            if manifest.get("schema") != "IGE_F1_LOCAL_BACKGROUND_REFERENCE_v1": raise ValueError("F1_REFERENCE_PACKET_SCHEMA")
            names = {f"background_{y}.zip" for y in range(window[0], window[1]+1)}
            if set(stored) != names | {"manifest.json"}: raise ValueError("F1_REFERENCE_PACKET_CENSUS")
    bases, files, rows = [], {}, []
    cache = OriginalSourceCache() if stored is None else None
    for year in range(window[0], window[1]+1):
        progress(f"Local reference: checking complete source year {year}")
        req = replace(original, year=year)
        if stored is not None:
            name = f"Graz_{year}_original_sources.zip" if expected_sha256 == REFERENCE_PACKET_SHA else f"background_{year}.zip"
            body = stored[name]; entry = manifest["members"][name]
            if entry["sha256"] != sha256(body).hexdigest() or entry["bytes"] != len(body):
                raise ValueError("F1_REFERENCE_MEMBER_HASH_OR_SIZE")
            inner = bounded_zip(body)
            saved = HistoricalRequest(**json.loads(inner["manifest.json"])["request"])
            # Labels do not alter source selection; all physical/clock request
            # fields must coincide. No rebasing to another cell or height.
            if replace(saved, label=req.label).to_dict() != req.to_dict():
                raise ValueError("F1_REFERENCE_ORIGINAL_SOURCE_REQUEST_MISMATCH")
            req = saved
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/"sources.zip"; path.write_bytes(body)
                payloads, receipts = read_source_bundle(path, entry["sha256"], req)
        else:
            cache_key = "F1_LOCAL_REFERENCE:"+json.dumps(req.to_dict(), sort_keys=True)
            saved = cache.get(cache_key)
            if saved is not None:
                body, _ = saved
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder)/"sources.zip"; path.write_bytes(body)
                    payloads, receipts = read_source_bundle(path, sha256(body).hexdigest(), req)
                progress(f"Local reference: resuming verified original source year {year}")
            else:
                payloads, receipts = {}, []
                for key, spec in source_plan(req).items():
                    payloads[key], receipt = fetch_original(key, spec); receipts.append(receipt)
                body = make_source_bundle(req, payloads, receipts)
        result = assemble_historical(req, payloads, receipts)
        a, b = base.location, result.location
        if (a.latitude, a.longitude, a.elevation_m) != (b.latitude, b.longitude, b.elevation_m):
            raise ValueError("F1_REFERENCE_BACKGROUND_CELL_OR_OROGRAPHY_CHANGED")
        epw, _ = serialize_epw(result)
        bases.append(admit_base(epw, calendar_kind="ACTUAL_YEAR", pressure_contract=SURFACE,
            water_curve=MK, vapour_authority="DEW_POINT", extras=result.data, source_kind="IGE_B0_REFERENCE",
            rounding_policy=PROVIDER_ROUNDING))
        if cache is not None:
            cache.put(cache_key, body)
        name = f"background_{year}.zip"; files[name] = body
        rows.append({"year": year, "source_sha256": sha256(body).hexdigest(), "original_hours": len(result.data), "estimator_hours": 8760})
        if "source_rounding_admission" in bases[-1].identity:
            rows[-1]["source_rounding_admission"] = bases[-1].identity["source_rounding_admission"]
    if packet is None:
        files["manifest.json"] = json_bytes({"schema": "IGE_F1_LOCAL_BACKGROUND_REFERENCE_v1", "reference_window": list(window),
            "members": {name: {"sha256": sha256(b).hexdigest(), "bytes": len(b)} for name,b in files.items()}})
        packet = _zip(files)
    return climatology(bases), {"kind": "SAME_CHAIN_BACKGROUND_MULTIYEAR", "reference_window": list(window),
        "reference_source_packet_sha256": sha256(packet).hexdigest(), "years": rows,
        "noleap_estimator": True, "leap_source_rows_preserved": True,
        "reference_sampling_uncertainty_qualified": False}, packet


def matching_saved_background_reference(base, window):
    """Exact physical request match only; never a fallback for another site."""
    if base.identity["source_kind"] != "IGE_B0_BACKGROUND" or tuple(window) != (2002, 2014): return None
    req = base.identity["source_provenance"]["historical_request"]
    expected = {"latitude": 47.0707, "longitude": 15.4395, "utc_offset_minutes": 60,
                "mode": "grid_background", "site_elevation_m": None, "site_elevation_reference": ""}
    if any(req.get(k) != v for k,v in expected.items()): return None
    raw = (RESEARCH/REFERENCE).read_bytes()
    if sha256(raw).hexdigest() != REFERENCE_PACKET_SHA: raise ValueError("F1_SAVED_REFERENCE_HASH_CHANGED")
    return raw


def run_selected_future(base: BaseYear, request: SignalRequest, *, reference_mode,
        period_evidence="", reference_base=None, reference_packet=None, reference_packet_sha256=None,
        nex_packet=None, nex_packet_sha256=None, allow_liquid_precipitation_proxy=False,
        retained_sources=None, progress=lambda message: None):
    """The only network-bearing F1 application call; publish atomically on success."""
    started = time.monotonic(); sources = dict(retained_sources or {})
    sources["selected_base.epw"] = base.epw
    if list(base.identity["signal_site"]) != [request.latitude, request.longitude]:
        raise ValueError("F1_SELECTED_SITE_AND_MODEL_REQUEST_MISMATCH")
    if reference_mode == "REPRESENTATIVE_BASE":
        ref, ref_evidence = epw_reference(base, base, request.reference_window, period_evidence)
    elif reference_mode == "SEPARATE_REFERENCE_EPW":
        if reference_base is None: raise ValueError("F1_COMPATIBLE_LOCAL_REFERENCE_EPW_REQUIRED")
        ref, ref_evidence = epw_reference(base, reference_base, request.reference_window, period_evidence)
        sources["local_reference.epw"] = reference_base.epw
        sources["reference_admission.json"] = json_bytes(reference_base.identity)
        sources["reference_hourly.csv.gz"] = gzip.compress(reference_base.data.to_csv(
            index_label="interval_start_utc", float_format="%.17g").encode(), mtime=0)
    elif reference_mode == "BACKGROUND_REFERENCE":
        # Reject an incompatible base before HTTP. The slow multi-year local
        # reference is deferred until NASA admission succeeds, so an unavailable
        # catalogue does not first waste 10–30 annual background acquisitions.
        if base.identity["source_kind"] != "IGE_B0_BACKGROUND" or base.pressure_contract != SURFACE:
            raise ValueError("F1_BACKGROUND_REFERENCE_CANNOT_REPLACE_STATION_OR_POINT_CLIMATOLOGY")
        if not 2002 <= request.reference_window[0] <= request.reference_window[1] <= 2025:
            raise ValueError("F1_BACKGROUND_REFERENCE_SOURCE_WINDOW_2002_TO_2025")
    else: raise ValueError("F1_LOCAL_REFERENCE_MODE_NOT_ADMITTED")
    if not allow_liquid_precipitation_proxy and ("total_precipitation_depth_mm" not in base.data
            or (reference_mode != "BACKGROUND_REFERENCE" and not all("total_precipitation_depth_mm" in ref[m] for m in range(1,13)))):
        raise ValueError("F1_TOTAL_PRECIPITATION_UNKNOWN_EXPLICIT_LIQUID_RAIN_PROXY_REQUIRED")
    if nex_packet is None:
        nex_packet = matching_saved_nex_packet(request)
        if nex_packet is not None:
            progress("Reusing the retained original NASA packet: exact point, model, scenario and climate periods match")
        else:
            progress("Acquiring original NASA point subsets; completed responses are kept for Retry")
            nex_packet = acquire_nex(request, progress=progress)
        nex_packet_sha256 = sha256(nex_packet).hexdigest()
    progress("Verifying every NASA source day, unit, grid cell and model operator")
    signals, nex_evidence = admit_nex_packet(nex_packet, nex_packet_sha256, request)
    sources["NASA_NEX_original.sources.zip"] = nex_packet
    if reference_mode == "BACKGROUND_REFERENCE":
        if reference_packet is None:
            reference_packet = matching_saved_background_reference(base, request.reference_window)
            if reference_packet is not None: reference_packet_sha256 = sha256(reference_packet).hexdigest()
        ref, ref_evidence, packet = background_reference(base, request.reference_window,
            packet=reference_packet, expected_sha256=reference_packet_sha256, progress=progress)
        sources["local_reference.sources.zip"] = packet
    if not allow_liquid_precipitation_proxy and not ("total_precipitation_depth_mm" in base.data and all("total_precipitation_depth_mm" in ref[m] for m in range(1,13))):
        raise ValueError("F1_TOTAL_PRECIPITATION_UNKNOWN_EXPLICIT_LIQUID_RAIN_PROXY_REQUIRED")
    progress("Applying monthly signals and the constrained moisture projection")
    result, epw, ledger, screen = morph_selected(base, ref, signals, request,
        reference_evidence=ref_evidence, nex_evidence=nex_evidence,
        allow_liquid_precipitation_proxy=allow_liquid_precipitation_proxy)
    frame = result.data.copy(); frame.index = base.request.local_starts
    frame.attrs.update({"ige_engine_ui_contract": UI_CONTRACT, "ige_f1_contract": CONTRACT,
        "ige_RH_phase": base.water_curve, "ige_f1_pressure_contract": base.pressure_contract,
        "ige_future_request": request.to_dict(), "ige_UI_humidity_phase_adapter_required": True,
        "ige_state_sample_offset_minutes_from_row_start": 60})
    dataset = CanonicalClimateDataset("ige-f1-"+base.sha256[:16]+"-"+request.scenario+"-"+str(request.future_window),
        f"{base.request.label} · {request.model} {request.scenario} {request.future_window[0]}–{request.future_window[1]}",
        frame, base.location, ClimateTemporalMetadata(60, "climatology", str(base.request.standard_timezone),
            "interval_start", base.source_years, base.request.year),
        ClimateProvenance("IGE / NASA NEX-GDDP-CMIP6", CONTRACT, "IGE F1", "selected-base future research year",
            notes=("Pattern chronology is not a future-date forecast or an independently selected TMY.",
                "See explicit reference period, source cells, pressure and water-curve assumptions in ui_report.json.")))
    analysis = prepare_engine_analysis_frame(dataset)
    report = {"schema": CONTRACT, "product_kind": "F1_SELECTED_BASE_FUTURE", "calendar_mode": "climatology",
        "rows": len(frame), "pattern_year": base.request.year, "original_source_years": list(base.source_years),
        "future_request": request.to_dict(), "base": base.identity, "diagnostics": result.diagnostics,
        "source_geometry": {"selected_base": asdict(base.location), "signal_site": base.identity["signal_site"], "NASA_grid": nex_evidence["grid"]},
        "row_clock": "fixed local-standard interval start; states at hour end; no DST; pattern dates only",
        "quality": {"execution_correctness": "COMPLETE_YEAR_SOURCE_HASHES_STATE_AND_EXPORT_CHECKS_PASS",
            "physical_admissibility": "CONDITIONAL_T_P_Q_WATER_RH_CLOSURE_AND_MONTHLY_TARGETS_PASS",
            "independent_accuracy": "NOT_INDEPENDENTLY_VALIDATED", "operational_and_application_scope": "RESEARCH_SELECTED_BASE_FUTURE"},
        "analysis_adapter": analysis.attrs["ige_ui_analysis"], "EPW": screen,
        "monthly_summary": json.loads(monthly_engine_summary(analysis).reset_index().to_json(orient="records")),
        "base_not_modified": True, "production_ready": False, "EnergyPlus_building_simulation_run": False,
        "calculation_seconds": time.monotonic()-started,
        "limitations": ["Monthly seasonal signal transfer; native NASA daily time bounds not verified.",
            "NASA tas is daily min/max midrange, not 24-hour mean; hurs phase unknown and hurs not enforced.",
            "No future pressure signal; stated historical pressure contract retained.",
            "Wind direction, clouds, event timing and precipitation phase are inherited; no new weather events.",
            "Solar components scale together; target-site solar geometry and independent DNI/DHI accuracy unqualified.",
            "Single GCM/member, declared local reference; no station-accuracy, ensemble-uncertainty or production qualification."]}
    sources["base_admission.json"] = json_bytes(base.identity)
    sources["selected_base_hourly.csv.gz"] = gzip.compress(base.data.to_csv(
        index_label="interval_start_utc", float_format="%.17g").encode(), mtime=0)
    files = {"climate.epw": epw, "ui_report.json": json_bytes(report),
        "hourly.csv.gz": gzip.compress(frame.to_csv(index_label="interval_start_local_standard", float_format="%.12g").encode(), mtime=0),
        "adjustment_ledger.csv.gz": gzip.compress(ledger.to_csv(index_label="interval_start_utc", float_format="%.12g").encode(), mtime=0),
        "monthly_signals.json": json_bytes(signals), "local_reference_climatology.json": json_bytes(ref)}
    for name, body in sources.items():
        if Path(name).name != name: raise ValueError("F1_UNSAFE_SOURCE_PACKET_NAME")
        files["source_packets/"+name] = body
    files["manifest.json"] = json_bytes({"schema": CONTRACT, "base_sha256": base.sha256,
        "request": request.to_dict(), "reference_mode": reference_mode, "period_evidence": period_evidence,
        "allow_liquid_precipitation_proxy": allow_liquid_precipitation_proxy,
        "files": {name: {"sha256": sha256(body).hexdigest(), "bytes": len(body)} for name, body in files.items()}})
    if len(files) > 96 or sum(len(body) for body in files.values()) > 256*1024**2:
        raise ValueError("F1_COMPLETE_PRODUCT_EXCEEDS_OFFLINE_REPLAY_BUDGET")
    stem = f"IGE_F1_{base.location.latitude:.4f}_{base.location.longitude:.4f}_{request.model}_{request.scenario}_{request.future_window[0]}-{request.future_window[1]}_RESEARCH"
    return EngineProduct(dataset, files, _zip(files), report, stem)


def replay_selected_future(archive, expected_sha256, *, progress=lambda message: None):
    """Rebuild a downloaded F1 ZIP entirely offline, checking every input hash."""
    if not expected_sha256 or sha256(archive).hexdigest() != expected_sha256:
        raise ValueError("F1_REPLAY_ARCHIVE_SHA256_REQUIRED")
    files = bounded_zip(archive, byte_limit=256*1024**2, member_limit=96)
    manifest = json.loads(files["manifest.json"])
    if manifest.get("schema") != CONTRACT or set(files) != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("F1_REPLAY_MANIFEST_OR_FILE_CENSUS")
    for name, entry in manifest["files"].items():
        if sha256(files[name]).hexdigest() != entry["sha256"] or len(files[name]) != entry["bytes"]:
            raise ValueError("F1_REPLAY_MEMBER_HASH_OR_SIZE_"+name)
    prefix = "source_packets/"
    sources = {name[len(prefix):]: body for name,body in files.items() if name.startswith(prefix)}
    info = json.loads(sources["base_admission.json"])
    def read_hourly(name):
        with gzip.GzipFile(fileobj=io.BytesIO(sources[name])) as stream:
            body = stream.read(16*1024**2+1)
        if len(body) > 16*1024**2: raise ValueError("F1_REPLAY_BASE_CSV_BUDGET")
        f = pd.read_csv(io.BytesIO(body), index_col=0, float_precision="round_trip")
        f.index = pd.to_datetime(f.index, utc=True)
        return f
    extras = read_hourly("selected_base_hourly.csv.gz")
    def restore(epw, metadata, extra=None):
        b = admit_base(epw, calendar_kind=metadata["calendar_kind"], pressure_contract=metadata["pressure_contract"],
            water_curve=metadata["water_curve"], vapour_authority=metadata["vapour_authority"],
            source_kind=metadata["source_kind"], signal_site=metadata["signal_site"],
            rounding_policy=metadata.get("source_rounding_admission", {}).get("policy"),
            extras=extra, provenance=metadata["source_provenance"])
        if b.identity != metadata: raise ValueError("F1_REPLAY_BASE_IDENTITY_CHANGED")
        return b
    base = restore(sources["selected_base.epw"], info, extras)
    ref = restore(sources["local_reference.epw"], json.loads(sources["reference_admission.json"]),
        read_hourly("reference_hourly.csv.gz")) if manifest["reference_mode"] == "SEPARATE_REFERENCE_EPW" else None
    values = manifest["request"]
    request = SignalRequest(**{**values, "reference_window": tuple(values["reference_window"]), "future_window": tuple(values["future_window"])})
    nex = sources["NASA_NEX_original.sources.zip"]
    local = sources.get("local_reference.sources.zip")
    reserved = {"base_admission.json", "reference_admission.json", "reference_hourly.csv.gz", "selected_base_hourly.csv.gz", "selected_base.epw", "local_reference.epw", "NASA_NEX_original.sources.zip", "local_reference.sources.zip"}
    return run_selected_future(base, request, reference_mode=manifest["reference_mode"],
        period_evidence=manifest["period_evidence"], reference_base=ref,
        reference_packet=local, reference_packet_sha256=sha256(local).hexdigest() if local is not None else None,
        nex_packet=nex, nex_packet_sha256=sha256(nex).hexdigest(),
        allow_liquid_precipitation_proxy=manifest["allow_liquid_precipitation_proxy"],
        retained_sources={name: body for name,body in sources.items() if name not in reserved}, progress=progress)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Offline replay of a downloaded F1 selected-base future ZIP")
    p.add_argument("--replay", type=Path, required=True); p.add_argument("--sha256", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    product = replay_selected_future(args.replay.read_bytes(), args.sha256, progress=print)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out/"climate.epw").write_bytes(product.files["climate.epw"])
    (args.out/"future.zip").write_bytes(product.archive)
    (args.out/"ui_report.json").write_bytes(product.files["ui_report.json"])
    print(json.dumps({"rows": len(product.dataset.data), "EPW_sha256": sha256(product.files["climate.epw"]).hexdigest(),
        "production_ready": False}, indent=2))
