"""Reproducible metadata-only catalog selection and A1.1 admission report.

No observation file, error score or weather model endpoint is opened here.
Catalog coordinates are recent nominal positions, not certified historical
sensor geometry. That remaining gate is carried into the output explicitly.
"""
from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sys
import zipfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools/climate_analyzer"))
from epw_climate_analyzer.station_reconstruction import StationReference, distance_km, select_donors, _csv

RESEARCH = ROOT/"research/ige_cmip6"
PACKETS = {
    "a1_1_metadata_sources_20261025.zip": "5c0954403e8e3572db1a0b48a4c7d01d3e4bb17052a6e6bdf9980204a210f10a",
    "a1_1_DWD_description_recovery_20261025.zip": "95974833cc9a4e16b20e8e594570c265519012a923cb6c2dd8b9fa871b0dc8f3",
}
ANCHORS = (("AT_LINZ", "AT", 48.3069,14.2858), ("AT_SALZBURG", "AT",47.8095,13.0550),
    ("DE_LEIPZIG", "DE",51.3397,12.3731), ("DE_FREIBURG", "DE",47.9990,7.8421),
    ("CH_BASEL", "CH",47.5596,7.5886), ("CH_ALTDORF", "CH",46.8804,8.6444))
WINDOWS = (("winter","2025-01-10","2025-01-16"), ("spring","2025-04-10","2025-04-16"),
    ("summer","2025-07-10","2025-07-16"), ("autumn","2025-10-10","2025-10-16"))


def metadata_sources():
    bodies, receipts, manifests = {}, {}, []
    for name, digest in PACKETS.items():
        raw = (RESEARCH/name).read_bytes()
        if sha256(raw).hexdigest() != digest: raise ValueError("A1_METADATA_PACKET_HASH_"+name)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or any(Path(n).name != n for n in names): raise ValueError("A1_METADATA_ZIP_MEMBERS")
            manifest = json.loads(archive.read("manifest.json")); manifests.append(manifest)
            for entry in manifest["sources"]:
                if entry["status"] != "ORIGINAL_METADATA_RECEIVED": continue
                member = entry["name"]
                if member in bodies: raise ValueError("A1_METADATA_REPLACEMENT_FORBIDDEN")
                if archive.getinfo(member).file_size > 8_000_000: raise ValueError("A1_METADATA_MEMBER_TOO_BIG")
                body = archive.read(member)
                if len(body) != entry["bytes"] or sha256(body).hexdigest() != entry["sha256"]: raise ValueError("A1_METADATA_MEMBER_HASH")
                bodies[member], receipts[member] = body, entry
    return bodies, receipts, manifests


def catalogs(bodies):
    first, last = pd.Timestamp("2025-01-01",tz="UTC"), pd.Timestamp("2025-12-31T23:00Z")
    at = json.loads(bodies["AT_hourly_v2_metadata.json"])
    entries = []
    for row in at["stations"]:
        if row["type"] != "INDIVIDUAL": continue
        if not pd.Timestamp(row["valid_from"]) <= first <= last <= pd.Timestamp(row["valid_to"]): continue
        entries.append(StationReference("AT",str(row["id"]),row["name"],float(row["lat"]),float(row["lon"]),float(row["altitude"]),
            sha256(bodies["AT_hourly_v2_metadata.json"]).hexdigest(), "AT_GROUP:"+str(row["group_id"])))
    for line in bodies["DE_TU_stations.txt"].decode("cp1252").splitlines():
        match = re.match(r"^\s*(\d{5})\s+(\d{8})\s+(\d{8})\s+(-?[\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(.+?)\s{2,}",line)
        if not match: continue
        sid, start, end, height, lat, lon, name = match.groups()
        if start > "20250101" or end < "20251231": continue
        entries.append(StationReference("DE",sid,name.strip(),float(lat),float(lon),float(height),sha256(bodies["DE_TU_stations.txt"]).hexdigest(),"DE_STATION:"+sid))
    inventory,_ = _csv(bodies["CH_inventory.csv"])
    available = set()
    for row in inventory:
        if row["parameter_shortname"] != "tre200h0": continue
        start = pd.to_datetime(row["data_since"],format="%d.%m.%Y %H:%M",utc=True)
        end = pd.to_datetime(row["data_till"],format="%d.%m.%Y %H:%M",utc=True) if row["data_till"].strip() else pd.Timestamp("2100-01-01",tz="UTC")
        if start <= first <= last <= end: available.add(row["station_abbr"])
    swiss,_ = _csv(bodies["CH_stations.csv"])
    for row in swiss:
        sid = row["station_abbr"]
        if sid not in available: continue
        entries.append(StationReference("CH",sid,row["station_name"],float(row["station_coordinates_wgs84_lat"]),
            float(row["station_coordinates_wgs84_lon"]),float(row["station_height_masl"]),sha256(bodies["CH_stations.csv"]).hexdigest(),
            "CH_WIGOS:"+row["station_wigos_id"] if row["station_wigos_id"].strip() else "CH_STATION:"+sid))
    if len({x.key for x in entries}) != len(entries): raise ValueError("A1_DUPLICATE_CATALOG_IDENTITIES")
    return sorted(entries,key=lambda s:s.key)


def prepare():
    bodies, receipts, acquisition = metadata_sources(); pool = catalogs(bodies)
    selected, target_anchors = [], []
    for anchor, country, lat, lon in ANCHORS:
        point = StationReference(country,"ANCHOR",anchor,lat,lon,0.,"0"*64)
        ordered = sorted((distance_km(point,s),s.key,s) for s in pool if s.country==country)
        if not ordered or ordered[0][0] > 35: raise ValueError("A1_NO_CATALOG_SITE_NEAR_REGISTERED_ANCHOR_"+anchor)
        selected.append(ordered[0][2]); target_anchors.append({"anchor":anchor,"latitude":lat,"longitude":lon,"distance_km":ordered[0][0]})
    if len(set(x.key for x in selected)) != 6: raise ValueError("A1_TARGET_ANCHOR_ALIAS")
    groups=[]
    for target,anchor in zip(selected,target_anchors):
        donors = select_donors(target,pool,heldout=selected)
        groups.append({"target":asdict(target),"target_key":target.key,"anchor":anchor,
            "donors":[{**asdict(s),"key":s.key,"distance_km":distance_km(target,s)} for s in donors],
            "geographic_donor_count_sufficient":len(donors)>=2,
            "validation_admitted":False,
            "remaining_source_gates":["historical station/sensor geometry for the 2025 windows",
                "station-specific temporal metadata; DE hourly operator remains unresolved" if target.country=="DE" else "registered parameter/operator evidence for the selected 2025 station",
                "exposure audit and observation quality/coverage before primary scoring"]})
    definitions = {"AT":{"temperature":"tl","humidity":"rf","absolute_pressure":"p","time_operator":"published_nominal_node",
            "time_basis":"prior frozen v1/v2 source chain; general field definition only, not new 2025 sensor certification",
            "QC_primary":[22],"QC_secondary":[12],"QC_changed_or_unspecified_origin_excluded":[0,10,11,20,21]},
        "DE":{"temperature":"TT_TU","humidity":"RF_TU","absolute_pressure":"P0","sea_level_pressure_excluded":"P",
            "time_operator":"unknown_for_hourly_product_until_own_parameter_metadata_read",
            "QC_TU":"QN_9","QC_pressure":"QN_8","QC_primary":[10],"QC_secondary":[3],
            "urban_schema_is_separate":"P0_ST_10 absolute; PP_ST_10 reduced; not used in this hourly adapter"},
        "CH":{"temperature":"tre200h0","humidity":"ure200h0","absolute_pressure":"prestah0",
            "sea_level_pressure_excluded":["pp0qffh0","pp0qnhh0"],"time_operator":"mean_six_10min_nominal_nodes",
            "pre_2018_hourly_operator":"NOT_ADMITTED","QC":"PUBLISHED_HISTORICAL_NO_PER_ROW_FLAG; separate stratum"}}
    requested_days = len(selected)*sum((pd.Timestamp(b)-pd.Timestamp(a)).days+1 for _,a,b in WINDOWS)
    protocol = {"schema":"IGE_A1_1_METADATA_AND_TEMPERATURE_PROTOCOL_v1","date":"2026-10-25",
        "product_function":"A: local historical reconstruction; sources/validation prerequisite, not a new weather generator release",
        "countries":["AT","DE","CH"],"windows":[{"season":s,"start_UTC":a,"end_UTC":b} for s,a,b in WINDOWS],
        "target_selection":"nearest full-2025 nominal catalog station to each fixed anchor, <=35km; no observed errors used",
        "targets":groups,"method":{"baseline":"B0 existing ERA5-derived elevation=nan",
            "candidate":"R1 same-time temperature residual IDW2, three nearest fixed donors, min2 QC-valid per hour",
            "donor_radius_km":150,"all_test_targets_and_identity_aliases_excluded":True,"minimum_distance_from_any_test_target_km":5,
            "distance_exponent":2,"lapse_or_inversion_fit":False,"target_measurements_used_in_prediction":False,
            "same_reference_operator_and_Celsius_units_required":True,"unqualified_hours":"NaN and explicit ledger; no hidden B0 substitution"},
        "time_comparison":{"AT":"ERA5 published hour node, internal sensor filter unknown",
            "DE":"BLOCKED until own hourly parameter/history evidence establishes an operator",
            "CH":"piecewise-linear ERA5 surrogate at six ten-minute reference nodes; coefficients 5/12 previous + 7/12 current",
            "CH_mean_RH_and_mean_T_do_not_define_observed_mean_q":True,"sensor_filter_or_subhour_model_path_equivalence_claimed":False},
        "observation_QC_policy":definitions,"requested_target_station_days":requested_days,
        "requested_target_reference_hours":requested_days*24,
        "scoring":{"primary":"paired MAE R1-B0 on exactly identical eligible reference timestamps per target/season",
            "also_report":["RMSE","bias","coverage and SOURCE_BLOCKED cells","all-reference B0 baseline","per-country and per-quality-stratum results"],
            "no_post_score_station_date_donor_or_QC_replacement":True,
            "uncertainty":"resample complete 7-day target-season blocks, 10000 draws, seed20261025; disclose 8 blocks/country and limited generality",
            "independent_qualification_gate":"not allowed until exposure + history + prediction seal and reference support checks pass",
            "automatic_promotion_to_default_or_EPW_allowed":False},
        "exposure":{"new_target_observations_read":False,"IV1_observations_opened":False,
            "prior_station_or_archive_exposure_exhaustively_audited":False,
            "new_2025_cohort_certified_strictly_blind":False,"ERA5_assimilation_independence_from_target_station_certified":False,
            "if_previous_exposure_found":"report as revealed regression, never re-label independent; separate future cohort needs its own registration"},
        "full_weather_integration":{"temperature_candidate_alone_is_not_a_complete_EPW":True,
            "RH_phase_pressure_height_radiation_and_precipitation_qualification_remain_separate":True,
            "A0_B_M1_and_U1_defaults_changed":False},"source_packets_sha256":PACKETS,
        "cost_budget_next_stage":{"distinct_catalog_sites":len({s.key for s in selected}|{d["key"] for g in groups for d in g["donors"]}),
            "metadata_requests_current":sum(m["total_HTTP_attempts"] for m in acquisition),
            "observation_or_ERA5_requests_current":0,"prospective_ERA5_annual_requests_max":24,
            "prospective_observation_assets_max":24,"prospective_raw_bytes_budget":200_000_000,
            "per_station_metadata_range_requests_need_separate_plan":True},
        "physical_accuracy_or_production_qualified":False,"global_validation_deferred_until_publication":True}
    status={"schema":"IGE_A1_1_ADMISSION_v1","status":"CATALOGS_AND_EXPERIMENT_CONTRACT_PREPARED_NOT_VALIDATION_READY",
        "eligible_nominal_catalog_stations":{c:sum(s.country==c for s in pool) for c in ("AT","DE","CH")},
        "target_count":6,"donor_slots":sum(len(g["donors"]) for g in groups),
        "target_reference_hours_planned":requested_days*24,"target_measurement_values_read":0,
        "historical_geometries_newly_verified":0,"fully_admitted_target_cells":0,
        "raw_metadata_HTTP_attempts":sum(m["total_HTTP_attempts"] for m in acquisition),
        "raw_metadata_bytes":sum(m["total_received_bytes"] for m in acquisition),
        "original_failed_requests":[e for m in acquisition for e in m["sources"] if e["status"]=="SOURCE_BLOCKED"],
        "field_contracts":definitions,"source_members_sha256":{n:e["sha256"] for n,e in receipts.items()},
        "quality_axes":{"execution_correctness":"METADATA_REPLAY_AND_PURE_ADAPTER_TESTS_REQUIRED",
            "physical_admissibility":"SOURCE_UNITS_AND_PRESSURE_SEMANTICS_ONLY; FULL_WEATHER_NOT_QUALIFIED",
            "independent_accuracy":"NOT_EVALUATED_AND_EXPOSURE_NOT_CERTIFIED",
            "operational_and_application_scope":"RESEARCH_COMPONENTS; A0_B_M1_U1_DEFAULTS_UNCHANGED"},
        "production_ready":False,"B4_qualified":False,"P2_superiority_established":False,"IV1_station_observations_opened":False}
    return protocol,status


if __name__ == "__main__":
    protocol,status=prepare()
    print(json.dumps({"targets":[{"target":g["target_key"],"name":g["target"]["name"],"donors":[d["key"] for d in g["donors"]]} for g in protocol["targets"]],
        "catalog_counts":status["eligible_nominal_catalog_stations"],"planned_reference_hours":status["target_reference_hours_planned"]},indent=2,ensure_ascii=False))
