#!/usr/bin/env python3
"""P9.1H2/H3 first FROZEN, *unfitted* physical near-surface inversion candidate.

Not qualified by real 2-m station observations. No artificial model-skill data.
ERA5 cloud cover is only a longwave-cooling PROXY, not observed radiative flux;
the terrain/cold-pool index MUST originate from independent DEM morphology.
The optional site profile measures INVERSIONS, not a deployable input.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

MODEL_ID="P9H23_PREDECLARED_V0_NONPRODUCTION_20261017"
MAX_COLD_POOL_CORRECTION_C=1.25
WIND_MIXING_SCALE_MS=3.0
CLOUD_CLEAR_SKY_EXPONENT=1.5
SNOW_FACTOR=1.20
SITE_BASELINE_LAPSE_K_PER_M=-0.0065


def clamp(x:float,lo:float=0,hi:float=1)->float:
    return min(hi,max(lo,x))


def solar_altitude_degrees(stamp:dt.datetime, latitude_deg:float,
                           longitude_deg:float)->float:
    """NOAA approximate geometric sun altitude, no atmospheric refraction.

    UTC date+time mandatory. Error near the exact horizon changes transitions;
    below -3 degrees is required for active inversion conditions.
    """
    if stamp.tzinfo is None or stamp.utcoffset()!=dt.timedelta(0):
        raise ValueError("P9H23_SOLAR_REQUIRES_UTC_DATETIME")
    if not (-90<=latitude_deg<=90 and -180<=longitude_deg<=180):
        raise ValueError("P9H23_UNREGISTERED_SOLAR_LOCATION")
    doy=stamp.timetuple().tm_yday
    hours=stamp.hour+stamp.minute/60+stamp.second/3600
    gamma=2*math.pi/365*(doy-1+(hours-12)/24)
    eqtime=229.18*(.000075+.001868*math.cos(gamma)-.032077*math.sin(gamma)
                    -.014615*math.cos(2*gamma)-.040849*math.sin(2*gamma))
    decl=(.006918-.399912*math.cos(gamma)+.070257*math.sin(gamma)
          -.006758*math.cos(2*gamma)+.000907*math.sin(2*gamma)
          -.002697*math.cos(3*gamma)+.00148*math.sin(3*gamma))
    true_minutes=(hours*60+eqtime+4*longitude_deg)%1440
    ha=math.radians(true_minutes/4-180)
    phi=math.radians(latitude_deg)
    sin_h=math.sin(phi)*math.sin(decl)+math.cos(phi)*math.cos(decl)*math.cos(ha)
    return math.degrees(math.asin(clamp(sin_h,-1,1)))


@dataclass(frozen=True)
class State:
    timestamp_utc:dt.datetime
    latitude_deg:float
    longitude_deg:float
    cloud_cover_percent:float|None
    wind_speed_10m_ms:float|None
    terrain_cold_pool_index:float|None
    independently_verified_snow_cover:bool|None=None


@dataclass(frozen=True)
class Candidate:
    id:str
    baseline_temperature_c:float
    corrected_temperature_c:float
    correction_c:float
    nighttime:bool
    inversion_risk_proxy:float|None
    status:str
    snow_contribution_verified:bool


def evaluate(state:State, baseline_temperature_c:float)->Candidate:
    """One physically monotonic exploratory candidate, no feature tuning.

    Requires external documented ERA5 cloud and wind, DEM terrain index.
    Missing source -> exactly the baseline, never fabricate an input.
    """
    if not math.isfinite(baseline_temperature_c) or not -90<baseline_temperature_c<65:
        raise ValueError("P9H23_BASELINE_TEMPERATURE_NONPHYSICAL")
    solar_h=solar_altitude_degrees(state.timestamp_utc,state.latitude_deg,state.longitude_deg)
    nighttime=solar_h<=-3
    vars_=(state.cloud_cover_percent,state.wind_speed_10m_ms,state.terrain_cold_pool_index)
    if any(v is None for v in vars_):
        return Candidate(MODEL_ID,baseline_temperature_c,baseline_temperature_c,0.,
                         nighttime,None,"MISSING_SOURCE_BACKOFF",False)
    cloud,wind,terrain=vars_
    if not all(math.isfinite(v) for v in (cloud,wind,terrain)) or not (
        0<=cloud<=100 and 0<=wind<=75 and 0<=terrain<=1
    ):
        raise ValueError("P9H23_SOURCE_FEATURE_UNITS_RANGE_INVALID")
    if not nighttime:
        return Candidate(MODEL_ID,baseline_temperature_c,baseline_temperature_c,0.,
                         False,0.,"DAYLIGHT_BACKOFF",False)
    if terrain==0:
        return Candidate(MODEL_ID,baseline_temperature_c,baseline_temperature_c,0.,
                         True,0.,"NO_DEM_COLD_POOL_SIGNAL_BACKOFF",False)
    cloud_cooling_proxy=(1-cloud/100)**CLOUD_CLEAR_SKY_EXPONENT
    mixed_wind_weight=1/(1+(wind/WIND_MIXING_SCALE_MS)**2)
    proxy=clamp(cloud_cooling_proxy*mixed_wind_weight)
    snow_verified=state.independently_verified_snow_cover is not None
    multiplier=SNOW_FACTOR if state.independently_verified_snow_cover is True else 1.
    correction=-min(MAX_COLD_POOL_CORRECTION_C,
                    MAX_COLD_POOL_CORRECTION_C*proxy*terrain*multiplier)
    status=("SOURCE_CONDITIONED_EXPERIMENTAL_NOT_VALIDATED"
            if snow_verified else "SNOW_UNAVAILABLE_EXPERIMENTAL_NOT_VALIDATED")
    return Candidate(MODEL_ID,baseline_temperature_c,baseline_temperature_c+correction,
                     correction,True,proxy,status,snow_verified)


def baselines(raw_era5_c:float,regular_grid_height_m:float,site_height_m:float,
              provider_altitude_c:float|None)->dict:
    """B0, B1, B2; provider always kept as externally sourced, no reverse engineering."""
    vals=(raw_era5_c,regular_grid_height_m,site_height_m)
    if not all(math.isfinite(v) for v in vals) or not -90<raw_era5_c<65:
        raise ValueError("P9H23_INVALID_SOURCE_OROGRAPHY")
    if provider_altitude_c is not None and not math.isfinite(provider_altitude_c):
        raise ValueError("P9H23_PROVIDER_DATA_NOT_FINITE")
    return {"B0_raw_ERA5_C":raw_era5_c,
            "B1_native_grid_fixed_lapse_C":
                raw_era5_c+SITE_BASELINE_LAPSE_K_PER_M*(site_height_m-regular_grid_height_m),
            "B2_provider_altitude_C":provider_altitude_c,
            "provider_B2_must_remain_separate_black_box":True}


def single_site_scores(original_observed_2m:dict, candidates:dict)->dict:
    """Scores original paired obs only; caller MUST supply independent QC and provenance.

    No 4.2m forest tower record treated as a 2m target. No extrapolation or
    missing-hour interpolation. The final holdout remains unread.
    """
    results={}
    for label,pred in candidates.items():
        paired=[(float(original_observed_2m[t]),float(pred[t]))
                for t in original_observed_2m.keys() & pred.keys()
                if original_observed_2m[t] is not None and pred[t] is not None]
        if not paired:
            results[label]={"source_qualified":False,"reason":"NO_PAIR"}
            continue
        errors=[p-o for o,p in paired]
        results[label]={"N_real_pairs":len(errors),
                        "MAE_C":sum(abs(x) for x in errors)/len(errors),
                        "bias_C":sum(errors)/len(errors),
                        "RMSE_C":math.sqrt(sum(x*x for x in errors)/len(errors)),
                        "site_source_QC_must_be_independently_authenticated":True}
    return results
