"""Read-only comparison of independent EPB Rhino result archives."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import math
import zipfile

import pandas as pd
import streamlit as st

from .bundle import BundleValidationError, METRICS, read_bundle, building_power, aggregate_thermal, thermal_metric_columns
from .charts import ChartSettings, timeline_chart, plotly_configuration


@dataclass(frozen=True)
class Study:
    key: str
    label: str
    bundle: object
    area_m2: float | None = None


def load_studies(uploads) -> list[Study]:
    if len(uploads) > 8:
        raise BundleValidationError('At most eight ZIP archives can be compared.')
    sources = [(f.name, f.getvalue()) for f in uploads]
    if sum(len(b) for _, b in sources) > 800 * 1024 * 1024:
        raise BundleValidationError('Combined ZIP upload exceeds 800 MiB; load fewer large bundles.')
    expanded = 0
    for name, payload in sources:
        try:
            with zipfile.ZipFile(BytesIO(payload)) as z:
                expanded += sum(x.file_size for x in z.infolist())
        except (zipfile.BadZipFile, OSError) as exc:
            raise BundleValidationError(f'Invalid ZIP: {name}') from exc
        if expanded > 16 * 1024 * 1024 * 1024:
            raise BundleValidationError('Archive manifest total exceeds 16 GiB; load fewer large bundles.')
    cache = st.session_state.setdefault('epb_bundle_cache', {})
    distinct, seen = [], set()
    for name, payload in sources:
        key = sha256(payload).hexdigest()
        if key in seen:
            st.warning(f'Identical ZIP ignored: {name}')
            continue
        seen.add(key)
        if key not in cache:
            # Never inflate massive trace tables at upload time. Source CSVs
            # are streamed only after a scope and quantity have been chosen.
            with zipfile.ZipFile(BytesIO(payload)) as z:
                large = (len(payload) > 90 * 1024 * 1024 or
                         any(m.filename in (
                             'visualization/validation-trace.csv',
                             'visualization/ventilation-hourly.csv') and
                             m.file_size > 80 * 1024 * 1024 for m in z.infolist()))
            cache[key] = read_bundle(payload, metadata_only=large)
        distinct.append((key, Path(name).stem, cache[key]))
    st.session_state['epb_bundle_cache'] = {key: cache[key] for key in seen if key in cache}
    if len(distinct) < 2:
        return [Study(*item) for item in distinct]
    result = []
    with st.expander('Variant names and conditioned floor areas', expanded=False):
        for key, default, bundle in distinct:
            label = st.text_input('Name · '+default, value=default, key='cmp_label_'+key).strip()
            input_area = st.text_input('Area in m² (optional) · '+default, value='', key='cmp_area_'+key)
            try:
                area = float(input_area.replace(',','.')) if input_area.strip() else None
            except ValueError as exc:
                raise BundleValidationError('Invalid floor area for '+label) from exc
            if area is not None and (area <= 0 or not math.isfinite(area)):
                raise BundleValidationError('Conditioned area must be finite and positive.')
            result.append(Study(key, label, bundle, area))
    labels = [s.label for s in result]
    if not all(labels) or len(set(labels)) != len(labels):
        raise BundleValidationError('Names must be unique and nonempty.')
    return result


def _provenance(studies):
    rows = []
    for s in studies:
        a, b = s.bundle.manifest, s.bundle.visualization_manifest
        def first(*items):
            for item in items:
                if item is not None and str(item).strip():
                    return str(item)
            return None
        climate = first(b.get('climate_fingerprint'),b.get('climate_sha256'),
                        a.get('climateFingerprint'),a.get('weatherFileSha256'))
        profile = first(b.get('calculation_profile_id'),a.get('calculationProfileId'))
        hours = int(s.bundle.hourly.hour_index.max()) if s.bundle.has_hourly else None
        rows.append(dict(variant=s.label, climate_id=climate, calculation_profile=profile,
                         simulation_hours=hours, area_m2=s.area_m2))
    table = pd.DataFrame(rows)
    issues = []
    for col, title in [('climate_id','Weather'),('calculation_profile','Calculation profile')]:
        values = table[col].dropna().unique()
        if len(values) > 1:
            issues.append(title+' is different across the uploaded calculations.')
        elif len(values) < 1 or table[col].isna().any():
            issues.append(title+' equivalence is not confirmed in every manifest.')
    if len(table.simulation_hours.dropna().unique()) > 1:
        issues.append('Simulation duration differs; temporal overlap must be checked.')
    return table, issues


def _thermal(studies, metric, cadence, mode, zones, normalize):
    frames, units = [], set()
    for study in studies:
        bundle = study.bundle
        if metric not in thermal_metric_columns(bundle):
            raise BundleValidationError('Metric absent: '+study.label)
        if METRICS[metric][1] == 'power':
            allzones = sorted(bundle.hourly.zone_id.unique().tolist())
            d, unit = building_power(bundle, metric, allzones, cadence, mode)
        else:
            d, unit = aggregate_thermal(bundle, metric, [zones[study.key]], cadence, 'Mean')
        if d.empty or d.series.nunique() != 1:
            raise BundleValidationError('Missing or ambiguous series: '+study.label)
        d = d[['time','value']].copy()
        if normalize:
            if unit != 'kWh' or not study.area_m2:
                raise BundleValidationError('Area normalization requires energy and provided areas.')
            d.value /= study.area_m2
            unit = 'kWh/m²'
        d['series'] = study.label
        units.add(unit)
        frames.append(d)
    if len(units) != 1:
        raise BundleValidationError('Mixed units; series cannot be overlaid.')
    return pd.concat(frames, ignore_index=True), next(iter(units))


def _national(studies, metric, scenario):
    frames, unit = [], None
    for study in studies:
        df = study.bundle.monthly_metrics
        df = df[(df.metric.astype(str)==metric) & (df.scenario.astype(str)==scenario)].copy()
        if df.empty or df.month.duplicated().any():
            raise BundleValidationError('Absent/ambiguous national monthly metric: '+study.label)
        df.month = pd.to_numeric(df.month,errors='raise').astype(int)
        if sorted(df.month.tolist()) != list(range(1,13)):
            raise BundleValidationError('Incomplete national year for '+study.label)
        u = df.unit.dropna().astype(str).unique()
        if len(u) != 1 or (unit is not None and unit != u[0]):
            raise BundleValidationError('Mixed national indicator units.')
        unit = u[0]
        df['time'] = pd.to_datetime({'year':2001,'month':df.month,'day':1})
        df['value'] = pd.to_numeric(df.value,errors='raise')
        df['series'] = study.label
        frames.append(df[['time','value','series']])
    return pd.concat(frames,ignore_index=True), unit


def _carrier(studies, carrier, scenario, export):
    frames = []
    for study in studies:
        d = study.bundle.carrier
        if d.empty or 'is_export' not in d:
            raise BundleValidationError('Carrier ledger missing: '+study.label)
        d = d[(d.carrier.astype(str)==carrier) & (d.scenario.astype(str)==scenario)].copy()
        out = d.is_export.astype(str).str.lower().isin(['1','true'])
        d = d[out==export].copy()
        if d.empty:
            raise BundleValidationError('Flow missing in '+study.label+' (missing is not zero).')
        d.month = pd.to_numeric(d.month,errors='raise').astype(int)
        if not d.month.between(1,12).all():
            raise BundleValidationError('Invalid carrier month.')
        d.value_kwh = pd.to_numeric(d.value_kwh,errors='raise')
        d = d.groupby('month',as_index=False).value_kwh.sum().rename(columns={'value_kwh':'value'})
        d['time'] = pd.to_datetime({'year':2001,'month':d.month,'day':1})
        d['series'] = study.label
        frames.append(d[['time','value','series']])
    return pd.concat(frames,ignore_index=True), 'kWh'


def _graph(frame, unit, settings, title, key):
    cfg = ChartSettings(settings.width,settings.height,settings.font_size,
                        settings.legend,settings.line_width,title)
    fig = timeline_chart(frame,unit=unit,settings=cfg,chart_type='Line')
    st.plotly_chart(fig,use_container_width=False,config=plotly_configuration(cfg),key=key)
    st.download_button('Export CSV',frame.to_csv(index=False).encode('utf-8-sig'),
                       file_name=key+'.csv',mime='text/csv',key='export-'+key)


def section_comparison(studies, settings):
    st.subheader('Compare buildings and design variants')
    same = st.radio('Comparison scope',['Architectural variants of one building','Different buildings'],horizontal=True)
    provenance, problems = _provenance(studies)
    st.dataframe(provenance,hide_index=True,use_container_width=True)
    for problem in problems:
        st.warning(problem)
    if same=='Different buildings':
        st.info('Different buildings may have different use, geometry, area and climate; numerical differences do not establish design improvement.')
    baseline = st.selectbox('Baseline',[s.label for s in studies])
    family = st.radio('Dataset',['ISO 52016 thermal','National indicators','Carrier ledger'],horizontal=True)
    try:
        if family=='ISO 52016 thermal':
            common = set(thermal_metric_columns(studies[0].bundle))
            for s in studies[1:]:
                common &= set(thermal_metric_columns(s.bundle))
            if not common:
                st.info('No thermal metric shared across all archives.')
                return
            metric = st.selectbox('Quantity',sorted(common),format_func=lambda k:METRICS[k][0])
            cadence = st.radio('Time resolution',['Hour','Day','Month','Year'],index=2,horizontal=True)
            kind = METRICS[metric][1]
            mode = st.selectbox('Aggregation',['Energy (kWh)','Mean power (W)','Peak power (W)']) if kind=='power' else 'Mean'
            zones = {}
            if kind!='power':
                st.caption('Nonadditive states are never averaged across buildings or summed across zones.')
                for s in studies:
                    zones[s.key] = st.selectbox('Zone · '+s.label,sorted(s.bundle.hourly.zone_id.unique()),key='cmp_zone_'+s.key)
            norm = st.checkbox('Normalize energy by supplied conditioned floor area [kWh/m²]') if kind=='power' and mode=='Energy (kWh)' else False
            frame, unit = _thermal(studies,metric,cadence,mode,zones,norm)
        elif family=='National indicators':
            if any(s.bundle.monthly_metrics.empty for s in studies):
                st.info('A ZIP lacks monthly national indicators.')
                return
            metrics = set(studies[0].bundle.monthly_metrics.metric.astype(str))
            scenarios = set(studies[0].bundle.monthly_metrics.scenario.astype(str))
            for s in studies[1:]:
                metrics &= set(s.bundle.monthly_metrics.metric.astype(str))
                scenarios &= set(s.bundle.monthly_metrics.scenario.astype(str))
            if not metrics or not scenarios:
                st.info('No shared native indicator and scenario.')
                return
            metric = st.selectbox('National indicator',sorted(metrics))
            scenario = st.selectbox('Scenario',sorted(scenarios))
            frame, unit = _national(studies,metric,scenario)
        else:
            if any(s.bundle.carrier.empty for s in studies):
                st.info('A ZIP lacks carrier ledger.')
                return
            carriers = set(studies[0].bundle.carrier.carrier.astype(str))
            scenarios = set(studies[0].bundle.carrier.scenario.astype(str))
            for s in studies[1:]:
                carriers &= set(s.bundle.carrier.carrier.astype(str))
                scenarios &= set(s.bundle.carrier.scenario.astype(str))
            if not carriers or not scenarios:
                st.info('No shared carrier and scenario.')
                return
            carrier = st.selectbox('Carrier',sorted(carriers))
            scenario = st.selectbox('Scenario',sorted(scenarios))
            direction = st.radio('Flow',['Import / onsite consumption','Export'],horizontal=True)
            frame, unit = _carrier(studies,carrier,scenario,direction=='Export')
        _graph(frame,unit,settings,'Overlaid independent calculations','epb-overlay')
        if unit in ('kWh','kWh/m²'):
            annual = frame.groupby('series',as_index=False).value.sum()
            annual['unit'] = unit
            st.markdown('#### Period totals')
            st.dataframe(annual,hide_index=True,use_container_width=True)
        pivot = frame.pivot(index='time',columns='series',values='value')
        if pivot.isna().any().any():
            st.warning('Unmatched or missing periods: baseline deltas are unavailable.')
            return
        d = pivot.drop(columns=[baseline]).subtract(pivot[baseline],axis=0)
        relative = st.checkbox('Show relative delta (%)')
        if relative:
            d = d.div(pivot[baseline].replace(0,float('nan')),axis=0)*100
        out = d.stack(dropna=False).rename('value').reset_index().rename(columns={'level_1':'series'})
        out['series'] = out['series']+' − '+baseline
        if out.value.isna().any():
            st.warning('Percent delta is undefined where baseline equals zero; no zero values are fabricated.')
        st.markdown('#### Difference from baseline')
        _graph(out[['time','series','value']], '%' if relative else unit,settings,
               'Variant minus baseline','epb-delta')
    except (BundleValidationError,ValueError,KeyError,TypeError) as exc:
        st.error(str(exc))
