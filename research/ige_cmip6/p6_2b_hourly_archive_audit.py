#!/usr/bin/env python3
"""P6.2B independent hourly station-30 1995–2014 quality/coverage audit.

Combines 20 immutable annual provider responses, checks UTC grids and hashes,
and compares quality-screened descriptive aggregates against *independent*
GeoSphere monthly station data. No re-bias-correction and no EPW.
"""
from __future__ import annotations
import argparse
import calendar
import csv
import gzip
import hashlib
import json
from pathlib import Path
from statistics import fmean

from p6_2b_hourly_observations import FIELDS,STATION
from p6_2a_geosphere_monthly import extract_monthly

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rows(path):
    with path.open(newline='',encoding='utf8') as f:
        return list(csv.DictReader(f))

def audit(root,station_monthly,out):
    obsdata=json.loads(station_monthly.read_text(encoding="utf8"))
    official=extract_monthly(obsdata)
    official_map={(r["year"],r["month"]):r for r in official}
    source={};monthly=[];used_dates=set();raw_over=0
    total_hourly=0;codes={p:{} for p in FIELDS}
    for year in range(1995,2015):
        folder=root/str(year)
        report=json.loads((folder/"quality_provenance.json").read_text(encoding="utf8"))
        if report.get("status")!="PASS" or report.get("station_id")!=STATION or report.get("year")!=year:
            raise ValueError(f"Incorrect P6.2B year source metadata: {folder}")
        expected=(366 if calendar.isleap(year) else 365)*24
        if report.get("hour_count")!=expected or report.get("expected_hours")!=expected:
            raise ValueError(f"Wrong annual hourly coverage {year}")
        if sha(folder/"hourly_raw_qc.csv.gz")!=report["hourly_csv_gzip_sha256"] \
            or sha(folder/"monthly_coverage.csv")!=report["monthly_csv_sha256"]:
            raise ValueError(f"Corrupt hourly or monthly CSV {year}")
        with gzip.open(folder/"original_hourly_provider.geojson.gz","rb") as f:
            raw=f.read()
        if hashlib.sha256(raw).hexdigest()!=report["source_uncompressed_sha256"]:
            raise ValueError(f"Provider byte provenance invalid {year}")
        with gzip.open(folder/"hourly_raw_qc.csv.gz","rt",encoding="utf8",newline="") as f:
            reader=csv.DictReader(f)
            count=0
            for r in reader:
                count+=1
                yearhour=r["timestamp_utc"]
                if yearhour in used_dates:raise ValueError("Duplicated cross-year UTC hour")
                if not yearhour.startswith(str(year)+"-"):
                    raise ValueError("Wrong UTC year in hourly data")
                used_dates.add(yearhour)
                for p in FIELDS:
                    if r.get(p+"_raw") is None or r.get(p+"_q21") is None \
                        or r.get(p+"_accepted") is None:
                        raise ValueError("Missing hourly source or QC schema")
            if count!=expected:
                raise ValueError(f"Hourly CSV incomplete {year}: {count}/{expected}")
        series=rows(folder/"monthly_coverage.csv")
        if len(series)!=12:raise ValueError(f"Year {year} has missing monthly data")
        for m,r in enumerate(series,1):
            if (int(r["year"]),int(r["month"]))!=(year,m):
                raise ValueError(f"Unordered monthly station data {year}")
            if int(r["expected_UTC_hours"])!=calendar.monthrange(year,m)[1]*24:
                raise ValueError(f"Incorrect calendar month hours {year}/{m}")
            data={"year":year,"month":m}
            for p in FIELDS:
                cov=float(r[p+"_coverage"])
                n=int(r[p+"_qc_hours"])
                expect=int(r["expected_UTC_hours"])
                if n<0 or n>expect or abs(n/expect-cov)>1e-8:
                    raise ValueError(f"Invalid QC coverage {p} {year}-{m}")
                data[p+"_qc_coverage"]=cov
                t=r[p+"_mean_if_90pct"]
                data[p+"_hourly_mean_90pct"]=float(t) if t else None
            raw_pr=r["rr_hourly_sum_unverified_mm"]
            data["rr_hourly_sum_unverified_mm"]=float(raw_pr) if raw_pr else None
            observation=official_map[(year,m)]
            data["official_monthly_tl_mittel_c"]=observation["obs_temp_c"]
            data["official_monthly_rr_mm"]=observation["obs_pr_mm"]
            data["tl_hourly_minus_official_tl_mittel_c"]=(
                data["tl_hourly_mean_90pct"]-observation["obs_temp_c"]
                if data["tl_hourly_mean_90pct"] is not None and observation["obs_temp_c"] is not None
                else None)
            data["rr_hourly_sum_minus_official_mm_UNVERIFIED"]=(
                data["rr_hourly_sum_unverified_mm"]-observation["obs_pr_mm"]
                if data["rr_hourly_sum_unverified_mm"] is not None and observation["obs_pr_mm"] is not None
                else None)
            monthly.append(data)
        for p in FIELDS:
            cc=report.get("q21_distribution",{}).get(p,{})
            for label,count in cc.items():
                codes[p][label]=codes[p].get(label,0)+int(count)
        source[str(year)]={
            "expected_hours":expected,
            "provider_raw_sha256":report["source_uncompressed_sha256"],
            "monthly_coverage_sha256":report["monthly_csv_sha256"],
            "hourly_file_sha256":report["hourly_csv_gzip_sha256"],
            "parameter_units":report.get("parameter_units"),
            "unavailable_quality_flags":report.get("unavailable_quality_flags",[]),
        }
        total_hourly+=expected
    if len(monthly)!=240 or len(used_dates)!=total_hourly:
        raise ValueError("Historical hourly completeness mismatch")
    expected_hours=sum((366 if calendar.isleap(y) else 365)*24 for y in range(1995,2015))
    if total_hourly!=expected_hours:raise ValueError("1995–2014 hours expected mismatch")
    if len({tuple((r["year"],r["month"])) for r in monthly})!=240:
        raise ValueError("Duplicated month-year observations")
    temp_dif=[r["tl_hourly_minus_official_tl_mittel_c"] for r in monthly
              if r["tl_hourly_minus_official_tl_mittel_c"] is not None]
    pr_dif=[r["rr_hourly_sum_minus_official_mm_UNVERIFIED"] for r in monthly
            if r["rr_hourly_sum_minus_official_mm_UNVERIFIED"] is not None]
    out.mkdir(parents=True,exist_ok=True)
    out_csv=out/"hourly_monthly_coverage_vs_official.csv"
    with out_csv.open("w",newline="",encoding="utf8") as f:
        writer=csv.DictWriter(f,fieldnames=list(monthly[0]))
        writer.writeheader();writer.writerows(monthly)
    assessment={
        "status":"PASS_SOURCE_INTEGRITY_ONLY",
        "stage":"P6.2B_1995_2014_STATION_HOURLY_QC",
        "observation_station_id":STATION,
        "years":20,"utc_hours":total_hourly,"months":len(monthly),
        "years_provenance":source,
        "quality_flag_counts":codes,
        "official_station_monthly_sha256":sha(station_monthly),
        "hourly_monthly_comparison_sha256":sha(out_csv),
        "tl_hourly_monthly_eligible_comparisons":len(temp_dif),
        "tl_hourly_minus_official_tl_mittel_monthly_mae_c":
            fmean(abs(v) for v in temp_dif) if temp_dif else None,
        "rr_hourly_sum_eligible_comparisons_UNVERIFIED":len(pr_dif),
        "rr_hourly_sum_minus_official_monthly_mae_mm_UNVERIFIED":
            fmean(abs(v) for v in pr_dif) if pr_dif else None,
        "monthly_qc_coverage":{p:{
            "months_ge90pct":sum(r[p+"_qc_coverage"]>=.9 for r in monthly),
            "months_ge99pct":sum(r[p+"_qc_coverage"]>=.99 for r in monthly),
            "mean_coverage":fmean(r[p+"_qc_coverage"] for r in monthly),
        } for p in FIELDS},
        "limitations":[
            "Pass certifies source retrieval, byte SHA-256, hourly UTC chronology and transparent QC screening, NOT station/model validation.",
            "tl hourly arithmetic mean differs in formal definition from GeoSphere monthly tl_mittel; differences are exploratory.",
            "Hourly rr sum remains UNVERIFIED until provider semantics are confirmed; no correction fitted.",
            "A null/raw rejected observation remains missing; no imputation or artificial zero filling.",
            "Days and model grid-cell comparison are not computed in this stage.",
        ],
    }
    (out/"p6_2b_hourly_historical_audit.json").write_text(json.dumps(
        assessment,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    return assessment

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--yearly-root",type=Path,default=Path("input_yearly"))
    p.add_argument("--official-monthly",type=Path,required=True)
    p.add_argument("--output",type=Path,default=Path("outputs/p6_2b_historical_audit"))
    a=p.parse_args()
    r=audit(a.yearly_root,a.official_monthly,a.output)
    print("P6.2B STATION AUDIT",r["status"],"hours",r["utc_hours"],
          "months",r["months"],"temperature comparable",r["tl_hourly_monthly_eligible_comparisons"],flush=True)

if __name__=="__main__":
    main()
