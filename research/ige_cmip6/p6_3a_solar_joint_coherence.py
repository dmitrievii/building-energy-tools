#!/usr/bin/env python3
"""IGE P6.3A: joint climate-dependence impact of locally adjusted daily GHI.

Four research branches M0, M1, M2 and M3 for 8 original NEX-GDDP-CMIP6
models across 1995–2014 and four future SSP periods. M1/M2 are *monthly*
solar correction mapped to each underlying NASA day using the original
GHI month's ratio: EXACT monthly energy preservation, NOT a calibrated
daily QDM. M3 is original P6.2D-C FAO-56 daily clear-sky-index additive QDM.
All other native climate variables are IMMUTABLE.

This is a *model-internal structural diagnostic*, not observed
multivariate validation: station solar GHI is the only trusted local
historical reference and model dates are not synchronous station weather.
"""
from __future__ import annotations
import argparse,calendar,csv,json,math
from collections import Counter,defaultdict
from pathlib import Path
from statistics import fmean

from p6_2d_solar_methods_benchmark import (
    MODELS,REPAIRED,HIST,METHODS,station_months,original_nasa_months,
    fit_months,checksum,csvwrite,
)
from p6_2d_b_daily_clearsky_benchmark import (
    NEW,nasa_daily,reference_daily,
)
from p6_2d_c_sensitivity_future_signals import (
    FUTURES,REPAIRED_FUTURES,normalized,fit,correct,year_months,
    monthly_methods,model_original_future,STATION_ALT_M,
)
from p6_2a_joint_diagnostics import load_daily,pearson
from p6_2a_eight_model_ensemble import original_quality

SEASONS={"ANNUAL":tuple(range(1,13)),"DJF":(12,1,2),
         "MAM":(3,4,5),"JJA":(6,7,8),"SON":(9,10,11)}
CLIMATE_FIELDS=("tas_c","hurs","pr_mm_day","rlds_kwh_m2_day","sfcWind")
PAIRS=(("tas_c","tas_rsds"),("hurs","hurs_rsds"),
       ("pr_mm_day","precip_rsds"),
       ("rlds_kwh_m2_day","longwave_rsds"),
       ("sfcWind","wind_rsds"))
ALL_METHODS=(*METHODS,NEW)
WET_THRESHOLD_MM=1.0
CORRELATION_REVIEW=.10
CORRELATION_CRITICAL=.20
DISTORTED_SOLAR_SIGNAL_REVIEW_PP=5.0
CANONICAL_ALTITUDE_M=366.
CANONICAL_CAP=1.10

def source_folder(model,window,access_historical,original_historical,
                  repaired_historical,access_future,original_future,repaired_future):
    if window==HIST:
        if model=="ACCESS-CM2":return access_historical/"ige-p6-access-historical-1995-2014"
        root=repaired_historical if model in REPAIRED else original_historical
        return root/f"ige-p6-{model}-{HIST}"
    if window not in FUTURES:raise ValueError("Unsupported original source period")
    if model=="ACCESS-CM2":return access_future/f"ige-p6-access-{window}"
    root=repaired_future if (model,window) in REPAIRED_FUTURES else original_future
    return root/f"ige-p6-{model}-{window}"

def validated_joint_file(path,model,window,solar):
    """No physical data reconstruction or invented missing optional variables."""
    qa,prov,digests,_=original_quality(path,model,window)
    original=load_daily(path/"joint_daily_raw.csv")
    if len(original)!=len(solar):raise ValueError("Joint climate/source solar day count mismatch")
    for i,(r,s) in enumerate(zip(original,solar)):
        if (r["year"],r["month"],r["day"])!= (s["year"],s["month"],s["day"]) or \
           r["date"]!=s["date"] or abs(r["rsds_kwh_m2_day"]-s["ghi_kwh_m2_day"])>1e-7:
            raise ValueError(f"Original NASA joint/solar native calendar drift at row {i}")
        if r["model"]!=model or (r["scenario"]!="historical" if window==HIST
                               else r["scenario"]!=window.split("-")[0]):
            raise ValueError("Wrong accepted model/scenario identity")
    if set(r["model"] for r in original)!={model}:raise ValueError("Mixed model joint source")
    if set(r["year"] for r in original)!= (set(range(1995,2015)) if window==HIST
                                      else set(range(int(window.split("-")[1]),
                                                     int(window.split("-")[2])+1))):
        raise ValueError("Original 20yr joint climate chronology incomplete")
    optional_missing={r["huss"] is None for r in original}
    if len(optional_missing)!=1:raise ValueError("Mixed missing/available model specific humidity")
    return original,{"source_sha256":digests["joint_daily_raw.csv"],
                     "days":len(original),"huss_missing":True in optional_missing,
                     "calendar":qa["calendar"]}

def native_daily_ghi(day):
    """Validate either immutable P6.1 daily solar or normalized P6.2D-C input.

    Normalized source uses 'raw'; original source uses 'ghi_kwh_m2_day'.
    When both exist, their numerical agreement is mandatory.
    """
    values=[float(day[k]) for k in ("raw","ghi_kwh_m2_day") if k in day]
    if not values or any(not math.isfinite(v) or v<0 for v in values):
        raise ValueError("Missing, negative or non-finite original daily GHI")
    if len(values)==2 and abs(values[0]-values[1])>1.e-7:
        raise ValueError("Original/normalized daily GHI mismatch")
    return values[0]

def daily_methods(original_solar,corrected_monthly,reference_m3):
    """Daily solar ratios conserve M1 and M2 month sums exactly."""
    if len(original_solar)!=len(reference_m3):
        raise ValueError("M3 source row mismatch")
    raw_month=defaultdict(float)
    for day in original_solar:
        raw_month[day["year"],day["month"]]+=native_daily_ghi(day)
    if set(raw_month)!=set(corrected_monthly):
        raise ValueError("Corrected monthly target incomplete")
    factors={}
    for key,raw in raw_month.items():
        if raw<=0 or not math.isfinite(raw):raise ValueError("Zero/non-finite monthly source GHI")
        vals=corrected_monthly[key]
        if set(vals)!=set(METHODS):raise ValueError("M0 M1 M2 monthly methods missing")
        if abs(vals[METHODS[0]]-raw)>1e-6:
            raise ValueError("Raw monthly source cannot be changed")
        factors[key]={name:vals[name]/raw for name in METHODS[1:]}
        if any(not math.isfinite(v) or v<=0 for v in factors[key].values()):
            raise ValueError("Invalid monthly daily-disaggregation scalar")
    result=[]
    calculated=defaultdict(lambda:defaultdict(float))
    for i,(day,m3) in enumerate(zip(original_solar,reference_m3)):
        if not math.isfinite(m3) or m3<0:raise ValueError("Invalid physical M3 daily value")
        raw=native_daily_ghi(day)
        key=(day["year"],day["month"])
        rows={METHODS[0]:raw,NEW:m3}
        for method in METHODS[1:]:
            rows[method]=raw*factors[key][method]
        if not all(math.isfinite(v) and v>=0 for v in rows.values()):
            raise ValueError("Nonfinite/negative multi-method solar GHI")
        for name,value in rows.items():calculated[key][name]+=value
        result.append(rows)
    for key in raw_month:
        for method in METHODS:
            if abs(calculated[key][method]-corrected_monthly[key][method])>1e-6:
                raise ValueError(f"Daily M1/M2 original monthly GHI is not conserved: {key} {method}")
    return result

def rank(values):
    """Pearson-compatible midranks; preserve tied wet/dry day and GHI zero ranks."""
    positions=sorted(range(len(values)),key=lambda i:values[i])
    results=[0.]*len(values)
    i=0
    while i<len(positions):
        j=i+1
        while j<len(positions) and values[positions[j]]==values[positions[i]]:
            j+=1
        mid=(i+j-1)/2.+1
        for t in positions[i:j]:results[t]=mid
        i=j
    return results

def corr_vectors(a,b):
    if len(a)!=len(b) or len(a)<30:return None
    ma=fmean(a);mb=fmean(b)
    a2=sum((x-ma)**2 for x in a);b2=sum((y-mb)**2 for y in b)
    if a2<=1e-18 or b2<=1e-18:return None
    value=sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(a2*b2)
    return max(-1.,min(1.,value))

def method_diagnostics(joint,solar,model,window):
    """Seasonal Pearson/Spearman and wet/rain + warm-day solar associations."""
    if len(joint)!=len(solar):raise ValueError("Joint records and GHI rows differ")
    stat=[];condition=[];physical=[];immutable=[]
    for method in ALL_METHODS:
        values=[r[method] for r in solar]
        for season,months in SEASONS.items():
            chosen=[i for i,row in enumerate(joint) if row["month"] in months]
            if len(chosen)<300:raise ValueError("Insufficient original season coverage")
            ghi=[values[i] for i in chosen]
            base={"model":model,"window":window,"method":method,"season":season,
                  "source_daily_count":len(chosen)}
            for field,short in PAIRS:
                src=[joint[i][field] for i in chosen]
                p=corr_vectors(src,ghi)
                rho=corr_vectors(rank(src),rank(ghi))
                stat.append({**base,"relationship":short,
                    "pearson":p,"spearman":rho})
            wet=[values[i] for i in chosen if joint[i]["pr_mm_day"]>=WET_THRESHOLD_MM]
            dry=[values[i] for i in chosen if joint[i]["pr_mm_day"]<WET_THRESHOLD_MM]
            if len(wet)<30 or len(dry)<30:raise ValueError("Invalid dry/wet season sample size")
            temps=[joint[i]["tas_c"] for i in chosen]
            t90=sorted(temps)[int(.9*(len(temps)-1))]
            hot=[values[i] for i in chosen if joint[i]["tas_c"]>=t90]
            solarmean=fmean(ghi)
            condition.append({**base,
                "wet_day_fraction":len(wet)/len(chosen),
                "wet_day_ghi_kwh_m2_day":fmean(wet),
                "dry_day_ghi_kwh_m2_day":fmean(dry),
                "wet_dry_ghi_ratio":fmean(wet)/fmean(dry) if fmean(dry)>0 else None,
                "upper_10pct_temp_day_mean_ghi_kwh_m2_day":fmean(hot),
                "relative_hot_day_ghi_to_all_days":fmean(hot)/solarmean if solarmean>0 else None})
    return stat,condition

def physical_metrics(joint,solar,geometry,model,window):
    result=[]
    if len(joint)!=len(solar) or len(joint)!=len(geometry):
        raise ValueError("Unaligned model solar/physics source records")
    original_non_solar_signature=sum(
        joint[i]["tas_c"]+joint[i]["hurs"]+joint[i]["pr_mm_day"]+
        joint[i]["rlds_kwh_m2_day"]+joint[i]["sfcWind"]
        for i in range(len(joint)))
    # Source values above 100% RH are already permitted with explicit source
    # QC flags in P6.1. Never clip originals or claim derived psychrometric
    # closure when source pressure and hourly humidity are unavailable.
    if not math.isfinite(original_non_solar_signature):
        raise ValueError("Invalid original multi-climate fields")
    for method in ALL_METHODS:
        values=[r[method] for r in solar]
        overtoa=sum(v>g["ra"]+1e-8 for v,g in zip(values,geometry))
        overclear=sum(v>CANONICAL_CAP*g["rso"]+1e-8
                      for v,g in zip(values,geometry))
        negative=sum(v<0 or not math.isfinite(v) for v in values)
        result.append({"model":model,"window":window,"method":method,
            "days":len(values),"source_hurs_above_100_count":
                sum(r["hurs"]>100. for r in joint),
            "huss_missing_all_days":all(r["huss"] is None for r in joint),
            "days_above_TOA":overtoa,
            "days_above_1p10_approx_clear_sky":overclear,
            "negative_or_invalid_GHI_days":negative,
            "mean_annual_GHI_kwh_m2":sum(values)/20.,
            "non_solar_fields_original_unmodified":True})
        if method==NEW and (overtoa or overclear or negative):
            raise ValueError("P6.3 M3 physical closure failed")
    return result

def dependence_change(historical,future):
    """Distortion in the *change* of joint relationship, not only its level."""
    idx=lambda d:{(r["method"],r["season"],r["relationship"]):r for r in d}
    hist=idx(historical);fut=idx(future)
    if set(hist)!=set(fut):raise ValueError("Incomplete 5-pair/season/method joint structure")
    rows=[]
    for (method,season,relationship),r in fut.items():
        h=hist[method,season,relationship]
        raw_hist=hist[METHODS[0],season,relationship]
        raw_fut=fut[METHODS[0],season,relationship]
        out={"model":r["model"],"window":r["window"],"method":method,
             "season":season,"relationship":relationship}
        for key in ("pearson","spearman"):
            a,b=h[key],r[key]
            raw_a,raw_b=raw_hist[key],raw_fut[key]
            if any(v is None for v in (a,b,raw_a,raw_b)):
                out[f"{key}_delta_future_minus_historical"]=None
                out[f"{key}_signal_distortion_vs_original"]=None
                out[f"{key}_abs_change_due_to_correction_current_period"]=None
                out[f"{key}_screen_gt_0p10"]=False
                out[f"{key}_screen_gt_0p20"]=False
                continue
            shift=(b-a)-(raw_b-raw_a)
            out[f"{key}_delta_future_minus_historical"]=b-a
            out[f"{key}_signal_distortion_vs_original"]=shift
            out[f"{key}_abs_change_due_to_correction_current_period"]=abs(b-raw_b)
            out[f"{key}_screen_gt_0p10"]=abs(shift)>CORRELATION_REVIEW
            out[f"{key}_screen_gt_0p20"]=abs(shift)>CORRELATION_CRITICAL
        rows.append(out)
    return rows

def read_original(model,window,access_historical,original_historical,
                  repaired_historical,access_future,original_future,repaired_future,
                  history_cache=None):
    src=source_folder(model,window,access_historical,original_historical,
                      repaired_historical,access_future,original_future,repaired_future)
    if window==HIST:
        solar,quality,provenance=nasa_daily(
            model,access_historical,original_historical,repaired_historical)
    else:
        solar,provenance=model_original_future(
            model,window,access_future,original_future,repaired_future)
    joint,source=validated_joint_file(src,model,window,solar)
    return solar,joint,{**provenance,**source,"model":model,"window":window}

def run(station_csv,access_historical,original_historical,repaired_historical,
        access_future,original_future,repaired_future,out):
    out.mkdir(parents=True,exist_ok=True)
    station,station_qc=reference_daily(station_csv)
    station_month=station_months(station_csv)
    stat_rows=[];condition_rows=[];phys_rows=[];changes=[];provenance=[]
    model_monthly_qa=[];source_count=0
    for model in MODELS:
        hist_solar,hist_joint,source=read_original(model,HIST,
            access_historical,original_historical,repaired_historical,
            access_future,original_future,repaired_future)
        provenance.append(source);source_count+=1
        hist_month,prov=original_nasa_months(
            model,access_historical,original_historical,repaired_historical)
        monthrules=fit_months(station_month,hist_month)
        observed_idx=normalized(station,STATION_ALT_M,CANONICAL_CAP,False)
        hist_idx=normalized(hist_solar,CANONICAL_ALTITUDE_M,CANONICAL_CAP,True)
        m3rules=fit(observed_idx,hist_idx,range(1995,2005),CANONICAL_CAP)
        hist_monthly=monthly_methods(hist_month,monthrules)
        hist_m3=correct(hist_idx,m3rules,CANONICAL_CAP,range(1995,2015))
        hist_methods=daily_methods(hist_idx,hist_monthly,hist_m3)
        hs,hc=method_diagnostics(hist_joint,hist_methods,model,HIST)
        stat_rows.extend(hs);condition_rows.extend(hc)
        phys_rows.extend(physical_metrics(hist_joint,hist_methods,hist_idx,model,HIST))
        model_monthly_qa.append({"model":model,"window":HIST,
            "GHI_monthly_M1_M2_conservation":"PASS",
            "source_model_monthly_sha256":source["model_monthly_source_sha256"]})
        for window in FUTURES:
            fut_solar,fut_joint,f_source=read_original(model,window,
                access_historical,original_historical,repaired_historical,
                access_future,original_future,repaired_future)
            provenance.append(f_source);source_count+=1
            fut_idx=normalized(fut_solar,CANONICAL_ALTITUDE_M,CANONICAL_CAP,True)
            monthly_raw=year_months(fut_idx)
            fut_monthly=monthly_methods(monthly_raw,monthrules)
            years=range(int(window.split("-")[1]),int(window.split("-")[2])+1)
            m3=correct(fut_idx,m3rules,CANONICAL_CAP,years)
            method_solar=daily_methods(fut_idx,fut_monthly,m3)
            fs,fc=method_diagnostics(fut_joint,method_solar,model,window)
            stat_rows.extend(fs);condition_rows.extend(fc)
            phys_rows.extend(physical_metrics(fut_joint,method_solar,fut_idx,model,window))
            changes.extend(dependence_change(hs,fs))
            model_monthly_qa.append({"model":model,"window":window,
                "GHI_monthly_M1_M2_conservation":"PASS",
                "source_model_monthly_sha256":f_source["model_monthly_sha256"]})
            print("P6.3A JOINT",model,window,
                  "daily",len(fut_joint),
                  "correlations",len(fs),
                  "signal_diagnostics",len(changes),flush=True)
    if (source_count!=40 or len(provenance)!=40 or
        len(stat_rows)!=40*4*5*5 or len(condition_rows)!=40*4*5 or
        len(phys_rows)!=40*4 or len(changes)!=32*4*5*5 or
        len(model_monthly_qa)!=40):
        raise ValueError("Incomplete eight model × five window × four method source closure")
    for item in phys_rows:
        if item["negative_or_invalid_GHI_days"] or item["days_above_TOA"]:
            if item["method"]==NEW:
                raise ValueError("M3 joint solar physical closure regression")
    screens=[r for r in changes if r["method"]!=METHODS[0] and any(
        r[f"{metric}_screen_gt_0p10"] for metric in ("pearson","spearman"))]
    severe=[r for r in changes if r["method"]!=METHODS[0] and any(
        r[f"{metric}_screen_gt_0p20"] for metric in ("pearson","spearman"))]
    tables={
        "p6_3a_solar_joint_seasonal_correlations.csv":stat_rows,
        "p6_3a_wet_dry_hot_day_solar_dependence.csv":condition_rows,
        "p6_3a_historical_to_future_dependence_signal_drift.csv":changes,
        "p6_3a_solar_physical_envelope_and_raw_humidity_qc.csv":phys_rows,
        "p6_3a_daily_to_monthly_energy_conservation.csv":model_monthly_qa,
        "p6_3a_original_source_sha_provenance.csv":provenance,
    }
    # Source provenance intentionally differs between ACCESS, seven other
    # models, past and future. Union all keys rather than dropping metadata.
    hashes={}
    for filename,records in tables.items():
        cols=list(dict.fromkeys(k for r in records for k in r))
        path=out/filename
        with path.open("w",newline="",encoding="utf8") as f:
            w=csv.DictWriter(f,fieldnames=cols)
            w.writeheader();w.writerows(records)
        hashes[filename]=checksum(path)
    audit={
        "stage":"IGE_P6_3A_SOLAR_JOINT_MULTIVARIATE_COHERENCE",
        "technical_status":"PASS_VALIDATED_SOURCE_AND_MONTHLY_ENERGY_CLOSURE",
        "scientific_status":"REVIEW_REQUIRED" if screens else "NO_0P10_SIGNAL_DRIFT_SCREEN",
        "models":list(MODELS),"windows":[HIST,*FUTURES],
        "model_window_sources":40,
        "methodology":"M0 original daily; M1/M2 model-month ratio applied to native model daily; M3 FAO56 daily clear sky QDM",
        "correlation_pairs":[p[1] for p in PAIRS],
        "training_years":[1995,2004],
        "historical_holdout_years":[2005,2014],
        "future_scenarios":list(FUTURES),
        "correlation_screen_threshold":CORRELATION_REVIEW,
        "correlation_severe_threshold":CORRELATION_CRITICAL,
        "signal_review_count":len(screens),
        "signal_severe_count":len(severe),
        "top_review_examples":sorted(screens,
            key=lambda r:max(abs(r.get("pearson_signal_distortion_vs_original") or 0.),
                             abs(r.get("spearman_signal_distortion_vs_original") or 0.)),
            reverse=True)[:30],
        "source_station_qa":station_qc,
        "source_station_sha256":checksum(station_csv),
        "source_file_hashes":hashes,
        "limitations":[
            "No independent station-based daily multivariable validation; only local station GHI provides measured reference.",
            "GCM weather dates and GeoSphere station days are NOT synchronous.",
            "All remaining variables are untouched original NASA NEX-GDDP data; apparent joint changes arise from solar corrections only.",
            "M1/M2 daily disaggregation simply scales each NASA day by a corrected model-month ratio. It is NOT a daily QDM method.",
            "M3 retains FAO-56 clear-sky approximation with unverified NASA cell elevation set to 366m proxy.",
            "No definitive psychrometric consistency test: site pressure, measured station huss and hourly coupling are unavailable.",
            "A raw model RH above 100 percent or missing huss is a source diagnostic, NOT silently clipped/fixed.",
            "Shortwave GHI and longwave downwelling alone do NOT constitute a full radiation/energy balance.",
            "Dependence correlation changes are structural metrics, not proof of physical causation or measured climate fidelity.",
            "Pearson/Spearman >0.10/0.20 are transparent screening thresholds, not statistically calibrated acceptance bounds.",
            "Do not derive HVAC loads, hourly diffuse/direct solar, or production future EPW from these datasets.",
            "Future climate change cannot be checked against future station observations.",
        ]
    }
    (out/"p6_3a_joint_physics_audit.json").write_text(
        json.dumps(audit,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P6.3A",audit["technical_status"],"scientific",
          audit["scientific_status"],"screen",len(screens),
          "severe",len(severe),"sources",source_count,flush=True)
    return audit

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--station-csv",required=True,type=Path)
    for key in ("access-historical","original-historical","repaired-historical",
                "access-future","original-future","repaired-future","out"):
        p.add_argument("--"+key,required=True,type=Path)
    a=p.parse_args()
    run(a.station_csv,a.access_historical,a.original_historical,
        a.repaired_historical,a.access_future,a.original_future,
        a.repaired_future,a.out)
