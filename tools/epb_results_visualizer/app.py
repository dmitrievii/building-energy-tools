"""EPB Results Visualizer — isolated Streamlit app, Climate Analyzer design language.

Run from repository root:
  streamlit run tools/epb_results_visualizer/app.py
"""
from __future__ import annotations

import re
import hashlib
import pandas as pd
import streamlit as st

from epb_results_visualizer.bundle import (
    BundleValidationError, METRICS, aggregate_thermal, building_power,
    read_bundle, reference_clock, thermal_metric_columns,
)
from epb_results_visualizer.charts import (
    ChartSettings, timeline_chart, duration_chart, calendar_heatmap,
    monthly_metrics_figure, plotly_configuration,
)

from epb_results_visualizer.multi_compare import load_studies, section_comparison

st.set_page_config(page_title='EPB Results Visualizer | IVANCALC', page_icon='📊', layout='wide')


def _load(payload: bytes):
    # Cache only within this Streamlit session: uploaded project data must not be
    # a shared application cache entry accessible to another session.
    fingerprint = hashlib.sha256(payload).hexdigest()
    if st.session_state.get('loaded_bundle_sha256') != fingerprint:
        loaded = read_bundle(payload)
        st.session_state['loaded_bundle'] = loaded
        st.session_state['loaded_bundle_sha256'] = fingerprint
    return st.session_state['loaded_bundle']


def chart_settings() -> ChartSettings:
    st.sidebar.markdown('### Chart presentation')
    preset = st.sidebar.selectbox('Canvas', ['16:9 Wide', '4:3 Presentation', '1:1 Square', 'Custom'], index=0)
    dimensions = {'16:9 Wide': (1280,720), '4:3 Presentation': (1200,900), '1:1 Square':(900,900)}
    initial_w, initial_h = dimensions.get(preset, (1200,700))
    if preset == 'Custom':
        width = st.sidebar.slider('Chart width (px)', 600, 2200, 1200, step=50)
        height = st.sidebar.slider('Chart height (px)', 350, 1600, 700, step=50)
    else:
        scale = st.sidebar.slider('Canvas scale', 50, 150, 100, step=10)
        width, height = round(initial_w*scale/100), round(initial_h*scale/100)
    font = st.sidebar.slider('Font size (pt)', 10, 26, 15)
    legend = st.sidebar.radio('Legend position', ['Top', 'Right'], horizontal=True)
    lw = st.sidebar.slider('Line width (px)', 1, 5, 2)
    return ChartSettings(width=width, height=height, font_size=font, legend=legend, line_width=lw)


def _show_chart(fig, settings: ChartSettings, key: str, frame: pd.DataFrame | None = None):
    st.plotly_chart(fig, use_container_width=False, config=plotly_configuration(settings), key=key)
    st.caption('Zoom or pan interactively. The Plotly camera icon exports vector SVG at the chosen canvas size.')
    if frame is not None and not frame.empty:
        st.download_button('Export displayed data (CSV)', frame.to_csv(index=False).encode('utf-8-sig'),
                           file_name=f'{key}.csv', mime='text/csv', key=f'dl-{key}')


def section_thermal(bundle, settings: ChartSettings):
    st.subheader('Thermal balance · ISO 52016')
    st.caption('Hourly thermal results are visualization-only. Initialization hours are excluded. ' 
               'Reference-year dates are chart coordinates, not source EPW timestamps.')
    metrics = thermal_metric_columns(bundle)
    if not metrics:
        st.warning('No hourly ISO 52016 vectors in this export. The monthly sections remain available.')
        return
    zones = sorted(bundle.hourly.zone_id.unique().tolist())
    c1,c2,c3 = st.columns([2,2,2])
    with c1:
        metric = st.selectbox('Physical quantity', metrics, format_func=lambda x: METRICS[x][0])
    with c2:
        scope = st.selectbox('Scope', ['Separate zones', 'Building sum'] if METRICS[metric][1] == 'power' else ['Separate zones'])
    with c3:
        cadence = st.selectbox('Time resolution', ['Hour', 'Day', 'Month', 'Year'], index=2)
    selected_zones = st.multiselect('Thermal zones', zones, default=zones[:min(5,len(zones))])
    if not selected_zones:
        st.info('Choose at least one zone.')
        return
    if METRICS[metric][1] == 'power':
        mode = st.radio('Aggregation meaning', ['Energy (kWh)', 'Mean power (W)', 'Peak power (W)'], horizontal=True)
    else:
        mode = 'Mean'
        st.caption('Temperatures and relative humidity are averaged over each reporting interval, never summed across zones.')
    try:
        if scope == 'Building sum':
            plotted, unit = building_power(bundle, metric, selected_zones, cadence, mode)
        else:
            plotted, unit = aggregate_thermal(bundle, metric, selected_zones, cadence, mode)
    except (BundleValidationError, ValueError) as e:
        st.error(str(e))
        return
    if plotted.empty:
        st.info('The selected quantity has no values for the selected zone(s).')
        return
    lo,hi = plotted.time.min().date(), plotted.time.max().date()
    chosen = st.date_input('Period', value=(lo,hi), min_value=lo, max_value=hi, key='thermal-period')
    if isinstance(chosen, tuple) and len(chosen)==2:
        start,end = chosen
        plotted = plotted[(plotted.time.dt.date >= start) & (plotted.time.dt.date <= end)]
    kind = st.selectbox('Chart type', ['Line', 'Bar', 'Duration curve'] + (['Calendar heatmap'] if cadence == 'Hour' else []))
    title = f'{METRICS[metric][0]} · {cadence.lower()} · {mode}'
    configured = ChartSettings(settings.width, settings.height, settings.font_size,settings.legend,settings.line_width,title)
    if kind == 'Duration curve':
        fig = duration_chart(plotted, unit=unit, settings=configured)
    elif kind == 'Calendar heatmap':
        if plotted.series.nunique() != 1:
            st.warning('Select one zone or a building sum to display the calendar heatmap.')
            return
        fig = calendar_heatmap(plotted, unit=unit, settings=configured)
    else:
        fig = timeline_chart(plotted, unit=unit, settings=configured, chart_type=kind)
    _show_chart(fig, configured, 'thermal-results', plotted)
    c1,c2,c3 = st.columns(3)
    c1.metric('Minimum', f'{plotted.value.min():,.2f} {unit}')
    c2.metric('Maximum', f'{plotted.value.max():,.2f} {unit}')
    if mode == 'Energy (kWh)':
        c3.metric('Selected-period energy', f'{plotted.value.sum():,.1f} kWh')
    else:
        c3.metric('Mean of displayed intervals', f'{plotted.value.mean():,.2f} {unit}')
    if cadence == 'Year' and unit == 'kWh':
        st.caption('Annual sums apply only to the selected series and reporting period; they do not imply final/fuel energy.')


def section_monthly(bundle, settings: ChartSettings):
    st.subheader('Monthly indicators & certificate ledger')
    df = bundle.monthly_metrics
    if df.empty:
        st.warning('No monthly-metrics.csv available.')
        return
    scenarios = sorted(df.scenario.dropna().astype(str).unique())
    scenario = st.selectbox('Scenario', scenarios)
    subset = df[df.scenario.astype(str) == scenario]
    metrics = sorted(subset.metric.dropna().astype(str).unique())
    selected = st.multiselect('Indicators', metrics, default=metrics[:min(4,len(metrics))])
    if not selected:
        st.info('Choose an indicator.')
        return
    selected_df = subset[subset.metric.astype(str).isin(selected)].copy()
    units = selected_df.unit.dropna().astype(str).unique()
    if len(units) != 1:
        st.warning('Selected indicators have different units. Choose indicators with a common unit; no mixed-unit charts are generated.')
        st.dataframe(selected_df, use_container_width=True)
        return
    graph_df = selected_df.rename(columns={'metric':'series'})
    fig = monthly_metrics_figure(graph_df, settings=ChartSettings(
        settings.width,settings.height,settings.font_size,settings.legend,settings.line_width,
        'Monthly energy indicators · ' + scenario), unit=units[0])
    _show_chart(fig, settings, 'monthly-indicators', graph_df)
    st.dataframe(selected_df, use_container_width=True, hide_index=True)
    st.caption('The imported certificate indicators are displayed without recalculation or conversion.')


def section_systems(bundle, settings: ChartSettings):
    st.subheader('Physical systems · hourly research traces')
    st.warning('Non-additive physical/research evidence. These series are NOT extra H5050 final-energy postings.')
    if not bundle.systems:
        st.info('No hourly system research CSVs were exported.')
        return
    filename = st.selectbox('Dataset', list(bundle.systems))
    df = bundle.systems[filename]
    if 'hour_index' not in df.columns:
        st.dataframe(df.head(500),use_container_width=True)
        return
    candidates = [c for c in df.columns if re.search(r'(_kwh|_c|_watts|_w|_litres|_kg)$',c)
                  and pd.api.types.is_numeric_dtype(df[c])]
    if not candidates:
        st.dataframe(df.head(500),use_container_width=True)
        return
    scope_cols = [c for c in ('system_id','generator_id','plant_id','circuit_id','zone_id') if c in df.columns]
    col1,col2 = st.columns(2)
    with col1:
        metric = st.selectbox('Quantity', candidates)
    with col2:
        cadence = st.selectbox('Resolution', ['Hour','Day','Month','Year'], index=2,key='sys-cadence')
    if scope_cols:
        group_col = st.selectbox('System identifier',scope_cols)
        choices = sorted(df[group_col].dropna().astype(str).unique())
        selected = st.multiselect('Systems',choices,default=choices[:min(4,len(choices))])
        df = df[df[group_col].astype(str).isin(selected)].copy()
    else:
        group_col = '_scope'
        df = df.assign(_scope=filename)
    if df.empty:
        st.info('No selected system data.')
        return
    # Preserve each trace's own hour index; no fabricated zone-to-system totals.
    try:
        df['hour_index'] = pd.to_numeric(df['hour_index'], errors='raise').astype(int)
        n = int(df.hour_index.max())
        if n not in (8760,8784) or df.hour_index.min() != 1:
            st.info('This system trace is not a complete canonical year; displaying raw simulation hour index.')
            d = df.rename(columns={group_col:'series', 'hour_index':'time',metric:'value'})
            fig = timeline_chart(d[['time','series','value']], unit=metric, settings=settings)
            fig.update_xaxes(title='System hour index (not calendar date)')
            _show_chart(fig, settings, 'system-hour-index', d)
            return
        df['time'] = reference_clock(df.hour_index,annual_hours=n)
        df['period'] = {'Hour':df.time, 'Day':df.time.dt.floor('D'),
                        'Month':df.time.dt.to_period('M').dt.to_timestamp(),
                        'Year':df.time.dt.to_period('Y').dt.to_timestamp()}[cadence]
        v = pd.to_numeric(df[metric],errors='raise')
        if metric.endswith('_kwh'):
            mode = st.radio('Energy aggregation', ['Total kWh', 'Average kWh per hour'],horizontal=True)
            agg = 'sum' if mode == 'Total kWh' else 'mean'
        else:
            mode = st.radio('State/quantity aggregation', ['Mean','Maximum'],horizontal=True)
            agg = 'mean' if mode == 'Mean' else 'max'
        df['value'] = v
        d = df.groupby([group_col,'period'],as_index=False).value.agg(agg)
        d = d.rename(columns={group_col:'series','period':'time'})
        fig = timeline_chart(d, unit=metric.split('_')[-1],settings=settings)
        _show_chart(fig,settings,'system-trace',d)
    except (BundleValidationError,ValueError) as e:
        st.error(str(e))


def section_trace(bundle, settings: ChartSettings):
    st.subheader('Validation Trace · controls, ventilation and equipment')
    df = bundle.trace
    if df.empty:
        st.info('No validation trace in this ZIP. Connect Calculate → Trace to Result Export → Trace and enable Trace Settings to capture these signals.')
        return
    st.caption('Captured signals only. The importer excludes initialization records; missing signals are not synthesized.')
    c1,c2,c3 = st.columns(3)
    with c1:
        category = st.selectbox('Category', sorted(df.category.astype(str).unique()))
    f = df[df.category.astype(str)==category].copy()
    with c2:
        signal = st.selectbox('Signal', sorted(f.signal.astype(str).unique()))
    f=f[f.signal==signal].copy()
    with c3:
        scope = st.selectbox('Object scope', sorted(f.scope.astype(str).unique()))
    f = f[f.scope.astype(str)==scope].copy()
    if 'zone_id' in f:
        zones = sorted(f.zone_id.dropna().astype(str).unique())
        chosen_zones = st.multiselect('Zone IDs',zones,default=zones[:min(8,len(zones))], key='trace-zones')
        f=f[f.zone_id.astype(str).isin(chosen_zones)].copy()
    if 'object_id' in f and f.object_id.notna().any():
        objects=sorted(f.object_id.dropna().astype(str).unique())
        selected_objects=st.multiselect('Object IDs',objects,default=objects[:min(8,len(objects))])
        f=f[f.object_id.astype(str).isin(selected_objects)]
    if f.empty:
        st.info('No matching records.')
        return
    if f.numeric_value.notna().sum() == 0:
        st.caption('This signal consists of categorical control states, not a numeric time series.')
        cols=[c for c in ['step','timestamp','zone_id','object_id','node_index','text_value','unit'] if c in f]
        st.dataframe(f[cols].head(10000),use_container_width=True,hide_index=True)
        st.download_button('Export state transitions (CSV)',f[cols].to_csv(index=False).encode('utf-8-sig'),
                           file_name='validation-states.csv',mime='text/csv')
        return
    f=f[f.numeric_value.notna()].copy()
    unit_values=f.unit.dropna().astype(str).unique()
    if len(unit_values)!=1:
        st.warning('Mixed-unit trace. Separate the quantity before aggregation.')
        st.dataframe(f.head(500),use_container_width=True)
        return
    unit=unit_values[0]
    f['series']=f.zone_id.fillna('').astype(str)+' / '+f.object_id.fillna('').astype(str)
    if 'node_index' in f:
        f['series']+= ' / node '+f.node_index.fillna('').astype(str)
    try:
        # Exact source timestamps are preserved in the CSV; UI uses normalized UTC for cross-offset alignment.
        f['time']=pd.to_datetime(f.timestamp,utc=True,errors='raise').dt.tz_localize(None)
    except (ValueError,TypeError):
        st.warning('Timestamps are not calendar-compatible; displaying the native simulation step.')
        f['time']=pd.to_numeric(f.step,errors='raise')
        st.dataframe(f.head(500),use_container_width=True)
        return
    cadence=st.radio('Resolution',['Hour','Day','Month','Year'],horizontal=True,key='trace-cadence')
    if cadence=='Hour':
        f['period']=f.time.dt.floor('h')
    elif cadence=='Day':
        f['period']=f.time.dt.floor('D')
    elif cadence=='Month':
        f['period']=f.time.dt.to_period('M').dt.to_timestamp()
    else:
        f['period']=f.time.dt.to_period('Y').dt.to_timestamp()
    if unit.lower() in ('kwh','wh','kj','mj'):
        agg=st.radio('Energy per recorded step', ['Sum','Mean'],horizontal=True)
        action='sum' if agg=='Sum' else 'mean'
    else:
        agg=st.radio('Aggregation', ['Mean','Maximum','Minimum'],horizontal=True)
        action={'Mean':'mean','Maximum':'max','Minimum':'min'}[agg]
        st.caption('No summation of temperature, concentration, power or state quantities. The unit remains unchanged.')
    # Do not combine distinct objects or thermal-node scopes in one line.
    plotted=f.groupby(['series','period'],as_index=False).numeric_value.agg(action)
    plotted=plotted.rename(columns={'period':'time','numeric_value':'value'})
    configured=ChartSettings(settings.width,settings.height,settings.font_size,settings.legend,
                              settings.line_width,signal+' · '+scope+' · '+agg)
    fig=timeline_chart(plotted,unit=unit,settings=configured)
    fig.update_xaxes(title='Trace source timestamp (UTC)')
    _show_chart(fig,configured,'validation-trace',plotted)
    st.caption('Trace values are not automatically added to certificate energy; source timestamps are shown in UTC.')


def section_ledger(bundle, settings: ChartSettings):
    st.subheader('Carrier ledger · national reporting')
    df = bundle.carrier
    if df.empty:
        st.info('No carrier-ledger.csv was provided.')
        return
    st.caption('The following values are imported native national ledger rows, not recomputed from physical research traces.')
    c1,c2 = st.columns(2)
    with c1:
        choices = sorted(df.scenario.dropna().astype(str).unique())
        scenario = st.selectbox('Scenario',choices,key='ledger-scenario')
    with c2:
        carrier = st.multiselect('Energy carrier', sorted(df.carrier.dropna().astype(str).unique()),
                                 default=sorted(df.carrier.dropna().astype(str).unique()))
    f = df[(df.scenario.astype(str)==scenario)&df.carrier.astype(str).isin(carrier)].copy()
    if f.empty:
        st.info('No matching carrier entries.')
        return
    group_by = st.selectbox('Group by', ['carrier','use','source_id','path'])
    f['value_kwh'] = pd.to_numeric(f.value_kwh, errors='coerce')
    f['month'] = pd.to_numeric(f.month, errors='coerce')
    if 'is_export' in f:
        flow = st.radio('Flow type',['Import / onsite consumption','Export'],horizontal=True)
        export_values = f.is_export.astype(str).str.lower().isin(['true','1'])
        f = f[export_values if flow=='Export' else ~export_values]
    d = f.groupby([group_by,'month'],as_index=False).value_kwh.sum().rename(columns={group_by:'series','value_kwh':'value'})
    fig = monthly_metrics_figure(d,unit='kWh',settings=settings)
    _show_chart(fig,settings,'carrier-ledger',d)
    st.dataframe(f,use_container_width=True,hide_index=True)


def section_overview(bundle):
    st.subheader('Calculation overview')
    m = bundle.manifest
    vm = bundle.visualization_manifest
    st.caption('Source: native EPB Rhino export. Viewer has no energy-calculation or compliance authority.')
    c = st.columns(4)
    c[0].metric('Calculation status',str(m.get('isComplete','Unknown')))
    c[1].metric('Thermal zones',str(bundle.hourly.zone_id.nunique() if not bundle.hourly.empty else len(bundle.zone_metadata)))
    c[2].metric('Hourly samples',f'{len(bundle.hourly):,}')
    c[3].metric('Captured trace records',f'{len(bundle.trace):,}')
    st.markdown('**Provenance**')
    st.json({
        'release': m.get('release') or vm.get('release'),
        'calculation_fingerprint': m.get('calculationFingerprint') or vm.get('calculation_fingerprint'),
        'profile': m.get('calculationProfileId') or vm.get('calculation_profile_id'),
        'exported_at_utc': m.get('exportedAtUtc'),
        'visualization_schema': vm.get('schema_version','legacy'),
        'clock': vm.get('time_basis','Reference calendar; exact EPW timestamps not exported'),
    },expanded=False)
    if not bundle.scenarios.empty:
        st.markdown('**Scenario summary**')
        st.dataframe(bundle.scenarios,use_container_width=True,hide_index=True)
    if not bundle.thermal_monthly.empty:
        st.markdown('**Zone monthly thermal demand**')
        st.dataframe(bundle.thermal_monthly,use_container_width=True,hide_index=True)


def section_quality(bundle):
    st.subheader('Data quality and export coverage')
    st.markdown('The viewer checks archive safety, thermal sign consistency, zone/hour uniqueness and the availability of monthly and hourly evidence.')
    data = [
        ('Visualization manifest', bool(bundle.visualization_manifest)),
        ('ISO 52016 hourly thermal data',bundle.has_hourly),
        ('ISO 52016 monthly zone results',not bundle.thermal_monthly.empty),
        ('National monthly metrics',not bundle.monthly_metrics.empty),
        ('Carrier ledger',not bundle.carrier.empty),
        ('System research traces',bool(bundle.systems)),
        ('Validation Trace',not bundle.trace.empty),
    ]
    st.dataframe(pd.DataFrame(data,columns=['Dataset','Present']),use_container_width=True,hide_index=True)
    if bundle.warnings:
        for w in bundle.warnings:
            st.warning(w)
    else:
        st.success('No importer warnings.')
    st.markdown('**Interpretation constraints:** reference calendar is synthetic; no building temperature averaging; missing signals are not zero. ' 
                'System research traces and certificate energy are not summed together. PNG/SVG uses the Plotly browser exporter.')


def main():
    st.title('IVANCALC · EPB Results Visualizer')
    st.markdown('Explore hourly EPB Rhino results and compare independent buildings or architectural design variants.')
    uploads = st.file_uploader('Upload EPB Rhino Result Export ZIP archives', type=['zip'],
                               accept_multiple_files=True, max_upload_size=100, key='epb_uploads',
                               help='One ZIP opens individual analyses; 2–8 ZIPs enable comparative analysis.')
    if not uploads:
        st.session_state.pop('epb_bundle_cache', None)
        st.info('Upload one ZIP for individual results or several ZIP files to compare independent calculations.')
        return
    try:
        studies = load_studies(uploads)
    except (BundleValidationError, ValueError, KeyError, RuntimeError, OSError) as exc:
        st.error('ZIP rejected: '+str(exc))
        return
    if not studies:
        st.info('No distinct valid ZIP archives selected.')
        return
    st.sidebar.title('Analysis navigation')
    pages = ['Overview','Thermal balance','Energy systems','Validation Trace',
             'National indicators','Carrier ledger','Data quality']
    if len(studies) > 1:
        pages.insert(1,'Compare buildings / variants')
    page = st.sidebar.radio('Section', pages, index=1 if len(studies)>1 else 0)
    settings = chart_settings()
    if page == 'Compare buildings / variants':
        section_comparison(studies, settings)
    else:
        if len(studies)>1:
            index = st.sidebar.selectbox('Individual ZIP',range(len(studies)),
                          format_func=lambda n:studies[n].label,key='epb_chosen_file')
            bundle = studies[index].bundle
        else:
            bundle = studies[0].bundle
        for warning in bundle.warnings:
            st.sidebar.warning(warning)
        if page == 'Overview':
            section_overview(bundle)
        elif page == 'Thermal balance':
            section_thermal(bundle, settings)
        elif page == 'Energy systems':
            section_systems(bundle, settings)
        elif page == 'Validation Trace':
            section_trace(bundle, settings)
        elif page == 'National indicators':
            section_monthly(bundle, settings)
        elif page == 'Carrier ledger':
            section_ledger(bundle, settings)
        else:
            section_quality(bundle)
    st.divider()
    st.caption('Independent visualization only: no physical or regulatory results are recalculated. '
               'Files are processed within the Streamlit session; hosting-provider retention is separate.')


if __name__=='__main__':
    main()
