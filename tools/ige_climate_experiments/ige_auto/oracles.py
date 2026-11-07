"""Independent hand-computable controls, not a weather accuracy benchmark."""
from __future__ import annotations

import numpy as np

from .fit import Unidentifiable, linear_solve


def self_check():
    x = np.array([-1., -.5, -.2, .1, .4, .9])[:, None]
    y = -7.3*x[:, 0]
    r = linear_solve(x, y, np.ones(len(y)), rcond=1e-12)
    assert abs(r["coefficients"][0]+7.3) < 1e-10
    try:
        linear_solve(np.column_stack((x, 2*x)), y, np.ones(len(y)))
    except Unidentifiable:
        rejected = True
    else:
        rejected = False
    assert rejected
    # Weighted normal equations for ridge in unit-RMS coordinates.
    ridge = linear_solve(x, y, np.ones(len(y)), loss="ridge", ridge=.25)
    assert abs(ridge["coefficients"][0]-(-7.3/1.25)) < 1e-10
    return {"OLS_known_gradient": "PASS", "collinear_features_rejected": "PASS", "ridge_analytic_solution": "PASS",
            "scientific_accuracy_qualified": False}
