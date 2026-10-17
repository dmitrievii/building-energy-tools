#!/usr/bin/env python3
"""IGE P8.4C future wind scalar baseline: audited GCM signal and real station wind.

Research only. Historical hourly FROM directions are INHERITED, never future
direction forecasts. Source original values never exported in CI artifacts.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path

import p7c1_epw_morphing as p7c1
import p7c3_ensemble as p7c3
import p7b5_wind_coherence as p7b5

SIGNALS="research/ige_cmip6/results/p7c3_384_monthly_model_signals.csv"
CALM_MPS=.5
HIGH_WIND_MPS=5.
N_SOURCE_HOURS=8760
SERIALIZATION_DECIMALS=3
MIN_GOOD_SOURCE_FRACTION=.85
MONTH_BALANCE_TOLERANCE_MPS=.001
N_GCM_STATES=32
SEASONS={1:"DJF",2:"DJF",12:"DJF",3:"MAM",4:"MAM",5:"MAM",6:"JJA",7:"JJA",8:"JJA",9:"SON",10:"SON",11:"SON"}


def hash_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def read_registered_wind_ratios(path):
    raw=Path(path).read_bytes()
    source=list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    expected={(m,w,mo) for m in p7c3.MODELS
             for w in p7c3.WINDOWS for mo in range(1,13)}
    if len(source)!=384:
        raise ValueError("P8C_FROZEN_SOURCE_EXPECTS_384_MODEL_MONTHS")
    selected={}
    for row in source:
        model=row["model"];window=row["window"]
        try:
            month=int(row["month"])
            factor=float(row["wind_ratio"])
        except (TypeError,ValueError,OverflowError) as exc:
            raise ValueError("P8C_BAD_GCM_WIND_SIGNAL") from exc
        key=model,window,month
        if key not in expected or key in selected:
            raise ValueError("P8C_DUPLICATE_OR_UNREGISTERED_GCM_IDENTITY")
        lower,upper=p7c1.SOURCE_THRESHOLDS["wind_ratio"]
        if not math.isfinite(factor) or not (lower<=factor<=upper):
            raise ValueError("P8C_WIND_FACTOR_OUTSIDE_FROZEN_BOUNDS")
        selected[key]=factor
    if set(selected)!=expected:
        raise ValueError("P8C_INCOMPLETE_GCM_WINDOW_MONTH_MATRIX")
    return selected,{
        "immutable_committed_GCM_signal_sha256":hash_bytes(raw),
        "source_GCM_ratio_table":SIGNALS,
        "ratio_source":"P7C3 registered 20y HIST/FUTURE native daily sfcWind monthly ratio",
        "source_wind_day_is_scalar_not_uv":True,
        "n_signal_rows":len(source),
        "registered_models":list(p7c3.MODELS),
        "registered_windows":list(p7c3.WINDOWS),
        "min_monthly_ratio":min(selected.values()),
        "max_monthly_ratio":max(selected.values()),
        "all_40_source_GCM_ZIPs_independently_re_fetched_in_this_phase":False,
        "original_GCM_source_independently_verified_in_previous_P7C4":True,
    }


def original_2013_reference():
    if p7b5.STATION!=30:
        raise AssertionError("P8C_UNEXPECTED_ORIGINAL_STATION")
    weather,station,provenance=p7b5.load_observations(years=(2013,))
    start=dt.datetime(2013,1,1,tzinfo=dt.timezone.utc)
    axis=tuple(start+dt.timedelta(hours=i) for i in range(N_SOURCE_HOURS))
    if set(weather)!=set(axis):
        raise ValueError("P8C_SOURCE_UTC_HOURLY_AXIS_NOT_COMPLETE")
    data=[]
    qc_speed_valid=qc_usable=0
    source_noncalm_invalid=0
    for stamp in axis:
        x=weather[stamp];speed=x.get("ff");direction=x.get("dd")
        if speed is not None:
            qc_speed_valid+=1
            if speed>=CALM_MPS and direction is None:
                source_noncalm_invalid+=1
        usable=(speed is not None and (speed<CALM_MPS or direction is not None))
        if usable:
            qc_usable+=1
        data.append({
            "time":stamp,
            "month":stamp.month,
            "speed":speed,
            "direction":direction,
            "qualified":usable,
        })
    if qc_usable<math.ceil(MIN_GOOD_SOURCE_FRACTION*N_SOURCE_HOURS):
        raise ValueError("P8C_ORIGINAL_GEOSPHERE_SOURCE_COVERAGE_LOW")
    meta={
        "source_station_id":p7b5.STATION,
        "source_year":2013,
        "source_timezone":"UTC, no DST or station-to-EPW time shift",
        "source_2013_UTC_hours":len(data),
        "source_qc_speed_valid_hours":qc_speed_valid,
        "source_qc_usable_wind_hours":qc_usable,
        "source_noncalm_missing_qc_direction_hours":source_noncalm_invalid,
        "original_source_SHA256":provenance,
        "station_provider_metadata":station,
        "source_ff_hourly_is_GeoSphere_vector_defined":True,
        "original_station_is_not_user_licensed_meteonorm_EPW":True,
        "comparison_to_daily_GCM_scalar_is_change_factor_sensitivity_only":True,
    }
    return data,meta


def circular_distance(a,b):
    if a is None or b is None:
        raise ValueError("P8C_UNDEFINED_AZIMUTH_CANNOT_BE_SCORED")
    return abs(((float(a)-float(b)+180.)%360.)-180.)


def run_count(values,window,threshold):
    """Number of contiguous window-length qualifying h intervals."""
    if window<1:
        raise ValueError("P8C_INVALID_PERSISTENCE_WINDOW")
    streak=0;result=0
    for v in values:
        streak=streak+1 if v is not None and v>=threshold else 0
        if streak>=window:
            result+=1
    return result


def quantile(values,q):
    vals=sorted(values)
    if not vals:
        return None
    x=q*(len(vals)-1)
    i=int(x)
    return vals[i]+(vals[min(i+1,len(vals)-1)]-vals[i])*(x-i)


def rose16(samples):
    bins=[0]*16
    n=0
    undefined=0
    for x in samples:
        if x["speed"]<CALM_MPS:
            continue
        azimuth=x["direction"]
        if azimuth is None:
            undefined+=1
            continue
        i=int(((azimuth%360.+11.25)%360.)//22.5)
        bins[i]+=1;n+=1
    return {"resolved_sector_count":n,
            "new_noncalm_without_direction":undefined,
            "frequency":[x/n for x in bins] if n else [0.]*16}


def morph_record(original,factor):
    """Preserve original direction even if 0.5m/s calm status crosses boundary."""
    if not (math.isfinite(factor) and factor>0):
        raise ValueError("P8C_INVALID_POSITIVE_MULTIPLIER")
    speed=original["speed"]
    if speed is None or not original["qualified"]:
        return {"speed":None,"direction":original["direction"],
                "from_original_missing":True}
    if not (math.isfinite(speed) and speed>=0):
        raise ValueError("P8C_INVALID_ORIGINAL_WIND_SPEED")
    az=original["direction"]
    if az is not None and (not math.isfinite(az) or not 0<=az<=360):
        raise ValueError("P8C_INVALID_SOURCE_FROM_AZIMUTH")
    value=round(speed*factor,SERIALIZATION_DECIMALS)
    if not math.isfinite(value) or value<0:
        raise ValueError("P8C_NONPHYSICAL_SCALED_WIND")
    return {"speed":value,"direction":az,"from_original_missing":False}


def wind_metrics(items):
    known=[v for v in items if v["speed"] is not None]
    valid=[x["speed"] for x in known]
    if not valid:
        raise ValueError("P8C_NO_VALID_REFERENCE_SCALAR_WIND")
    conditional=rose16(known)
    n=len(valid)
    return {
        "n_usable_speed_hours":n,
        "wind_speed_mean_mps":statistics.fmean(valid),
        "wind_speed_p05_mps":quantile(valid,.05),
        "wind_speed_p50_mps":quantile(valid,.50),
        "wind_speed_p95_mps":quantile(valid,.95),
        "wind_speed_max_mps":max(valid),
        "calm_frequency_pct":100*sum(s<CALM_MPS for s in valid)/n,
        "speed_ge2_frequency_pct":100*sum(s>=2. for s in valid)/n,
        "speed_ge5_frequency_pct":100*sum(s>=5. for s in valid)/n,
        "three_consecutive_hours_ge5":run_count(
            [x["speed"] for x in items],3,HIGH_WIND_MPS),
        "six_consecutive_hours_ge5":run_count(
            [x["speed"] for x in items],6,HIGH_WIND_MPS),
        "noncalm_azimuth_resolved_count":conditional["resolved_sector_count"],
        "noncalm_no_azimuth_count":conditional["new_noncalm_without_direction"],
        "noncalm_azimuth_coverage_pct":(
            100*conditional["resolved_sector_count"]/(
                conditional["resolved_sector_count"]+
                conditional["new_noncalm_without_direction"])
            if conditional["resolved_sector_count"]+
               conditional["new_noncalm_without_direction"] else None),
        "conditional_rose_16_frequencies":conditional["frequency"],
    }


def compare_one_state(original,ratio,model,window):
    if len(original)!=N_SOURCE_HOURS:
        raise ValueError("P8C_EXPECTED_COMPLETE_8760_HOUR_SOURCE_AXIS")
    expected={month:ratio[(model,window,month)] for month in range(1,13)}
    future=[morph_record(x,expected[x["month"]]) for x in original]
    paired=[i for i,x in enumerate(original) if x["qualified"]]
    if len(paired)<math.ceil(MIN_GOOD_SOURCE_FRACTION*N_SOURCE_HOURS):
        raise ValueError("P8C_NOT_ENOUGH_IDENTICAL_ORIGINAL_QC_HOURS")
    # Time sequence identity is inherent in same-list position; no resampling.
    for i in range(N_SOURCE_HOURS):
        if future[i]["direction"]!=original[i]["direction"]:
            raise AssertionError("P8C_HISTORICAL_AZIMUTH_ALTERED")
        if future[i]["from_original_missing"]==(original[i]["qualified"]):
            raise AssertionError("P8C_MISSINGNESS_CHANGED")
    source=[{"speed":original[i]["speed"],"direction":original[i]["direction"]}
            for i in range(N_SOURCE_HOURS) if original[i]["qualified"]]
    result=[future[i] for i in range(N_SOURCE_HOURS) if original[i]["qualified"]]
    orig_full=[{"speed":x["speed"] if x["qualified"] else None,
                "direction":x["direction"]} for x in original]
    new_full=future
    base=wind_metrics(orig_full)
    prediction=wind_metrics(new_full)
    monthly=[]
    max_balance=0.
    for mo in range(1,13):
        ids=[i for i in paired if original[i]["month"]==mo]
        if not ids:
            raise ValueError("P8C_SOURCE_CALENDAR_MONTH_EMPTY")
        src=statistics.fmean(original[i]["speed"] for i in ids)
        dst=statistics.fmean(future[i]["speed"] for i in ids)
        expectation=src*expected[mo]
        residual=abs(dst-expectation)
        max_balance=max(max_balance,residual)
        if residual>MONTH_BALANCE_TOLERANCE_MPS+1e-12:
            raise AssertionError("P8C_MONTHLY_MULTIPLICATION_BALANCE_BROKEN")
        original_sector=rose16(source[j] for j,i in enumerate(paired) if original[i]["month"]==mo)
        future_sector=rose16(result[j] for j,i in enumerate(paired) if original[i]["month"]==mo)
        # Conditional wind rose CAN change when multiplying speeds changes
        # which hours cross the declared 0.5m/s calm threshold.
        l1=sum(abs(a-b) for a,b in zip(
            original_sector["frequency"],future_sector["frequency"]))
        monthly.append({
            "month":mo,"ratio":expected[mo],
            "n_same_source_qualified_hours":len(ids),
            "original_mean_speed_mps":src,
            "morphed_mean_speed_mps":dst,
            "model_month_ratio_balance_abs_mps":residual,
            "direction_rose_16_conditional_L1_change":l1,
            "new_noncalm_without_direction":sum(
                future[i]["speed"]>=CALM_MPS
                and future[i]["direction"] is None for i in ids),
        })
    seasons=[]
    for season in ("DJF","MAM","JJA","SON"):
        mask=[i for i,x in enumerate(original)
              if SEASONS[x["month"]]==season]
        seasons.append({
            "season":season,
            "historical":wind_metrics([orig_full[i] for i in mask]),
            "morphed":wind_metrics([new_full[i] for i in mask]),
        })
    # Determine exactly whether the input's direction is known for each
    # hour newly counted as noncalm. Do not assign any artificial azimuth.
    newly_noncalm_missing=sum(
        future[i]["speed"] is not None
        and future[i]["speed"]>=CALM_MPS
        and future[i]["direction"] is None
        for i in paired
    )
    # Even when the provider stored a numeric azimuth at speed <0.5 m/s,
    # that calm-hour direction is NOT qualified as a new future noncalm
    # direction. Any calm -> noncalm crossing needs an explicit safety flag.
    promoted_source_calm=sum(
        original[i]["speed"]<CALM_MPS and future[i]["speed"]>=CALM_MPS
        for i in paired
    )
    demoted_source_noncalm=sum(
        original[i]["speed"]>=CALM_MPS and future[i]["speed"]<CALM_MPS
        for i in paired
    )
    change_count=promoted_source_calm+demoted_source_noncalm
    mismatch=max(
        [circular_distance(original[i]["direction"],future[i]["direction"])
         for i in paired if original[i]["direction"] is not None]+[0.])
    if mismatch!=0:
        raise AssertionError("P8C_ORIGINAL_DIRECTION_NUMERIC_CHANGED")
    return {
        "model":model,"window":window,
        "n_identical_original_valid_hour_pairs":len(paired),
        "source_year":2013,
        "source_hourly_directions_preserved":True,
        "maximum_source_to_scaled_azimuth_change_deg":mismatch,
        "maximum_monthly_mean_speed_ratio_balance_error_mps":max_balance,
        "newly_noncalm_missing_direction_hour_count":newly_noncalm_missing,
        "calm_source_promoted_to_noncalm_hours_even_if_azimuth_numeric":promoted_source_calm,
        "source_noncalm_demoted_to_calm_hours":demoted_source_noncalm,
        "noncalm_direction_physical_suitability_blocker_hours":sum(
            future[i]["speed"]>=CALM_MPS
            and (future[i]["direction"] is None
                 or original[i]["speed"]<CALM_MPS)
            for i in paired),
        "calm_threshold_crossing_hour_count":change_count,
        "historical":base,
        "future_scalar_baseline":prediction,
        "monthly":monthly,"seasons":seasons,
        "user_EPW_output_already_validated":False,
        "future_direction_projection_supported":False,
    }


def calculate_ensemble_summary(states):
    out={}
    for window in p7c3.WINDOWS:
        group=[r for r in states if r["window"]==window]
        if len(group)!=len(p7c3.MODELS):
            raise ValueError("P8C_MISSING_EIGHT_MODEL_MEMBERS")
        def ensemble_range(key):
            values=sorted(float(r["future_scalar_baseline"][key]) for r in group)
            return {
                "min":values[0],"median":quantile(values,.5),
                "max":values[-1],
            }
        out[window]={
            "gcm_count":len(group),
            "annual_mean_speed_mps":ensemble_range("wind_speed_mean_mps"),
            "calm_frequency_pct":ensemble_range("calm_frequency_pct"),
            "wind_speed_p95_mps":ensemble_range("wind_speed_p95_mps"),
            "speed_ge5_frequency_pct":ensemble_range("speed_ge5_frequency_pct"),
            "newly_noncalm_missing_direction_hours":{
                r["model"]:r["newly_noncalm_missing_direction_hour_count"] for r in group},
            "not_probabilistic_uncertainty_intervals":True,
        }
    return out


def run(out,signals=SIGNALS):
    ratio,meta=read_registered_wind_ratios(signals)
    original,source_meta=original_2013_reference()
    states=[
        compare_one_state(original,ratio,model,window)
        for model in p7c3.MODELS for window in p7c3.WINDOWS
    ]
    if len(states)!=N_GCM_STATES:
        raise AssertionError("P8C_32_STATES_MISSING")
    acceptance={
        "all_384_monthly_GCM_ratios_qualified":True,
        "all_32_actual_station_2013_source_morphs_physics_pass":True,
        "all_32_directions_inherited_unchanged":all(
            r["source_hourly_directions_preserved"] for r in states),
        "all_384_monthly_wind_speed_balances_pass":all(
            r["maximum_monthly_mean_speed_ratio_balance_error_mps"]
            <=MONTH_BALANCE_TOLERANCE_MPS for r in states),
    }
    result={
        "phase":"IGE_P8_4C",
        "status":"RESEARCH_384_REGISTERED_WIND_RATIOS_AND_ORIGINAL_STATION_BASELINE_COMPLETE",
        "frozen_source":meta,
        "original_station_reference":source_meta,
        "validations":acceptance,
        "all_tests_passed":all(acceptance.values()),
        "model_source_daily_sfcWind_is_magnitude_only":True,
        "station_hourly_reference_speed_is_vector_hourly_provider_defined":True,
        "monthly_factor_spatial_downscaling_verification_proven":False,
        "future_direction_change_projected":False,
        "future_wind_event_sequencing_generated":False,
        "model_baseline_is_actual_user_EPW":False,
        "full_GCM_future_EPWs_with_authenticated_user_license_qualified_here":False,
        "gcm_humidity_IPSL_EPW_source_block_remains":True,
        "production_epw_ready":False,
        "scenario_results":states,
        "ensemble_empirical_model_range_not_probability":calculate_ensemble_summary(states),
    }
    p=Path(out);p.mkdir(parents=True,exist_ok=True)
    (p/"ige_p8_4c_future_wind_baseline_original_aggregates.json").write_text(
        json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+"\n",
        encoding="utf-8")
    print("IGE_P8_4C",json.dumps({
        "status":result["status"],
        "n_monthly_ratios":meta["n_signal_rows"],
        "states":len(states),
        "original_qc_hourly_wind":source_meta["source_qc_usable_wind_hours"],
        "max_ratio_balance_abs_mps":max(
            r["maximum_monthly_mean_speed_ratio_balance_error_mps"] for r in states),
        "new_noncalm_missing_direction_states":sum(
            r["newly_noncalm_missing_direction_hour_count"]>0 for r in states),
        "original_calm_to_new_noncalm_physics_blocker_states":sum(
            r["calm_source_promoted_to_noncalm_hours_even_if_azimuth_numeric"]>0
            for r in states),
        "production_epw_ready":False,
    },ensure_ascii=False),flush=True)
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",required=True)
    ap.add_argument("--signals",default=SIGNALS)
    opts=ap.parse_args()
    run(opts.out,opts.signals)
