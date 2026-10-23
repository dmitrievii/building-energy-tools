"""TPA1 immutable source/operator/pressure contracts; no station truth inputs."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import datetime as dt
import json
import math

from p9_3b3_compare_vertical_frame import fingerprint
from p9_3b3_pressure_reference import PressureReference
from p9_3b3_source_semantics import DailyTarget, SourceSemantics


UNIFORM = (1/24,)*24


def weights(values):
    values = tuple(float(v) for v in values)
    if len(values) != 24 or any(not math.isfinite(v) or v < 0 for v in values) or abs(sum(values)-1) > 1e-12:
        raise ValueError('TPA_INVALID_OPERATOR_WEIGHTS')
    return values


@dataclass(frozen=True)
class DailyClimateConstraints:
    date: str
    Tmin_K: float
    Tmax_K: float
    tas_K: float
    q_mean_kgkg: float
    RH_mean_pct: float
    source_kind: str
    source_sha256: str
    semantics_sha256: str
    source_identity: str
    temperature_operator: str = 'DERIVED_TAS_MIDRANGE'
    rh_phase: str = 'WATER_ICE'
    calendar: str = '365_day'
    q_weights: tuple = UNIFORM
    RH_weights: tuple = UNIFORM
    T_weights: tuple = UNIFORM
    time_support: str = '24_UNIFORM_UTC_NODES_NATIVE_BOUNDS_UNRESOLVED'
    fully_verified: bool = False

    def __post_init__(self):
        if self.fully_verified or 'UNRESOLVED' not in self.time_support:
            raise ValueError('TPA_NATIVE_BOUNDS_AND_TAS_METADATA_CONFLICT_NOT_RESOLVED')
        if self.rh_phase not in ('WATER', 'ICE', 'WATER_ICE'):
            raise ValueError('TPA_UNKNOWN_PHASE')
        for name in ('source_sha256', 'semantics_sha256'):
            value = getattr(self, name)
            if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('TPA_SOURCE_HASH_REQUIRED')
        if not self.source_identity or self.source_kind not in ('NASA_REGISTERED_REGRESSION', 'SYNTHETIC_OPERATOR_CONTROL'):
            raise ValueError('TPA_SOURCE_IDENTITY_REQUIRED')
        for name in ('q_weights', 'RH_weights', 'T_weights'):
            object.__setattr__(self, name, weights(getattr(self, name)))
        self.legacy_target()  # SI range, phase, calendar and midrange checks.

    @property
    def fingerprint(self):
        return fingerprint(asdict(self))

    def legacy_target(self):
        sem = SourceSemantics(self.temperature_operator, self.rh_phase, self.calendar,
            'NATIVE_AVERAGING_BOUNDS_NOT_VERIFIED_UTC_DAY_ASSUMED', False, self.source_identity)
        return DailyTarget(self.date, self.Tmin_K, self.Tmax_K, self.tas_K,
                           self.q_mean_kgkg, self.RH_mean_pct, sem)


@dataclass(frozen=True)
class PressureTrajectory:
    target_date: str
    source_date: str
    timestamps_UTC: tuple
    values_Pa: tuple
    prior_T_K: tuple
    prior_q_kgkg: tuple
    latitude: float
    longitude: float
    height_MSL_m: float
    role: str
    method: str
    donor_slot: str
    source_archive_sha256: str
    provenance_json: str
    alignment: str = 'TARGET_DAY_EXTERNAL_FIXED'
    usage: str = 'MODEL_SOURCE_ONLY'
    datum_policy: str = 'DATED_MSL_EQUALS_GEOPOTENTIAL_HEIGHT_CONSTANT_G0_NOT_CERTIFIED'

    def __post_init__(self):
        dt.date.fromisoformat(self.target_date)
        dt.date.fromisoformat(self.source_date)
        if self.role != 'THERMO_SENSOR' or self.usage != 'MODEL_SOURCE_ONLY':
            raise ValueError('TPA_THERMO_MODEL_PRESSURE_REQUIRED_OBSERVATIONS_FORBIDDEN')
        if self.alignment not in ('TARGET_DAY_EXTERNAL_FIXED', 'DONOR_DATE_SENSITIVITY'):
            raise ValueError('TPA_EXPLICIT_PRESSURE_DATE_ALIGNMENT_REQUIRED')
        if self.alignment == 'TARGET_DAY_EXTERNAL_FIXED' and self.target_date != self.source_date:
            raise ValueError('TPA_SOURCE_AND_TARGET_DAY_MISMATCH')
        expected = tuple(self.source_date+'T'+str(h).zfill(2)+':00' for h in range(24))
        object.__setattr__(self, 'timestamps_UTC', tuple(self.timestamps_UTC))
        if self.timestamps_UTC != expected:
            raise ValueError('TPA_24_ORDERED_SOURCE_UTC_NODES_REQUIRED')
        for field, lower, upper in (('values_Pa', 30000, 115000), ('prior_T_K', 173, 332), ('prior_q_kgkg', -1e-300, 1)):
            value = tuple(float(x) for x in getattr(self, field))
            if len(value) != 24 or any(not math.isfinite(v) or not lower < v < upper for v in value):
                raise ValueError('TPA_PRESSURE_STATE_SI_DOMAIN_'+field)
            object.__setattr__(self, field, value)
        if (not all(math.isfinite(v) for v in (self.latitude, self.longitude, self.height_MSL_m))
                or not -90 <= self.latitude <= 90 or not 0 <= self.longitude < 360):
            raise ValueError('TPA_SENSOR_GEOMETRY_DOMAIN')
        if (len(self.source_archive_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.source_archive_sha256)
                or not self.method or not self.donor_slot):
            raise ValueError('TPA_PRESSURE_PROVENANCE_REQUIRED')
        if not isinstance(json.loads(self.provenance_json), dict):
            raise ValueError('TPA_PRESSURE_PROVENANCE_REQUIRED')

    @property
    def fingerprint(self):
        return fingerprint(asdict(self))

    def comparison_reference(self):
        """Legacy comparison adapter keeps the actual source day unchanged."""
        return PressureReference(self.values_Pa, 'SEALED_NV2_THERMO|'+self.method,
            'THERMO_SENSOR|'+self.datum_policy, mode='SITE_HYDROSTATIC_PROVISIONAL',
            height_m=self.height_MSL_m, source_sha256=self.fingerprint,
            reference_date=self.source_date, time_support='INSTANTANEOUS_UTC_NODES|'+self.alignment)

    def generation_reference(self):
        if self.alignment != 'TARGET_DAY_EXTERNAL_FIXED' or self.target_date != self.source_date:
            raise ValueError('TPA_DONOR_SENSITIVITY_IS_NOT_TARGET_DAY_GENERATOR_PRESSURE')
        return self.comparison_reference()

    def metadata(self):
        return {k: v for k, v in asdict(self).items() if k not in ('values_Pa', 'prior_T_K', 'prior_q_kgkg')} | {
            'fingerprint': self.fingerprint, 'datum_verified': False, 'uncertainty_calibrated': False,
            'station_2m_observation_operator_qualified': False,
            'hydrostatic_reintegration_after_T_q_change': False,
            'independent_accuracy': 'NOT_QUALIFIED', 'operational_ready': False}
