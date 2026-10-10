#!/usr/bin/env python3
"""IGE P6.2D-B, M3: daily clear-sky-index additive QDM with physical bounds.

Research only. FAO-56 Ra/Rso uses site latitude and altitude. Unpaired
historical training = 1995–2004; independent verification = 2005–2014.
GCM days are NOT synchronous with station days and must never be scored
as same-date weather. Station and GCM time axes keep their own calendars.

M3 on k=GHI/Rso (0..1.10), with additive quantile-delta mapping:
    k_adj(q) = clamp(k_obs_hist(q) + k_target(q)-k_mod_hist(q), 0,1.10)
    GHI_adj(day) = k_adj(q_day) * Rso(day)
Allow up to 1.10 Rso because measured cloud enhancement can exceed nominal
FAO clear-sky values. Physically independent hard cap Ra is also checked.
The above is our benchmark variant, NOT a claimed exact implementation
of Bailey et al. or of externally calibrated pvlib/REST2 clear sky.
"""
from __future__ import annotations
import argparse,calendar,csv,json,hashlib,math
from collections import defaultdict,Counter
from pathlib import Path
from statistics import fmean

from p6_2d_solar_methods_benchmark import (
    MODELS,REPAIRED,HIST,CAL,TEST,METHODS,station_months,
    original_nasa_months,fit_months,apply_heldout_month,discrepancy,
    csvread,csvwrite,checksum,
)
from p6_2a_eight_model_ensemble import original_quality
from p6_2a_joint_diagnostics import quantile

STATION_LAT=47.080000
STATION_ALT_M=366.0
NASA_LAT=46.875000
# NASA 0.25° grid-cell elevation is NOT available in P6.1 artifacts.
# Assume station altitude as a PROXY for model clear-sky model, report it,
# and reserve a sensitivity experiment for actual model-grid elevation.
NASA_ALT_PROXY_M=366.0
MAX_CLEARSKY_INDEX=1.10
NEW="M3_daily_clearsky_index_QDM"
TRAIN_YEARS=tuple(CAL)
TEST_YEARS=tuple(TEST)
EXTRATERRESTRIAL_UNIT="kWh/m²/day"

def solar_geometry(month,day,year,latitude_deg,elevation_m,noleap=False):
    """FAO-56 Ra (MJ/m²/day) / 3.6 and Rso = (0.75+2e-5*z)*Ra.

    Exact Gregorian day ordinal for observed data; native noleap day
    ordinal for calendar=365_day/noleap GCM. FAO coefficients use /365.
    """
    if not math.isfinite(latitude_deg) or abs(latitude_deg)>89.0 \
       or not math.isfinite(elevation_m) or not -300<=elevation_m<=7000:
        raise ValueError("Unsupported latitude/elevation geometry")
    if not 1<=month<=12:raise ValueError("Invalid solar calendar month")
    if noleap:
        lengths=[31,28,31,30,31,30,31,31,30,31,30,31]
        if not 1<=day<=lengths[month-1]:
            raise ValueError("Noleap calendar contains invalid day")
        j=sum(lengths[:month-1])+day
    else:
        from datetime import date
        try:j=date(year,month,day).timetuple().tm_yday
        except ValueError as exc:raise ValueError("Invalid Gregorian date") from exc
    phi=math.radians(latitude_deg)
    dr=1.+.033*math.cos(2*math.pi*j/365.)
    decl=.409*math.sin(2*math.pi*j/365.-1.39)
    angle=max(-1.,min(1.,-math.tan(phi)*math.tan(decl)))
    omega=math.acos(angle)
    ra_mj=(24.*60./math.pi)*.0820*dr*(
        omega*math.sin(phi)*math.sin(decl)
        +math.cos(phi)*math.cos(decl)*math.sin(omega))
    ra=max(0.,ra_mj/3.6)
    clear=(.75+2e-5*elevation_m)*ra
    if not 0<=clear<=ra:
        raise ValueError("Clear sky approximation outside extraterrestrial physical envelope")
    return ra,clear

def safe_ratio(ghi,rso,ra):
    if not math.isfinite(ghi) or ghi<0 or not math.isfinite(rso) or rso<=0:
        raise ValueError("Invalid daily GHI or daily clear sky reference")
    if ghi>ra+1e-8:
        # Keep this diagnostic measurable in QA but do not silently overwrite
        # raw archived NASA solar (source is preserved elsewhere).
        return min(MAX_CLEARSKY_INDEX,ghi/rso),True,True
    return min(MAX_CLEARSKY_INDEX,ghi/rso),ghi>MAX_CLEARSKY_INDEX*rso+1e-8,False

def reference_daily(path):
    rows=csvread(path)
    if len(rows)!=7305:raise ValueError("Expected Gregorian GeoSphere 1995–2014 daily series")
    expected=set();out=[];qa=Counter()
    for r in rows:
        year,month,day=(int(r[k]) for k in ("year","month","day"))
        if not 1995<=year<=2014 or not 1<=month<=12 or \
           not 1<=day<=calendar.monthrange(year,month)[1]:
            raise ValueError("Invalid station date")
        key=(year,month,day)
        if key in expected or r["date_geo_moz_utc_label"]!=f"{year:04d}-{month:02d}-{day:02d}":
            raise ValueError("Duplicate or mislabelled station record")
        expected.add(key)
        if int(r["q21"]) not in (10,11,12,20,21,22):
            raise ValueError("Unverified GeoSphere GHI source cannot calibrate M3")
        value=float(r["trusted_daily_kwh_m2"])
        raw=float(r["cglo_j_raw_J_cm2"])
        if abs(value-raw/360.)>1e-7:raise ValueError("Original GeoSphere J/cm² scale changed")
        ra,rso=solar_geometry(month,day,year,STATION_LAT,STATION_ALT_M)
        index,overclear,overtoa=safe_ratio(value,rso,ra)
        qa["raw_above_1p1_clear_sky"]+=overclear
        qa["raw_above_extraterrestrial"]+=overtoa
        out.append({"year":year,"month":month,"day":day,"date":r["date_geo_moz_utc_label"],
                    "ghi_kwh_m2_day":value,"ra":ra,"rso":rso,"index":index})
    if len(expected)!=7305:raise ValueError("Incomplete accepted GeoSphere 20-year archive")
    return out,dict(qa)

def nasa_daily(model,access,original,repaired):
    if model=="ACCESS-CM2":folder=access/"ige-p6-access-historical-1995-2014"
    elif model in REPAIRED:folder=repaired/f"ige-p6-{model}-{HIST}"
    else:folder=original/f"ige-p6-{model}-{HIST}"
    qa,provenance,digests,_=original_quality(folder,model,HIST)
    cal=qa.get("calendar")
    if cal not in ("gregorian","noleap"):raise ValueError(f"Unsupported model calendar {cal}")
    daily=csvread(folder/"joint_daily_raw.csv")
    expected_days=sum(365+(year%4==0 and (year%100!=0 or year%400==0))
                      if cal=="gregorian" else 365 for year in range(1995,2015))
    if len(daily)!=expected_days:raise ValueError("Incomplete original NASA CF calendar")
    out=[];seen=set();counts=Counter()
    for row in daily:
        year,month,day=[int(row[k]) for k in ("year","month","day")]
        if not 1995<=year<=2014 or row["scenario"]!="historical" \
           or row["model"]!=model or row["date"]!=f"{year:04d}-{month:02d}-{day:02d}":
            raise ValueError("Wrong NASA model/date/scenario")
        key=(year,month,day)
        if key in seen:raise ValueError("Duplicate NASA daily source record")
        seen.add(key)
        value=float(row["rsds_kwh_m2_day"])
        if not math.isfinite(value) or abs(float(row["rsds"])*.024-value)>1e-6:
            raise ValueError("NASA native rsds physical unit conversion drift")
        ra,rso=solar_geometry(month,day,year,NASA_LAT,NASA_ALT_PROXY_M,cal=="noleap")
        idx,overclear,overtoa=safe_ratio(value,rso,ra)
        counts["raw_above_1p1_clear_sky"]+=overclear
        counts["raw_above_extraterrestrial"]+=overtoa
        out.append({"year":year,"month":month,"day":day,"date":row["date"],
                    "ghi_kwh_m2_day":value,"ra":ra,"rso":rso,"index":idx})
    monthly,prov=original_nasa_months(model,access,original,repaired)
    sums=defaultdict(float)
    for day in out:sums[day["year"],day["month"]]+=day["ghi_kwh_m2_day"]
    if set(sums)!=set(monthly) or any(abs(sums[k]-monthly[k])>1e-6 for k in sums):
        raise ValueError("P6.1 NASA source daily-to-monthly GHI conservation failed")
    return out,dict(counts),{"calendar":cal,**prov,"daily_records":len(out)}

def fit_daily_clear_index(observed,model):
    """Only train on 1995-2004 month-of-year unpaired empirical CDFs."""
    rules={}
    for month in range(1,13):
        obs=[r["index"] for r in observed if r["month"]==month and r["year"] in CAL]
        gcm=[r["index"] for r in model if r["month"]==month and r["year"] in CAL]
        if not 280<=len(obs)<=310 or not 280<=len(gcm)<=310:
            raise ValueError("Too few calendar-month days for daily M3 calibration")
        if any(x<0 or x>MAX_CLEARSKY_INDEX or not math.isfinite(x) for x in obs+gcm):
            raise ValueError("Invalid clear-sky index calibration sample")
        rules[month]={"station_index":tuple(sorted(obs)),
                      "model_index":tuple(sorted(gcm))}
    return rules

def corrected_daily_indices(target,rules):
    """QDM of clear-sky index in unpaired MONTHLY TARGET DISTRIBUTIONS.

    Observations in target years are neither passed nor accessed.
    Unlike M2 monthly multiplicative QDM, M3 uses additive QDM on k.
    Model target empirical rank is recomputed for each calendar month.
    """
    groups=defaultdict(list)
    for j,r in enumerate(target):
        if r["year"] not in TEST:raise ValueError("Target contains training/non-holdout day")
        groups[r["month"]].append((j,r))
    if set(groups)!=set(range(1,13)):raise ValueError("Missing target months")
    output=[None]*len(target)
    for month,pairs in groups.items():
        a=sorted(pairs,key=lambda item:(item[1]["index"],item[1]["year"],item[1]["month"],item[1]["day"]))
        rule=rules[month]
        for rank,(j,r) in enumerate(a):
            q=(rank+0.5)/len(a)
            obsq=quantile(rule["station_index"],q)
            modq=quantile(rule["model_index"],q)
            k=min(MAX_CLEARSKY_INDEX,max(0.,obsq+r["index"]-modq))
            cap=min(r["ra"],MAX_CLEARSKY_INDEX*r["rso"])
            ghi=min(cap,k*r["rso"])
            if not 0<=ghi<=cap+1.e-8:
                raise ValueError("M3 violates solar geometry physical bound")
            output[j]={"model_year":r["year"],"month":month,"day":r["day"],
                       "date":r["date"],"raw_kwh_m2_day":r["ghi_kwh_m2_day"],
                       "m3_kwh_m2_day":ghi,"ra_kwh_m2_day":r["ra"],
                       "rso_kwh_m2_day":r["rso"],
                       "raw_k":r["index"],"corrected_k":k,
                       "physical_cap_kwh_m2_day":cap}
    if any(v is None for v in output):raise ValueError("Unassigned daily correction record")
    return output

def aggregate_months(rows):
    sums=defaultdict(float);daycounts=Counter()
    for r in rows:
        key=(r["model_year"],r["month"])
        sums[key]+=r["m3_kwh_m2_day"]
        daycounts[key]+=1
    if len(sums)!=120 or sum(daycounts.values()) not in (3650,3652,3653):
        raise ValueError("Incomplete heldout GCM monthly chronology")
    return sums

def run(station_csv,access,original,repaired,out):
    out.mkdir(parents=True,exist_ok=True)
    station,stationflags=reference_daily(station_csv)
    monthly_station=station_months(station_csv)
    m3_scores=[];all_method_scores=[];monthly_comparison=[];daily_predictions=[]
    physical=[];provenance=[]
    for name in MODELS:
        nasa,flags,source=nasa_daily(name,access,original,repaired)
        rules=fit_daily_clear_index(station,nasa)
        corrected=corrected_daily_indices(
            [v for v in nasa if v["year"] in TEST],rules)
        monthly_m3=aggregate_months(corrected)
        nasa_month,monthly_prov=original_nasa_months(name,access,original,repaired)
        monthly_rules=fit_months(monthly_station,nasa_month)
        baselines=apply_heldout_month(nasa_month,monthly_rules)
        combined={k:{**baselines[k],NEW:monthly_m3[k]} for k in baselines}
        for method in (*METHODS,NEW):
            monthly,score=discrepancy(combined,monthly_station,method)
            all_method_scores.append({"model":name,"method":method,**score})
            for month,r in monthly.items():
                monthly_comparison.append({"model":name,"method":method,"month":month,**r})
            if method==NEW:m3_scores.append({"model":name,**score})
        for r in corrected:daily_predictions.append({"model":name,**r})
        cap_violation=sum(r["m3_kwh_m2_day"]>r["physical_cap_kwh_m2_day"]+1e-8
                          for r in corrected)
        physical.append({"model":name,"nasa_calendar":source["calendar"],
                         "source_native_daily_count":source["daily_records"],
                         "heldout_days":len(corrected),
                         "model_source_above_1p1_clear_sky":flags.get("raw_above_1p1_clear_sky",0),
                         "model_source_above_extraterrestrial":flags.get("raw_above_extraterrestrial",0),
                         "M3_heldout_physical_cap_violations":cap_violation,
                         "M3_nonnegative_violations":sum(r["m3_kwh_m2_day"]<0 for r in corrected),
                         "M3_monthly_checksum_provenance":source["model_monthly_source_sha256"]})
        provenance.append(source)
        print("CLEARSKY GHI",name,
              "M0",round(all_method_scores[-4]["annual_climatological_bias_percent"],2),
              "M1",round(all_method_scores[-3]["annual_climatological_bias_percent"],2),
              "M2",round(all_method_scores[-2]["annual_climatological_bias_percent"],2),
              "M3",round(all_method_scores[-1]["annual_climatological_bias_percent"],2),
              "overTOA",flags.get("raw_above_extraterrestrial",0),flush=True)
    if len(all_method_scores)!=32 or len(monthly_comparison)!=384 or len(m3_scores)!=8 \
       or any(r["M3_heldout_physical_cap_violations"] or r["M3_nonnegative_violations"]
              for r in physical):
        raise ValueError("Incomplete method benchmark or M3 physical-closure failure")
    outputs={
        "m3_heldout_daily_solar_eight_gcm.csv":daily_predictions,
        "m0_m1_m2_m3_heldout_model_scores.csv":all_method_scores,
        "m0_m1_m2_m3_month_of_year_scores.csv":monthly_comparison,
        "m3_model_physical_bounds_audit.csv":physical,
    }
    digests={name:csvwrite(out/name,records) for name,records in outputs.items()}
    report={"status":"PASS_MONTHLY_HOLDOUT_AND_M3_DAILY_PHYSICS_ONLY",
            "stage":"P6.2D-B_ClearSkyAware_GHI",
            "methods":list(METHODS)+[NEW],
            "original_QC_station":stationflags,"original_source_sha256":checksum(station_csv),
            "NASA_original_provenance":provenance,
            "years_calibrated":[1995,2004],"years_heldout":[2005,2014],
            "station_geometry":{"lat":STATION_LAT,"altitude_m":STATION_ALT_M},
            "model_geometry":{"lat":NASA_LAT,"altitude_m_proxy":NASA_ALT_PROXY_M},
            "extraterrestrial_radiation":"FAO-56 solar geometry Gsc=0.0820 MJ/m²/min",
            "daily_clear_sky":"FAO-56 Eq37 Rso=(0.75+2e-5*z)*Ra",
            "daily_index_hard_max":MAX_CLEARSKY_INDEX,
            "solar_bounds":"0 <= corrected GHI <= min(Ra, 1.10 Rso)",
            "M3_mapping":"additive monthwise clear-sky-index QDM with target-model-only heldout ranks",
            "sensitivity_status":"NOT_DONE: altitude proxy, clear-sky multiplier, and blocked resampling",
            "output_sha256":digests,
            "restrictions":[
                "Independent station and GCM daily values are not synchronous; never compute paired daily errors.",
                "Climatological monthly/annual holdout and solar physical bounds ONLY; not an hourly energy weather generator.",
                "FAO-56 Rso approximate clear sky, cloud-edge enhancement admitted up to 10 percent.",
                "NASA grid altitude approximated by station altitude; not actual terrain/grid-corrected.",
                "No spatial transfer, operational EPW, production changes, or future SSP calibration.",
                "M3 is a proposed methodological variant, not a byte-equivalent reimplementation of Bailey et al. 2025.",
                "NEX-GDDP v2 already BCSD-adjusted; M3 is an additional empirical local correction.",
            ]}
    (out/"p6_2d_b_clearsky_benchmark_report.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P6.2D-B",report["status"],"8 models",len(all_method_scores),
          "model-method scores and",len(daily_predictions),"corrected daily GHI outputs",flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--station-csv",type=Path,required=True)
    for k in ("access","original","repaired","out"):p.add_argument("--"+k,type=Path,required=True)
    args=p.parse_args()
    run(args.station_csv,args.access,args.original,args.repaired,args.out)
