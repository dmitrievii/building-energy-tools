from __future__ import annotations

import collections

import numpy as np

from .cases import macro_weights


def nearest(cases):
    p = np.full(len(cases.y), np.nan)
    if len(cases.d):
        j = np.argmin(np.where(cases.mask, cases.dist, np.inf), axis=1)
        ix = np.arange(len(p)); yes = cases.n_donors > 0
        p[yes] = cases.dv[ix[yes], j[yes]]
    return p


def metrics(cases, pred, mask=None):
    use = cases.obs & np.isfinite(pred)
    if mask is not None:
        use &= mask
    e = pred[use]-cases.y[use]
    result = {"N_calendar_sampled": len(pred), "N_calendar_population": cases.population,
              "N_observed": int(cases.obs.sum()), "N_predicted_all_calendar": int(np.isfinite(pred).sum()),
              "N_predicted_observed": int(np.sum(cases.obs & np.isfinite(pred))), "N_scored": int(use.sum()),
              "N_no_eligible_target": int((~cases.obs).sum()),
              "N_observed_without_prediction": int(np.sum(cases.obs & ~np.isfinite(pred))),
              "coverage_observed": float(np.sum(cases.obs & np.isfinite(pred))/cases.obs.sum()) if cases.obs.sum() else None}
    for name, labels in (("by_country", cases.country), ("by_station", cases.station), ("by_month", cases.month)):
        groups = {}
        for label in sorted(set(labels.tolist())):
            group = labels == label; scored = use & group
            err = pred[scored]-cases.y[scored]
            groups[str(label)] = {"N_calendar": int(group.sum()), "N_observed": int((cases.obs & group).sum()),
                                  "N_predicted": int((np.isfinite(pred) & group).sum()), "N_scored": len(err),
                                  "MAE": float(np.mean(np.abs(err))) if len(err) else None,
                                  "RMSE": float(np.sqrt(np.mean(err*err))) if len(err) else None,
                                  "bias": float(np.mean(err)) if len(err) else None}
        result[name] = groups
    if not len(e):
        return result | {"MAE": None, "RMSE": None, "bias": None, "P95_abs": None, "equal_country_station_macro_MAE": None}
    w = macro_weights(cases, use, month_balance=False)[use]
    result.update(MAE=float(np.mean(np.abs(e))), RMSE=float(np.sqrt(np.mean(e*e))), bias=float(np.mean(e)),
                  P95_abs=float(np.quantile(np.abs(e), .95)), equal_country_station_macro_MAE=float(np.sum(w*np.abs(e))))
    qc = {}
    for q in sorted(set(map(int, cases.target_qc[use]))):
        sub = use & (cases.target_qc == q); err = pred[sub]-cases.y[sub]
        qc[str(q)] = {"N": len(err), "MAE": float(np.mean(np.abs(err))), "bias": float(np.mean(err)),
                      "stratum": cases.cube.meta["qc_codebook"][q]["stratum"]}
    result["target_QC_strata"] = qc
    if cases.variable == "RH":
        result["predicted_outside_0_100_all_calendar"] = int(np.sum(np.isfinite(pred) & ((pred < 0) | (pred > 100))))
    return result


def prediction_rows(cases, pred, neff=None, weights=None):
    book = cases.cube.meta["qc_codebook"]
    for i, rid in enumerate(cases.row_id):
        donor_strata = set()
        if weights is not None:
            donor_strata = {book[int(q)]["stratum"] for q in cases.donor_qc[i, weights[i] > 1e-6]}
        yield {"case_id": rid, "station": cases.station[i], "timestamp_utc": cases.cube.times[cases.t[i]],
               "country": cases.country[i], "variable": cases.variable,
               "observed": float(cases.y[i]) if cases.obs[i] else "",
               "predicted": float(pred[i]) if np.isfinite(pred[i]) else "",
               "error": float(pred[i]-cases.y[i]) if cases.obs[i] and np.isfinite(pred[i]) else "",
               "target_available": bool(cases.obs[i]), "independent_donors": int(cases.n_donors[i]),
               "n_eff": float(neff[i]) if neff is not None else "",
               "target_qc_stratum": book[int(cases.target_qc[i])]["stratum"],
               "donor_qc_strata": "|".join(sorted(donor_strata)),
               "operator": cases.cube.meta["operator_codebook"][int(cases.target_op[i])],
               "status": "PREDICTED" if np.isfinite(pred[i]) else "UNKNOWN_TARGET_OPERATOR" if cases.target_op[i] == 0 else "INSUFFICIENT_COMPATIBLE_DONORS"}


PREDICTION_FIELDS = ["case_id", "station", "timestamp_utc", "country", "variable", "observed", "predicted", "error",
                     "target_available", "independent_donors", "n_eff", "target_qc_stratum", "donor_qc_strata", "operator", "status"]
