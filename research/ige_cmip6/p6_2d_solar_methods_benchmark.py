#!/usr/bin/env python3
"""IGE P6.2D GHI correction method benchmark, 1995–2014, eight NASA GCMs.

Research ONLY. Split station AND model data by year:
calibration=1995–2004, evaluation=2005–2014. All model years unpaired to
station weather. Scoring is by MONTH-OF-YEAR DISTRIBUTION, never paired daily
or per-year weather error. Three methods:
M0 original already-BCSD-adjusted NEX-GDDP-CMIP6 (unchanged);
M1 calendar-month climatological multiplicative correction;
M2 multiplicative empirical quantile-delta mapping (QDM), evaluated on each
heldout model monthly distribution without using heldout station observations.

QDM quantile change preservation is algebraic. It is NOT an hourly physical
closure algorithm, nor a proof of generalization outside historical support.
"""
from __future__ import annotations
import argparse,calendar,csv,hashlib,json,math
from collections import defaultdict
from pathlib import Path
from statistics import fmean

from p6_2a_eight_model_ensemble import MODELS,original_quality
from p6_2a_joint_diagnostics import quantile

CAL=range(1995,2005)
TEST=range(2005,2015)
HIST="historical-1995-2014"
REPAIRED=frozenset(("EC-Earth3","IPSL-CM6A-LR","MPI-ESM1-2-HR"))
METHODS=("M0_raw_nex","M1_monthly_climatology","M2_multiplicative_QDM")

def checksum(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def csvread(path):
    with Path(path).open(newline="",encoding="utf8") as f:return list(csv.DictReader(f))

def csvwrite(path,rows):
    if not rows:raise ValueError(f"No output rows for {path}")
    with path.open("w",newline="",encoding="utf8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    return checksum(path)

def ensure_complete(mapping,start=1995,end=2014):
    if set(mapping)!={(y,m) for y in range(start,end+1) for m in range(1,13)}:
        raise ValueError(f"Missing/duplicated monthly chronology {start}-{end}")

def station_months(path):
    rows=csvread(path)
    if len(rows)!=7305:raise ValueError("Station 20-year Gregorian record count !=7305")
    expected=set();monthdays=defaultdict(list);seen=set()
    for r in rows:
        y,m,d=int(r["year"]),int(r["month"]),int(r["day"])
        if not 1995<=y<=2014 or not 1<=m<=12 or not 1<=d<=calendar.monthrange(y,m)[1]:
            raise ValueError("Station calendar row malformed")
        key=(y,m,d)
        if key in seen or r["date_geo_moz_utc_label"]!=f"{y:04d}-{m:02d}-{d:02d}":
            raise ValueError("Repeated/mismatched station day")
        seen.add(key)
        original=r["cglo_j_raw_J_cm2"]
        qc=r["q21"]
        accepted=r["trusted_daily_kwh_m2"]
        if original=="" or qc=="" or accepted=="":
            raise ValueError("Station not fully quality-checked; no synthetic infilling")
        if int(qc) not in (10,11,12,20,21,22):
            raise ValueError("Unchecked station value cannot calibrate solar benchmark")
        raw=float(original);energy=float(accepted)
        if not math.isfinite(energy) or abs(energy-raw/360)>1e-7 or not 0<=energy<=12.5:
            raise ValueError("Station GHI conversion invalid")
        monthdays[(y,m)].append(energy)
    if len(seen)!=7305:raise ValueError("Repeated station days")
    result={}
    for y in range(1995,2015):
        for m in range(1,13):
            rr=monthdays[(y,m)]
            if len(rr)!=calendar.monthrange(y,m)[1]:
                raise ValueError("Incomplete station calendar month")
            result[(y,m)]=sum(rr)
    ensure_complete(result)
    return result

def original_nasa_months(model,access,original,repaired):
    if model not in MODELS:raise ValueError(f"Unexpected GCM {model}")
    if model=="ACCESS-CM2":folder=access/"ige-p6-access-historical-1995-2014"
    elif model in REPAIRED:folder=repaired/f"ige-p6-{model}-{HIST}"
    else:folder=original/f"ige-p6-{model}-{HIST}"
    qa,prov,hashes,days=original_quality(folder,model,HIST)
    rr=csvread(folder/"model_monthly.csv")
    if len(rr)!=240:raise ValueError(f"{model} missing original 240 monthly values")
    monthly={}
    for row in rr:
        y,m=int(row["year"]),int(row["month"])
        if row["scenario"]!="historical" or row["window"]!=HIST or not 1995<=y<=2014 \
           or not 1<=m<=12 or (y,m) in monthly:
            raise ValueError("NASA source month missing/duplicate/wrong scenario")
        value=float(row["ghi_kwh_m2"])
        if not math.isfinite(value) or not 0<value<600:
            raise ValueError("Invalid NASA monthly solar value")
        monthly[y,m]=value
    ensure_complete(monthly)
    provenance={"model":model,"model_monthly_source_sha256":hashes["model_monthly.csv"],
                "quality_report_sha256":checksum(folder/"quality_report.json"),
                "provenance_report_sha256":checksum(folder/"source_provenance.json"),
                "model_grid":qa.get("grid"),"calendar":qa.get("calendar")}
    return monthly,provenance

def interp_percentile(values,p):
    if not values:raise ValueError("Empty calibration quantile")
    if not 0<=p<=1:raise ValueError("Invalid percentile")
    a=sorted(values)
    if not all(math.isfinite(float(x)) and x>0 for x in a):
        raise ValueError("Invalid positive solar quantiles")
    return float(quantile(a,p))

def fit_months(station,model):
    """Freeze only independent 1995–2004 calibration samples."""
    ensure_complete(station);ensure_complete(model)
    rules={}
    for month in range(1,13):
        obs=tuple(station[y,month] for y in CAL)
        sim=tuple(model[y,month] for y in CAL)
        if len(obs)!=10 or len(sim)!=10:raise ValueError("Insufficient training years")
        mean_obs=fmean(obs);mean_model=fmean(sim)
        if mean_obs<=0 or mean_model<=0:raise ValueError("Nonpositive monthly solar")
        rules[month]={
            "observed_calibration_sorted":tuple(sorted(obs)),
            "model_calibration_sorted":tuple(sorted(sim)),
            "monthly_factor":mean_obs/mean_model,
            "reference_station_mean":mean_obs,
            "historical_model_mean":mean_model,
        }
    return rules

def qdm_target(values,rule):
    """Multiplicative QDM by percentile of a full unpaired model target period.

    This is NOT model-day matching: the observed and model histories are sorted
    separately. q rank from model target only, with no heldout station data.
    If future model q = 1.2 * hist model q, corrected q = 1.2 * obs hist q.
    """
    if not values or any(not math.isfinite(x) or x<=0 for x in values):
        raise ValueError("QDM target must be positive finite GHI")
    ranks=sorted(range(len(values)),key=lambda i:(values[i],i))
    out=[None]*len(values)
    for ordinal,i in enumerate(ranks):
        q=(ordinal+0.5)/len(values)
        observed=interp_percentile(rule["observed_calibration_sorted"],q)
        baseline=interp_percentile(rule["model_calibration_sorted"],q)
        out[i]=values[i]*(observed/baseline)
    if any(x is None or x<=0 or not math.isfinite(x) for x in out):
        raise ValueError("Bad QDM output")
    return out

def apply_heldout_month(model,rules):
    """Inputs include NO held-out station observed values."""
    corrected={}
    for m in range(1,13):
        raw=[model[y,m] for y in TEST]
        qdm=qdm_target(raw,rules[m])
        for i,y in enumerate(TEST):
            corrected[y,m]={
                METHODS[0]:raw[i],
                METHODS[1]:raw[i]*rules[m]["monthly_factor"],
                METHODS[2]:qdm[i],
            }
    if len(corrected)!=120:raise AssertionError("Not 120 corrected months")
    return corrected

def discrepancy(heldout,observed,method):
    """DO NOT compare matching model vs station YEAR climate realizations."""
    mm={}
    monthly_errors=[]
    for m in range(1,13):
        sim=[heldout[y,m][method] for y in TEST]
        obs=[observed[y,m] for y in TEST]
        s=fmean(sim);o=fmean(obs)
        mm[m]={"predicted_month_of_year_climatology_kwh_m2":s,
               "observed_month_of_year_climatology_kwh_m2":o,
               "climatological_bias_kwh_m2":s-o,
               "model_q10_kwh_m2":interp_percentile(sim,.1),
               "model_q90_kwh_m2":interp_percentile(sim,.9),
               "obs_q10_kwh_m2":interp_percentile(obs,.1),
               "obs_q90_kwh_m2":interp_percentile(obs,.9)}
        monthly_errors.append(abs(s-o))
    modelyears=[sum(heldout[y,m][method] for m in range(1,13)) for y in TEST]
    obsyears=[sum(observed[y,m] for m in range(1,13)) for y in TEST]
    mean_model=fmean(modelyears);mean_obs=fmean(obsyears)
    return mm,{
        "heldout_years":"2005-2014",
        "mean_annual_ghi_model_kwh_m2":mean_model,
        "mean_annual_ghi_station_kwh_m2":mean_obs,
        "annual_climatological_bias_kwh_m2":mean_model-mean_obs,
        "annual_climatological_bias_percent":100*(mean_model/mean_obs-1),
        "month_of_year_climatology_MAE_kwh_m2":fmean(monthly_errors),
        "interannual_annual_p10_abs_delta_kwh_m2":
            abs(interp_percentile(modelyears,.1)-interp_percentile(obsyears,.1)),
        "interannual_annual_p90_abs_delta_kwh_m2":
            abs(interp_percentile(modelyears,.9)-interp_percentile(obsyears,.9)),
        "not_paired_model_year_rmse":True,
    }

def run(station_csv,access,original,repaired,out):
    out.mkdir(parents=True,exist_ok=True)
    obs=station_months(station_csv)
    prov={"station_sha256":checksum(station_csv),"NASA_original":[]}
    metrics=[];monthlyout=[];predictions=[];train=[]
    for name in MODELS:
        baseline,source=original_nasa_months(name,access,original,repaired)
        prov["NASA_original"].append(source)
        rules=fit_months(obs,baseline)
        corrected=apply_heldout_month(baseline,rules)
        for month,r in rules.items():
            train.append({"model":name,"month":month,
                "calibration_start":1995,"calibration_end":2004,
                "monthly_factor":r["monthly_factor"],
                "station_cal_ghi_kwh_m2":r["reference_station_mean"],
                "model_cal_ghi_kwh_m2":r["historical_model_mean"]})
        for (year,month),methods in sorted(corrected.items()):
            for method,value in methods.items():
                predictions.append({"model":name,"year":year,"month":month,
                    "method":method,"predicted_GHI_kwh_m2":value,
                    "station_heldout_reference_GHI_kwh_m2":obs[year,month],
                    "warning":"not paired years or daily weather: DO NOT use annual paired RMSE"})
        for method in METHODS:
            month_audit,score=discrepancy(corrected,obs,method)
            metrics.append({"model":name,"method":method,**score})
            for month,d in month_audit.items():
                monthlyout.append({"model":name,"method":method,"month":month,**d})
        print("GHI BENCHMARK",name,"raw %",round(metrics[-3]["annual_climatological_bias_percent"],2),
              "M1 %",round(metrics[-2]["annual_climatological_bias_percent"],2),
              "M2 %",round(metrics[-1]["annual_climatological_bias_percent"],2),flush=True)
    if len(metrics)!=8*3 or len(predictions)!=8*10*12*3 or len(monthlyout)!=8*12*3:
        raise ValueError("Incorrect eight-model benchmark coverage")
    output={
        "solar_method_monthly_calibration.csv":train,
        "solar_method_heldout_predictions.csv":predictions,
        "solar_method_heldout_scores.csv":metrics,
        "solar_method_month_of_year_scores.csv":monthlyout,
    }
    hashes={filename:csvwrite(out/filename,content) for filename,content in output.items()}
    audit={
        "status":"PASS_RESEARCH_MONTHLY_HOLDOUT_ONLY",
        "stage":"IGE_P6.2D_M0_M1_M2",
        "GCM_models":list(MODELS),"model_count":len(MODELS),
        "calibration":"1995–2004 inclusive", "independent_holdout":"2005–2014 inclusive",
        "station":"GeoSphere Graz #30 quality-approved full daily cglo_j",
        "model_source":"NASA NEX-GDDP-CMIP6 v2 historical rsds original accepted P6.1",
        "source_provenance":prov,"output_sha256":hashes,
        "method_notes":{
            METHODS[0]:"Already GMFD-BCSD-adjusted NASA historical GHI, unmodified",
            METHODS[1]:"Per-GCM station/month mean ratio trained 1995–2004 only",
            METHODS[2]:"Multiplicative quantile-delta mapping by unpaired target model monthly distribution and independent historic observed/monthly model quantiles. Requires future transfer tests.",
        },
        "scientific_limits":[
            "No correction applied to Climate Analyzer; research data only.",
            "No full historical reference training + independent future periods yet.",
            "NASA historical model internal variability does not track observed station-year weather.",
            "Monthly 10-sample QDM quantiles are small-sample estimates; check robustness before production.",
            "No paired date/year MAE, RMSE, R², daily solar timing or physical hourly closure implied.",
            "Comparison of empirical climatology alone cannot establish model/weather time-series fidelity.",
            "GeoSphere station and NASA model grid are spatially mismatched; investigate representativeness.",
            "Cannot validate future GHI truth; future preservation is methodological, not observational.",
            "M2 does not enforce clear-sky GHI limits; later stage must implement and validate physical feasibility.",
            "NASA is already BCSD-adjusted; additional local correction may double-adjust and is experimental.",
        ],
    }
    (out/"ige_p6_2d_solar_methods_benchmark_report.json").write_text(
        json.dumps(audit,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P6.2D SOLAR METHODS",audit["status"],"models",len(MODELS),
          "scores",len(metrics),flush=True)
    return audit

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--station-csv",type=Path,required=True)
    for s in ("access","original","repaired","out"):
        p.add_argument("--"+s,type=Path,required=True)
    a=p.parse_args()
    run(a.station_csv,a.access,a.original,a.repaired,a.out)

if __name__=="__main__":main()
