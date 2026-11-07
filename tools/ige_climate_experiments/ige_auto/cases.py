"""Synchronous spatial contrasts. Sampling and donor pools never depend on errors."""
from __future__ import annotations

import collections
import math

import numpy as np

from ige_local.common import InputError, digest, distance
from .data import rank_key


def feature_names(basis):
    return {"height": ["height"],
            "seasonal_height": ["height_DJF", "height_MAM", "height_JJA", "height_SON"],
            "monthly_height": ["height_month_%02d" % m for m in range(1, 13)],
            "harmonic_height": ["height", "height_sin_year", "height_cos_year"],
            "height_geo": ["height", "east", "north"],
            "seasonal_geo": ["height_DJF", "height_MAM", "height_JJA", "height_SON", "east", "north"]}[basis]


def sample_grid(cube, panels, cap, seed):
    """Equal quotas per station/month, chosen before consulting observations."""
    groups = collections.defaultdict(set)
    population = 0
    for stations, times in panels:
        population += len(stations)*len(times)
        for s in stations:
            for t in times:
                groups[(int(s), int(cube.month[t]))].add(int(t))
    keys = sorted(groups, key=lambda k: rank_key(seed, cube.stations[k[0]]["key"], k[1]))
    ordered = {}
    for k in keys:
        ts = sorted(groups[k])
        # A seeded cyclic walk avoids an enormous list of timestamp hashes.
        n = len(ts); start = int(rank_key(seed, *k, "offset")[:12], 16) % n
        step = max(1, int(rank_key(seed, *k, "stride")[:12], 16) % n)
        while math.gcd(step, n) != 1:
            step += 1
        ordered[k] = [ts[(start+i*step) % n] for i in range(n)]
    rows = []
    level = 0
    while len(rows) < cap:
        added = False
        for k in keys:
            if level < len(ordered[k]):
                rows.append((k[0], ordered[k][level])); added = True
                if len(rows) == cap:
                    break
        if not added:
            break
        level += 1
    rows.sort()
    return np.array(rows, dtype=np.int64).reshape((-1, 2)), population


class Cases:
    def __init__(self, cube, panels, donors, variable, c, label):
        self.label = label; self.variable = variable; self.cube = cube
        rows, population = sample_grid(cube, panels, c["cases_per_partition"], c["split_seed"])
        self.s, self.t = rows[:, 0], rows[:, 1]
        self.d = np.asarray(sorted(set(map(int, donors))), dtype=int)
        estimate = max(1, len(rows))*max(1, len(self.d))*96
        if estimate > c["memory_budget_bytes"]//(c["workers"]*8):
            raise InputError("Case matrix exceeds per-worker memory allocation: " + label)
        self.population = population
        self.month = cube.month[self.t]; self.phase = cube.phase[self.t]
        self.country = np.array([cube.stations[s]["country"] for s in self.s])
        self.station = np.array([cube.stations[s]["key"] for s in self.s])
        v = cube.meta["variables"].index(variable)
        self.y = np.asarray(cube.values[self.s, self.t, v]).copy()
        self.obs = np.asarray(cube.eligible[self.s, self.t, v]) & np.isfinite(self.y)
        self.target_qc = np.asarray(cube.qc[self.s, self.t, v])
        self.target_op = np.asarray(cube.operators[self.s, self.t, v])
        self.dv = np.asarray(cube.values[self.d[None, :], self.t[:, None], v]).copy()
        self.donor_qc = np.asarray(cube.qc[self.d[None, :], self.t[:, None], v])
        dop = np.asarray(cube.operators[self.d[None, :], self.t[:, None], v])
        self.mask = (np.asarray(cube.eligible[self.d[None, :], self.t[:, None], v])
                     & np.isfinite(self.dv) & (dop == self.target_op[:, None]) & (dop != 0))
        geom = {}; dxy = {}; dz = {}
        for s in sorted(set(map(int, self.s))):
            a = cube.stations[s]
            geom[s] = np.array([distance(a, cube.stations[d]) for d in self.d])
            dxy[s] = np.array([[(a["lon"]-cube.stations[d]["lon"])*111.19508*math.cos(math.radians((a["lat"]+cube.stations[d]["lat"])/2)),
                               (a["lat"]-cube.stations[d]["lat"])*111.19508] for d in self.d]).reshape((-1, 2))
            dz[s] = np.array([(a["height_m"]-cube.stations[d]["height_m"])/1000 for d in self.d])
            same = np.array([a["family"] == cube.stations[d]["family"] or a["country"] != cube.stations[d]["country"] for d in self.d])
            ix = self.s == s
            self.mask[ix] &= ~same & (geom[s] > max(c["co_location_km"], 1e-9))
        self.dist = np.array([geom[int(s)] for s in self.s]).reshape((len(rows), len(self.d)))
        self.dz = np.array([dz[int(s)] for s in self.s]).reshape(self.dist.shape)
        xy = np.array([dxy[int(s)] for s in self.s]).reshape((len(rows), len(self.d), 2))
        self.dx, self.dy = xy[:, :, 0], xy[:, :, 1]
        # A relocated station/duplicate series is at most one donor per family/hour.
        families = collections.defaultdict(list)
        for j, d in enumerate(self.d):
            families[cube.stations[d]["family"]].append(j)
        for cols in families.values():
            if len(cols) > 1:
                scored = np.where(self.mask[:, cols], self.dist[:, cols], np.inf)
                best = np.argmin(scored, axis=1)
                for j, col in enumerate(cols):
                    self.mask[:, col] &= best == j
        self.dv[~self.mask] = 0
        self.n_donors = self.mask.sum(axis=1)
        self.ready = self.n_donors >= 2
        self.fit_mask = self.ready & self.obs
        self.row_id = [cube.stations[s]["key"] + "|" + cube.times[t] for s, t in rows]
        self.case_id = digest({"label": label, "variable": variable, "rows": self.row_id,
                               "donors": [cube.stations[d]["key"] for d in self.d]})
        self.ledger = {"label": label, "case_id": self.case_id, "population_calendar_cases": population,
                       "sampled_calendar_cases": len(rows), "target_observed": int(self.obs.sum()),
                       "donor_ready_all_calendar": int(self.ready.sum()), "scorable": int(self.fit_mask.sum()),
                       "target_families": sorted({cube.stations[s]["family"] for s in self.s}),
                       "donor_families": sorted(families), "target_years": sorted(set(map(int, cube.years[self.t]))),
                       "min_independent_donors": 2, "sampling": "pre-observation station/month quotas",
                       "sample_is_full_population": len(rows) == population}

    def weights(self, kernel, eta):
        az = np.exp(eta[1])
        r2 = np.maximum(self.dist*self.dist + (az*self.dz)**2, 1e-24)
        if kernel == "idw":
            lw = -.5*eta[0]*np.log(r2)
        else:
            lw = -.5*r2/np.exp(2*eta[0])
        lw = np.where(self.mask, lw, -np.inf)
        top = np.max(lw, axis=1, initial=-np.inf)
        top[~np.isfinite(top)] = 0
        w = np.exp(lw-top[:, None])
        total = w.sum(axis=1)
        return np.divide(w, total[:, None], out=np.zeros_like(w), where=total[:, None] > 0)

    def design(self, basis, kernel, eta):
        w = self.weights(kernel, eta)
        base = np.sum(w*self.dv, axis=1)
        z = np.sum(w*self.dz, axis=1)
        season = (self.month % 12)//3
        if basis in {"seasonal_height", "seasonal_geo"}:
            x = z[:, None]*(season[:, None] == np.arange(4)[None, :])
        elif basis == "monthly_height":
            x = z[:, None]*(self.month[:, None] == np.arange(1, 13)[None, :])
        elif basis == "harmonic_height":
            x = z[:, None]*np.column_stack((np.ones(len(z)), np.sin(self.phase), np.cos(self.phase)))
        else:
            x = z[:, None]
        if basis in {"height_geo", "seasonal_geo"}:
            x = np.column_stack((x, np.sum(w*self.dx, axis=1), np.sum(w*self.dy, axis=1)))
        return base, x, w


def macro_weights(cases, mask, month_balance=True):
    """Equal country, equal station, optionally equal month. No QC confidence weights."""
    ix = np.flatnonzero(mask); w = np.zeros(len(mask))
    if not len(ix):
        return w
    countries = sorted(set(cases.country[ix]))
    for country in countries:
        stations = sorted(set(cases.station[ix[cases.country[ix] == country]]))
        for station in stations:
            s = ix[cases.station[ix] == station]
            months = sorted(set(cases.month[s])) if month_balance else [None]
            for month in months:
                g = s[cases.month[s] == month] if month is not None else s
                w[g] = 1/(len(countries)*len(stations)*len(months)*len(g))
    return w


def role_cases(cube, c, variable, target_role, time_role, donor_roles, label=None):
    return Cases(cube, [(np.flatnonzero(cube.roles == target_role), np.flatnonzero(cube.time_roles == time_role))],
                 np.flatnonzero(np.isin(cube.roles, list(donor_roles))), variable, c, label or target_role+time_role)


def inner_cases(cube, c, variable):
    result = []
    times = np.flatnonzero(cube.time_roles == "D")
    for fold in range(c["inner_folds"]):
        train = np.flatnonzero((cube.roles == "D") & (cube.folds != fold))
        test = np.flatnonzero((cube.roles == "D") & (cube.folds == fold))
        result.append((Cases(cube, [(train, times)], train, variable, c, "inner_%s_fit" % fold),
                       Cases(cube, [(test, times)], train, variable, c, "inner_%s_check" % fold)))
    return result
