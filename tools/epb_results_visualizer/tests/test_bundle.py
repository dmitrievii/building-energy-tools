from __future__ import annotations
from io import BytesIO
import json
import os
import sys
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from epb_results_visualizer.bundle import (
    BundleValidationError, read_bundle, aggregate_thermal, building_power,
    thermal_metric_columns, reference_clock,
)
from epb_results_visualizer.charts import ChartSettings, timeline_chart, calendar_heatmap


def make_zip(*, schema=True, bad=False, legacy=False, trace=True):
    hourly = pd.DataFrame({
        'zone_id':['A']*8760+['B']*8760,
        'hour_index':list(range(1,8761))*2,
        'signed_load_w':[100]*8760+[-50]*8760,
        'heating_load_w':[100]*8760+[0]*8760,
        'cooling_load_w':[0]*8760+[50]*8760,
        'air_temp_c':[20]*8760+[24]*8760,
        'rh_pct':[40]*8760+[60]*8760,
    })
    if bad:
        hourly.loc[0,'cooling_load_w']=1000
    out=BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json',json.dumps({'release':'TEST ONLY','calculationFingerprint':'f123','isComplete':True}))
        z.writestr('monthly-metrics.csv','scenario,metric,unit,month,value\nS1,HWB,kWh,1,12\n')
        z.writestr('carrier-ledger.csv','scenario,path,carrier,use,is_export,source_id,month,value_kwh\nS1,p,Electricity,Heating,false,x,1,3\n')
        if schema:
            z.writestr('visualization/manifest.json',json.dumps({'schema_version':1}))
            z.writestr('visualization/hourly-thermal.csv',hourly.to_csv(index=False))
        if legacy:
            native = {'thermalBalance': {'zones': [{'zoneId':'A','months':[], 'hourly': {
                'initializationHours':2, 'annualHours':8760,
                'signedLoadWatts':[1,2]+[100]*8760,
                'airTemperatureCelsius':[0,0]+[20]*8760,
                'operativeTemperatureCelsius':[0,0]+[20]*8760,
                'meanRadiantTemperatureCelsius':[0,0]+[20]*8760,
                'solarGainWatts':[0,0]+[5]*8760,
                'monthIndexOneBased':None}}]}}
            z.writestr('result.json',json.dumps(native))
        if trace:
            z.writestr('visualization/validation-trace.csv',(
                'step,timestamp,period_label,initialization,category,quantity,scope,zone_id,object_id,node_index,numeric_value,text_value,unit\n'
                '0,2001-01-01T00:00:00+00:00,,true,thermal,air_c,Zone,A,,,19,,C\n'
                '1,2001-01-01T01:00:00+00:00,,false,thermal,air_c,Zone,A,,,20,,C\n'
            ))
    return out.getvalue()


def test_import_new_zip_hourly_and_trace():
    b=read_bundle(make_zip())
    assert len(b.hourly)==17520
    assert len(b.trace)==1
    assert b.hourly.zone_id.nunique()==2
    assert 'air_temp_c' in thermal_metric_columns(b)
    assert not b.monthly_metrics.empty


def test_energy_sum_no_zone_cancellation():
    b=read_bundle(make_zip())
    h,unit=aggregate_thermal(b,'heating_load_w',['A','B'],'Year','Energy (kWh)')
    assert unit=='kWh'
    assert h.set_index('series').value.to_dict()=={'A':pytest.approx(876),'B':0}
    c,unit=aggregate_thermal(b,'cooling_load_w',['A','B'],'Year','Energy (kWh)')
    assert c.set_index('series').value.to_dict()=={'A':0,'B':pytest.approx(438)}
    total,unit=building_power(b,'heating_load_w',['A','B'],'Year','Energy (kWh)')
    assert total.iloc[0].value==pytest.approx(876)


def test_nonadditive_state_never_summed():
    b=read_bundle(make_zip())
    df,unit=aggregate_thermal(b,'air_temp_c',['A','B'],'Month','Mean')
    assert unit=='°C'
    assert df.series.nunique()==2
    assert set(df.groupby('series').value.mean())=={20,24}
    with pytest.raises(BundleValidationError):
        aggregate_thermal(b,'air_temp_c',['A'],'Day','Energy (kWh)')
    with pytest.raises(BundleValidationError):
        building_power(b,'air_temp_c',['A','B'],'Day','Mean power (W)')


def test_cadence_integral_and_reference_year():
    b=read_bundle(make_zip())
    day,unit=aggregate_thermal(b,'heating_load_w',['A'],'Day','Energy (kWh)')
    assert len(day)==365 and day.iloc[0].value==pytest.approx(2.4)
    month,unit=aggregate_thermal(b,'heating_load_w',['A'],'Month','Energy (kWh)')
    assert len(month)==12 and month.iloc[0].value==pytest.approx(74.4)
    assert month.value.sum()==pytest.approx(876)
    assert reference_clock(pd.Series([1, 8784]),annual_hours=8784)[-1].year == 2000


def test_bad_signed_load_rejected():
    with pytest.raises(BundleValidationError,match='Signed thermal load'):
        read_bundle(make_zip(bad=True))


def test_legacy_zip_and_initialization_exclusion():
    b=read_bundle(make_zip(schema=False,legacy=True,trace=False))
    assert len(b.hourly)==8760
    assert b.hourly.iloc[0].signed_load_w==100
    assert 'Legacy ZIP' in ' '.join(b.warnings)


def test_security_traversal_and_schema_version():
    out=BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('../escape.txt','bad')
        z.writestr('manifest.json','{}')
    with pytest.raises(BundleValidationError,match='Unsafe'):
        read_bundle(out.getvalue())
    out=BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('manifest.json','{}')
        z.writestr('visualization/manifest.json',json.dumps({'schema_version':42}))
    with pytest.raises(BundleValidationError,match='schema'):
        read_bundle(out.getvalue())


def test_plotly_presentation_and_heatmap():
    b=read_bundle(make_zip())
    df,_=aggregate_thermal(b,'air_temp_c',['A'],'Hour','Mean')
    cfg=ChartSettings(width=1200,height=700,font_size=19,legend='Right')
    fig=timeline_chart(df,unit='°C',settings=cfg)
    assert fig.layout.width==1200 and fig.layout.height==700
    heat=calendar_heatmap(df,unit='°C',settings=cfg)
    assert heat.data[0].z.shape==(24,365)
