"""Opt-in experimental recovery of missing H1 observations for fixed S1 references."""
from dataclasses import replace
import gzip
import io

import numpy as np
import pandas as pd

from .engine.point_interpolation import T, RH, P, E, distance_km, saturation_buck_hpa

GAP_POLICY = "PEER_ANOMALY_MASKED_WINDOWS_V1"
FIELDS = (T, RH, P)
MAX_GAP_HOURS = 72
LIMITS = {T: (1.5, 4.0), RH: (8.0, 20.0), P: (100.0, 300.0)}
BOUNDS = {T: (-75., 65.), RH: (0., 100.), P: (30000., 115000.)}


def _eligible(donor):
    return (donor.source_kind == "GEOSPHERE_H1_ENDPOINTS_BUCK_RH_ASSUMPTION"
            and bool(donor.source_admission) and not donor.source_admission["global_blockers"]
            and set(donor.blockers) <= {"H1_CORE_NOT_ADMITTED_"+k for k in FIELDS})


def _missing(donor):
    n = len(donor.data)
    ledger = pd.read_csv(io.BytesIO(gzip.decompress(donor.source_gaps_csv_gz)))
    masks = {k: np.zeros(n, dtype=bool) for k in FIELDS}
    for row in ledger.itertuples(index=False):
        if row.field not in masks:
            continue
        if row.reason != "MISSING_VALUE":
            raise ValueError("NON_MISSING_SOURCE_REJECTION")
        i = donor.data.index.get_loc(pd.Timestamp(row.first_interval_start_utc))
        j = donor.data.index.get_loc(pd.Timestamp(row.last_interval_start_utc))
        if j-i+1 != row.hours:
            raise ValueError("GAP_LEDGER_HOUR_MISMATCH")
        masks[row.field][i:j+1] = True
    for k in FIELDS:
        if not np.array_equal(masks[k], ~np.isfinite(donor.data[k].to_numpy(float))):
            raise ValueError("GAP_LEDGER_DATA_MISMATCH")
    return masks


def _episode(values, peer, mask, start, n):
    # Interpolate only the local-minus-peer offset between observed anchors.
    # Peer hourly anomalies are retained inside the missing period.
    f = {k: values[k][start:start+n].copy() for k in FIELDS}
    def predict(local, series):
        left, right = start-1, start+n
        if not np.isfinite(local[[left, right]]).all() or not np.isfinite(series[left:right+1]).all():
            raise ValueError("MISSING_ANCHOR_OR_PEER_OBSERVATION")
        fraction = np.arange(1, n+1)/(n+1)
        return series[start:right] + (1-fraction)*(local[left]-series[left]) + fraction*(local[right]-series[right])
    for k in (T, P):
        if mask[k].any():
            f[k][mask[k]] = predict(values[k], peer[k])[mask[k]]
    if mask[RH].any():
        vapour = predict(values[E], peer[E])
        t = f[T][mask[RH]]
        f[RH][mask[RH]] = 100*vapour[mask[RH]]/saturation_buck_hpa(t)
    for k in FIELDS:
        v = f[k][mask[k]]
        lo, hi = BOUNDS[k]
        if not np.isfinite(v).all() or (v < lo).any() or (v > hi).any():
            raise ValueError(f"RECONSTRUCTION_OUTSIDE_PHYSICAL_BOUNDS {k}: {float(np.min(v)):.6g} to {float(np.max(v)):.6g}")
    return f


def _validate(values, peer, mask, start, n):
    # Use disjoint complete windows at the same UTC hour within ±45 days.
    used = []
    errs = {k: [] for k in FIELDS if mask[k].any()}
    for offset in (sign*d*24 for d in range(1,46) for sign in (-1,1)):
        i = start+offset
        if i < 1 or i+n >= len(values[T]):
            continue
        if any(abs(i-j) <= n+1 for j in [start, *used]):
            continue
        if not all(np.isfinite(values[k][i-1:i+n+1]).all() for k in FIELDS):
            continue
        # Invalid predictions are failures, not selectively dropped controls.
        try:
            trial = _episode(values, peer, mask, i, n)
        except ValueError as exc:
            if str(exc) == "MISSING_ANCHOR_OR_PEER_OBSERVATION":
                continue
            raise
        for k in errs:
            errs[k].extend(np.abs(trial[k][mask[k]] - values[k][i:i+n][mask[k]]))
        used.append(i)
        if len(used) == 12:
            break
    metrics = {k: {"MAE": float(np.mean(v)), "max_abs": float(np.max(v))}
               for k,v in errs.items() if v}
    passed = (len(used) >= 8 and any(i < start for i in used) and any(i > start for i in used)
              and all(m["MAE"] <= LIMITS[k][0] and m["max_abs"] <= LIMITS[k][1] for k,m in metrics.items()))
    return passed, metrics, used


def recover_station_gaps(donors):
    """Return derived donors plus diagnostics; original station packets stay unchanged."""
    if len(donors) != 4 or len({d.station_id for d in donors}) != 4:
        return donors, {"policy": GAP_POLICY, "status": "FOUR_ORIGINAL_DONORS_REQUIRED", "stations": []}
    output, audit = [], []
    for target in donors:
        if not target.blockers:
            output.append(target)
            continue
        row = {"station_id": target.station_id, "episodes": []}
        audit.append(row)
        try:
            if not all(_eligible(d) and d.data.index.equals(target.data.index) for d in donors):
                raise ValueError("INELIGIBLE_OR_MISALIGNED_ORIGINAL_DONOR")
            masks = _missing(target)
            peers = [d for d in donors if d is not target]
            for d in peers: _missing(d)
            combined = np.logical_or.reduce(list(masks.values()))
            positions = np.flatnonzero(combined)
            if not len(positions) or len(positions) > len(combined)//100:
                raise ValueError("ANNUAL_MISSING_HOUR_BUDGET")
            weights = np.array([1/max(1.,distance_km(target.location.latitude,target.location.longitude,
                d.location.latitude,d.location.longitude))**2 for d in peers])
            weights /= weights.sum()
            peer = {k: np.sum(weights[:,None]*np.stack([d.data[k].to_numpy(float) for d in peers]),axis=0)
                    for k in (*FIELDS,E)}
            values = {k: target.data[k].to_numpy(float) for k in (*FIELDS,E)}
            frame = target.data.copy()
            for group in np.split(positions, np.flatnonzero(np.diff(positions)!=1)+1):
                start, n = int(group[0]), len(group)
                if start < 1 or start+n >= len(combined) or n > MAX_GAP_HOURS:
                    raise ValueError("GAP_TOO_LONG_OR_UNBRACKETED")
                mask = {k: masks[k][start:start+n] for k in FIELDS}
                estimates = _episode(values,peer,mask,start,n)
                passed, metrics, windows = _validate(values,peer,mask,start,n)
                episode = {"first_utc": frame.index[start].isoformat(), "hours": n, "validation": metrics,
                    "validation_windows_utc": [frame.index[i].isoformat() for i in windows], "accepted": passed}
                row["episodes"].append(episode)
                if not passed:
                    raise ValueError("MASKED_WINDOW_ACCURACY_GATE")
                for k in FIELDS:
                    ix = frame.index[group[mask[k]]]
                    frame.loc[ix,k] = estimates[k][mask[k]]
                episode["estimated_values"] = {k: [{"utc":frame.index[i].isoformat(),"value":float(frame[k].iloc[i])}
                    for i in group[mask[k]]] for k in FIELDS if mask[k].any()}
            changed = masks[T] | masks[RH]
            frame.loc[changed,E] = frame.loc[changed,RH]/100*saturation_buck_hpa(frame.loc[changed,T])
            row["status"] = "RECONSTRUCTED_NOT_OBSERVED"
            output.append(replace(target, data=frame, blockers=()))
        except ValueError as exc:
            row["status"] = "BLOCKED"
            row["reason"] = str(exc)
            output.append(target)
    return output, {"policy": GAP_POLICY, "status": "ASSESSED", "stations": audit}
