#!/usr/bin/env python3
"""IGE P9.1H regional-only research cohort guard, 2022 AT/DE/CH.

This is a hard safety and provenance boundary for H research, not a change to
the general IGE engine's ability to generate climates at arbitrary sites.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

ALLOWED_COUNTRIES=frozenset(("AT","DE","CH"))
ALLOWED_DAYS=frozenset(
    (dt.date(2022,month,10)+dt.timedelta(days=day)).isoformat()
    for month in (1,7) for day in range(7))
MAX_SITES_COUNTRY=3

def qualification_scope(country:str,timestamp_utc:str)->tuple[str,str]:
    if country not in ALLOWED_COUNTRIES:
        raise ValueError("P9H_REGIONAL_ONLY_COUNTRY_NOT_AT_DE_CH")
    stamp=dt.datetime.fromisoformat(timestamp_utc.replace("Z","+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset()!=dt.timedelta(0):
        raise ValueError("P9H_REGIONAL_HOURLY_TIMESTAMP_MUST_BE_UTC")
    if stamp.date().isoformat() not in ALLOWED_DAYS:
        raise ValueError("P9H_FROZEN_2022_COUNTRY_SEASON_WINDOW_VIOLATION")
    return country,stamp.isoformat()

def validate_manifest(data:dict)->bool:
    if data.get("phase")!="IGE_P9_1H_AT_DE_CH_FROZEN_REGIONAL_ONLY":
        raise ValueError("P9H_REGIONAL_MANIFEST_MISSING_OR_WRONG")
    if set(data.get("allowed_country_codes",[]))!=ALLOWED_COUNTRIES:
        raise ValueError("P9H_COUNTRY_LIST_NOT_LOCKED")
    if data.get("max_stations_per_country")!=MAX_SITES_COUNTRY:
        raise ValueError("P9H_TOO_MANY_SITES")
    if data.get("no_2021_Nordic_holdout_read") is not True:
        raise ValueError("P9H_2021_HOLDOUT_GUARD_NOT_FROZEN")
    if data.get("no_other_country_data_fetch") is not True:
        raise ValueError("P9H_GLOBAL_BENCHMARK_LEAKAGE")
    if not all(data["claims"][k] is False for k in (
        "regional_AT_DE_CH_qualified","near_surface_inversion_model_qualified",
        "global_arbitrary_point_weather_qualified","production_epw_ready")):
        raise ValueError("P9H_PREMATURE_QUALIFICATION_CLAIM")
    return True

def read_manifest():
    return json.loads(Path(__file__).with_name("p9_1h_regional_at_de_ch_2022_scope.json").read_text())
