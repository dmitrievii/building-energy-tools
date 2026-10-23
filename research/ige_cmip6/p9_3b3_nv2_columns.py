"""NV2 per-instrument admission, fixed donors and same-surface P1/P2 pairs."""
from __future__ import annotations

from dataclasses import asdict
import math

import numpy as np

from p9_3b3_compare_pressure import hydrostatic_pressure
from p9_3b3_compare_vertical_frame import G0, PressureSeries, SourceBlocked, VerticalCoordinate
from p9_3b3_native_columns import NativeColumns
from p9_3b3_native_sources import synthesize
from p9_3b3_nv2_geometry import ROLES, distances_km, freeze_donors, horizontal_support, radius_census
from p9_3b3_reference_column import GASES, transfer_pressure


def instrument_target(sensor):
    return VerticalCoordinate(sensor['height_MSL_m'], 'GEOPOTENTIAL_HEIGHT_M', 'MSL_GEOID',
                              sensor['role'], 'WMDR_DATED_MSL_APPROX_H:'+sensor['source_sha256'], True)


def admission(column, sensor, stamp, protocol):
    if column is None:
        return {'admitted': False, 'reasons': ['FIXED_DONOR_MISSING_NO_SUBSTITUTION']}
    d = float(distances_km([column.latitude], [column.longitude], sensor, protocol['earth_radius_km'])[0])
    phi = G0*sensor['height_MSL_m']
    reasons = []
    if column.timestamp_UTC != stamp:
        reasons.append('PROFILE_TIME_MISMATCH')
    if column.gas != protocol['gas']:
        reasons.append('GAS_FORMULATION_MISMATCH')
    if d > protocol['radius_km']:
        reasons.append('OUTSIDE_FIXED_RADIUS')
    if phi < column.domain[0]:
        reasons.append('TARGET_BELOW_NATIVE_SURFACE')
    if phi > column.domain[1]:
        reasons.append('TARGET_ABOVE_AVAILABLE_PROFILE_TOP')
    return {'admitted': not reasons, 'reasons': reasons, 'distance_km': d,
            'surface_H_m': column.domain[0]/G0, 'top_H_m': column.domain[1]/G0,
            'target_minus_surface_m': (phi-column.domain[0])/G0,
            'buffer_2m_lower_boundary_sensitivity_pass': bool(phi-column.domain[0] >= 2*G0),
            'buffer_interpretation': 'DESIGN_SENSITIVITY_NOT_CALIBRATED_DATUM_UNCERTAINTY',
            'top_minus_target_m': (column.domain[1]-phi)/G0,
            'profile_fingerprint': column.fingerprint}


def single_donor(column, sensor, stamp):
    """All three methods share native SURFACE pressure and geopotential.

    The P2 containing-layer inversion is equivalent to integrating upward
    from that surface. Export its independent bottom-up residual as a check.
    """
    target = instrument_target(sensor)
    phi = G0*target.value
    t, q = column.state(phi)
    anchor_phi = column.domain[0]
    anchor_log_p = math.log(column.half_pressure_Pa[-1])
    anchor = VerticalCoordinate(anchor_phi/G0, target.kind, target.datum,
                                'GRID_SURFACE', 'NATIVE_PAIRED_PHI_LNSP', True)
    series = PressureSeries((column.half_pressure_Pa[-1],), anchor, stamp[:10], column.source,
                            'INSTANTANEOUS_UTC_NODE:'+stamp, source_sha256=column.source_sha256)
    common = {'status': 'CONDITIONAL_NATIVE_HYDROSTATIC_RESULT', 'target': asdict(target),
              'timestamp_UTC': stamp, 'source_column_fingerprint': column.fingerprint,
              'anchor_phi_m2s2': anchor_phi, 'anchor_log_pressure': anchor_log_p,
              'target_phi_m2s2': phi, 'target_layer_T_K': t, 'target_layer_q_kgkg': q,
              'gas_formulation': column.gas, 'independent_accuracy': 'NOT_QUALIFIED',
              'physical_scope': 'GAS_HYDROSTATIC_NO_CONDENSATE_SATURATION_NOT_CHECKED',
              'surface_layer_status': 'NATIVE_LAYER_STATE_NOT_STATION_2M_OBSERVATION_OPERATOR',
              'datum': 'H_EQUALS_DATED_MSL_CONSTANT_G0_APPROXIMATION_NOT_CERTIFIED'}
    results = {}
    for name, lapse in (('P1_ISOTHERMAL', 0.), ('P1_LAPSE_0065', .0065)):
        value = hydrostatic_pressure(series, target, [t], [q], proxy_source=column.source+'|'+stamp,
                                     proxy_date=stamp[:10], lapse_K_per_m=lapse)
        results[name] = {**common, 'pressure_Pa': value.pressure.values_Pa[0], 'lapse_K_per_m': lapse}
    rd, coef = GASES[column.gas]
    integral = 0.
    for j in range(len(column.temperature_K)-1, -1, -1):
        lower = column.half_geopotential_m2s2[j+1]
        upper = min(phi, column.half_geopotential_m2s2[j])
        if upper > lower:
            integral += ((upper-lower)/(rd*column.temperature_K[j]
                         *(1+coef*column.specific_humidity_kgkg[j])))
    p2 = math.exp(column.log_pressure(phi))
    check = math.exp(anchor_log_p-integral)
    if abs(p2-check) > 1e-6:
        raise ValueError('NV2_INDEPENDENT_BOTTOM_UP_INVERSION_RESIDUAL')
    results['P2_NATIVE'] = {**common, 'pressure_Pa': p2,
                            'bottom_up_pressure_residual_Pa': p2-check,
                            'integrated_surface_to_target_delta_log_p': -integral}
    return results


def predict_role(columns, slots, sensor, country, stamp, protocol):
    methods = {m: {'status': 'SOURCE_BLOCKED', 'reason': 'FIXED_DONOR_NOT_ADMITTED'}
               for m in protocol['methods_by_country'][country]}
    admissions = {slot: admission(columns.get(index), sensor, stamp, protocol)
                  for slot, index in slots.items()}
    for slot, index in slots.items():
        if not admissions[slot]['admitted']:
            for method in methods:
                if method.endswith('_'+slot):
                    methods[method]['reason'] = '|'.join(admissions[slot]['reasons'])
            continue
        try:
            for kind, value in single_donor(columns[index], sensor, stamp).items():
                methods[kind+'_'+slot] = value
        except SourceBlocked as exc:
            for method in methods:
                if method.endswith('_'+slot):
                    methods[method] = {'status': 'SOURCE_BLOCKED', 'reason': str(exc)}
    support = None
    if all(index is not None and index in columns for index in slots.values()):
        cs = [columns[index] for index in slots.values()]
        ds = [admissions[slot]['distance_km'] for slot in slots]
        support = horizontal_support([(c.latitude, c.longitude) for c in cs], sensor, ds,
                                     protocol['earth_radius_km'])
    blend_name = 'P2_FIXED_D1_D2_BLEND'
    if blend_name in methods:
        if len(slots) != 2 or not all(a['admitted'] for a in admissions.values()):
            methods[blend_name] = {'status': 'SOURCE_BLOCKED',
                                  'reason': 'BOTH_FIXED_DONORS_REQUIRED_NO_DROP_OR_RENORMALIZATION'}
        else:
            cs = [columns[index] for index in slots.values()]
            ds = [admissions[slot]['distance_km'] for slot in slots]
            value = transfer_pressure(cs, ds, instrument_target(sensor), timestamp_UTC=stamp)
            methods[blend_name] = {**value, 'status': 'CONDITIONAL_BLEND_SENSITIVITY_ONLY',
                                  'independent_accuracy': 'NOT_QUALIFIED',
                                  'donor_spread_is_confidence_interval': False}
            # Both pressures evaluated on the SAME target equipotential.
            logs = [c.log_pressure(G0*sensor['height_MSL_m']) for c in cs]
            support['same_target_phi_native_log_pressure_D2_minus_D1'] = logs[1]-logs[0]
            support['donor_pressure_spread_Pa'] = abs(math.exp(logs[1])-math.exp(logs[0]))
    return {'target_sensor': sensor, 'admissions': admissions, 'methods': methods,
            'horizontal_support': support, 'direct_barometer_truth_at_this_role': sensor['role'] == 'BAROMETER'}


class NV2Columns(NativeColumns):
    """Reuse frozen source reader; add radius census without modifying G0."""
    def __init__(self, cache, source_protocol, heights, nv2_protocol):
        super().__init__(cache, source_protocol, heights)
        self.nv2_protocol = nv2_protocol
        self.catalogue, self.donors = {}, {}
        all_selected = set(self.indices)  # Preserve original G0 stencil.
        for country in nv2_protocol['countries']:
            sensors = heights[country].get('sensors')
            if sensors is None:
                self.catalogue[country], self.donors[country] = [], ({'D1': None, 'D2': None}
                                                                  if country == 'AT' else {'D1': None})
                continue
            ds = [distances_km(self.grid.latitude, self.grid.longitude, sensors[role],
                               nv2_protocol['earth_radius_km']) for role in ROLES]
            ids = np.flatnonzero(np.min(ds, axis=0) <= nv2_protocol['radius_km']).tolist()
            if not 0 < len(ids) <= nv2_protocol['max_census_points']:
                raise SourceBlocked('NV2_RADIUS_CENSUS_POINT_COUNT')
            points = self.grid.points(ids)
            surfaces = {stamp: synthesize(self.surface.field('z', stamp), points)
                        for stamp in source_protocol['source_control_hours']}
            rows = radius_census(ids, points, surfaces, sensors, nv2_protocol)
            self.catalogue[country] = rows
            slots = freeze_donors(rows, country, nv2_protocol)
            self.donors[country] = slots
            all_selected.update(index for index in slots.values() if index is not None)
        self.indices = sorted(all_selected)
        self.points = self.grid.points(self.indices)
        self.manifest.update(source_points=self.points, fixed_nv2_donor_indices=self.donors,
                             G0_bracketing_stencil=self.by_country,
                             selection_uses_T_q_or_observations=False)

    def geometry_report(self):
        return {'full_radius_catalogue': self.catalogue, 'fixed_pressure_donor_slots': self.donors,
                'G0_bracketing_stencil': self.by_country, 'roles': list(ROLES),
                'selection_uses_T_q_or_observations': False,
                'scope': 'LOWER_BOUND_GEOMETRY_HOURLY_TOP_AND_PROFILE_NOT_YET_CHECKED'}

    def predict(self, columns, stamp):
        old = super().predict(columns, stamp)
        result = {}
        for country in self.nv2_protocol['countries']:
            sensors = self.heights[country].get('sensors')
            if sensors is None:
                result[country] = {'roles': {}, 'methods': {
                    m: {'status': 'SOURCE_BLOCKED', 'reason': 'DATED_SENSOR_REFERENCE_BLOCKED'}
                    for m in self.nv2_protocol['methods_by_country'][country]}, 'G0': old[country]}
                continue
            roles = {role: predict_role(columns, self.donors[country], sensors[role], country,
                                         stamp, self.nv2_protocol) for role in ROLES}
            result[country] = {'roles': roles, 'methods': roles['pressure']['methods'], 'G0': old[country]}
        return result
