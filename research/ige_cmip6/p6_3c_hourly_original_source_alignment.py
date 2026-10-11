#!/usr/bin/env python3
"""IGE P6.3C hourly UTC/source-QC and measured daily solar integration seam.

Hourly solar values cglo (W/m², calibrated hour MEAN) must NOT be
treated as independently verified when their q21 flag is 0. Diagnostics
compare raw hourly sums under TWO alternative hourly timestamp-position
hypotheses against separately q21-approved calibrated daily cglo_j.
No interpolation, no promotion of unverified hourly flux to weather truth.
"""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from statistics import fmean

from p6_2d_solar_methods_benchmark import csvread,csvwrite,checksum
from p6_3c_precip_semantics_daily_alignment import QC_GOOD

YEARS=range(2005,2015)
LABELS=("hour_value_end_stamped","hour_value_start_stamped")
EXPECTED_HOURS=3652*24

def hourly_metadata_qa(qa,year,raw_path):
    if qa.get("status")!="PASS" or qa.get("station_id")!=30 or qa.get("year")!=year:
        raise ValueError("Wrong original verified annual GeoSphere source identity")
    if qa.get("expected_hours")!=(366 if year%4==0 else 365)*24:
        raise ValueError("Wrong original verified source hours/year")
    if qa.get("hourly_csv_gzip_sha256")!=checksum(raw_path):
        raise ValueError("Immutable original hourly source digest drift")
    specs=qa.get("parameter_metadata",{})
    if "kalibrierter Stunden-Mittelwert" not in specs.get("cglo",{}).get("description","") \
       or specs.get("cglo",{}).get("unit")!="W/m²":
        raise ValueError("Original hourly radiation physical unit or calibration description mismatch")
    if specs.get("tl",{}).get("unit")!="°C":
        raise ValueError("Hourly temperature physical unit unknown")
    return qa["hourly_csv_gzip_sha256"]

def read_annual(root,year):
    folder=root/f"ige-p6-2b-station30-{year}"
    quality=json.loads((folder/"quality_provenance.json").read_text(encoding="utf8"))
    raw=folder/"hourly_raw_qc.csv.gz"
    sha=hourly_metadata_qa(quality,year,raw)
    with gzip.open(raw,"rt",encoding="utf8",newline="") as f:
        data=list(csv.DictReader(f))
    if len(data)!=quality["expected_hours"]:
        raise ValueError("Annual hourly source incomplete")
    out=[];source_qa=Counter()
    for i,row in enumerate(data):
        when=datetime.fromisoformat(row["timestamp_utc"].replace("Z","+00:00"))
        expected=datetime(year,1,1,tzinfo=timezone.utc)+timedelta(hours=i)
        if when!=expected:raise ValueError("Provider hourly UTC time axis missing/duplicated")
        solar=float(row["cglo_raw"]) if row["cglo_raw"] not in ("",None) else None
        sflag=int(row["cglo_q21"]) if row["cglo_q21"] not in ("",None) else None
        checked=(sflag in QC_GOOD and solar is not None and -20<=solar<=2000)
        if checked != (row["cglo_accepted"] not in ("",None)):
            raise ValueError("Solar accepted q21 original source inconsistent")
        tl=float(row["tl_accepted"]) if row["tl_accepted"] not in ("",None) else None
        if solar is not None and (not math.isfinite(solar) or not -20<=solar<=2000):
            raise ValueError("Invalid original unverified solar power")
        source_qa["hourly_solar_checked" if checked else "hourly_solar_unverified"]+=1
        if sflag==0:source_qa["solar_q21_zero"]+=1
        if tl is not None:source_qa["hourly_temp_accepted"]+=1
        out.append({"date_utc":when.isoformat(),"datetime_utc":when,
                    "solar_Wm2_raw":solar,"solar_q21":sflag,
                    "solar_checked":checked,"temperature_c_accepted":tl})
    return out,{"year":year,"source_sha256":sha,
                "counts":dict(source_qa),
                "calibrated_hourly_solar_desc":
                     quality["parameter_metadata"]["cglo"]["description"],
                "hourly_utc_labels":len(data)}

def reconstruct(hourly_records,solar_daily,window):
    if window not in LABELS:raise ValueError("Unknown hourly timestamp convention")
    index={r["datetime_utc"]:r for r in hourly_records}
    out=[]
    for day in solar_daily:
        d=date.fromisoformat(day["date"])
        # Daily calibrated GeoSphere solar integrates [D-1 23:00, D 23:00) UTC.
        # The provider metadata does NOT specify whether hourly stamp
        # represents START or END of the preceding interval. Test both.
        beginning=datetime.combine(d-timedelta(days=1),datetime.min.time(),
                                   tzinfo=timezone.utc)+timedelta(hours=23)
        first=beginning if window=="hour_value_start_stamped" \
            else beginning+timedelta(hours=1)
        vals=[index.get(first+timedelta(hours=i)) for i in range(24)]
        complete=all(x is not None and x["solar_Wm2_raw"] is not None for x in vals)
        checked=complete and all(x["solar_checked"] for x in vals)
        # The entire 24h hourly source flux is hourly MEAN in W/m².
        # One hour * W/m² = Wh/m² -> divide by 1000 to kWh/m².
        energy=(sum(r["solar_Wm2_raw"] for r in vals)/1000.
                if complete else None)
        observed=day["ghi_kwh_m2_day"]
        out.append({"date":day["date"],"year":int(day["year"]),
            "month":int(day["month"]),"convention":window,
            "original_official_qc_daily_GHI_kwh_m2":observed,
            "raw_hourly_sum_kwh_m2":energy,
            "raw_hourly_minus_calibrated_daily_kwh_m2":(
                energy-observed if energy is not None else None),
            "original_hourly_complete":complete,
            "all_24_hourly_solar_q21_approved":bool(checked),
            "readiness":"VALIDATED_HOURLY" if checked else
                        "UNVERIFIED_HOURLY_SOLAR_NEVER_USE_AS_OBSERVATION",
            "reason":"Hourly cglo q21=0 denotes unchecked even when original calibrated daily cglo_j q21=20"})
    return out

def run(hourly_root,station_clean,out):
    out.mkdir(parents=True,exist_ok=True)
    raw=[];checks=[]
    for y in YEARS:
        year,prov=read_annual(hourly_root,y)
        raw.extend(year);checks.append(prov)
        print("P6.3C HOURLY",y,"q21=0",prov["counts"].get("solar_q21_zero",0),
              "q21 approved",prov["counts"].get("hourly_solar_checked",0),flush=True)
    if len(raw)!=EXPECTED_HOURS or \
       any(raw[i]["datetime_utc"]!=datetime(2005,1,1,tzinfo=timezone.utc)
           +timedelta(hours=i) for i in range(len(raw))):
        raise ValueError("10-year hourly source has gaps or conflicting UTC clock")
    stations=csvread(station_clean)
    if len(stations)!=3652:raise ValueError("Station daily QC full sample required")
    station=[]
    for r in stations:
        if int(r["station_id"])!=30:raise ValueError("Wrong measured reference station")
        station.append({"date":r["date"],"year":int(r["year"]),
                        "month":int(r["month"]),
                        "ghi_kwh_m2_day":float(r["ghi_kwh_m2_day"])})
    predictions=[]
    for convention in LABELS:
        predictions.extend(reconstruct(raw,station,convention))
    stats=[]
    for method in LABELS:
        test=[r for r in predictions if r["convention"]==method]
        for season,months in (("ANNUAL",range(1,13)),("JJA",(6,7,8))):
            subset=[r for r in test if r["month"] in months]
            available=[r for r in subset if r["raw_hourly_sum_kwh_m2"] is not None]
            trusted=[r for r in available if r["all_24_hourly_solar_q21_approved"]]
            diffs=[r["raw_hourly_minus_calibrated_daily_kwh_m2"] for r in available]
            stats.append({"convention":method,"season":season,
                "raw_hourly_reconstruction_complete_days":len(available),
                "hourly_q21_approved_complete_days":len(trusted),
                "official_accepted_daily_solar_days":len(subset),
                "raw_hourly_vs_daily_mean_absolute_error_kwh_m2":(
                     fmean(abs(x) for x in diffs) if diffs else None),
                "raw_hourly_vs_daily_mean_signed_bias_kwh_m2":(
                    fmean(diffs) if diffs else None),
                "hourly_verified_scientific_status":
                  "NO_INDEPENDENT_HOURLY_RADIATION_VALIDATION"
                  if not trusted else "SOME_Q21_CHECKED_HOURLY_AVAILABLE"})
    csvwrite(out/"p6_3c_2005_2014_hourly_daily_boundary_hypotheses.csv",
             predictions)
    csvwrite(out/"p6_3c_hourly_solar_comparison_summary.csv",stats)
    hashes={"daily_hypothesis_comparison":
        checksum(out/"p6_3c_2005_2014_hourly_daily_boundary_hypotheses.csv"),
        "summary":checksum(out/"p6_3c_hourly_solar_comparison_summary.csv")}
    report={"stage":"IGE_P6_3C_HOURLY_GEOSPHERE_ORIGINAL_Q21_BOUNDARY",
       "status":"PASS_HOURLY_SOURCE_UNVERIFIED_SOLAR_QUALITY_MUST_NOT_CALIBRATE",
       "hourly_counts_total":len(raw),
       "hourly_solar_flag_approved":sum(v["counts"].get("hourly_solar_checked",0)
                                      for v in checks),
       "hourly_solar_unverified":sum(v["counts"].get("hourly_solar_unverified",0)
                                   for v in checks),
       "official_daily_GHI_source":"Independent q21-accepted GeoSphere daily cglo_j, 23:00 previous UTC through 23:00 current UTC",
       "hourly_source":"GeoSphere original 1h cglo calibrated hourly mean W/m², q21 original is preserved",
       "hourly_timestamp_semantics":"Ambiguous: both start/end stamped assumptions retained, never silently select the higher correlation.",
       "annual_sources":checks,"method_summary":stats,
       "output_sha256":hashes,
       "limitations":["Hourly radiation q21=0 is UNCHECKED; reconstructed raw hourly cannot be treated as independently validated observation.",
           "Official daily cglo_j is calibrated 24-hour irradiance, not identical to arbitrary sum of unchecked hourly inputs.",
           "Interpolation, clipping raw original hourly source or shifting weather timestamps is forbidden at this stage.",
           "Window reconstruction is a sensitivity test, not proof of hourly timestamp interpretation.",
           "Long-wave and cloud-based multi-variable physical closure not established."]}
    (out/"p6_3c_hourly_original_qc_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("P6.3C HOURLY",report["status"],
          "hours",len(raw),"checked_hourly_ghi",
          report["hourly_solar_flag_approved"],flush=True)
    return report

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--yearly-root",type=Path,required=True)
    a.add_argument("--station-clean",type=Path,required=True)
    a.add_argument("--out",type=Path,required=True)
    v=a.parse_args()
    run(v.yearly_root,v.station_clean,v.out)
