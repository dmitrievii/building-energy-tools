#!/usr/bin/env python3
"""IGE P7B.3B: independent Meteonorm 8.2 TAG-informed M0/M1 GHI benchmark.

NOT an exact Meteonorm implementation. See accompanying science protocol.
No fitting to the GeoSphere 2012-14 validation observations. Research only.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean

from p7b3_observed_hourly_solar import (
    groups_hours, paired_metrics, percentile, select_observations,
)

SEASONS = {
    "DJF": (12, 1, 2), "MAM": (3, 4, 5),
    "JJA": (6, 7, 8), "SON": (9, 10, 11),
}


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tag_coeff(kt):
    """Published Meteonorm v8.2 handbook 7.6.10 parameters, dimensionless."""
    kt = min(1., max(0., kt))
    phi = .148 + 2.356 * kt - 5.195 * kt**2 + 3.758 * kt**3
    sigma = .32 * math.exp(-50. * (kt - .4)**2) + .002
    return phi, sigma


def exact_bounded_daily_scale(raw, target, caps):
    """IGE-specific bounded projection; daily GHI unchanged, no GHI > TOA."""
    if len(raw) != len(caps) or not raw:
        raise ValueError("non-conforming daily vectors")
    if any(not math.isfinite(v) or v < 0 for v in raw + caps):
        raise ValueError("unphysical generation input")
    if not 0 <= target <= sum(caps) + 1e-9:
        raise ValueError("daily energy cannot be physically assigned")
    if target == 0:
        return [0.] * len(raw)
    w = [max(v, 1e-10 * cap) if cap > 0 else 0.
         for v, cap in zip(raw, caps)]
    upper = 1.
    while sum(min(cap, upper * v) for v, cap in zip(w, caps)) < target:
        upper *= 2
        if upper > 1e15:
            raise ValueError("cannot bracket exact daily scale")
    lower = 0.
    for _ in range(66):
        middle = (lower + upper) / 2
        if sum(min(cap, middle * v) for v, cap in zip(w, caps)) < target:
            lower = middle
        else:
            upper = middle
    out = [min(cap, upper * v) for v, cap in zip(w, caps)]
    if abs(sum(out) - target) > 1e-9:
        raise ValueError("daily energy closure lost")
    return out


def tag_day(day, ghis, toas, seed):
    """Handbook phi/sigma and 2*phi AR; own baseline and bounds."""
    if len(ghis) != 24 or len(toas) != 24:
        raise ValueError("24 source hours required")
    target = sum(ghis)
    if target <= 0:
        return [0.] * 24
    total_toa = sum(toas)
    if total_toa <= 0:
        raise ValueError("no daylight for nonzero GHI")
    phi, sigma = tag_coeff(target / total_toa)
    innovation_sigma = sigma * math.sqrt(max(0., 1 - phi**2))
    rng_seed = int.from_bytes(
        hashlib.sha256(f"{seed}:{day}".encode()).digest()[:8], "big")
    rng = random.Random(rng_seed)
    y = 0.
    candidate = []
    for ghi, toa in zip(ghis, toas):
        if toa <= 0:
            y = 0.
            candidate.append(0.)
            continue
        # Ref: Meteonorm 8.2 Theory Eq. 7.6.10 and 7.6.11.
        y = 2 * phi * y + rng.gauss(0., innovation_sigma)
        # Source GHI/TOA substitutes missing ESRA/Solis clear-sky profile.
        candidate.append(toa * min(1., max(0., ghi / toa + y)))
    return exact_bounded_daily_scale(candidate, target, toas)


def load_p7b2(path):
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            dt = datetime.fromisoformat(r["local_hour"]).replace(tzinfo=None)
            ghi = float(r["ghi_Wh"]) / 1000.
            toa = max(0., float(r["toa_horizontal_Wh"]) / 1000.)
            if not math.isfinite(ghi + toa) or ghi < 0 or ghi > toa + 1e-4:
                raise ValueError("source GHI/TOA physical violation")
            if rows and dt - rows[-1][0] != timedelta(hours=1):
                raise ValueError("model calendar gap")
            rows.append((dt, ghi, toa))
    if len(rows) != 8760 or rows[0][0] != datetime(2013, 1, 1):
        raise ValueError("must use the immutable P7B.2 2013 source")
    return rows


def generate(source, seed):
    result = []
    daily_max_error = 0.
    for idx in range(365):
        day = source[24 * idx:24 * (idx + 1)]
        if len({dt.date() for dt, _, _ in day}) != 1:
            raise ValueError("broken day boundaries")
        ghis = [ghi for _, ghi, _ in day]
        toas = [toa for _, _, toa in day]
        values = tag_day(day[0][0].date().isoformat(), ghis, toas, seed)
        daily_max_error = max(daily_max_error, abs(sum(values) - sum(ghis)))
        result.extend((dt, val) for (dt, _, _), val in zip(day, values))
    return result, daily_max_error


def seasonal_deltas(records, months):
    pairs = []
    sequence = sorted(records.items())
    for (a, x), (b, y) in zip(sequence, sequence[1:]):
        if (b - a == timedelta(hours=1) and a.month in months and
                b.month in months and 8 <= a.hour <= 17 and 8 <= b.hour <= 17):
            pairs.append(abs(y - x))
    return pairs


def scores(obs, synthetic):
    profile, full, daylight = paired_metrics(
        groups_hours(obs), groups_hours(synthetic))
    if daylight["cells"] < 120:
        raise ValueError("insufficient monthly-hour daytime climatology cells")
    res = {
        "climatological_daylight_month_hour_mae": daylight["mae_kwh_m2_hour"],
        "daylight_month_hour_cells": daylight["cells"],
    }
    for s, months in SEASONS.items():
        ground = seasonal_deltas(obs, months)
        generated = seasonal_deltas(synthetic, months)
        if not ground or not generated:
            raise ValueError("empty seasonal hourly deltas")
        res[s + "_ground_p95_delta"] = percentile(ground, .95)
        res[s + "_generated_p95_delta"] = percentile(generated, .95)
        res[s + "_abs_p95_delta_error"] = abs(
            res[s + "_ground_p95_delta"] - res[s + "_generated_p95_delta"])
        res[s + "_ground_delta_pairs"] = len(ground)
    return res


def run(model_csv, geo_csv, output, seeds=20):
    if not 2 <= seeds <= 100:
        raise ValueError("seed ensemble size must be between 2 and 100")
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    source = load_p7b2(model_csv)
    baseline = {dt: ghi for dt, ghi, _ in source}
    realizations = [generate(source, seed) for seed in range(seeds)]
    audits = []
    report = {}
    for window in ("record_start", "record_end"):
        observed, qc = select_observations(geo_csv, window)
        base = scores(observed, baseline)
        runs = []
        for seed, (generated, conservation) in enumerate(realizations):
            result = scores(observed, dict(generated))
            result.update({"window": window, "method": "M1",
                           "seed": seed, "maximum_daily_energy_residual": conservation})
            runs.append(result)
            audits.append(result)
        audits.append({**base, "window": window, "method": "M0", "seed": ""})
        report[window] = {
            "qc_original_station_hours": len(observed),
            "M0": base,
            "M1_mean_daylight_mae": fmean(
                r["climatological_daylight_month_hour_mae"] for r in runs),
            "M1_mean_p95_delta_by_season": {
                s: fmean(r[s + "_generated_p95_delta"] for r in runs)
                for s in SEASONS},
            "M1_max_daily_energy_residual": max(
                r["maximum_daily_energy_residual"] for r in runs),
        }
    fields = sorted(set().union(*(r.keys() for r in audits)))
    with (out / "p7b3b_method_scores.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(audits)
    with (out / "p7b3b_m1_seed0_solar.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["local_hour", "M0_GHI_kWh_m2_hour",
                    "M1_GHI_kWh_m2_hour", "TOA_kWh_m2_hour"])
        for (dt, base, toa), (_, gen) in zip(source, realizations[0][0]):
            w.writerow([dt.isoformat(), base, gen, toa])
    science = {
        "stage": "P7B.3B", "method": "M1_INDEPENDENT_TAG_INSPIRED",
        "not_exact_meteonorm": True, "production_ready": False,
        "observations_used_for_training_M1": False,
        "observational_comparison_dates_unpaired_to_model_weather": True,
        "station_duplication_excluded": True,
        "qc0_diffuse_not_used": True,
        "two_timestamp_hypotheses": ["record_start", "record_end"],
        "method_caveats": [
            "Daily clearness uses extraterrestrial energy instead of full ESRA/Solis reference",
            "M0 source hourly GHI/TOA substitutes for original clear-sky baseline",
            "Physical cap uses TOA instead of Meteonorm's 110 percent clear-sky cap",
            "IGE bisection conserves daily energy rather than Meteonorm regeneration",
            "Only one GCM year vs 2012-2014 observations; holdout previously consulted",
            "No validation of hourly DHI, DNI or future climate signal"],
        "seed_count": seeds,
        "source_sha256": {"p7b2_hourly": file_sha(model_csv),
                          "geosphere_original_hourly": file_sha(geo_csv)},
        "results": report,
        "derived_sha256": {
            n: file_sha(out / n) for n in
            ("p7b3b_method_scores.csv", "p7b3b_m1_seed0_solar.csv")},
    }
    (out / "p7b3b_science_audit.json").write_text(
        json.dumps(science, indent=2) + "\n", encoding="utf-8")
    return science


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p7b2-hourly", required=True)
    parser.add_argument("--geosphere-hourly", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seeds", type=int, default=20)
    args = parser.parse_args()
    answer = run(args.p7b2_hourly, args.geosphere_hourly, args.out, args.seeds)
    print(json.dumps(answer["results"], indent=2))
