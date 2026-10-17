#!/usr/bin/env python3
"""IGE P9.1F3 forensic source counts only, NEVER station values.

The original P9.1F1 2019 July 9×168 QC observations were all missing.
Check actual provider schema/flags and four fixed adjacent original periods.
No imputation, no override of scientific P9.1F1 result.
"""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import json
import math
import urllib.parse
from pathlib import Path

import p9_1b_geosphere_original_station_holdouts as original
import p9_1f1_terrain_inversion_2019_holdout as study

PERIODS=(("summer_2018","2018-07-10","2018-07-16"),
         ("june_2019","2019-06-10","2019-06-16"),
         ("july_2019","2019-07-10","2019-07-16"),
         ("august_2019","2019-08-10","2019-08-16"),
         ("summer_2020","2020-07-10","2020-07-16"))


def original_source_qc_metadata_only(result,sids,start,end):
    first=dt.datetime.fromisoformat(start+"T00:00+00:00")
    n=(dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days*24+24
    expected=[first+dt.timedelta(hours=i) for i in range(n)]
    observed=[dt.datetime.fromisoformat(str(t).replace("Z","+00:00"))
              for t in result.get("timestamps",[])]
    if observed!=expected:
        raise ValueError("P9F3_ORIGINAL_PROVIDER_TIME_AXIS_GAP_OR_DRIFT")
    station_count={}
    for fid in sids:
        station_count[fid]={
            "source_station_id":fid,
            "source_feature_present":False,
            "record_expected_hours":n,
            "temperature_nonmissing_hour_count":0,
            "original_QC_flag_frequencies":{},
            "original_QC_accepted_hour_count":0,
            "original_QC_rejected_or_missing_hour_count":n,
        }
    for f in result.get("features",[]):
        props=f.get("properties",{})
        obj=props.get("station")
        sid=int(obj["id"] if isinstance(obj,dict) else obj)
        if sid not in station_count or station_count[sid]["source_feature_present"]:
            raise ValueError("P9F3_UNREGISTERED_OR_DUPLICATED_STATION_FEATURE")
        p=props.get("parameters",{})
        t=p.get("tl",{})
        qc=p.get("tl_flag",{})
        values=t.get("data") if isinstance(t,dict) else None
        flags=qc.get("data") if isinstance(qc,dict) else None
        x=station_count[sid]
        x["source_feature_present"]=True
        if values is None or flags is None:
            x["source_parameters_tl_or_tl_flag_missing"]=True
            continue
        if len(values)!=n or len(flags)!=n:
            raise ValueError("P9F3_PROVIDER_VARIABLE_NOT_COMPLETE_168_HOUR_SUPPORT")
        code_hist=collections.Counter("NULL" if v is None else str(v) for v in flags)
        x["original_QC_flag_frequencies"]=dict(sorted(code_hist.items()))
        nonmissing=sum(v is not None and isinstance(v,(int,float))
                       and math.isfinite(v) for v in values)
        ok=sum(v is not None and isinstance(v,(int,float)) and math.isfinite(v)
               and flag in original.GOOD_FLAGS
               for v,flag in zip(values,flags))
        x["temperature_nonmissing_hour_count"]=nonmissing
        x["original_QC_accepted_hour_count"]=ok
        x["original_QC_rejected_or_missing_hour_count"]=n-ok
    return list(station_count.values())


def run(out):
    folder=Path(out);folder.mkdir(parents=True,exist_ok=True)
    samples=[]
    for name,start,end in PERIODS:
        params=urllib.parse.urlencode({
            "parameters":"tl,tl_flag",
            "station_ids":",".join(str(sid) for sid in study.IDS),
            "start":start+"T00:00Z","end":end+"T23:00Z",
            "output_format":"geojson"})
        response,sha=original.source_json(original.BASE+"?"+params)
        report=original_source_qc_metadata_only(response,study.IDS,start,end)
        assert len(report)==9
        samples.append({
            "name":name,"original_provider_source_sha256":sha,
            "original_provider_timestamps_exact_168":True,
            "n_stations":len(report),
            "aggregate_nonmissing_raw_tl_hours":sum(x["temperature_nonmissing_hour_count"]
                                                     for x in report),
            "aggregate_QC_accepted_hours":sum(x["original_QC_accepted_hour_count"]
                                              for x in report),
            "per_station_original_source_counts":report,
        })
        print("P9F3_ORIGINAL_GEOSPHERE_QC",json.dumps({
            "period":name,"source_nonmissing":samples[-1]["aggregate_nonmissing_raw_tl_hours"],
            "source_QC_accepted":samples[-1]["aggregate_QC_accepted_hours"],
            "QC_valid_sites":sum(x["original_QC_accepted_hour_count"]>=120 for x in report),
        }),flush=True)
    original_july=next(s for s in samples if s["name"]=="july_2019")
    result={
        "phase":"IGE_P9_1F3_ORIGINAL_2019_JULY_168H_GEOSPHERE_QC_GAP_FORENSIC",
        "registered_stations":list(study.IDS),
        "registered_original_source_periods":PERIODS,
        "n_original_ERA5_temperature_prediction_scores_recomputed":0,
        "original_P9F1_2019_July_QC_qualification_unchanged":False,
        "source_report_contains_no_original_hourly_station_temperature_values":True,
        "july_2019_original_QC_accepted_total":original_july["aggregate_QC_accepted_hours"],
        "no_override_of_original_QC_flags":True,
        "production_epw_ready":False,
        "periods":samples}
    (folder/"p9_1f3_original_2019_july_source_QC_forensic.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",required=True)
    run(p.parse_args().out)
