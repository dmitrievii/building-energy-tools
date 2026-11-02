"""Read EPB Rhino evidence ZIPs without extracting files or running uploaded code.

The preferred contract is visualization/manifest.json + hourly-thermal.csv.
The legacy result.json thermalBalance is supported to make existing Result Export
bundles immediately viewable. Missing values are never replaced with zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath
import json
import re
import zipfile

import numpy as np
import pandas as pd

MAX_COMPRESSED = 100 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 650 * 1024 * 1024
MAX_SINGLE_MEMBER = 240 * 1024 * 1024
MAX_MEMBERS = 80
MAX_ROWS = 2_000_000
SYSTEM_FILES = (
    'hourly-generation-physical-research.csv',
    'hourly-generation-generator-only.csv',
    'hourly-storage-research-ledger.csv',
    'hourly-heating-circuit-research.csv',
    'hourly-combined-dhw-tank-in-tank-research.csv',
    'hourly-en15316-1-system-research-ledger.csv',
)
REQUIRED_HOURLY = ('zone_id', 'hour_index', 'signed_load_w', 'heating_load_w', 'cooling_load_w')
MONTH_COLUMNS = ('scenario', 'metric', 'unit', 'month', 'value')
YEAR_8760 = 2001  # visualization reference only, not a project/weather year
YEAR_8784 = 2000


class BundleValidationError(ValueError):
    pass


@dataclass
class EpbBundle:
    manifest: dict
    visualization_manifest: dict
    hourly: pd.DataFrame
    thermal_monthly: pd.DataFrame
    monthly_metrics: pd.DataFrame
    carrier: pd.DataFrame
    scenarios: pd.DataFrame
    systems: dict[str, pd.DataFrame]
    trace: pd.DataFrame
    zone_metadata: dict
    warnings: list[str] = field(default_factory=list)

    @property
    def has_hourly(self) -> bool:
        return not self.hourly.empty


def _member(z: zipfile.ZipFile, name: str) -> bytes | None:
    if name not in z.namelist():
        return None
    return z.read(name)


def _json(z: zipfile.ZipFile, name: str) -> dict:
    raw = _member(z, name)
    if raw is None:
        return {}
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise BundleValidationError(f'{name} must be a JSON object.')
    return obj


def _csv(z: zipfile.ZipFile, name: str) -> pd.DataFrame:
    raw = _member(z, name)
    if not raw:
        return pd.DataFrame()
    try:
        frame = pd.read_csv(BytesIO(raw), low_memory=False)
    except (ValueError, pd.errors.ParserError) as e:
        raise BundleValidationError(f'Invalid CSV: {name}: {e}') from e
    if len(frame) > MAX_ROWS:
        raise BundleValidationError(f'Too many rows in {name}.')
    return frame


def _validate_archive(data: bytes) -> zipfile.ZipFile:
    if len(data) > MAX_COMPRESSED:
        raise BundleValidationError('ZIP exceeds 100 MiB upload limit.')
    try:
        z = zipfile.ZipFile(BytesIO(data))
    except (zipfile.BadZipFile, OSError) as e:
        raise BundleValidationError('Not a valid ZIP.') from e
    members = z.infolist()
    if len(members) > MAX_MEMBERS:
        z.close()
        raise BundleValidationError('ZIP contains too many entries.')
    total = 0
    seen = set()
    for info in members:
        path = PurePosixPath(info.filename)
        if info.filename in seen or path.is_absolute() or '..' in path.parts or '\\' in info.filename:
            z.close()
            raise BundleValidationError('Unsafe or duplicate archive member.')
        seen.add(info.filename)
        if info.is_dir():
            continue
        if info.file_size > MAX_SINGLE_MEMBER:
            z.close()
            raise BundleValidationError('One archive member exceeds the size limit.')
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED:
            z.close()
            raise BundleValidationError('ZIP exceeds maximum uncompressed size.')
    return z


def _native_fallback(result: dict, warnings: list[str]):
    """Read only the native thermalBalance; no inference of absent system signals."""
    tb = result.get('thermalBalance')
    if not isinstance(tb, dict):
        return pd.DataFrame(), pd.DataFrame(), {}
    hourly_rows, month_rows = [], []
    metadata = tb.get('zoneMetadataByZoneId') or {}
    for zone in tb.get('zones') or []:
        zid = str(zone.get('zoneId', ''))
        if not zid:
            continue
        for m in zone.get('months') or []:
            month_rows.append({
                'zone_id': zid,
                'month': m.get('month'),
                'heating_need_kwh': m.get('heatingNeedKilowattHours'),
                'cooling_need_kwh': m.get('coolingNeedKilowattHours'),
            })
        h = zone.get('hourly')
        if not isinstance(h, dict):
            continue
        init = int(h.get('initializationHours', 0))
        annual = int(h.get('annualHours', 0))
        signed = h.get('signedLoadWatts') or []
        if init < 0 or annual <= 0 or len(signed) != init + annual:
            raise BundleValidationError(f'Invalid thermalBalance hourly length for {zid}.')
        mapping = {
            'signed_load_w': 'signedLoadWatts',
            'air_temp_c': 'airTemperatureCelsius',
            'operative_temp_c': 'operativeTemperatureCelsius',
            'radiant_temp_c': 'meanRadiantTemperatureCelsius',
            'free_floating_temp_c': 'freeFloatingOperativeTemperatureCelsius',
            'solar_gain_w': 'solarGainWatts',
            'rh_pct': 'relativeHumidityPercent',
            'humidification_load_w': 'humidificationLoadWatts',
            'dehumidification_load_w': 'dehumidificationLoadWatts',
        }
        df = pd.DataFrame({'zone_id': zid, 'hour_index': np.arange(1, annual + 1)})
        for target, source in mapping.items():
            a = h.get(source)
            if a is not None:
                if len(a) != len(signed):
                    raise BundleValidationError(f'{source} length mismatch in {zid}.')
                df[target] = np.asarray(a[init:], dtype=float)
        df['heating_load_w'] = df['signed_load_w'].clip(lower=0)
        df['cooling_load_w'] = (-df['signed_load_w']).clip(lower=0)
        months = h.get('monthIndexOneBased')
        if months is not None:
            if len(months) != len(signed):
                raise BundleValidationError(f'Month index length mismatch in {zid}.')
            df['month'] = months[init:]
        hourly_rows.append(df)
    if hourly_rows:
        warnings.append('Hourly data read from legacy result.json. The visualization CSV contract is not present.')
    return (
        pd.concat(hourly_rows, ignore_index=True) if hourly_rows else pd.DataFrame(),
        pd.DataFrame(month_rows), metadata,
    )


def _validate_hourly(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    missing = set(REQUIRED_HOURLY) - set(frame.columns)
    if missing:
        raise BundleValidationError(f'Missing hourly columns: {sorted(missing)}')
    f = frame.copy()
    f['zone_id'] = f['zone_id'].astype(str)
    if f['zone_id'].eq('').any():
        raise BundleValidationError('Blank zone_id in hourly dataset.')
    f['hour_index'] = pd.to_numeric(f['hour_index'], errors='raise')
    if (f['hour_index'] < 1).any() or (f['hour_index'] % 1 != 0).any():
        raise BundleValidationError('hour_index must be a positive integer, excluding initialization.')
    f['hour_index'] = f['hour_index'].astype('int32')
    if f.duplicated(['zone_id', 'hour_index']).any():
        raise BundleValidationError('Duplicate zone/hour records.')
    for c in f.columns:
        if c.endswith(('_w', '_c', '_pct', '_kwh')):
            f[c] = pd.to_numeric(f[c], errors='raise')
            if not np.isfinite(f[c].dropna().to_numpy(dtype='float64')).all():
                raise BundleValidationError(f'Nonfinite values for {c}.')
    if not np.allclose(f['signed_load_w'], f['heating_load_w'] - f['cooling_load_w'], rtol=0, atol=1e-5):
        raise BundleValidationError('Signed thermal load does not equal heating minus cooling.')
    if 'month' in f.columns:
        months = pd.to_numeric(f['month'], errors='raise')
        if months.isna().any() or (~months.between(1, 12)).any():
            raise BundleValidationError('Invalid native monthly indices.')
        f['month'] = months.astype('int8')
    return f.sort_values(['zone_id', 'hour_index']).reset_index(drop=True)


def read_bundle(data: bytes) -> EpbBundle:
    warnings: list[str] = []
    with _validate_archive(data) as z:
        manifest = _json(z, 'manifest.json')
        vm = _json(z, 'visualization/manifest.json')
        if vm and vm.get('schema_version') != 1:
            raise BundleValidationError('Unsupported visualization schema version.')
        if not manifest and not vm:
            raise BundleValidationError('This ZIP has no EPB result manifest.')
        hourly = _csv(z, 'visualization/hourly-thermal.csv')
        tm = _csv(z, 'visualization/monthly-thermal.csv')
        meta = _json(z, 'visualization/zone-metadata.json')
        if hourly.empty and 'result.json' in z.namelist():
            raw = _member(z, 'result.json')
            assert raw is not None
            if len(raw) > 150 * 1024 * 1024:
                warnings.append('Legacy result.json exceeds safe fallback size; only available CSV files loaded.')
            else:
                try:
                    legacy_h, legacy_m, legacy_meta = _native_fallback(json.loads(raw), warnings)
                except (ValueError, TypeError, KeyError) as e:
                    raise BundleValidationError(f'Native thermalBalance cannot be parsed: {e}') from e
                hourly, tm = legacy_h, tm if not tm.empty else legacy_m
                if not meta:
                    meta = legacy_meta
        hourly = _validate_hourly(hourly)
        metrics = _csv(z, 'monthly-metrics.csv')
        if not metrics.empty:
            if not set(MONTH_COLUMNS).issubset(metrics.columns):
                raise BundleValidationError('Invalid monthly-metrics CSV columns.')
            metrics['month'] = pd.to_numeric(metrics['month'], errors='raise')
            metrics['value'] = pd.to_numeric(metrics['value'], errors='raise')
        carrier = _csv(z, 'carrier-ledger.csv')
        scenarios = _csv(z, 'scenario-summary.csv')
        systems = {n: _csv(z, n) for n in SYSTEM_FILES if n in z.namelist()}
        trace = _csv(z, 'visualization/validation-trace.csv')
        if not trace.empty:
            required = {'step','timestamp','initialization','category','quantity','scope','zone_id','object_id','numeric_value','text_value','unit'}
            if not required.issubset(trace.columns):
                raise BundleValidationError('Validation trace is missing required fields.')
            trace['numeric_value'] = pd.to_numeric(trace['numeric_value'],errors='coerce')
            trace['initialization'] = trace['initialization'].astype(str).str.lower().eq('true')
            trace = trace[~trace['initialization']].copy()
            trace['signal'] = trace.category.astype(str) + '.' + trace.quantity.astype(str)
    if not hourly.empty:
        if 'month' in hourly:
            for zone, group in hourly.groupby('zone_id'):
                steps = int(group.hour_index.max())
                if steps in (8760, 8784):
                    reference_months = reference_clock(group.hour_index, annual_hours=steps).month
                    if not np.array_equal(group['month'].to_numpy(), np.asarray(reference_months)):
                        warnings.append(f'{zone}: native month indices differ from reference calendar. Monthly totals use native indices; day/hour dates remain relative visualization coordinates.')
        hrs = hourly.groupby('zone_id').hour_index.agg(['min', 'max', 'count'])
        if (hrs['min'] != 1).any() or (hrs['max'] != hrs['count']).any():
            warnings.append('Some hourly vectors have missing steps; graphs will not fill missing values.')
        if (hrs['count'] > 8784).any():
            warnings.append('More than 8784 reporting hours detected; chronological reference-year display limited.')
    if not vm:
        warnings.append('Legacy ZIP without visualization/manifest.json; export provenance is limited.')
    return EpbBundle(manifest, vm, hourly, tm, metrics, carrier, scenarios, systems, trace, meta, warnings)


METRICS = {
    'heating_load_w': ('Heating load', 'power', 'W'),
    'cooling_load_w': ('Cooling load', 'power', 'W'),
    'signed_load_w': ('Signed heating/cooling load', 'power', 'W'),
    'solar_gain_w': ('Solar heat gains', 'power', 'W'),
    'humidification_load_w': ('Humidification load', 'power', 'W'),
    'dehumidification_load_w': ('Dehumidification load', 'power', 'W'),
    'air_temp_c': ('Air temperature', 'state', '°C'),
    'operative_temp_c': ('Operative temperature', 'state', '°C'),
    'radiant_temp_c': ('Mean radiant temperature', 'state', '°C'),
    'free_floating_temp_c': ('Free-floating operative temperature', 'state', '°C'),
    'rh_pct': ('Relative humidity', 'state', '%'),
}


def thermal_metric_columns(bundle: EpbBundle) -> list[str]:
    return [k for k in METRICS if k in bundle.hourly.columns and bundle.hourly[k].notna().any()]


def reference_clock(hours: pd.Series | np.ndarray, *, annual_hours: int) -> pd.DatetimeIndex:
    if annual_hours not in (8760, 8784):
        raise BundleValidationError('Calendar plots require exactly 8760 or 8784 reporting hours.')
    base = pd.Timestamp(YEAR_8784 if annual_hours == 8784 else YEAR_8760, 1, 1)
    return pd.DatetimeIndex(base + pd.to_timedelta(np.asarray(hours, dtype='int64') - 1, unit='h'))


def aggregate_thermal(bundle: EpbBundle, metric: str, zone_ids: list[str],
                      cadence: str, mode: str = 'Energy (kWh)') -> tuple[pd.DataFrame, str]:
    """Preserves semantic meaning: powers can be integrated, state variables averaged.

    Building scope only sums additive powers. Nonadditive state variables remain
    separate zone lines even when multiple zones are selected.
    """
    if metric not in METRICS or metric not in bundle.hourly.columns:
        raise BundleValidationError('Metric is not available.')
    if cadence not in ('Hour', 'Day', 'Month', 'Year'):
        raise BundleValidationError('Unsupported cadence.')
    title, kind, native_unit = METRICS[metric]
    if kind == 'state' and mode != 'Mean':
        raise BundleValidationError('State variables may only be averaged, never summed.')
    if kind == 'power' and mode not in ('Energy (kWh)', 'Mean power (W)', 'Peak power (W)'):
        raise BundleValidationError('Invalid power aggregation mode.')
    source_columns = ['zone_id', 'hour_index', metric]
    if 'month' in bundle.hourly:
        source_columns.append('month')
    f = bundle.hourly[bundle.hourly.zone_id.isin(zone_ids)][source_columns].dropna(subset=[metric]).copy()
    if f.empty:
        return pd.DataFrame(columns=['time', 'series', 'value']), native_unit
    length = bundle.hourly.groupby('zone_id').hour_index.max()
    if len(set(length.loc[z] for z in zone_ids if z in length.index)) != 1:
        raise BundleValidationError('Selected zones have incompatible reporting durations.')
    annual_hours = int(length.loc[f['zone_id'].iloc[0]])
    f['time'] = reference_clock(f.hour_index, annual_hours=annual_hours)
    if cadence == 'Hour':
        f['period'] = f.time
    elif cadence == 'Day':
        f['period'] = f.time.dt.floor('D')
    elif cadence == 'Month':
        # Prefer the owning native month index, if supplied, rather than silently
        # replacing it with reference-calendar month coordinates.
        if 'month' in f:
            year = YEAR_8784 if annual_hours == 8784 else YEAR_8760
            f['period'] = pd.to_datetime({'year': year, 'month': f['month'], 'day': 1})
        else:
            f['period'] = f.time.dt.to_period('M').dt.to_timestamp()
    else:
        f['period'] = f.time.dt.to_period('Y').dt.to_timestamp()
    # Energy is integrated as power*1 hour / 1000; other aggregations do not
    # implicitly convert the mean W to kWh or sum a temperature.
    grouping = f.groupby(['zone_id', 'period'], sort=True)[metric]
    if kind == 'power' and mode == 'Energy (kWh)':
        values = grouping.sum() / 1000.0
        unit = 'kWh'
    elif kind == 'power' and mode == 'Peak power (W)':
        values = grouping.max()
        unit = 'W'
    else:
        values = grouping.mean()
        unit = native_unit
    r = values.rename('value').reset_index().rename(columns={'zone_id': 'series', 'period': 'time'})
    return r[['time', 'series', 'value']], unit


def building_power(bundle: EpbBundle, metric: str, zone_ids: list[str], cadence: str,
                   mode: str) -> tuple[pd.DataFrame, str]:
    if METRICS[metric][1] != 'power':
        raise BundleValidationError('Building-scope state averaging is prohibited.')
    cols = ['zone_id', 'hour_index', metric]
    if 'month' in bundle.hourly:
        cols.append('month')
    f = bundle.hourly[bundle.hourly.zone_id.isin(zone_ids)][cols].copy()
    if f.empty:
        return pd.DataFrame(columns=['time','series','value']), 'kWh' if mode == 'Energy (kWh)' else 'W'
    wide = f.pivot(index='hour_index', columns='zone_id', values=metric)
    # Require all selected zones at every step; otherwise totals are incomplete.
    if wide.isna().any().any() or set(wide.columns) != set(zone_ids):
        raise BundleValidationError('Building-scope sum requires complete, aligned zone series.')
    summed = wide.sum(axis=1)
    if 'month' in f.columns:
        month_wide = f.pivot(index='hour_index', columns='zone_id', values='month')
        if month_wide.isna().any().any() or month_wide.nunique(axis=1).gt(1).any():
            raise BundleValidationError('Selected zones have inconsistent native month indices.')
        reference_months = month_wide.iloc[:, 0].astype(int).to_numpy()
    else:
        reference_months = None
    pseudo = EpbBundle({}, {}, pd.DataFrame({
        'zone_id': 'Building', 'hour_index': summed.index.to_numpy(), metric: summed.to_numpy(),
    }), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}, pd.DataFrame(), {})
    if reference_months is not None:
        pseudo.hourly['month'] = reference_months
    # Aggregate the selected quantity alone. Fabricated surrogate channels
    # previously replaced building cooling with zeros.
    return aggregate_thermal(pseudo, metric, ['Building'], cadence, mode)
