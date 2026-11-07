"""Synthetic spatial fields; no figures in these fixtures are weather evidence."""
from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ige_local.common import UTC, digest, file_hash, iso, read_json, write_json
from ige_auto.config import data_signature, load
from ige_auto.data import ALL_VARIABLES, Cube, buck_water, choose_and_split


def config(base, models=None):
    base = Path(base); (base/"Database").mkdir(parents=True, exist_ok=True)
    p = base/"ClimateExperiments"/"config_auto.json"; p.parent.mkdir(parents=True, exist_ok=True)
    c = read_json(ROOT/"config_auto_regression.json")
    c.update(countries=["AT"], variables=["T"], years={"D": [2020], "V": [2023], "C": [2025]},
             sample_days_per_month=1, sites_per_country=15, cases_per_partition=180, memory_budget_bytes=256*1024**2)
    c["models"] = models or [c["models"][0], c["models"][2]]
    c["optimizer"].update(max_evaluations=160, max_iterations=20, starts=1, min_fit_cases=20, wall_seconds_per_model=30)
    write_json(p, c)
    return load(p)


def save_cube(path, meta, arrays):
    path = Path(path); path.mkdir(parents=True, exist_ok=True)
    meta = copy.deepcopy(meta); meta.pop("cube_id", None)
    meta["array_hashes"] = {}
    for n, a in arrays.items():
        np.save(path/(n+".npy"), a, allow_pickle=False)
        meta["array_hashes"][n+".npy"] = file_hash(path/(n+".npy"))
    meta["cube_id"] = digest(meta); write_json(path/"metadata.json", meta)
    return Cube(path)


def synthetic_cube(base, c, seasonal=False, missing=True):
    rng = np.random.default_rng(193)
    stations = []
    for i in range(15):
        stations.append({"key": "AT:test:"+str(i), "country": "AT", "station_id": str(i), "network": "",
                         "name": "SYNTHETIC "+str(i), "family": "AT:family:"+str(i), "station_type": "INDIVIDUAL",
                         "lat": float(46.5+rng.random()), "lon": float(13.+rng.random()*3),
                         "height_m": float(100+rng.random()*1800)})
    mapping = {s["key"]: s for s in stations}
    keys, roles, folds, notes = choose_and_split(mapping, set(mapping), c)
    stations = [mapping[k] for k in keys]
    times = [iso(dt.datetime(year, month, 15, h, tzinfo=UTC)) for year in (2020, 2023, 2025) for month in range(1, 13) for h in range(24)]
    shape = (len(stations), len(times), 4)
    values = np.full(shape, np.nan)
    for s, st in enumerate(stations):
        z = st["height_m"]/1000
        for h in range(len(times)):
            month = h//24 % 12+1
            gamma = -7.3 if not seasonal else -4.-.3*month
            values[s, h, 0] = 15+10*np.sin(month*np.pi/6)+np.sin(h % 24*np.pi/12)+gamma*z
            values[s, h, 1] = 65-2.5*z+5*np.sin(h % 24*np.pi/12)
            values[s, h, 2] = 1020-95*z+np.cos(h % 24*np.pi/12)
            values[s, h, 3] = np.log(values[s, h, 1]*buck_water(values[s, h, 0])/100)
    eligible = np.ones(shape, dtype=bool)
    if missing:
        for s in range(len(stations)):
            values[s, s::19, 0] = np.nan; eligible[s, s::19, 0] = False
            values[s, (s+2)::29, 2] = np.nan; eligible[s, (s+2)::29, 2] = False
    arrays = {"values": values, "eligible": eligible,
              "operators": np.broadcast_to(np.arange(1, 5), shape).astype(np.int32).copy(),
              "qc": np.ones(shape, dtype=np.int32), "sources": np.ones(shape, dtype=np.int32)}
    meta = {"schema": "IGE_AUTO_CUBE_v1", "fixture": "SYNTHETIC_NOT_OBSERVATIONS", "stations": stations,
            "times": times, "variables": ALL_VARIABLES, "array_shape": list(shape), "data_signature": data_signature(c),
            "time_roles": ["D"]*288+["V"]*288+["C"]*288, "family_roles": roles, "inner_folds": folds,
            "qc_codebook": [{"stratum": "unknown"}, {"stratum": "automatic_original"}],
            "operator_codebook": ["unknown", "test:T", "test:RH", "test:p", "test:log_e_water"],
            "source_codebook": [{"status": "none"}, {"status": "SYNTHETIC"}], "notes": notes, "source_errors": []}
    return save_cube(Path(base)/"cube", meta, arrays)
