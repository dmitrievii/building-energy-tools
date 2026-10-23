"""CD3 posthoc derivatives: no endpoint repair and no optimizer interception.

Unchanged coordinates may retain a recorded float64 conversion residual.
The varied coordinate is always inside its exact box. Three actual offsets
give a quadratic-exact stencil on the endpoint's original phase branch.
"""
from __future__ import annotations

from collections import Counter
import numpy as np


STEPS = (1e-5, 5e-6)
ERROR_LIMIT = 1e-5
MAX_HALVINGS = 20


def three_point_weights(a, b):
    """Weights multiplying f(a)-f(0), f(b)-f(0) to estimate f'(0)."""
    if not np.isfinite(a+b) or a == 0 or b == 0 or a == b:
        raise ValueError('CD3_DEGENERATE_STENCIL')
    return b/(a*(b-a)), -a/(b*(b-a))


def second_order_fd(view, x, step):
    x = np.asarray(x, dtype=float)
    original = x.copy()
    if not np.isfinite(step) or step <= 0:
        raise ValueError('CD3_INVALID_FD_STEP')
    bounds, D = np.asarray(view.bounds), np.asarray(view.D)
    if (x.ndim != 1 or bounds.shape != (len(x), 2) or D.shape != x.shape
            or np.any(D <= 0) or not np.all(np.isfinite(x))):
        raise ValueError('CD3_INVALID_FD_COORDINATES')
    eta = 8*np.finfo(float).eps*np.maximum(1., np.maximum(abs(x), np.max(abs(bounds), axis=1)))
    overshoot = np.maximum(bounds[:, 0]-x, 0)+np.maximum(x-bounds[:, 1], 0)
    if np.any(overshoot > eta):
        raise ValueError('CD3_BASE_OUTSIDE_ROUNDOFF_ENVELOPE')
    F, gradient = view.objective(x)
    normalization = max(1., abs(F))
    analytic = np.asarray(gradient)*D/normalization
    g, Ag, h, Ah = view.values(x)
    c0, jac = np.r_[g, h], np.vstack([Ag, Ah])
    phase = view.phase(x)
    columns, unavailable, stencils = [], [], Counter()

    def candidate(j, delta):
        y = x.copy()
        y[j] += delta*D[j]
        if (y[j] == x[j] or not bounds[j, 0] <= y[j] <= bounds[j, 1]
                or not np.array_equal(view.phase(y), phase)):
            return None
        return y

    for j in range(len(x)):
        chosen = None
        for halvings in range(MAX_HALVINGS+1):
            s = step*2.**(-halvings)
            minus, plus = candidate(j, -s), candidate(j, s)
            if minus is not None and plus is not None:
                chosen = minus, plus, 'CENTRAL_SECOND_ORDER', halvings
            else:
                for sign, y in ((1, plus), (-1, minus)):
                    y2 = candidate(j, 2*sign*s)
                    if y is not None and y2 is not None and y[j] != y2[j]:
                        chosen = y, y2, 'ONE_SIDED_SECOND_ORDER_SAME_BRANCH', halvings
                        break
            if chosen is not None:
                break
        if chosen is None:
            unavailable.append({'column': j, 'reason': 'NO_THREE_DISTINCT_BOX_AND_SAME_BRANCH_POINTS'})
            continue
        a, b, stencil, halvings = chosen
        da, db = (a[j]-x[j])/D[j], (b[j]-x[j])/D[j]
        wa, wb = three_point_weights(da, db)
        fa = view.objective(a)[0]
        fb = view.objective(b)[0]
        ga, _, ha, _ = view.values(a)
        gb, _, hb, _ = view.values(b)
        numeric = (wa*(fa-F)+wb*(fb-F))/normalization
        cj = wa*(np.r_[ga, ha]-c0)+wb*(np.r_[gb, hb]-c0)
        ferr = abs(numeric-analytic[j])/max(1., abs(numeric), abs(analytic[j]))
        jerr = abs(cj-jac[:, j])/np.maximum(1., np.maximum(abs(cj), abs(jac[:, j])))
        if not np.isfinite(ferr) or not np.all(np.isfinite(jerr)):
            raise ValueError('CD3_NONFINITE_FD_ERROR')
        columns.append({'column': j, 'stencil': stencil, 'actual_offsets_y': [float(da), float(db)],
            'step_halvings': halvings, 'objective_relative_error': float(ferr),
            'Jacobian_max_relative_error': float(np.max(jerr, initial=0))})
        stencils[stencil] += 1
    if not np.array_equal(x, original):
        raise AssertionError('CD3_ENDPOINT_MUTATED')
    ferr = max((r['objective_relative_error'] for r in columns), default=None)
    jerr = max((r['Jacobian_max_relative_error'] for r in columns), default=None)
    return {'dimensionless_step': step, 'column_count': len(x), 'checked_columns': len(columns),
        'unavailable_columns': unavailable, 'columns': columns, 'stencils': dict(stencils),
        'objective_max_relative_error': ferr, 'constraint_Jacobian_max_relative_error': jerr,
        'recorded_base_roundoff_columns': np.flatnonzero(overshoot > 0).tolist(),
        'max_base_box_overshoot': float(np.max(overshoot, initial=0)),
        'max_base_box_overshoot_over_envelope': float(np.max(overshoot/eta, initial=0)),
        'objective_normalization': normalization, 'error_limit': ERROR_LIMIT,
        'pass': not unavailable and ferr is not None and ferr <= ERROR_LIMIT and jerr <= ERROR_LIMIT,
        'endpoint_unchanged': True, 'phase_crossing_stencils_used': False,
        'scope': 'BRANCHWISE_DERIVATIVES_NOT_SWITCH_DIFFERENTIABILITY_OR_OPTIMALITY'}
