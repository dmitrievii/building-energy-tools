"""Regression checks for multi-ZIP scientific comparison semantics."""
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest

from test_bundle import make_zip
from epb_results_visualizer.bundle import read_bundle, BundleValidationError
from epb_results_visualizer.multi_compare import (
    Study, _thermal, _national, _carrier, _provenance,
)


def pair():
    b = read_bundle(make_zip())
    return [Study('base','Base',b,100), Study('option','Option',b,200)]


def test_heating_cooling_remain_separate_and_integrated():
    studies = pair()
    heat, unit = _thermal(studies,'heating_load_w','Year','Energy (kWh)',{},False)
    cool, unit2 = _thermal(studies,'cooling_load_w','Year','Energy (kWh)',{},False)
    assert unit == unit2 == 'kWh'
    assert heat.value.tolist() == pytest.approx([876,876])
    assert cool.value.tolist() == pytest.approx([438,438])


def test_area_normalization_and_nonadditive_zone_selection():
    studies = pair()
    heat, unit = _thermal(studies,'heating_load_w','Year','Energy (kWh)',{},True)
    assert unit == 'kWh/m²'
    assert heat.value.tolist() == pytest.approx([8.76,4.38])
    with pytest.raises((BundleValidationError, KeyError)):
        _thermal(studies,'air_temp_c','Month','Mean',{},False)
    temps, unit = _thermal(studies,'air_temp_c','Month','Mean',
                           {'base':'A','option':'B'},False)
    assert unit == '°C'
    assert temps[temps.series=='Base'].value.mean() == pytest.approx(20)
    assert temps[temps.series=='Option'].value.mean() == pytest.approx(24)


def test_national_metric_preserves_months_and_units():
    monthly = pd.DataFrame({
        'metric':['HWB']*12,'scenario':['S']*12,'unit':['kWh']*12,
        'month':list(range(1,13)),'value':[10]*12,
    })
    studies=[Study('a','A',SimpleNamespace(monthly_metrics=monthly)),
             Study('b','B',SimpleNamespace(monthly_metrics=monthly.assign(value=15)))]
    d,unit=_national(studies,'HWB','S')
    assert unit=='kWh'
    assert d.groupby('series').value.sum().to_dict() == {'A':120,'B':180}
    with pytest.raises(BundleValidationError):
        _national([Study('a','A',SimpleNamespace(monthly_metrics=monthly.iloc[:11]))],'HWB','S')


def test_carrier_import_export_never_net():
    carrier = pd.DataFrame({
        'carrier':['Electricity']*24,'scenario':['S']*24,
        'month':list(range(1,13))*2,'value_kwh':[20]*12+[2]*12,
        'is_export':[False]*12+[True]*12,
    })
    studies=[Study('a','A',SimpleNamespace(carrier=carrier)),
             Study('b','B',SimpleNamespace(carrier=carrier))]
    consumed,unit=_carrier(studies,'Electricity','S',False)
    exported,unit2=_carrier(studies,'Electricity','S',True)
    assert unit == unit2 == 'kWh'
    assert consumed[consumed.series=='A'].value.sum()==240
    assert exported[exported.series=='A'].value.sum()==24


def test_climate_comparability_provenance_warning():
    studies=[]
    for name, climate in [('A','weather-A'),('B','weather-B')]:
        bundle=SimpleNamespace(manifest={'calculationProfileId':'p1'},
                  visualization_manifest={'climate_fingerprint':climate},
                  has_hourly=False,hourly=pd.DataFrame())
        studies.append(Study(name,name,bundle))
    table,warnings=_provenance(studies)
    assert len(table)==2
    assert any('Weather is different' in msg for msg in warnings)


def test_large_zip_monthly_needs_compare_without_hourly_tables():
    from epb_results_visualizer.multi_compare import _monthly_needs
    monthly = pd.DataFrame({
        'zone_id': ['A'] * 12 + ['B'] * 12,
        'month': list(range(1, 13)) * 2,
        'heating_need_kwh': [100] * 12 + [50] * 12,
        'cooling_need_kwh': [20] * 12 + [10] * 12,
    })
    empty_hourly = pd.DataFrame()
    meta = {'A': {'floorAreaSquareMetres': 60},
            'B': {'floorAreaSquareMetres': 40}}
    bundles = [
        SimpleNamespace(thermal_monthly=monthly, hourly=empty_hourly,
                        zone_metadata=meta),
        SimpleNamespace(thermal_monthly=monthly.assign(heating_need_kwh=monthly.heating_need_kwh * 2),
                        hourly=empty_hourly, zone_metadata=meta),
    ]
    studies = [Study('base', 'Base', bundles[0]), Study('opt', 'Option', bundles[1])]
    compared, unit = _monthly_needs(studies, 'heating_need_kwh', True)
    assert unit == 'kWh/m²'
    assert compared.groupby('series').value.sum().to_dict() == {
        'Base': pytest.approx(18), 'Option': pytest.approx(36)}
    partial = monthly[~((monthly.zone_id == 'B') & (monthly.month == 4))]
    studies[1] = Study('opt','Option',SimpleNamespace(thermal_monthly=partial,
                                       hourly=empty_hourly, zone_metadata=meta))
    with pytest.raises(BundleValidationError, match="Incomplete"):
        _monthly_needs(studies, 'heating_need_kwh', False)
