"""NV2 source geometry and immutable donor slots. No observation inputs."""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import linprog

from p9_3b3_compare_vertical_frame import G0


ROLES = ('pressure', 'temperature', 'RH_water')


def distances_km(latitudes, longitudes, sensor, earth_radius_km=6371.0088):
    lat, lon = np.deg2rad(np.asarray(latitudes)), np.deg2rad(np.asarray(longitudes))
    a, b = math.radians(sensor['latitude']), math.radians(sensor['longitude'])
    v = np.sin((lat-a)/2)**2 + np.cos(lat)*math.cos(a)*np.sin((lon-b)/2)**2
    return 2*earth_radius_km*np.arcsin(np.sqrt(np.clip(v, 0, 1)))


def radius_census(indices, points, surface_phi_by_time, sensors, protocol):
    """Export EVERY point in the union of instrument radii, including rejects.

    The first control surface is used for donor selection. Both controls are
    exported and checked for unexpected nonstationarity before any T/q read.
    This lower-bound census does not assert hourly top/profile admissibility.
    """
    indices = [int(i) for i in indices]
    xy = np.asarray(points, float)
    arrays = [np.asarray(v, float) for v in surface_phi_by_time.values()]
    if (not arrays or xy.shape != (len(indices), 2) or len(set(indices)) != len(indices)
            or any(v.shape != (len(indices),) for v in arrays)
            or not np.isfinite(xy).all() or not all(np.isfinite(v).all() for v in arrays)):
        raise ValueError('NV2_CENSUS_SHAPE_OR_FINITE')
    heights = np.array(arrays)/G0
    if np.any((heights < -500) | (heights > 5500)):
        raise ValueError('NV2_SURFACE_HEIGHT_DOMAIN')
    if np.max(np.ptp(heights, axis=0), initial=0) > protocol['surface_control_max_delta_m']:
        raise ValueError('NV2_CONTROL_SURFACES_NOT_STATIONARY')
    ds = {role: distances_km(xy[:, 0], xy[:, 1], sensors[role], protocol['earth_radius_km'])
          for role in ROLES}
    rows = []
    for k, index in enumerate(indices):
        if not any(ds[r][k] <= protocol['radius_km'] for r in ROLES):
            continue
        admissions = {}
        for role in ROLES:
            margin = sensors[role]['height_MSL_m']-heights[0, k]
            inside = bool(ds[role][k] <= protocol['radius_km'])
            reasons = ([] if inside else ['OUTSIDE_FIXED_RADIUS'])
            if margin < 0:
                reasons.append('TARGET_BELOW_NATIVE_SURFACE')
            admissions[role] = {
                'distance_km': float(ds[role][k]), 'inside_radius': inside,
                'target_minus_surface_m': float(margin),
                'lower_boundary_admitted': bool(inside and margin >= 0),
                'buffer_2m_sensitivity_admitted': bool(inside and margin >= 2),
                'rejection_reasons': reasons,
                'full_air_domain_status': 'TOP_AND_PROFILE_NOT_YET_CHECKED'}
        rows.append({'native_index': index, 'latitude': float(xy[k, 0]),
                     'longitude': float(xy[k, 1]),
                     'surface_phi_m2s2_by_control': {
                         stamp: float(v[k]) for stamp, v in surface_phi_by_time.items()},
                     'surface_H_m': float(heights[0, k]), 'roles': admissions})
    return sorted(rows, key=lambda r: (r['roles']['pressure']['distance_km'],
                                       r['latitude'], r['longitude']))


def freeze_donors(catalogue, country, protocol):
    """No scores or T/q in this function; slots never change by hour or role."""
    if country == 'AT':
        result = {}
        for fixed in protocol['AT_pressure_donors']:
            matches = [r for r in catalogue if abs(r['latitude']-fixed['latitude']) < 1e-9
                       and abs(r['longitude']-fixed['longitude']) < 1e-9]
            result[fixed['slot']] = (matches[0]['native_index'] if len(matches) == 1
                                    and matches[0]['roles']['pressure']['lower_boundary_admitted'] else None)
        return result
    if country not in ('DE', 'CH'):
        raise ValueError('NV2_COUNTRY_OUTSIDE_AT_DE_CH')
    valid = [r for r in catalogue if r['roles']['pressure']['lower_boundary_admitted']]
    valid.sort(key=lambda r: (r['roles']['pressure']['distance_km'], r['latitude'], r['longitude']))
    return {'D1': valid[0]['native_index'] if valid else None}


def fixed_weights(distances):
    d = np.asarray(distances, float)
    if d.ndim != 1 or not len(d) or not np.isfinite(d).all() or np.any(d < 0):
        raise ValueError('NV2_DISTANCE_DOMAIN')
    if np.any(d == 0):
        # Distinct nodes cannot share zero distance; reject ambiguous inputs.
        if sum(d == 0) != 1:
            raise ValueError('NV2_DUPLICATE_ZERO_DISTANCE')
        return (d == 0).astype(float)
    w = (min(d)/d)**2
    return w/w.sum()


def horizontal_support(points, sensor, distances, earth_radius_km=6371.0088):
    """Local tangent first moment; interpolation support is not uncertainty."""
    xy = np.asarray(points, float)
    d = np.asarray(distances, float)
    if xy.shape != (len(d), 2) or not len(d) or not np.isfinite(xy).all():
        raise ValueError('NV2_HORIZONTAL_SHAPE_OR_FINITE')
    w = fixed_weights(d)
    east = (np.deg2rad((xy[:, 1]-sensor['longitude']+180) % 360-180)
            * earth_radius_km*math.cos(math.radians(sensor['latitude'])))
    north = np.deg2rad(xy[:, 0]-sensor['latitude'])*earth_radius_km
    offsets = np.column_stack((east, north))
    moment = w@offsets
    design = np.column_stack((np.ones(len(d)), offsets))
    # This geometric feasibility problem uses no pressure values.
    hull = linprog(np.zeros(len(d)), A_eq=design.T, b_eq=[1, 0, 0],
                   bounds=(0, None), method='highs')
    return {'weights': w.tolist(), 'offsets_east_north_km': offsets.tolist(),
            'first_moment_east_north_km': moment.tolist(),
            'first_moment_norm_km': float(np.linalg.norm(moment)),
            'target_in_nonnegative_weight_convex_hull': bool(hull.success),
            'affine_design_rank': int(np.linalg.matrix_rank(design)),
            'full_2D_gradient_identifiable': bool(np.linalg.matrix_rank(design) == 3),
            'interpretation': 'HORIZONTAL_SENSITIVITY_NOT_CALIBRATED_CONFIDENCE_INTERVAL'}
