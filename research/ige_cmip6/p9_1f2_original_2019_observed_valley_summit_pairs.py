#!/usr/bin/env python3
"""IGE P9.1F2 independent 2019 observed mountain/valley station-pair stratification.

Pairs are spatially separated, never equivalent to a collocated air column.
This diagnostic is NOT used to fit or select P9.1F1 fixed source-weather models.
"""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import json
import math
import statistics
import urllib.parse
from pathlib import Path
from zoneinfo import ZoneInfo
import p9_1b_geosphere_original_station_holdouts as source

PAIRS=((119,14305,"StAnton_Galzig"),(28,17005,"Galtuer_Idalpe"),
       (66,184,"Obergurgl_Pitztal"),(39,196,"Innsbruck_Patscherkofel"))
PERIODS=(("winter_2019","2019-01-10","2019-01-16"),
         ("summer_2019","2019-07-10","2019-07-16"),
         ("autumn_2019","2019-10-10","2019-10-16"))
MIN_SIMULTANEOUS_QC_PAIRS=100
MIN_PHASE_QC_PAIRS=20
TZ=ZoneInfo("Europe/Vienna")


def daypart_utc(s):
    stamp=dt.datetime.fromisoformat(s+"+00:00").astimezone(TZ)
    h=stamp.hour
    return "night" if h>=22 or h<6 else ("day" if 10<=h<16 else "transition")


def compute_pair(low,high,dz):
    if dz<=150:raise ValueError("P9F2_REGISTERED_UPPER_STATION_NOT_HIGHER")
    keys=sorted(low.keys() & high.keys())
    if len(keys)<MIN_SIMULTANEOUS_QC_PAIRS:
        return {"status":"INSUFFICIENT_ORIGINAL_QC_PAIRED_HOURS",
                "n_original_QC_simultaneous_hours":len(keys)}
    sample=collections.defaultdict(list)
    for t in keys:
        value=float(high[t])-float(low[t])
        sample["all"].append(value)
        sample[daypart_utc(t)].append(value)
    def aggregates(d):
        if len(d)<MIN_PHASE_QC_PAIRS:return None
        return {
            "n_original_source_accepted_pairs":len(d),
            "Tupper_minus_Tlower_mean_C":statistics.fmean(d),
            "observed_spatial_upper_warmer_fraction":sum(x>0 for x in d)/len(d),
            "observed_upper_warmer_than_standard_lapse_fraction":
                sum(x>-.0065*dz for x in d)/len(d),
            "standard_lapse_reference_upper_minus_lower_C":-.0065*dz,
            "observed_Tupper_above_Tlower_is_not_proof_collocated_inversion":True,
        }
    return {"status":"ORIGINAL_OBSERVED_PAIR_QC_QUALIFIED",
            "n_original_QC_simultaneous_hours":len(keys),
            "observed_pair_temperature_stratification_not_collocated_local_inversion":True,
            "groups":{phase:aggregates(sample[phase]) for phase in ("all","night","day","transition")}}


def run(out):
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    metadata,msha=source.source_json(source.BASE+"/metadata")
    catalog={int(s["id"]):s for s in metadata["stations"]}
    wanted=sorted({x for lo,hi,name in PAIRS for x in (lo,hi)})
    if not all(x in catalog for x in wanted):
        raise ValueError("P9F2_PREDECLARED_SOURCE_STATION_META_INCOMPLETE")
    rows=[];sources=[]
    for season,start,end in PERIODS:
        query=urllib.parse.urlencode({
            "station_ids":",".join(map(str,wanted)),
            "parameters":"tl,tl_flag",
            "start":start+"T00:00Z","end":end+"T23:00Z",
            "output_format":"geojson"})
        original,sha=source.source_json(source.BASE+"?"+query)
        records=source.decode_observed(original,set(wanted),start,end)
        sources.append({"season":season,"source_original_GeoSphere_SHA256":sha})
        for low,high,name in PAIRS:
            dz=float(catalog[high]["altitude"])-float(catalog[low]["altitude"])
            x=compute_pair(records[low],records[high],dz)
            row={
                "name":name,"lower_station_id":low,"upper_station_id":high,
                "lower_station_altitude_m":float(catalog[low]["altitude"]),
                "upper_station_altitude_m":float(catalog[high]["altitude"]),
                "upper_minus_lower_station_altitude_m":dz,
                "season":season,"source_original_GeoSphere_QC_SHA256":sha,**x}
            rows.append(row)
            print("P9F2_OBSERVED_PAIR",json.dumps({
                "pair":name,"period":season,
                "source_QC_status":x["status"],
                "n":x["n_original_QC_simultaneous_hours"],
                "night_upper_warmer_fraction":(
                    x.get("groups",{}).get("night") or {}).get(
                    "observed_spatial_upper_warmer_fraction"),
            }),flush=True)
    if len(rows)!=len(PAIRS)*len(PERIODS):
        raise ValueError("P9F2_PREDECLARED_OBSERVED_SOURCE_PAIR_CENSUS_INCOMPLETE")
    winter=[r for r in rows if r["season"]=="winter_2019" and
            r["status"]=="ORIGINAL_OBSERVED_PAIR_QC_QUALIFIED"]
    result={
        "phase":"IGE_P9_1F2_ORIGINAL_2019_SPATIALLY_SEPARATED_STATION_PAIR_STRATIFICATION",
        "n_frozen_station_pairs":len(PAIRS),
        "n_original_2019_pair_seasons_expected":len(rows),
        "n_QC_qualified_original_pair_seasons":sum(
            r["status"]=="ORIGINAL_OBSERVED_PAIR_QC_QUALIFIED" for r in rows),
        "n_qualified_winter_station_pairs":len(winter),
        "n_original_QC_matched_pair_hour_slots":sum(
            r["n_original_QC_simultaneous_hours"] for r in rows
            if r["status"]=="ORIGINAL_OBSERVED_PAIR_QC_QUALIFIED"),
        "original_station_meta_sha256":msha,
        "source_responses":sources,
        "station_upper_minus_lower_is_spatial_gradient_not_local_vertical_profile":True,
        "relevant_to_source_weather_cold_pool_diagnostics_not_temperature_model_fitting":True,
        "new_climate_region_outside_Austria_independently_validated":False,
        "local_inversion_physical_model_fully_qualified":False,
        "production_epw_ready":False,
        "members":rows}
    (root/"p9_1f2_2019_independent_original_station_pair_stratification.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print("P9F2_ORIGINAL_PAIR_SUMMARY",json.dumps({
        "qualified":result["n_QC_qualified_original_pair_seasons"],
        "winter":len(winter),"matched_pairs":result["n_original_QC_matched_pair_hour_slots"],
        "global_production_ready":False}),flush=True)
    if len(winter)<2:
        raise RuntimeError("P9F2_INSUFFICIENT_REAL_SOURCE_WINTER_PAIRS")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",required=True)
    run(p.parse_args().out)
