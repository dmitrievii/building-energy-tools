#!/usr/bin/env python3
"""Canonical source-certified station-pressure semantics for IGE P9.3B2D onward.

Do not infer absolute/site pressure from field name P; DWD varies across
product families. This registry is deliberately explicit, no name fallback.
Historical research scripts P9.3B2/B2C carry a documented erratum.
"""
from __future__ import annotations
import math

REGISTRY = {
    "DWD_HOURLY_P0": {
        "station": "P0", "sea_level": "P", "unit": "hPa",
        "native_qc": "QN_8", "source": "DWD CDC climate/hourly/pressure",
        "time_support": "hour-stamped observation"},
    "DWD_URBAN_10MIN": {
        "station": "P0_ST_10", "sea_level": "PP_ST_10", "unit": "hPa",
        "native_qc": "QN", "source": "DWD CDC climate_urban/10_minutes/pressure",
        "time_support": "instant at original 10-minute timestamp"},
    "DWD_SUBDAILY_PP": {
        "station": "PP_TER", "sea_level": None, "unit": "hPa",
        "native_qc": "QN_4", "source": "DWD CDC climate/subdaily/pressure",
        "time_support": "synoptic observation at original term"},
    "GEOSPHERE_KLIMA_1H": {
        "station": "p", "sea_level": "pred", "unit": "hPa",
        "native_qc": "p_flag", "source": "GeoSphere Austria klima-v2-1h",
        "time_support": "provider original 1h support"},
    "METEOSWISS_SMN_1H": {
        "station": "prestah0", "sea_level": "pp0qffh0", "unit": "hPa",
        "native_qc": None, "source": "MeteoSwiss OGD SwissMetNet 1h",
        "time_support": "UTC hour-end aggregate from previous hour"},
}


def original_absolute_station_pressure(row, product):
    """Strict original source read, no P0/PP/QFF fallback or sea-level alias."""
    if product not in REGISTRY:
        raise ValueError("IGE_UNKNOWN_PRESSURE_PRODUCT_NO_SEMANTICS")
    field=REGISTRY[product]["station"]
    if field not in row or row[field] is None or str(row[field]).strip()=="":
        return None
    try:
        p=float(str(row[field]).strip())
    except (ValueError,TypeError):
        return None
    if not (math.isfinite(p) and 450<p<1100):
        return None
    return p


def pressure_qc_tier(row,product):
    if product not in REGISTRY:
        raise ValueError("IGE_UNKNOWN_PRESSURE_PRODUCT_NO_QC")
    qfield=REGISTRY[product]["native_qc"]
    if qfield is None:
        return "PUBLISHED_SOURCE_WITHOUT_COMPARABLE_PER_SAMPLE_QC"
    q=str(row.get(qfield) or "").strip()
    if q=="10":
        return "DWD_QN10_FINAL" if product.startswith("DWD") else "PROVIDER_QC10"
    if q=="3":
        return "DWD_QN3_AUTOMATIC" if product.startswith("DWD") else "PROVIDER_QC3"
    if q=="":
        return "NATIVE_QC_FIELD_EMPTY"
    return "SOURCE_QC_OTHER_"+q


def synthetic_contracts():
    assert REGISTRY["DWD_HOURLY_P0"]["station"]=="P0"
    assert REGISTRY["DWD_HOURLY_P0"]["sea_level"]=="P"
    assert REGISTRY["DWD_URBAN_10MIN"]["station"]=="P0_ST_10"
    assert REGISTRY["DWD_URBAN_10MIN"]["sea_level"]=="PP_ST_10"
    assert REGISTRY["DWD_SUBDAILY_PP"]["station"]=="PP_TER"
    assert original_absolute_station_pressure({"P0":"937.0","P":"1025.0"}, "DWD_HOURLY_P0")==937.
    assert original_absolute_station_pressure({"P":"1025.0"}, "DWD_HOURLY_P0") is None
    assert original_absolute_station_pressure({"PP_ST_10":"1025.0"}, "DWD_URBAN_10MIN") is None
    assert original_absolute_station_pressure({"P0_ST_10":"982.4","PP_ST_10":"1013.5"},
                                             "DWD_URBAN_10MIN")==982.4
    assert original_absolute_station_pressure({"PP_TER":"911.2"}, "DWD_SUBDAILY_PP")==911.2
    assert original_absolute_station_pressure({"p": 969.1,"pred":1013.},
                                              "GEOSPHERE_KLIMA_1H")==969.1
    assert original_absolute_station_pressure({"prestah0":"852.1","pp0qffh0":"1010."},
                                              "METEOSWISS_SMN_1H")==852.1
    assert original_absolute_station_pressure({"P0_ST_10":"-999"},
                                              "DWD_URBAN_10MIN") is None
    assert pressure_qc_tier({"QN":""},"DWD_URBAN_10MIN")=="NATIVE_QC_FIELD_EMPTY"
    assert pressure_qc_tier({"QN_8":3},"DWD_HOURLY_P0")=="DWD_QN3_AUTOMATIC"
    assert pressure_qc_tier({"QN_8":10},"DWD_HOURLY_P0")=="DWD_QN10_FINAL"
    print("P93B2D_ORIGINAL_PRESSURE_FIELD_SEMANTICS_CONTRACTS_PASS")


if __name__=="__main__":
    synthetic_contracts()
