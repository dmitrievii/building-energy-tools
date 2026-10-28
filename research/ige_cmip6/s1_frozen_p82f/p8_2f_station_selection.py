#!/usr/bin/env python3
"""IGE P8.2F: station metadata/coverage donor selection ONLY.

Does not modify P8.2E physics, reconciliation, IDW weighting or derived RH.
Model inputs must be sourced from other stations; target values used for scoring only.
"""
from __future__ import annotations
import math
import calendar
from p8_2e_crossyear import haversine

REQUIRED_FIELDS = ('T', 'P', 'e', 'RH')
DEFAULT_NEAREST_METADATA = 20  # search window, not a fitted parameter
DEFAULT_DONORS = 4


def metadata_candidates(metadata, targets, original_pool, nearest_count=DEFAULT_NEAREST_METADATA):
    """All Swiss metadata ranked per site; fetch nearest K + original control donors.

    The original station list is always included so the reference is reproducible.
    Candidate discovery uses ONLY coordinates and station identifiers.
    """
    if nearest_count < DEFAULT_DONORS:
        raise ValueError('Search window smaller than requested donor set')
    per_site = {}
    union = set(original_pool)
    for tid in targets:
        if tid not in metadata:
            raise ValueError('Target metadata unavailable: ' + tid)
        target = metadata[tid]
        candidates = sorted(((float(haversine(target['lat'], target['lon'], station['lat'], station['lon'])), sid)
                             for sid, station in metadata.items() if sid != tid),
                            key=lambda row: (row[0], row[1]))
        per_site[tid] = [sid for _, sid in candidates[:nearest_count]]
        union.update(per_site[tid])
        union.add(tid)
    return per_site, sorted(sid for sid in union if sid in metadata)


def coverage(weather, monthly, year, expected_hours=None):
    """Require all physical UTC hours, all measured T/P/e/RH, and all monthly e.

    Counts provider rows separately from complete observations: 8760 rows full
    of missing values are not an eligible annual station. No interpolation.
    """
    if expected_hours is None:
        expected_hours = 8784 if calendar.isleap(year) else 8760
    weather = weather or {}
    monthly = monthly or {}
    complete = sum(all(row.get(key) is not None and math.isfinite(row[key]) for key in REQUIRED_FIELDS)
                   for row in weather.values())
    months = sum(monthly.get(f'{year}-{m:02d}', {}).get('e') is not None and
                 math.isfinite(monthly[f'{year}-{m:02d}']['e']) and
                 monthly[f'{year}-{m:02d}']['e'] > 0
                 for m in range(1, 13))
    is_complete = len(weather) == expected_hours and complete == expected_hours and months == 12
    return {'n_hour_rows': len(weather), 'n_hour_complete_TPeRH': complete,
            'n_monthly_e': months, 'eligible_complete': bool(is_complete)}


def closest_eligible_donors(target, metadata, qualified, excluded_target, n_donors=DEFAULT_DONORS):
    """Select nearest completely observed external stations; preserve physical distance.

    No station observations are read here. Original 1/d² model weights and
    elevation corrections in P8.2E remain unchanged.
    """
    if excluded_target != target['station_id']:
        raise AssertionError('Target identity mismatch')
    available = [(float(haversine(target['lat'], target['lon'], station['lat'], station['lon'])), station)
                 for sid, station in metadata.items() if sid in qualified and sid != excluded_target]
    ranked = sorted(available, key=lambda x: (x[0], x[1]['station_id']))
    if len(ranked) < n_donors:
        raise ValueError(f'Only {len(ranked)} complete independent candidate stations')
    return ranked[:n_donors]


def physical_donor_distance_report(target, donors):
    return [{'station': station['station_id'], 'distance_km': round(d, 3),
             'target_height_m': float(target['hoehe_m']),
             'donor_height_m': float(station['hoehe_m']),
             'height_difference_m': round(float(station['hoehe_m']-target['hoehe_m']), 3)}
            for d, station in donors]