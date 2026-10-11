#!/usr/bin/env python3
"""IGE P6.3B: independent observed-climatology dependence and 2 M3 anomalies.

Two affected model-window/relationship cases are reproduced from original
SHA-verified NASA P6.1 climate variables and P6.2D-C correction algorithms,
not from the saved P6.3A scores. GeoSphere Graz #30 daily QC observations
and NASA POWER gridded satellite/reanalysis data 2005–14 independently
estimate observed-reference day-scale meteorological associations.

No future observational truth exists. M3 future anomaly diagnosis is
source-model-internal distribution analysis, not validation against future
weather or proof of cause. Model/station daily weather is NEVER paired.
"""
from __future__ import annotations
import argparse,csv,json,math,random
from collections import defaultdict
from pathlib import Path
from statistics import fmean

from p6_2d_solar_methods_benchmark import (
    HIST,METHODS,station_months,original_nasa_months,fit_months,checksum,csvwrite
)
from p6_2d_b_daily_clearsky_benchmark import STATION_ALT_M
from p6_2d_c_sensitivity_future_signals import normalized,fit,correct,monthly_methods,year_months
from p6_3a_solar_joint_coherence import (
    NEW,ALL_METHODS,read_original,daily_methods,method_diagnostics,
    dependence_change,corr_vectors,rank,
)
from p6_3b_independent_reference_sources import acquire_geosphere,acquire_power

ANOMALIES=(
    {"model":"CanESM5","relationship":"tas_rsds","climate_variable":"tas_c",
     "reference_variable":"temperature_air_c","window":"ssp585-2080-2099",
     "expected_pearson_change_signal_distortion":.10090383691079702},
    {"model":"IPSL-CM6A-LR","relationship":"longwave_rsds",
     "climate_variable":"rlds_kwh_m2_day",
     "reference_variable":"longwave_kwh_m2_day","window":"ssp585-2080-2099",
     "expected_pearson_change_signal_distortion":.13913161372266142},
)
EVALUATION_YEARS=range(2005,2015)
FULL_HIST_YEARS=range(1995,2015)
FUTURE_YEARS=range(2080,2100)
BOOTSTRAP_N=500
STATION_MIN_PAIRS=150
POWER_MIN_PAIRS=300

def unpaired_corr(rows,met_field,ghi_field="ghi_kwh_m2_day",month_subset=(6,7,8)):
    candidates=[]
    years=set()
    for r in rows:
        if int(r["month"]) not in month_subset or not r.get("is_complete",True):
            continue
        solar=r.get(ghi_field)
        other=r.get(met_field)
        if solar in ("",None) or other in ("",None):continue
        s=float(solar);v=float(other)
        if not math.isfinite(s) or not math.isfinite(v):
            raise ValueError("Nonfinite reference climatological pair")
        candidates.append((int(r["year"]),v,s))
        years.add(int(r["year"]))
    return candidates

def estimate(pairs):
    if len(pairs)<30:return {"n":len(pairs),"pearson":None,"spearman":None}
    a=[x[1] for x in pairs];b=[x[2] for x in pairs]
    return {"n":len(pairs),"pearson":corr_vectors(a,b),
            "spearman":corr_vectors(rank(a),rank(b))}

def block_bootstrap(pairs,seed):
    """Resample whole YEARS, never individual days and never align GCM years."""
    baseline=estimate(pairs)
    if baseline["n"]<30 or baseline["pearson"] is None:
        return {**baseline,"ci_95_low":None,"ci_95_high":None}
    byyear=defaultdict(list)
    for record in pairs:byyear[record[0]].append(record)
    yrs=sorted(byyear)
    if len(yrs)<8:return {**baseline,"ci_95_low":None,"ci_95_high":None}
    generator=random.Random(seed)
    distribution=[]
    for _ in range(BOOTSTRAP_N):
        sample=[r for y in generator.choices(yrs,k=len(yrs)) for r in byyear[y]]
        score=estimate(sample)["pearson"]
        if score is not None:distribution.append(score)
    if len(distribution)<450:raise ValueError("Too few valid year-block bootstrap draws")
    distribution.sort()
    return {**baseline,"ci_95_low":distribution[12],
            "ci_95_high":distribution[487],
            "bootstrap_year_blocks":len(yrs),
            "bootstrap_repetitions":BOOTSTRAP_N,
            "ci_method":"resampled entire years of daily JJA data, percentile 95%"}

def source_model_methods(name,station_csv,
                         access_hist,original_hist,repaired_hist,
                         access_future,original_future,repaired_future):
    station_month=station_months(station_csv)
    from p6_2d_b_daily_clearsky_benchmark import reference_daily
    station_daily,_=reference_daily(station_csv)
    h,hjoint,hprov=read_original(name,HIST,access_hist,original_hist,
            repaired_hist,access_future,original_future,repaired_future)
    hm,_=original_nasa_months(name,access_hist,original_hist,repaired_hist)
    monthrules=fit_months(station_month,hm)
    station_norm=normalized(station_daily,STATION_ALT_M,1.10,False)
    hist_norm=normalized(h,366.,1.10,True)
    m3rule=fit(station_norm,hist_norm,range(1995,2005),1.10)
    hist_m1_m2=monthly_methods(hm,monthrules)
    hist_solar=daily_methods(hist_norm,hist_m1_m2,
        correct(hist_norm,m3rule,1.10,FULL_HIST_YEARS))
    hstats,_=method_diagnostics(hjoint,hist_solar,name,HIST)
    target="ssp585-2080-2099"
    f,fjoint,fprov=read_original(name,target,access_hist,original_hist,
            repaired_hist,access_future,original_future,repaired_future)
    future_norm=normalized(f,366.,1.10,True)
    future_month=monthly_methods(year_months(future_norm),monthrules)
    future_solar=daily_methods(future_norm,future_month,
        correct(future_norm,m3rule,1.10,FUTURE_YEARS))
    fstats,_=method_diagnostics(fjoint,future_solar,name,target)
    drift=dependence_change(hstats,fstats)
    return {"name":name,
            "historical":{"joint":hjoint,"solar":hist_solar,"geometry":hist_norm,
                          "source":hprov,"stats":hstats},
            "future":{"joint":fjoint,"solar":future_solar,"geometry":future_norm,
                      "source":fprov,"stats":fstats},
            "change_drift":drift}

def case_audit(item,anomaly,station_rows,power_rows):
    met=anomaly["climate_variable"]
    ref=anomaly["reference_variable"]
    historical=item["historical"];future=item["future"]
    model=item["name"];rel=anomaly["relationship"]
    selected=[r for r in item["change_drift"]
              if r["method"]==NEW and r["season"]=="JJA" and
                 r["relationship"]==rel]
    if len(selected)!=1:raise ValueError("Expected unique reproducible anomaly")
    record=selected[0]
    numerical=record["pearson_signal_distortion_vs_original"]
    if numerical is None or abs(numerical-
         anomaly["expected_pearson_change_signal_distortion"])>1e-8:
        raise ValueError("P6.3A previously accepted anomaly could not be reproduced")
    raw_and_corrected=[]
    for window,group in ((HIST,historical),(anomaly["window"],future)):
        joint=group["joint"];solar=group["solar"];geom=group["geometry"]
        for method in ALL_METHODS:
            raw_ref=[{"year":r["year"],"month":r["month"],"day":r["day"],
                      met:r[met],"ghi_kwh_m2_day":s[method]}
                     for r,s in zip(joint,solar)
                     if r["year"] in (EVALUATION_YEARS if window==HIST else FUTURE_YEARS)]
            pairs=unpaired_corr(raw_ref,met)
            r=estimate(pairs)
            raw_and_corrected.append({"model":model,"window":window,
                  "relationship":rel,"method":method,
                  "reference_kind":"GCM_MODEL_INTERNAL",
                  **r})
    observational=[]
    for reference_type,reference_rows,ref_var,threshold in (
          ("GeoSphere_station30_OBSERVED",station_rows,ref,STATION_MIN_PAIRS),
          ("NASA_POWER_GRIDDED_SATELLITE_REANALYSIS",power_rows,ref,POWER_MIN_PAIRS)):
        if reference_type.startswith("GeoSphere") and ref=="longwave_kwh_m2_day":
            observational.append({"model":model,"relationship":rel,
                "reference_kind":reference_type,
                "status":"UNAVAILABLE_NO_DIRECT_STATION_LONGWAVE",
                "n":0,"pearson":None,"spearman":None,
                "ci_95_low":None,"ci_95_high":None})
            continue
        pairs=unpaired_corr(reference_rows,ref_var)
        result=block_bootstrap(pairs,seed=6301+(0 if model=="CanESM5" else 11))
        status="VALID_REFERENCE_DESCRIPTIVE" if len(pairs)>=threshold else "INSUFFICIENT_QC_SAMPLE"
        observational.append({"model":model,"relationship":rel,
            "reference_kind":reference_type,"status":status,**result})
    return record,raw_and_corrected,observational

def decile_mechanism(item,anomaly):
    """Descriptive: day-wise differential M3 vs M0 in temperature/LW deciles.

    No causal identification; deciles of original climate variable by
    period, JJA, with original model days preserving their chronology.
    """
    model=item["name"];met=anomaly["climate_variable"];out=[]
    for window,group in ((HIST,item["historical"]),
                         (anomaly["window"],item["future"])):
        pairs=[]
        for r,s,g in zip(group["joint"],group["solar"],group["geometry"]):
            if r["month"] not in (6,7,8):continue
            pairs.append((r[met],s[METHODS[0]],s[NEW],g["rso"],g["ra"],r["year"]))
        pairs.sort(key=lambda x:x[0])
        if len(pairs)<1800:raise ValueError("Expected at least 20 JJA seasons")
        for decile in range(10):
            low=(decile*len(pairs))//10
            high=((decile+1)*len(pairs))//10
            sample=pairs[low:high]
            if not sample:raise ValueError("Missing original climate variable decile")
            raw=fmean(x[1] for x in sample)
            revised=fmean(x[2] for x in sample)
            out.append({"model":model,"window":window,
                "climate_variable":met,
                "decile":decile+1,
                "original_variable_min":min(x[0] for x in sample),
                "original_variable_max":max(x[0] for x in sample),
                "days":len(sample),
                "raw_GHI_kwh_m2_day":raw,
                "M3_GHI_kwh_m2_day":revised,
                "M3_minus_raw_GHI_kwh_m2_day":revised-raw,
                "M3_divided_by_raw_GHI":revised/raw if raw>0 else None,
                "raw_above_FAO_1p10_Rso":sum(x[1]>1.10*x[3]+1e-8 for x in sample),
                "M3_reaching_FAO_cap":sum(abs(x[2]-min(x[4],1.10*x[3]))<1e-9
                                           for x in sample)})
    return out

def save_union(path,records):
    if not records:raise ValueError("No scientific source rows")
    keys=list(dict.fromkeys(k for row in records for k in row))
    with path.open("w",encoding="utf8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=keys)
        writer.writeheader();writer.writerows(records)
    return checksum(path)

def run(station_csv,access_historical,original_historical,repaired_historical,
        access_future,original_future,repaired_future,out):
    out.mkdir(parents=True,exist_ok=True)
    stations,geoqc=acquire_geosphere(out,station_csv)
    power,powerqc=acquire_power(out)
    anomaly_rows=[];modelrows=[];reference_rows=[];deciles=[];provenance=[]
    for anomaly in ANOMALIES:
        item=source_model_methods(anomaly["model"],station_csv,
             access_historical,original_historical,repaired_historical,
             access_future,original_future,repaired_future)
        critical,models,references=case_audit(item,anomaly,stations,power)
        anomaly_rows.append(critical)
        modelrows.extend(models)
        reference_rows.extend(references)
        deciles.extend(decile_mechanism(item,anomaly))
        for period in ("historical","future"):
            provenance.append({"model":anomaly["model"],"window":period,
                "source_metadata":item[period]["source"]})
        print("P6.3B REPRODUCED",anomaly["model"],anomaly["relationship"],
              "delta Pearson",round(
                  critical["pearson_signal_distortion_vs_original"],5),
              "station ref",references[0]["status"],
              "grid ref",references[1]["status"],flush=True)
    if len(anomaly_rows)!=2 or len(modelrows)!=16 or len(reference_rows)!=4 \
       or len(deciles)!=40:raise ValueError("Incomplete two-anomaly science closure")
    outputs={
        "p6_3b_reproduced_anomaly_dependence_signal.csv":anomaly_rows,
        "p6_3b_original_model_jja_heldout_or_future_correlations.csv":modelrows,
        "p6_3b_independent_station_and_gridded_reference_JJA.csv":reference_rows,
        "p6_3b_original_meteorology_deciles_M3_shift.csv":deciles,
        "p6_3b_original_NASA_model_source_hashes.csv":provenance}
    hashes={name:save_union(out/name,rows) for name,rows in outputs.items()}
    observational_judgement={
        "CanESM5_tas_rsds":next(r for r in reference_rows
            if r["model"]=="CanESM5" and r["reference_kind"].startswith("GeoSphere")),
        "IPSL_longwave_rsds":next(r for r in reference_rows
            if r["model"]=="IPSL-CM6A-LR" and r["reference_kind"].startswith("NASA_POWER")),
    }
    status="PASS_TWO_ANOMALIES_REPRODUCED_SOURCES_QC_REVIEW_REQUIRED"
    report={"stage":"IGE_P6_3B_INDEPENDENT_MULTIVARIATE_HISTORICAL_REFERENCE",
      "status":status,
      "scientific_decision":"REVIEW_REQUIRED_NOT_READY_FOR_PRODUCTION",
      "historical_reference_period":"2005–2014",
      "historical_model_calibration_period":"1995–2004",
      "future_anomaly_windows":["ssp585-2080-2099"],
      "independent_reference_quality":{
          "GeoSphere_station_observations":geoqc,
          "NASA_POWER_grid_satellite_reanalysis":powerqc,
      },
      "validation_targets":observational_judgement,
      "reproduced_anomalies":anomaly_rows,
      "results_sha256":hashes,
      "scientific_boundaries":[
          "GeoSphere temperature, RH, precipitation and wind are QC station observations, not necessarily simultaneous with original solar daily integration window.",
          "NASA POWER is a gridded satellite/reanalysis product, NOT ground station longwave observations.",
          "Model internal climate days never paired by date with station or NASA POWER historical daily weather.",
          "Original 1995–2014 GCM and reference comparisons are of unpaired seasonally aggregated association statistics only.",
          "No observations for 2080–2099: future correlation anomalies are physically interrogated but cannot be validated against future truth.",
          "M1/M2 daily values are exact month-conserving scaled native model days, NOT daywise fitted QDM.",
          "FAO-56 clear-sky approximation and NASA model-cell elevation proxy 366m remain uncertain.",
          "Daily GHI × T association and GHI × LW correlation do not demonstrate a full energy or cloud/radiative closure.",
          "Year-block bootstrap intervals capture only 10 observed JJA year blocks, not structural error, station time-boundary uncertainty or GCM internal variability.",
          "No hourly climate generation, no production EPW, no main changes.",
      ]}
    (out/"p6_3b_independent_validation_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("P6.3B",status,"anomalies",len(anomaly_rows),
          "observational proxies",len(reference_rows),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--station-csv",type=Path,required=True)
    for key in ("access-historical","original-historical","repaired-historical",
                "access-future","original-future","repaired-future","out"):
        p.add_argument("--"+key,type=Path,required=True)
    a=p.parse_args()
    run(a.station_csv,a.access_historical,a.original_historical,
        a.repaired_historical,a.access_future,a.original_future,a.repaired_future,a.out)
