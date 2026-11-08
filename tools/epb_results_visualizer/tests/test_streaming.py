"""Source-level regressions for selective ISO 52016 and Validation Trace readers."""
from __future__ import annotations

from io import BytesIO, StringIO
import csv
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from epb_results_visualizer.bundle import BundleValidationError, read_bundle
from epb_results_visualizer.streaming import (
    available_source_signals, select_series, time_aggregate,
)


def _csv(header, data):
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(data)
    return buf.getvalue()


@pytest.fixture(scope="module")
def evidence():
    """2 zones, 8760 hours, two initialization steps; all records source-owned."""
    zones = ["z1", "z2"]
    thermal = []
    ventilation = []
    trace = []
    for zone, heat, temp, flow, active in [
        ("z1", 100.0, 20.0, 0.2, 1),
        ("z2", 200.0, 24.0, 0.3, 0),
    ]:
        for hour in range(1, 8761):
            thermal.append([zone, hour, heat, temp, 0.0])
        for step in range(8762):
            initial = "true" if step < 2 else "false"
            for signal, value, unit in [
                ("actual_m3s", flow, "m3/s"),
                ("mechanical_active", active, "bool"),
            ]:
                ventilation.append([step, initial, "ventilation", signal,
                                    zone, value, unit])
            trace.append([step, initial, "thermal", "air_c",
                          zone, temp, "degC"])
    files = {
        "manifest.json": json.dumps({"calculationFingerprint": "valid"}),
        "visualization/manifest.json": json.dumps({
            "schema_version": 1, "annual_hours": 8760, "initialization_hours": 2}),
        "visualization/zone-metadata.json": json.dumps({
            z: {"zoneId": z, "zoneName": z.upper(),
                "floorAreaSquareMetres": 100} for z in zones}),
        "visualization/hourly-thermal.csv": _csv(
            ["zone_id", "hour_index", "heating_load_w", "air_temp_c", "solar_gain_w"],
            thermal),
        "visualization/ventilation-hourly.csv": _csv(
            ["step", "initialization", "category", "quantity", "zone_id",
             "value", "unit"], ventilation),
        "visualization/validation-trace.csv": _csv(
            ["step", "initialization", "category", "quantity", "zone_id",
             "numeric_value", "unit"], trace),
        "visualization/signal-catalog.csv": _csv(
            ["quantity_id", "unit"],
            [("trace.ventilation.actual_m3s", "m3/s"),
             ("trace.ventilation.mechanical_active", "bool"),
             ("trace.thermal.air_c", "degC")]),
        "visualization/monthly-thermal.csv": _csv(
            ["zone_id", "month", "heating_need_kwh", "cooling_need_kwh"],
            [("z1", m, 73, 0) for m in range(1,13)] +
            [("z2", m, 146, 0) for m in range(1,13)]),
    }
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path, content in files.items():
            z.writestr(path, content)
    return out.getvalue()


def test_selective_metadata_does_not_load_raw_hourly_or_trace(evidence):
    result = read_bundle(evidence, metadata_only=True)
    assert result.hourly.empty and result.trace.empty
    assert len(result.zone_metadata) == 2
    assert len(result.thermal_monthly) == 24


def test_building_heating_summed_with_complete_coverage(evidence):
    values = select_series(evidence, source="thermal", scope="building",
                           quantities=["heating_load_w", "solar_gain_w"])
    assert values.n_zones == 2 and len(values.frame) == 8760
    assert (values.frame.heating_load_w == 300).all()
    assert (values.frame.solar_gain_w == 0).all()
    annual, units = time_aggregate(values.frame, values.units, "Year", "Energy")
    assert annual.heating_load_w.iloc[0] == pytest.approx(2628)
    assert units["heating_load_w"] == "kWh"


def test_zone_temperature_not_aggregated_across_building(evidence):
    choices = available_source_signals(evidence, "thermal", "building")
    assert "air_temp_c" not in choices
    with pytest.raises(BundleValidationError):
        select_series(evidence, source="thermal", scope="building",
                      quantities=["air_temp_c"])
    zone = select_series(evidence, source="thermal", scope="zone",
                         zone_id="z2", quantities=["air_temp_c"])
    assert zone.frame.air_temp_c.mean() == 24


def test_zone_trace_excludes_initialization_and_preserves_step(evidence):
    sample = select_series(evidence, source="trace", scope="zone", zone_id="z1",
                           quantities=["thermal.air_c"])
    assert len(sample.frame) == 8760
    assert sample.frame.iloc[0].hour_index == 1
    assert (sample.frame["thermal.air_c"] == 20).all()


def test_building_flow_sum_and_boolean_share(evidence):
    sample = select_series(evidence, source="ventilation", scope="building",
                           quantities=["ventilation.actual_m3s",
                                       "ventilation.mechanical_active"])
    assert (sample.frame["ventilation.actual_m3s"] == 0.5).all()
    assert (sample.frame["ventilation.mechanical_active"] == 50).all()
    derived, units = time_aggregate(sample.frame, sample.units, "Day", "Mean")
    assert units["ventilation.mechanical_active"] == "%"
    assert len(derived) == 365 and derived.iloc[0]["ventilation.mechanical_active"] == 50


def test_missing_zone_hour_is_nan_not_partial_sum(evidence):
    source = BytesIO()
    with zipfile.ZipFile(BytesIO(evidence)) as old, zipfile.ZipFile(
            source, "w", compression=zipfile.ZIP_DEFLATED) as new:
        for name in old.namelist():
            body = old.read(name)
            if name == "visualization/ventilation-hourly.csv":
                f = pd.read_csv(BytesIO(body))
                f = f[~((f.zone_id == "z2") & (f.step == 5) &
                         (f.quantity == "actual_m3s"))]
                body = f.to_csv(index=False).encode("utf-8")
            new.writestr(name, body)
    result = select_series(source.getvalue(), source="ventilation", scope="building",
                           quantities=["ventilation.actual_m3s"])
    assert pd.isna(result.frame.iloc[3]["ventilation.actual_m3s"])
    assert result.missing["ventilation.actual_m3s"] == 1
    day, _ = time_aggregate(result.frame, result.units, "Day")
    assert pd.isna(day.iloc[0]["ventilation.actual_m3s"])


def test_bad_source_zone_and_selection_rejected(evidence):
    with pytest.raises(BundleValidationError):
        select_series(evidence, source="thermal", scope="zone", zone_id="other",
                      quantities=["heating_load_w"])
    with pytest.raises(BundleValidationError):
        select_series(evidence, source="trace", scope="building",
                      quantities=["thermal.air_c"])
    with pytest.raises(BundleValidationError):
        select_series(evidence, source="thermal", scope="building",
                      quantities=["heating_load_w"] * 2)


def test_time_range_keeps_original_hour_reference(evidence):
    sample = select_series(evidence, source="thermal", scope="zone",
                           zone_id="z1", quantities=["heating_load_w"])
    subset = sample.frame.iloc[24:48].copy()
    subset.attrs = sample.frame.attrs.copy()
    day, _ = time_aggregate(subset, sample.units, "Day", "Energy")
    assert len(day) == 1
    assert day.iloc[0].heating_load_w == pytest.approx(2.4)
    assert str(day.time.iloc[0].date()) == "2001-01-02"
