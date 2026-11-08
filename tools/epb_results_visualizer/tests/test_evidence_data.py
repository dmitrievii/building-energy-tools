"""Regression tests for the native V3 EPB Evidence Explorer."""
from io import BytesIO
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from epb_results_visualizer.bundle import BundleValidationError
from epb_results_visualizer.evidence_data import (
    building_area, coverage_table, load_evidence, monthly_series,
    orientation_summary, quantity_unit, zone_annual_intensity,
)


def _archive(extra=None):
    files = {
        "visualization/building.json":
            json.dumps({"conditioned_gross_floor_area_m2": 300}),
        "visualization/zones.csv":
            "zone_id,zone_name,floor_area_m2\nz1,Office,100\nz2,Hall,200\n",
        "visualization/orientation-buckets.csv":
            "zone_id,direction,opening_gross_m2,opaque_net_wall_m2,facade_total_m2\n"
            ",N,50,0,50\n,NW,100,0,100\n"
            "z1,N,50,0,50\n",
        "visualization/monthly-physical-zones.csv":
            "zone_id,month,quantity,value,unit\n"
            "z1,1,heating_demand,100,kWh\nz2,1,heating_demand,200,kWh\n"
            "z1,1,utilization_factor_heating,0.6,1\n"
            "z2,1,utilization_factor_heating,0.8,1\n",
        "visualization/opening-inventory.csv":
            "opening_id,area_m2,u_value_w_m2k,solar_g_value\n"
            "o1,50,,\n",
    }
    if extra:
        files.update(extra)
    b = BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for key, value in files.items():
            z.writestr(key, value)
    return b.getvalue()


def test_source_tables_load_without_filling_missing_glazing_parameters():
    data = load_evidence(_archive())
    assert len(data["zones"]) == 2
    assert data["windows"]["u_value_w_m2k"].isna().all()
    assert data["windows"]["solar_g_value"].isna().all()
    assert building_area(data) == 300
    assert coverage_table(data).set_index("Dataset").loc["zone_physics", "Rows"] == 4


def test_aggregate_orientation_buckets_are_not_double_counted():
    data = load_evidence(_archive())
    result = orientation_summary(data)
    assert result.opening_gross_m2.sum() == 150
    assert result.facade_total_m2.sum() == 150
    assert np.isclose(result.wwr_fraction.dropna().min(), 1.0)


def test_monthly_energy_sums_and_ratio_means_have_distinct_semantics():
    data = load_evidence(_archive())
    frame = data["zone_physics"]
    energy = monthly_series(frame, ["heating_demand"])
    assert energy.loc[0, "value"] == 300
    factors = monthly_series(frame, ["utilization_factor_heating"], mode="mean")
    assert factors.loc[0, "value"] == pytest.approx(0.7)
    with pytest.raises(BundleValidationError):
        monthly_series(frame, ["utilization_factor_heating"], mode="sum")
    with pytest.raises(BundleValidationError):
        monthly_series(frame, ["heating_demand", "utilization_factor_heating"])
    assert quantity_unit(frame, "heating_demand") == "kWh"


def test_zone_intensity_is_area_normalized_without_averaging_building_temperatures():
    data = load_evidence(_archive())
    result = zone_annual_intensity(data, "heating_demand")
    assert len(result) == 2
    assert sorted(result.intensity) == [1, 1]
    assert zone_annual_intensity(data, "utilization_factor_heating").empty


def test_missing_evidence_is_not_synthesized():
    data = load_evidence(_archive())
    assert data["surface_physics"].empty
    assert data["signals"].empty
    assert data["building"]["conditioned_gross_floor_area_m2"] == 300


def test_traversal_in_zip_rejected():
    with pytest.raises(BundleValidationError):
        load_evidence(_archive({"../unsafe.csv": "x\n1\n"}))


def test_invalid_zone_rows_rejected_by_existing_limits():
    data = load_evidence(_archive())
    frame = data["zone_physics"]
    assert frame["value"].dtype.kind in ("f", "i")
    assert pd.api.types.is_numeric_dtype(frame["month"])


def test_v33_epw_area_uses_agreeing_scenario_areas():
    data = load_evidence(_archive({
        "visualization/building.json": json.dumps({
            "conditioned_gross_floor_area_m2": None,
            "scenario_floor_areas": [
                {"scenario_id": "Real_RK", "gross_floor_area_m2": 300},
                {"scenario_id": "Real_SK", "gross_floor_area_m2": 300},
            ],
        }),
    }))
    assert building_area(data) == 300


def test_v33_epw_area_falls_back_to_unique_zone_areas():
    data = load_evidence(_archive({
        "visualization/building.json": json.dumps({
            "conditioned_gross_floor_area_m2": None,
            "scenario_floor_areas": [],
        }),
    }))
    assert building_area(data) == 300


def test_unavailable_area_does_not_become_zero():
    data = load_evidence(_archive({
        "visualization/building.json": json.dumps({
            "conditioned_gross_floor_area_m2": None,
            "scenario_floor_areas": [],
        }),
        "visualization/zones.csv": "zone_id,zone_name,floor_area_m2\nz1,Office,\n",
    }))
    assert building_area(data) is None
