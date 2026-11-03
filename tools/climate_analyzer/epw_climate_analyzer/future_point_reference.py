"""Build/replay a strict, same-donor S1 multiyear climate reference."""
from dataclasses import replace
from hashlib import sha256
import json

from .engine.f1_base import BUCK, COLLOCATED, climatology
from .engine.historical import json_bytes
from .engine.model_sources import bounded_zip
from .engine.point_interpolation import PointRequest
from .engine.source_cache import OriginalSourceCache
from .geosphere_station_year import _zip
from .point_interpolation import run_point_product

SCHEMA = "IGE_F1_LOCAL_POINT_REFERENCE_v1"
POINT_MODE = "POINT_REFERENCE"
POINT_LABEL = "Same-chain multi-year station point reference"
POINT_KIND = "IGE_S1_INTERPOLATED_POINT"
LIMIT = 128 * 1024**2
STATION_KIND = "GEOSPHERE_H1_ENDPOINTS_BUCK_RH_ASSUMPTION"
BACKGROUND_FIELDS = ("requested_point", "background_cell", "elevation_m_provider_response_proxy",
                     "site_elevation_or_native_orography_verified", "local_height_correction_applied")
DONOR_FIELDS = ("station_id", "source_kind", "latitude", "longitude",
                "temperature_elevation_m", "pressure_elevation_m", "height_reference", "height_is_proxy", "monthly_origin")


def _donors(rows):
    return sorted([{key: row[key] for key in DONOR_FIELDS} for row in rows if row["selected"]],
                  key=lambda row: row["station_id"])


def point_reference_spec(base, window):
    if (base.identity["source_kind"] != POINT_KIND or base.calendar_kind != "ACTUAL_YEAR"
            or base.pressure_contract != COLLOCATED or base.water_curve != BUCK):
        raise ValueError("F1_POINT_REFERENCE_REQUIRES_ADMITTED_STATION_POINT_BASE")
    if (len(window) != 2 or any(type(y) is not int for y in window)
            or not 2002 <= window[0] <= window[1] <= 2025 or not 10 <= window[1] - window[0] + 1 <= 30):
        raise ValueError("F1_POINT_REFERENCE_REQUIRES_10_TO_30_COMPLETE_YEARS_IN_2002_TO_2025")
    p = base.identity["source_provenance"]
    request = PointRequest(**p["point_request"])
    if ((request.latitude, request.longitude, request.elevation_m, request.utc_offset_minutes, request.year)
            != (base.location.latitude, base.location.longitude, base.location.elevation_m,
                base.request.utc_offset_minutes, base.request.year)):
        raise ValueError("F1_POINT_REFERENCE_BASE_GEOMETRY_OR_CLOCK_MISMATCH")
    donors = _donors(p["donor_admission"])
    if (len(donors) != 4 or len({d["station_id"] for d in donors}) != 4
            or any(d["source_kind"] != STATION_KIND for d in donors)):
        raise ValueError("F1_POINT_REFERENCE_REQUIRES_FOUR_REAL_GEOSPHERE_DONORS")
    return request, {"base_sha256": base.sha256, "point_request": request.to_dict(),
                     "donors": donors, "field_sources": p["field_sources"],
                     "background_geometry": {key: p["background_geometry"][key] for key in BACKGROUND_FIELDS}}


def _admit_year(product, request, spec):
    report = product.report
    if report["status"] != "POINT_YEAR_COMPLETE_RESEARCH":
        missing = [f"{row['station_id']}: T {row['T_admitted_hours']}, RH {row['RH_admitted_hours']}, "
                   f"p {row['p_admitted_hours']} / {row['expected_hours']} h ({', '.join(row['blocker_types'])})"
                   for row in report.get("station_core_coverage", []) if not row["donor_admitted"]]
        excluded = [f"{row['station_id']}: {row['reason']}"
                    for row in report.get("candidate_metadata_exclusions", [])]
        reasons = [*report["global_blockers"], *missing, *excluded]
        raise ValueError(f"F1_POINT_REFERENCE_YEAR_BLOCKED {request.year}: " + "; ".join(reasons))
    if report["EPW_status"] != "ADMITTED_MIXED_SOURCE_RESEARCH":
        raise ValueError(f"F1_POINT_REFERENCE_BACKGROUND_BLOCKED {request.year}: " + "; ".join(report["EPW_blockers"]))
    differences = []
    if product.request != request: differences.append("point request")
    if _donors(report["donor_admission"]) != spec["donors"]: differences.append("station identities or heights")
    if report["field_sources"] != spec["field_sources"]: differences.append("field sources")
    geometry = report["background_source_geometry"]
    for field in BACKGROUND_FIELDS:
        if field not in geometry or field not in spec["background_geometry"] or geometry[field] != spec["background_geometry"][field]:
            differences.append(field)
    # Distance is a derived display diagnostic. Live and replay paths can use
    # different Earth radii without any change in the physical source location.
    if differences:
        raise ValueError(f"F1_POINT_REFERENCE_SOURCE_GEOMETRY_OR_METHOD_CHANGED {request.year}: " + ", ".join(differences))


def point_reference(base, window, *, packet=None, expected_sha256=None, progress=lambda message: None):
    """Require every requested year; retain original S1 donors and background bytes."""
    from .future_selected import base_from_point

    original, spec = point_reference_spec(base, window)
    years = range(window[0], window[1] + 1)
    names = {f"{kind}_{year}.zip" for year in years for kind in ("station", "background")}
    cache = OriginalSourceCache() if packet is None else None
    stored = None
    if packet is not None:
        if len(packet) > LIMIT or not expected_sha256 or sha256(packet).hexdigest() != expected_sha256:
            raise ValueError("F1_POINT_REFERENCE_PACKET_HASH_OR_SIZE")
        stored = bounded_zip(packet, byte_limit=LIMIT, member_limit=61)
        manifest = json.loads(stored["manifest.json"])
        if (manifest["schema"] != SCHEMA or manifest["base"] != spec
                or manifest["reference_window"] != list(window)
                or set(stored) != names | {"manifest.json"} or set(manifest["members"]) != names):
            raise ValueError("F1_POINT_REFERENCE_PACKET_IDENTITY_OR_CENSUS")
        for name in names:
            if manifest["members"][name] != {"bytes": len(stored[name]), "sha256": sha256(stored[name]).hexdigest()}:
                raise ValueError("F1_POINT_REFERENCE_MEMBER_HASH_OR_SIZE")

    rows, monthly, files = [], [], {}
    size = 0
    for year in years:
        req = replace(original, year=year)
        progress(f"Station point reference: checking {year} with the same four donors")
        station_name, background_name = f"station_{year}.zip", f"background_{year}.zip"
        key = "F1_POINT_REFERENCE:"+sha256(json_bytes({"base": spec, "year": year, "schema": SCHEMA})).hexdigest()
        cached = cache.get(key) if cache is not None else None
        if stored is not None or cached is not None:
            members = stored if stored is not None else bounded_zip(cached[0], byte_limit=LIMIT, member_limit=2)
            stations, background = members[station_name], members[background_name]
            product = run_point_product(req, input_packet=stations, expected_sha256=sha256(stations).hexdigest(),
                include_background=True, background_packet=background, background_sha256=sha256(background).hexdigest())
        else:
            product = run_point_product(req, required_station_ids=tuple(d["station_id"] for d in spec["donors"]),
                                        include_background=True, progress=progress)
        _admit_year(product, req, spec)
        stations, background = product.files["inputs.zip"], product.files["background.sources.zip"]
        annual = base_from_point(product)
        # All years have identical month lengths after 29 February is removed.
        # Averaging their monthly estimators is equivalent to pooling all hours/days.
        monthly.append(climatology([annual]))
        size += len(stations) + len(background)
        if size > LIMIT:
            raise ValueError("F1_POINT_REFERENCE_SOURCE_BUDGET")
        files.update({station_name: stations, background_name: background})
        if cache is not None and cached is None:
            cache.put(key, _zip({station_name: stations, background_name: background}))
        rows.append({"year": year, "original_hours": len(annual.data), "estimator_hours": 8760,
                     "station_packet_sha256": sha256(stations).hexdigest(),
                     "background_packet_sha256": sha256(background).hexdigest()})
    ref = {m: {k: sum(v[m][k] for v in monthly)/len(monthly) for k in monthly[0][m]} for m in range(1,13)}
    if packet is None:
        files["manifest.json"] = json_bytes({"schema": SCHEMA, "base": spec, "reference_window": list(window),
            "members": {name: {"bytes": len(b), "sha256": sha256(b).hexdigest()} for name,b in files.items()}})
        if size + len(files["manifest.json"]) > LIMIT:
            raise ValueError("F1_POINT_REFERENCE_SOURCE_BUDGET")
        packet = _zip(files)
    return ref, {"kind": "SAME_CHAIN_STATION_POINT_MULTIYEAR", "reference_window": list(window),
        "reference_source_packet_sha256": sha256(packet).hexdigest(), "years": rows,
        "fixed_donors": spec["donors"], "noleap_estimator": True, "leap_source_rows_preserved": True,
        "reference_sampling_uncertainty_qualified": False}, packet
