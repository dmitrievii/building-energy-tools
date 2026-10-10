#!/usr/bin/env python3
"""P6.2B solar historical benchmark and eight NEX-GDDP-CMIP6 model comparisons.

Validates four immutable GeoSphere 5-year sources; independently obtains the
official 240-month cglo_j series; compares only QC-complete station months.
Model years are stochastic realisations, not observed day/year predictions;
metrics are month-of-year CLIMATOLOGY/UNPAIRED distributions, no per-date RMSE.
"""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math
from collections import Counter,defaultdict
from datetime import date,timedelta
from pathlib import Path
from statistics import fmean

from p6_2b_solar_daily_reference import (
    URL,STATION,NAME,FLAG,UNIT,QC_GOOD,KWH_PER_J_CM2,PERIODS,
    dates_between,meta_contract,read_json,sha,
)
from p6_2a_eight_model_ensemble import MODELS,original_quality
from p6_2a_joint_diagnostics import quantile

HIST="historical-1995-2014"
REPAIRED_HIST={"EC-Earth3","IPSL-CM6A-LR","MPI-ESM1-2-HR"}

def table(path):
    with Path(path).open(newline="",encoding="utf8") as f:
        return list(csv.DictReader(f))

def write(path,rows):
    if not rows:raise ValueError("Missing output rows: "+str(path))
    with path.open("w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader();w.writerows(rows)
    return sha(path.read_bytes())

def stage_daily(root):
    records=[];sources={};periods=set()
    for first,last in PERIODS:
        key=f"{first}-{last}"
        folder=root/key
        qa=json.loads((folder/"source_quality_report.json").read_text(encoding="utf8"))
        if qa.get("status")!="PASS_SOURCE_QC" or (
            qa.get("year_start"),qa.get("year_end"))!=(first,last):
            raise ValueError("Wrong source period/quality report "+key)
        csvfile=folder/"daily_station30_cglo_j_qc.csv"
        if sha(csvfile.read_bytes())!=qa["csv_sha256"]:
            raise ValueError("Corrupt daily source CSV "+key)
        with gzip.open(folder/"original_geosphere_daily_5y.geojson.gz","rb") as f:
            raw=f.read()
        if sha(raw)!=qa["provider_raw_uncompressed_sha256"]:
            raise ValueError("Corrupt original source response "+key)
        chunk=table(csvfile)
        wanted=list(dates_between(date(first,1,1),date(last,12,31)))
        if len(chunk)!=len(wanted) or qa["expected_days"]!=len(wanted):
            raise ValueError("Wrong calendar chunk "+key)
        for row,day in zip(chunk,wanted):
            if row["date_geo_moz_utc_label"]!=day.isoformat() or int(row["year"])!=day.year \
               or int(row["month"])!=day.month or int(row["day"])!=day.day:
                raise ValueError("Missing or reordered station calendar day")
            rawvalue=row["cglo_j_raw_J_cm2"]
            flag=row["cglo_j_q21"]
            accepted=row["cglo_j_accepted_kwh_m2"]
            v=float(rawvalue) if rawvalue not in ("",None) else None
            q=int(flag) if flag not in ("",None) else None
            ok=(v is not None and q in QC_GOOD and 0<=v<=4500)
            if ok:
                if accepted in ("",None) or abs(float(accepted)-v*KWH_PER_J_CM2)>1.e-7:
                    raise ValueError("Solar conversion or QC integrity mismatch "+day.isoformat())
            elif accepted not in ("",None):
                raise ValueError("Unverified raw solar value promoted to trusted output")
            records.append({
                "date_geo_moz_utc_label":day.isoformat(),
                "year":day.year,"month":day.month,"day":day.day,
                "cglo_j_raw_J_cm2":v,"q21":q,
                "trusted_daily_kwh_m2":float(accepted) if ok else None,
            })
        sources[key]={"raw_sha256":qa["provider_raw_uncompressed_sha256"],
                      "csv_sha256":qa["csv_sha256"],
                      "dates":len(chunk),"q21_distribution":qa["q21_distribution"],
                      "accepted":qa["quality_counts"]["accepted"]}
        periods.add(key)
    if len(records)!=7305 or len(periods)!=4:
        raise ValueError(f"Unexpected 20-year Gregorian daily coverage {len(records)}")
    return records,sources

def official_monthly():
    meta_bytes,meta=read_json(URL.replace("klima-v2-1d","klima-v2-1m")+"/metadata",8000000)
    params={p["name"]:p for p in meta.get("parameters",[])}
    if params.get(NAME,{}).get("unit")!=UNIT or FLAG not in params:
        raise ValueError("Official monthly calibrated solar unit or flag unavailable")
    stations={int(s["id"]):s for s in meta.get("stations",[]) if "id" in s}
    if STATION not in stations:raise ValueError("Missing monthly station 30")
    from urllib.parse import urlencode
    url=URL.replace("klima-v2-1d","klima-v2-1m")+"?"+urlencode({
        "parameters":f"{NAME},{FLAG}",
        "station_ids":str(STATION),"start":"1995-01-01","end":"2014-12-31",
        "output_format":"geojson"})
    raw,data=read_json(url,12000000)
    times=data.get("timestamps",[])
    want=[f"{y}-{m:02d}" for y in range(1995,2015) for m in range(1,13)]
    if len(times)!=240 or [str(t)[:7] for t in times]!=want:
        raise ValueError("Official monthly time series incomplete")
    features=data.get("features",[])
    if len(features)!=1:raise ValueError("Wrong official monthly station count")
    prop=features[0]["properties"];id=prop["station"]
    if int(id if not isinstance(id,dict) else id["id"])!=STATION:
        raise ValueError("Wrong station for official monthly observations")
    ps=prop.get("parameters",{})
    if ps.get(NAME,{}).get("unit")!=UNIT or len(ps[NAME].get("data",[]))!=240 \
       or len(ps.get(FLAG,{}).get("data",[]))!=240:
        raise ValueError("Official monthly source/flags lengths or units wrong")
    records=[]
    for i,(label,value,flag) in enumerate(zip(want,ps[NAME]["data"],ps[FLAG]["data"])):
        q=int(flag) if flag is not None else None
        v=float(value) if value is not None else None
        if v is not None and not math.isfinite(v):raise ValueError("Nonfinite monthly solar")
        ok=v is not None and q in QC_GOOD and 0<=v<=140000
        records.append({
            "year":1995+i//12,"month":1+i%12,
            "official_monthly_cglo_j_raw_J_cm2":v,
            "official_q21":q,
            "official_monthly_kwh_m2_if_checked":v*KWH_PER_J_CM2 if ok else None,
        })
    return records,raw,{
        "provider_url":url,
        "provider_sha256":sha(raw),
        "metadata_sha256":sha(meta_bytes),
        "parameter_metadata":params[NAME],
        "source_station_metadata":stations[STATION],
        "quality_distribution":dict(Counter(str(r["official_q21"]) for r in records)),
    }

def monthly_closure(daily,official):
    bymonth=defaultdict(list)
    for row in daily:bymonth[(row["year"],row["month"])].append(row)
    officialmap={(r["year"],r["month"]):r for r in official}
    rows=[];daily_all=[];deltas=[];fullqc_annual=defaultdict(list)
    for key in sorted(bymonth):
        year,month=key;rr=bymonth[key]
        expected=len(rr)
        verified=[r["trusted_daily_kwh_m2"] for r in rr if r["trusted_daily_kwh_m2"] is not None]
        if not 28<=expected<=31:raise ValueError("Incorrect month calendar")
        complete=len(verified)==expected
        source=officialmap[key]
        monthly=source["official_monthly_kwh_m2_if_checked"]
        total=sum(verified) if complete else None
        diff=(total-monthly) if total is not None and monthly is not None else None
        diff_pct=100*diff/monthly if diff is not None and monthly else None
        if diff is not None:deltas.append(diff)
        if complete:fullqc_annual[year].append(month)
        row={"year":year,"month":month,"days":expected,"verified_days":len(verified),
             "daily_qc_fraction":len(verified)/expected,
             "observed_daily_sum_kwh_m2_if_complete":total,
             "official_monthly_kwh_m2_if_checked":monthly,
             "daily_sum_minus_monthly_kwh_m2":diff,
             "daily_sum_minus_monthly_pct":diff_pct,
             "official_q21":source["official_q21"],
             "time_boundary_note":"daily MOZ 23prev-23 UTC; monthly calibrated hours; totals not guaranteed identical"}
        rows.append(row)
    if len(rows)!=240:
        raise ValueError("Solar month coverage incomplete")
    complete_years=[y for y,m in fullqc_annual.items() if len(m)==12]
    return rows,{
        "days_observed":len(daily),
        "qc_accepted_days":sum(r["trusted_daily_kwh_m2"] is not None for r in daily),
        "months_with_all_daily_checked":sum(r["verified_days"]==r["days"] for r in rows),
        "months_with_approved_official_monthly":sum(r["official_monthly_kwh_m2_if_checked"] is not None for r in rows),
        "months_comparable_daily_to_monthly":len(deltas),
        "monthly_mean_absolute_difference_kwh_m2":fmean(abs(v) for v in deltas) if deltas else None,
        "monthly_max_abs_difference_kwh_m2":max(map(abs,deltas)) if deltas else None,
        "years_with_12_checked_daily_months":complete_years,
    }

def compare_to_8_models(solar_months,access,original,repaired):
    observed=defaultdict(list)
    for r in solar_months:
        if r["observed_daily_sum_kwh_m2_if_complete"] is not None:
            observed[r["month"]].append(r["observed_daily_sum_kwh_m2_if_complete"])
    comparisons=[];qc={}
    for model in MODELS:
        if model=="ACCESS-CM2":folder=access/"ige-p6-access-historical-1995-2014"
        elif model in REPAIRED_HIST:folder=repaired/f"ige-p6-{model}-{HIST}"
        else:folder=original/f"ige-p6-{model}-{HIST}"
        q,p,hashes,days=original_quality(folder,model,HIST)
        monthly=table(folder/"model_monthly.csv")
        if len(monthly)!=240:raise ValueError(f"Missing original NASA monthly GHI: {model}")
        bymonth=defaultdict(list)
        for row in monthly:
            if row["window"]!=HIST or row["scenario"]!="historical" or \
               not 1995<=int(row["year"])<=2014:
                raise ValueError("Wrong NASA model/month/scenario")
            mm=int(row["month"])
            kwh=float(row["ghi_kwh_m2"])
            if not math.isfinite(kwh) or kwh<0:raise ValueError("Invalid original NASA GHI")
            bymonth[mm].append(kwh)
        if len(bymonth)!=12 or any(len(x)!=20 for x in bymonth.values()):
            raise ValueError("NASA monthly model years missing")
        qc[model]={"source_quality_sha256":sha((folder/"quality_report.json").read_bytes()),
                   "source_provenance_sha256":sha((folder/"source_provenance.json").read_bytes()),
                   "source_monthly_csv_sha256":hashes["model_monthly.csv"],
                   "model_grid_center":q["grid"],"calendar":q["calendar"],
                   "days":days,"source_count":len(p["subset_provenance"])}
        for m in range(1,13):
            o=observed[m];g=bymonth[m]
            usable=len(o)>=15
            mean_station=fmean(o) if usable else None
            mean_gcm=fmean(g)
            comparisons.append({
                "model":model,"month":m,
                "NASA_model_years":20,"station_complete_qc_years":len(o),
                "station_sufficient_for_reference_15_years":usable,
                "NASA_ghi_mean_kwh_m2":mean_gcm,
                "station_daily_QC_ghi_mean_kwh_m2":mean_station,
                "NASA_minus_station_month_climatology_kwh_m2":
                    mean_gcm-mean_station if usable else None,
                "NASA_to_station_ratio":
                    mean_gcm/mean_station if usable and mean_station>0 else None,
                "NASA_ghi_p10_kwh_m2":quantile(g,.1),
                "NASA_ghi_p90_kwh_m2":quantile(g,.9),
                "station_ghi_p10_kwh_m2":quantile(o,.1) if usable else None,
                "station_ghi_p90_kwh_m2":quantile(o,.9) if usable else None,
                "interpretation":"unpaired_20yr_month_of_year_distributions_not_daily_rmse",
            })
    if len(comparisons)!=96:
        raise ValueError("Not eight model month-climatology records")
    return comparisons,qc

def execute(chunks,access,original,repaired,out):
    solar,source_inventory=stage_daily(chunks)
    monthly_raw,official_raw,monthly_provenance=official_monthly()
    solar_months,solar_stats=monthly_closure(solar,monthly_raw)
    comparisons,model_provenance=compare_to_8_models(solar_months,access,original,repaired)
    out.mkdir(parents=True,exist_ok=True)
    with gzip.open(out/"geosphere_official_monthly_cglo_j.geojson.gz","wb") as f:
        f.write(official_raw)
    outputs={
        "station30_1995_2014_daily_solar_qc.csv":solar,
        "station30_daily_monthly_solar_closure.csv":solar_months,
        "eight_nasa_model_monthly_ghi_vs_geosphere.csv":comparisons,
    }
    hashes={name:write(out/name,rows) for name,rows in outputs.items()}
    reference_usable=sum(r["station_sufficient_for_reference_15_years"] for r in comparisons)==96
    summary={
        "status":"PASS_SOURCE_INTEGRITY" if reference_usable else "PASS_SOURCE_INTEGRITY_LIMITED_REFERENCE",
        "stage":"P6.2B_SOLAR_REFERENCE_CLOSURE",
        "source":"GeoSphere Austria Station Data-v2 1d cglo_j and 1m cglo_j",
        "station":STATION,
        "daily_calendar":"Gregorian",
        "raw_daily_unit":"J/cm²",
        "conversion":"kWh/m² = J/cm² / 360",
        "daily_window":"00–24 MOZ (23:00 preceding UTC day to 23:00 stated UTC day)",
        "model_day_warning":"NASA grid/model and GeoSphere station daily boundaries differ; only month-of-year unpaired climatologies are compared",
        "model_count":8,"model_monthly_rows":len(comparisons),
        "solar_observation_summary":solar_stats,
        "model_and_source_provenance":model_provenance,
        "geosphere_daily_chunks":source_inventory,
        "geosphere_official_monthly_source":monthly_provenance,
        "results_sha256":hashes,
        "reference_sufficient_15_complete_months":reference_usable,
        "limitations":[
            "Station 30 at 47.08N is not the NASA sampled grid cell at 46.875N.",
            "NASA data are already bias-corrected and downscaled with BCSD, NO second correction was fitted.",
            "Monthly source itself may use different window boundaries, so daily/monthly differences are diagnostic, not forced to zero.",
            "Any incomplete observed month is excluded from its sum; no infilling or scaling.",
            "Model-year 1995 is NOT assumed to be the observed weather in station year 1995.",
            "No local pressure/humidity/radiation joint hourly series or EPW produced.",
        ]
    }
    (out/"p6_2b_solar_reference_audit.json").write_text(json.dumps(
        summary,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P6.2B SOLAR REF",summary["status"],"days",solar_stats["days_observed"],
          "checked",solar_stats["qc_accepted_days"],"complete monthly",solar_stats["months_with_all_daily_checked"],
          "full obs support",reference_usable,flush=True)
    return summary

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--chunks",type=Path,required=True)
    p.add_argument("--access",type=Path,required=True)
    p.add_argument("--original",type=Path,required=True)
    p.add_argument("--repaired",type=Path,required=True)
    p.add_argument("--out",type=Path,default=Path("outputs/p6_2b_solar_reference_audit"))
    a=p.parse_args()
    execute(a.chunks,a.access,a.original,a.repaired,a.out)

if __name__=="__main__":
    main()
