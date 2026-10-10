#!/usr/bin/env python3
"""IGE P6.2D-C: historical sensitivity + all eight GCM future solar change signals.

Research-only. Preserve immutable P6.1 source hashes, native CF calendars,
non-synchronous station and model weather, and production main.
P6.2D-B is the trusted baseline (M0/M1/M2 monthly, M3 daily).
The future change-signal audit distinguishes historical holdout skill from
methodological change preservation; future weather cannot be validated against
future observations.
"""
from __future__ import annotations
import argparse,calendar,csv,json,math,hashlib
from collections import defaultdict,Counter
from pathlib import Path
from statistics import fmean

from p6_2d_solar_methods_benchmark import (
    MODELS,REPAIRED,HIST,CAL,TEST,METHODS,station_months,original_nasa_months,
    fit_months,discrepancy,qdm_target,csvwrite,checksum,csvread,
)
from p6_2d_b_daily_clearsky_benchmark import (
    STATION_LAT,STATION_ALT_M,NASA_LAT,NASA_ALT_PROXY_M,NEW,
    solar_geometry,reference_daily,nasa_daily,
)
from p6_2a_eight_model_ensemble import original_quality
from p6_2a_joint_diagnostics import quantile

FUTURES=("ssp245-2040-2059","ssp585-2040-2059",
         "ssp245-2080-2099","ssp585-2080-2099")
REPAIRED_FUTURES=frozenset((
    ("EC-Earth3","ssp245-2040-2059"),
    ("IPSL-CM6A-LR","ssp245-2080-2099"),
    ("MPI-ESM1-2-HR","ssp245-2040-2059"),
    ("MPI-ESM1-2-HR","ssp585-2040-2059"),
))
ALTITUDES=(200.,366.,600.)
CAPS=(1.05,1.10,1.15)
BLOCKS={"train_1995_2004":tuple(range(1995,2005)),
        "train_1995_2001":tuple(range(1995,2002)),
        "train_1998_2004":tuple(range(1998,2005))}
SEASONS={"ANNUAL":tuple(range(1,13)),"DJF":(12,1,2),
         "MAM":(3,4,5),"JJA":(6,7,8),"SON":(9,10,11)}
GRID_ALT_STATUS="PROXY_ASSUMED_NOT_OBSERVED"

def sorted_q(a,p):
    """Sorted prevalidated values; avoids 300-element resort on each day."""
    if not a or not 0<=p<=1:raise ValueError("Empty sample or invalid percentile")
    k=(len(a)-1)*p
    i=math.floor(k);j=math.ceil(k)
    return a[i] if i==j else a[i]*(j-k)+a[j]*(k-i)

def normalized(rows,altitude,cap,model):
    """Return NEW dictionaries, never mutate accepted NASA/Graz daily records."""
    if not 1<=cap<=1.2:raise ValueError("Unsupported experimental clear-sky cap")
    out=[]
    factor=(.75+2e-5*altitude)/(.75+2e-5*(NASA_ALT_PROXY_M if model else STATION_ALT_M))
    if not .8<factor<1.2:raise ValueError("Altitude sensitivity outside tested range")
    for r in rows:
        rso=r["rso"]*factor
        ra=r["ra"]
        raw=r["ghi_kwh_m2_day"]
        if not 0<=raw or not math.isfinite(raw) or rso<=0:
            raise ValueError("Invalid source surface irradiation")
        k=min(cap,raw/rso)
        out.append({"year":r["year"],"month":r["month"],"day":r["day"],
                    "date":r["date"],"rso":rso,"ra":ra,"raw":raw,"index":k})
    return out

def fit(obs,model,years,cap):
    if not years or any(y not in CAL for y in years):
        raise ValueError("M3 scientific training-leakage violation")
    years=set(years)
    rules={}
    for month in range(1,13):
        o=sorted(r["index"] for r in obs if r["month"]==month and r["year"] in years)
        g=sorted(r["index"] for r in model if r["month"]==month and r["year"] in years)
        if len(o)<180 or len(g)<180 or any(not 0<=v<=cap for v in o+g):
            raise ValueError("Incomplete or invalid baseline calibration daily index")
        rules[month]=(o,g)
    return rules

def correct(target,rules,cap,allowed_years,write_daily=False):
    """M3 daily additive QDM in k, with rank of target MODEL ONLY.

    Allowed years may be a future scenario or 2005–2014 holdout, never
    observed target-year station data. Output is ordered as source input.
    """
    allowed=set(allowed_years)
    if not target or any(r["year"] not in allowed for r in target):
        raise ValueError("Wrong target climate window/year")
    groups=defaultdict(list)
    for i,r in enumerate(target):groups[r["month"]].append((i,r))
    if set(groups)!=set(range(1,13)):raise ValueError("Incomplete target calendar")
    outputs=[None]*len(target)
    for month,pairs in groups.items():
        o,g=rules[month]
        ranks=sorted(pairs,key=lambda item:(item[1]["index"],item[1]["date"]))
        for rank,(i,record) in enumerate(ranks):
            q=(rank+.5)/len(ranks)
            adjusted=max(0.,min(cap,sorted_q(o,q)+record["index"]-sorted_q(g,q)))
            upper=min(record["ra"],cap*record["rso"])
            flux=min(upper,adjusted*record["rso"])
            if not 0<=flux<=upper+1e-9:raise ValueError("M3 physical solar bound violation")
            outputs[i]={"year":record["year"],"month":record["month"],
                        "day":record["day"],"date":record["date"],
                        "raw_kwh_m2_day":record["raw"],
                        "corrected_kwh_m2_day":flux,
                        "clear_sky_kwh_m2_day":record["rso"],
                        "physical_cap_kwh_m2_day":upper,
                        "raw_index_clipped":record["index"],
                        "corrected_index":adjusted} if write_daily else flux
    if any(x is None for x in outputs):raise ValueError("Missing M3 output")
    return outputs

def year_months(rows,values=None):
    result=defaultdict(float);count=Counter()
    if values is not None and len(rows)!=len(values):
        raise ValueError("M3 daily flux/source alignment failed")
    for i,r in enumerate(rows):
        k=(r["year"],r["month"])
        v=r["raw"] if values is None else (
            values[i]["corrected_kwh_m2_day"] if isinstance(values[i],dict) else values[i])
        if v<0 or not math.isfinite(v):raise ValueError("Invalid monthly aggregation source")
        result[k]+=v;count[k]+=1
    expected={(y,m) for y in set(y for y,m in count) for m in range(1,13)}
    if set(result)!=expected or len(result)!=len(set(y for y,m in count))*12:
        raise ValueError("GCM daily output missing monthly coverage")
    return dict(result)

def model_original_future(model,window,access_future,original_future,repaired_future):
    if window not in FUTURES:raise ValueError("Unsupported future source period")
    label=f"ige-p6-{model}-{window}"
    if model=="ACCESS-CM2":folder=access_future/label
    elif (model,window) in REPAIRED_FUTURES:folder=repaired_future/label
    else:folder=original_future/label
    qa,prov,sha,_=original_quality(folder,model,window)
    native_cal=qa["calendar"]
    if native_cal not in ("gregorian","noleap"):
        raise ValueError(f"Unapproved future calendar: {native_cal}")
    scenario,first,last=window.split("-")
    start,end=int(first),int(last)
    if end-start!=19:raise ValueError("Future period not 20 years")
    arr=csvread(folder/"joint_daily_raw.csv")
    expected_count=sum(365+(y%4==0 and (y%100!=0 or y%400==0))
                       if native_cal=="gregorian" else 365
                       for y in range(start,end+1))
    if len(arr)!=expected_count:raise ValueError("Future original daily coverage incomplete")
    raw=[];seen=set()
    for row in arr:
        year,month,day=(int(row[k]) for k in ("year","month","day"))
        key=(year,month,day)
        if key in seen or year<start or year>end or \
           row["scenario"]!=scenario or row["model"]!=model or \
           row["date"]!=f"{year:04d}-{month:02d}-{day:02d}":
            raise ValueError("Future daily provenance/calendar inconsistent")
        seen.add(key)
        energy=float(row["rsds_kwh_m2_day"])
        if not math.isfinite(energy) or energy<0 or \
            abs(float(row["rsds"])*.024-energy)>1e-6:
            raise ValueError("Future original NASA rsds unit invalid")
        ra,rso=solar_geometry(month,day,year,NASA_LAT,NASA_ALT_PROXY_M,
                               native_cal=="noleap")
        raw.append({"year":year,"month":month,"day":day,"date":row["date"],
                    "ghi_kwh_m2_day":energy,"ra":ra,"rso":rso})
    monthly=csvread(folder/"model_monthly.csv")
    if len(monthly)!=240:raise ValueError("Original future monthly data incomplete")
    accepted={}
    for item in monthly:
        y,m=int(item["year"]),int(item["month"])
        if not start<=y<=end or not 1<=m<=12 or (y,m) in accepted or \
           item["scenario"]!=scenario or item["window"]!=window:
            raise ValueError("Future source monthly provenance/date mismatch")
        accepted[y,m]=float(item["ghi_kwh_m2"])
    sums=defaultdict(float)
    for r in raw:sums[r["year"],r["month"]]+=r["ghi_kwh_m2_day"]
    if set(sums)!=set(accepted) or \
       any(abs(sums[k]-accepted[k])>1e-6 for k in sums):
        raise ValueError("Future GCM daily/monthly source checksum closure failed")
    return raw,{
        "model":model,"window":window,"calendar":native_cal,
        "original_daily_count":len(raw),"model_monthly_sha256":sha["model_monthly.csv"],
        "source_provenance_sha256":checksum(folder/"source_provenance.json"),
        "quality_report_sha256":checksum(folder/"quality_report.json"),
    }

def score_heldout(target_norm,rules,cap,observed_months,method):
    t=[r for r in target_norm if r["year"] in TEST]
    values=correct(t,rules,cap,TEST)
    months=year_months(t,values)
    combined={key:{method:flux} for key,flux in months.items()}
    _,metrics=discrepancy(combined,observed_months,method)
    return metrics

def monthly_methods(rawmonthly,monthrules):
    """M0/M1/M2 for *one entire* 20yr target window; no target observations."""
    out={k:{METHODS[0]:float(v),METHODS[1]:float(v)*monthrules[k[1]]["monthly_factor"]}
         for k,v in rawmonthly.items()}
    if len(rawmonthly)!=240:raise ValueError("20yr target has incomplete months")
    for m in range(1,13):
        keys=sorted(k for k in rawmonthly if k[1]==m)
        vals=[rawmonthly[k] for k in keys]
        result=qdm_target(vals,monthrules[m])
        for k,v in zip(keys,result):out[k][METHODS[2]]=v
    if any(set(entry)!=set(METHODS) for entry in out.values()):
        raise ValueError("Not all monthly methods computed")
    return out

def mean_climatological_months(data,method,months):
    years=sorted(set(y for y,m in data))
    if len(years)!=20:raise ValueError("Not exactly 20 climate years")
    # For DJF this is a composite climatological season, not
    # a contiguous cross-year meteorological winter.
    return fmean(sum(data[y,m][method] for m in months) for y in years)

def future_signal_scores(model,window,historical,future):
    rows=[]
    for method in (*METHODS,NEW):
        for season,months in SEASONS.items():
            before=mean_climatological_months(historical,method,months)
            after=mean_climatological_months(future,method,months)
            if before<=0 or after<0:raise ValueError("Nonphysical seasonal source GHI")
            ratio=after/before
            rows.append({"model":model,"window":window,"method":method,
                         "season":season,"historical_ghi_kwh_m2":before,
                         "future_ghi_kwh_m2":after,"future_over_historical":ratio,
                         "future_change_percent":100*(ratio-1)})
    raw={r["season"]:r["future_change_percent"] for r in rows
         if r["method"]==METHODS[0]}
    for r in rows:
        r["shift_from_raw_nex_pp"]=r["future_change_percent"]-raw[r["season"]]
        # Transparent screening threshold, not a scientific proof of impact.
        r["exceeds_5pp_signal_screen"]=abs(r["shift_from_raw_nex_pp"])>5
        r["exceeds_10pp_signal_screen"]=abs(r["shift_from_raw_nex_pp"])>10
    return rows

def write_union_csv(path,records):
    """Losslessly preserve metadata from historical and future P6.1 products."""
    columns=list(dict.fromkeys(key for r in records for key in r))
    if not records:raise ValueError("No source records")
    with path.open("w",newline="",encoding="utf8") as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction="raise")
        w.writeheader();w.writerows(records)
    return checksum(path)

def run(station_csv,access_historical,original_historical,repaired_historical,
        access_future,original_future,repaired_future,out):
    out.mkdir(parents=True,exist_ok=True)
    obs,obsflags=reference_daily(station_csv)
    obsmonthly=station_months(station_csv)
    sensitivity=[];future_signals=[];future_daily=[]
    input_manifest=[];future_bounds=[];calibration_checks=[]
    for model in MODELS:
        historical,flags,history_prov=nasa_daily(
            model,access_historical,original_historical,repaired_historical)
        input_manifest.append({"role":"historical",**history_prov,"model":model})
        months_hist,monthly_prov=original_nasa_months(
            model,access_historical,original_historical,repaired_historical)
        monthrules=fit_months(obsmonthly,months_hist)
        annual_qdm_hist=monthly_methods(months_hist,monthrules)
        future_reference_hist=normalized(historical,366.,1.10,True)
        for altitude in ALTITUDES:
            for cap in CAPS:
                o=normalized(obs,STATION_ALT_M,cap,False)
                h=normalized(historical,altitude,cap,True)
                rules=fit(o,h,BLOCKS["train_1995_2004"],cap)
                metric=score_heldout(h,rules,cap,obsmonthly,NEW)
                sensitivity.append({"model":model,"experiment":"altitude_clear_sky_cap",
                    "grid_altitude_proxy_m":altitude,"solar_k_cap":cap,
                    "calibration_block":"1995–2004",**metric})
                if altitude==366. and cap==1.10:
                    baseline_rule=rules
                    historical_M3=year_months(h,correct(
                        h,rules,cap,range(1995,2015)))
                    # Unaltered historic raw NASA daily must match accepted P6.1
                    # original monthly in native (Gregorian/noleap) calendar.
                    rawfromdaily=year_months(h)
                    if set(rawfromdaily)!=set(months_hist) or any(
                        abs(rawfromdaily[k]-months_hist[k])>1e-6 for k in rawfromdaily):
                        raise ValueError("M3 source future baseline daily/monthly mismatch")
                    for k in annual_qdm_hist:annual_qdm_hist[k][NEW]=historical_M3[k]
                    calibration_checks.append({"model":model,"baseline_M3_holdout_bias_percent":
                        metric["annual_climatological_bias_percent"],
                        "original_historical_source_sha":history_prov["model_monthly_source_sha256"]})
        for block in ("train_1995_2001","train_1998_2004"):
            years=BLOCKS[block]
            o=normalized(obs,STATION_ALT_M,1.10,False)
            h=normalized(historical,366.,1.10,True)
            rules=fit(o,h,years,1.10)
            metric=score_heldout(h,rules,1.10,obsmonthly,NEW)
            sensitivity.append({"model":model,"experiment":"calibration_block",
                "grid_altitude_proxy_m":366.,"solar_k_cap":1.10,
                "calibration_block":f"{min(years)}–{max(years)}",**metric})
        for window in FUTURES:
            future_raw,prov=model_original_future(
                model,window,access_future,original_future,repaired_future)
            input_manifest.append({"role":"future",**prov})
            future_month=year_months(normalized(future_raw,366.,1.10,True))
            full_monthly=monthly_methods(future_month,monthrules)
            future_norm=normalized(future_raw,366.,1.10,True)
            start,end=(int(window.split("-")[1]),int(window.split("-")[2]))
            revised=correct(future_norm,baseline_rule,1.10,
                            range(start,end+1),write_daily=True)
            corr_month=year_months(future_norm,revised)
            if set(corr_month)!=set(full_monthly):
                raise ValueError("Future daily/year/month mapping incomplete")
            physical_violations=0
            for r in revised:
                physical_violations+=not (0<=r["corrected_kwh_m2_day"]<=
                                         r["physical_cap_kwh_m2_day"]+1e-9)
                future_daily.append({"model":model,"window":window,**r})
            for k in full_monthly:full_monthly[k][NEW]=corr_month[k]
            if physical_violations:raise ValueError("Future M3 solar bounds violated")
            future_bounds.append({"model":model,"window":window,
                                  "native_calendar":prov["calendar"],
                                  "future_daily_count":len(revised),
                                  "M3_daily_physical_violations":physical_violations,
                                  "raw_source_above_FAO_1p10_Rso":sum(
                                      r["raw"]>1.10*r["rso"] for r in future_norm),
                                  "raw_source_above_TOA":sum(
                                      r["raw"]>r["ra"]+1e-9 for r in future_norm),
                                  "M3_clipped_at_upper":sum(
                                      abs(r["corrected_kwh_m2_day"]-
                                          r["physical_cap_kwh_m2_day"])<1e-9
                                      for r in revised)})
            future_signals.extend(future_signal_scores(
                model,window,annual_qdm_hist,full_monthly))
            raw_ann=[r for r in future_signals if
                      r["model"]==model and r["window"]==window and
                      r["season"]=="ANNUAL"]
            print("P6.2D-C FUTURE",model,window,
                  " | ".join(f'{r["method"].split("_")[0]} {r["future_change_percent"]:+.2f}%'
                           for r in raw_ann),flush=True)
        print("P6.2D-C SENSITIVITY",model,"11 variants",flush=True)
    if len(input_manifest)!=40 or len(sensitivity)!=8*11 or \
       len(future_signals)!=8*4*4*5 or len(future_bounds)!=32 or \
       len(calibration_checks)!=8:
        raise ValueError("Incomplete 8×5 original P6.1 source or sensitivity audit")
    if any(row["M3_daily_physical_violations"] for row in future_bounds):
        raise ValueError("Physical closure invalid")
    csvsets={
        "p6_2d_c_historical_m3_sensitivity_8gcm.csv":sensitivity,
        "p6_2d_c_four_methods_future_8gcm_4windows_signals.csv":future_signals,
        "p6_2d_c_future_m3_daily_8gcm_4windows.csv":future_daily,
        "p6_2d_c_future_m3_physical_audit.csv":future_bounds,
        "p6_2d_c_source_original_sha_manifest.csv":input_manifest,
        "p6_2d_c_historical_baseline_holdout_check.csv":calibration_checks,
    }
    hashes={key:(write_union_csv(out/key,data) if key=="p6_2d_c_source_original_sha_manifest.csv" else csvwrite(out/key,data)) for key,data in csvsets.items()}
    screen5=[r for r in future_signals if
             r["method"]!=METHODS[0] and r["exceeds_5pp_signal_screen"]]
    screen10=[r for r in future_signals if
              r["method"]!=METHODS[0] and r["exceeds_10pp_signal_screen"]]
    summary={
        "stage":"IGE_P6_2D_C_historical_robustness_and_future_change_signal",
        "technical_result":"PASS_SOURCE_QC_AND_M3_DAILY_PHYSICAL_CLOSURE",
        "scientific_future_signal_assessment":
            "REVIEW_REQUIRED" if screen5 else "NO_5PP_SCREEN_EXCEEDANCES",
        "model_count":8,"original_nasa_P6_1_period_datasets":40,
        "future_model_windows":32,"methods":list(METHODS)+[NEW],
        "sensitivity_altitude_proxies_m":list(ALTITUDES),
        "sensitivity_clearsky_max_ratios":list(CAPS),
        "sensitivity_training_blocks":{k:list(v) for k,v in BLOCKS.items()},
        "historical_holdout":[2005,2014],
        "future_windows":list(FUTURES),
        "models":list(MODELS),
        "altitude_source":GRID_ALT_STATUS,
        "altitude_warning":"200/366/600m are sensitivity PROXIES, not surveyed NASA cell DEM heights",
        "source_station_sha256":checksum(station_csv),
        "source_station_qc_flags":obsflags,
        "screen_5pp_count":len(screen5),
        "screen_10pp_count":len(screen10),
        "screen_5pp_examples":screen5[:25],
        "counts":{
            "historical_sensitivity_rows":len(sensitivity),
            "future_change_signal_rows":len(future_signals),
            "future_daily_corrected_rows":len(future_daily),
            "future_original_native_sources":len(future_bounds),
        },
        "artifact_sha256":hashes,
        "scientific_limits":[
            "NOT an externally validated future-weather forecast: no future observed GHI exists.",
            "Raw NASA historical and scenario years are unpaired climate realisations; do not compute per-date skill.",
            "Comparison quantifies, and does not guarantee preservation of climate change signal.",
            "M3 is approximate FAO56 clear-sky-index QDM, not a radiative transfer model.",
            "NASA cell elevation remains unverified and all tested elevations are sensitivity proxies.",
            "No full future multivariate physical closure, no hourly EPW, no production changes.",
            "NASA NEX-GDDP-CMIP6 v2 is already adjusted via BCSD; local correction is experimental.",
            "5pp/10pp flags are screening thresholds, not inferred confidence bounds.",
            "Historical M2 monthly quantile calibration uses only 10 samples/calendar month.",
            "Scenario future change is evaluated relative to the model's 1995-2014 source full-period climatology.",
            "Native Gregorian and noleap days and original source file hashes remain distinct.",
        ],
    }
    (out/"p6_2d_c_science_audit.json").write_text(
        json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P6.2D-C",summary["technical_result"],"future_screens_5pp",
          summary["screen_5pp_count"],"future_screens_10pp",
          summary["screen_10pp_count"],"future_daily",
          len(future_daily),flush=True)
    return summary

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--station-csv",type=Path,required=True)
    for key in ("access-historical","original-historical","repaired-historical",
                "access-future","original-future","repaired-future","out"):
        p.add_argument("--"+key,type=Path,required=True)
    a=p.parse_args()
    run(a.station_csv,a.access_historical,a.original_historical,
        a.repaired_historical,a.access_future,a.original_future,
        a.repaired_future,a.out)
