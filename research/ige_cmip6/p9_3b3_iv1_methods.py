"""IV1 five-method assembly using frozen operators and one common prior.

This module does not fetch station observations or qualify source lineage.
It is an executable preparation component, not the complete IV1 source/scorer
pipeline. No production default or frozen numerical module is changed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import numpy as np

from p9_3b3_c2_projection import ProjectionProblem, project_day
from p9_3b3_cd2_solvers import solve_variant
from p9_3b3_cd3_stability import empirical_envelopes, run_starts
from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_generator import _choose
from p9_3b3_joint_solver import affine_temperature
from p9_3b3_pressure_reference import PressureReference
from p9_3b3_source_semantics import DailyTarget, SourceSemantics
from p9_3b3_thermodynamics import MK, epsilon_for, q_from_e, q_saturation, relative_humidity, saturation
from p9_3b3_tpa_compare import METHODS as TPA_METHODS, package, project_q, strict_joint
from p9_3b3_tpa_contracts import PressureTrajectory, UNIFORM


METHODS = ('STRICT_CLOSURE', 'Q_ONLY_PROJECTION', 'FROZEN_C2_3_STARTS',
           'SLSQP_SCALED_X_3_STARTS', 'SLSQP_SCALED_X_12_STARTS')


@dataclass(frozen=True)
class IV1PressureTrajectory(PressureTrajectory):
    """Keep the source date and identify IV1 instead of the old NV2 archive."""
    def __post_init__(self):
        super().__post_init__()
        if (self.target_date != self.source_date or self.source_date[:4] != '2022'
                or self.method != 'P2_NATIVE' or self.alignment != 'TARGET_DAY_EXTERNAL_FIXED'):
            raise ValueError('IV1_NEW_2022_NATIVE_TARGET_DAY_PRESSURE_REQUIRED')

    def comparison_reference(self):
        return PressureReference(self.values_Pa, 'IV1_NATIVE_THERMO|'+self.method,
            'THERMO_SENSOR|'+self.datum_policy, mode='SITE_HYDROSTATIC_PROVISIONAL',
            height_m=self.height_MSL_m, source_sha256=self.fingerprint,
            reference_date=self.source_date, time_support='INSTANTANEOUS_UTC_NODES|'+self.alignment)


@dataclass(frozen=True)
class ReferenceConstraints:
    date: str
    Tmin_K: float
    Tmax_K: float
    tas_K: float
    q_mean_kgkg: float
    RH_mean_pct: float
    source_sha256: str
    source_identity: str
    temperature_operator: str = 'DERIVED_TAS_MIDRANGE'
    rh_phase: str = 'WATER_ICE'
    calendar: str = 'proleptic_gregorian'
    q_weights: tuple = UNIFORM
    RH_weights: tuple = UNIFORM
    T_weights: tuple = UNIFORM
    source_kind: str = 'ERA5_REFERENCE_DEFINED_DAILY_INPUTS_NOT_NATIVE_NEX'
    time_support: str = 'REFERENCE_DEFINED_24_UTC_NODES_NATIVE_NEX_BOUNDS_UNRESOLVED'
    fully_verified: bool = False

    def __post_init__(self):
        if (len(self.source_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.source_sha256)
                or not self.source_identity or self.fully_verified
                or self.temperature_operator != 'DERIVED_TAS_MIDRANGE' or self.rh_phase != 'WATER_ICE'
                or self.calendar != 'proleptic_gregorian'
                or self.source_kind != 'ERA5_REFERENCE_DEFINED_DAILY_INPUTS_NOT_NATIVE_NEX'
                or self.time_support != 'REFERENCE_DEFINED_24_UTC_NODES_NATIVE_NEX_BOUNDS_UNRESOLVED'):
            raise ValueError('IV1_REFERENCE_OPERATOR_OR_PROVENANCE')
        for name in ('q_weights', 'RH_weights', 'T_weights'):
            if tuple(getattr(self, name)) != UNIFORM:
                raise ValueError('IV1_REGISTERED_UNIFORM_24_NODE_OPERATORS_REQUIRED')
            object.__setattr__(self, name, UNIFORM)
        self.legacy_target()

    @property
    def fingerprint(self):
        return fingerprint(asdict(self))

    @property
    def semantics_sha256(self):
        return fingerprint(asdict(self.legacy_target().semantics))

    def legacy_target(self):
        semantics = SourceSemantics(self.temperature_operator, self.rh_phase, self.calendar,
            self.time_support, False, self.source_identity)
        return DailyTarget(self.date, self.Tmin_K, self.Tmax_K, self.tas_K,
                           self.q_mean_kgkg, self.RH_mean_pct, semantics)


def reference_constraints(date, T_K, Td_K, pressure, source_sha256):
    """Apply the registered NASA-style discrete operators to reference nodes.

    Dew point is water-defined; RH diagnostics use the exact WATER_ICE switch.
    Physical input failures remain failures, without clipping or substitution.
    """
    T, Td = np.asarray(T_K, float), np.asarray(Td_K, float)
    if (T.shape != (24,) or Td.shape != (24,) or not np.isfinite(np.r_[T, Td]).all()
            or np.any(T <= 173) or np.any(T >= 332) or np.any(Td <= 173) or np.any(Td >= 332)
            or pressure.target_date != date or pressure.source_date != date
            or pressure.alignment != 'TARGET_DAY_EXTERNAL_FIXED'):
        raise ValueError('IV1_REFERENCE_24_NODE_DOMAIN_OR_PRESSURE_DATE')
    e = saturation(Td, 'WATER', MK)
    if np.any(e > saturation(T, 'WATER', MK)*(1+1e-8)):
        raise ValueError('IV1_NONPHYSICAL_REFERENCE_NO_CLIPPING')
    q = q_from_e(e, pressure.values_Pa, epsilon_for(MK))
    R = relative_humidity(T, pressure.values_Pa, q, 'WATER_ICE', MK)
    return ReferenceConstraints(date, float(T.min()), float(T.max()), float((T.min()+T.max())/2),
        float(np.mean(q)), float(np.mean(R)), source_sha256,
        'IV1_CONTROLLED_ERA5_REFERENCE_OPERATORS|'+source_sha256)


def choose_common_prior(target, donors, wet):
    """Choose before method feasibility; never reselect after solver failure."""
    dates = [d.date for d in donors]
    if len(dates) != len(set(dates)):
        raise ValueError('IV1_DUPLICATE_DONOR_DATES')
    if any(int(d[:4]) not in (2019, 2020) or not 15 <= int(d[8:10]) <= 28
           or int(d[5:7]) not in (2, 8) for d in dates):
        raise ValueError('IV1_UNREGISTERED_DONOR_WINDOW')
    for donor in donors:
        validate_donor_source(donor)
    eligible = [d for d in donors if d.date[5:7] == target.date[5:7] and d.wet == wet]
    if not eligible:
        raise ValueError('IV1_SHARED_TARGET_BLOCKED_NO_ELIGIBLE_DONOR')
    return _choose([(d, None) for d in eligible], target.legacy_target(), None, 7313)[0]


def validate_donor_source(donor):
    if (len(donor.T_K) != 24 or len(donor.q_kgkg) != 24
            or donor.pressure.mode != 'ERA5_GRID_PROVISIONAL'
            or donor.pressure.reference_date != donor.date or not donor.pressure.source_sha256):
        raise ValueError('IV1_MODEL_GRID_DONOR_SOURCE_AND_DATE_REQUIRED_OBSERVATIONS_FORBIDDEN')


def _scaled_twelve(target, pressure, donor, frozen_raw, case_id):
    # A strict-first state is preserved, just as in frozen C2. Extra starts may
    # only solve the soft stage; they do not override a strict witness.
    if frozen_raw.get('status') == 'EXACT_SOURCE_PRESERVED':
        return dict(frozen_raw), {'strict_witness_preserved': True, 'trials': [], 'envelopes': {}}
    problem = ProjectionProblem(donor.T_K, donor.q_kgkg, target.legacy_target(),
        pressure.comparison_reference(), target.q_weights, target.RH_weights, target.T_weights)
    tcheck = problem.temperature_feasibility()
    if tcheck['status'] in ('CERTIFIED_T_DOMAIN_INFEASIBLE', 'T_DOMAIN_NUMERICALLY_UNRESOLVED'):
        return {'status': tcheck['status'], 'certificate': tcheck}, {'trials': [], 'envelopes': {}}
    trials = run_starts(problem, case_id)
    valid = [r for r in trials if r.get('physical_admissibility') == 'VALIDATED'
             and np.isfinite(r.get('F_original', np.nan))]
    # Keep the frozen rule: validated finite states are eligible even if a
    # solver's stopping flag is false. Stable list order resolves exact ties.
    if not valid:
        return {'status': 'UNRESOLVED', 'reason': 'IV1_NO_VALIDATED_12_START_STATE'}, {
            'strict_witness_preserved': False, 'trials': trials, 'envelopes': {}}
    chosen = min(valid, key=lambda r: r['F_original'])
    T, q = problem.base.unpack(np.asarray(chosen['final_x']))
    raw = {'status': 'SOFT_SOURCE_PROJECTION', 'method': 'IV1_SCALED_X_12_VALIDATED_NOT_GLOBAL',
        'T_K': T.tolist(), 'q_kgkg': q.tolist(), 'p_Pa': list(pressure.values_Pa),
        'objective': {'total': chosen['F_original']}, 'selected_start_id': chosen['id'],
        'selected_solver_reported_success': chosen['solver_success'],
        'correction_acceptance': 'NOT_ESTABLISHED_RESEARCH_ONLY'}
    return raw, {'strict_witness_preserved': False, 'trials': trials,
        'envelopes': empirical_envelopes(problem, valid)}


def compare_five(country, target, pressure, donor):
    """Run the exact registered five methods with immutable shared inputs.

    Source admission and the full cohort are checked by the calling stage;
    this pure computational component has no observation or network argument.
    """
    if (country not in ('AT', 'DE', 'CH') or target.date != pressure.target_date
            or target.date[:7] not in ('2022-02', '2022-08') or not 15 <= int(target.date[8:10]) <= 28
            or not isinstance(pressure, IV1PressureTrajectory)):
        raise ValueError('IV1_CASE_COUNTRY_OR_PRESSURE_ALIGNMENT')
    if pressure.source_date != target.date or pressure.alignment != 'TARGET_DAY_EXTERNAL_FIXED':
        raise ValueError('IV1_TARGET_DAY_NATIVE_PRESSURE_REQUIRED')
    if int(donor.date[:4]) not in (2019, 2020) or donor.date[5:7] != target.date[5:7] or not 15 <= int(donor.date[8:10]) <= 28:
        raise ValueError('IV1_REGISTERED_COMMON_DONOR_REQUIRED')
    validate_donor_source(donor)
    prior_sha = fingerprint({'T': list(donor.T_K), 'q': list(donor.q_kgkg)})
    before = fingerprint({'target': asdict(target), 'pressure': asdict(pressure), 'donor': asdict(donor)})
    strict = strict_joint(donor.T_K, donor.q_kgkg, target, pressure)
    affine = affine_temperature(donor.T_K, target.legacy_target())
    qraw = project_q(donor.q_kgkg, q_saturation(affine, pressure.values_Pa),
                     target.q_mean_kgkg, target.q_weights)
    if qraw['status'] == 'FEASIBLE':
        qraw = {**qraw, 'status': 'Q_MEAN_EXACT_RH_DIAGNOSTIC',
                'T_K': affine.tolist(), 'p_Pa': list(pressure.values_Pa)}
    kwargs = dict(donor_date=donor.date, pressure_alignment='TARGET_DAY_EXTERNAL_FIXED',
        strict_witness=strict if strict.get('status') == 'EXACT_DEFINED_OPERATORS' else None,
        q_weights=target.q_weights, RH_weights=target.RH_weights, T_weights=target.T_weights)
    frozen = project_day(donor.T_K, donor.q_kgkg, target.legacy_target(), pressure.comparison_reference(),
                         mode='BOTH_SOFT', **kwargs)
    scaled = solve_variant(donor.T_K, donor.q_kgkg, target.legacy_target(),
        pressure.comparison_reference(), 'SLSQP_SCALED_X', **kwargs)
    case_id = 'IV1|'+country+'|'+target.date+'|P2_NATIVE_THERMO'
    twelve, details = _scaled_twelve(target, pressure, donor, frozen, case_id)
    rows = []
    for method, raw, mapping in zip(METHODS, (strict, qraw, frozen, scaled['frozen_result'], twelve),
                                     (TPA_METHODS[0], TPA_METHODS[1], TPA_METHODS[2], TPA_METHODS[2], TPA_METHODS[2])):
        row = package(raw, mapping, target, pressure, donor.T_K, donor.q_kgkg)
        row.update(IV1_method=method, IV1_case_id=case_id, common_prior_sha256=prior_sha,
                   common_donor_date=donor.date, local_optimum_certified=False, global_optimum_certified=False)
        rows.append(row)
    if fingerprint({'target': asdict(target), 'pressure': asdict(pressure), 'donor': asdict(donor)}) != before:
        raise AssertionError('IV1_COMMON_INPUT_MUTATED')
    return {'country': country, 'date': target.date, 'case_id': case_id,
        'common_prior_sha256': prior_sha, 'results': rows,
        'inputs': {'target': asdict(target), 'pressure': asdict(pressure), 'donor': asdict(donor)},
        'scaled_3_diagnostics': scaled, 'scaled_12_diagnostics': details,
        'station_values_opened': False, 'independent_accuracy': 'NOT_RUN', 'operational_ready': False}
