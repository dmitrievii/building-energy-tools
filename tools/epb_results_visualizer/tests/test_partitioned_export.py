"""Native EPB Rhino V3.4 fast-path tests (legacy streams must not be scanned)."""
from io import BytesIO
import zipfile
import hashlib

import pandas as pd
import pytest

from test_bundle import make_zip
from epb_results_visualizer.streaming import select_series, available_source_signals
from epb_results_visualizer.bundle import read_bundle


@pytest.fixture(scope="module")
def indexed_export():
    raw = make_zip()
    zone_id = "A"
    key = hashlib.sha256(zone_id.encode()).hexdigest()
    zone_path = f"visualization/zones/{key}/hourly-thermal.csv"
    trace_path = f"visualization/zones/{key}/validation-trace.csv"
    hours = range(1, 8761)
    zone_hourly = pd.DataFrame({
        "zone_id": [zone_id] * 8760, "hour_index": hours,
        "heating_load_w": [100] * 8760,
        "cooling_load_w": [0] * 8760,
        "air_temp_c": [21] * 8760,
    })
    building = pd.DataFrame({
        "hour_index": hours,
        "heating_load_w": [100] * 8760,
        "cooling_load_w": [50] * 8760,
        "solar_gain_w": [30] * 8760,
        "zone_count": [2] * 8760,
    })
    records = pd.DataFrame({
        "hour_index": hours,
        "category": ["thermal"] * 8760,
        "quantity": ["air_c"] * 8760,
        "numeric_value": [21] * 8760,
    })
    append = {
        "visualization/zone-metadata.json": '{"A":{"zoneName":"A"},"B":{"zoneName":"B"}}',
        "visualization/zones.csv": "zone_id,floor_area_m2\nA,100\nB,100\n",
        "visualization/zone-index.csv":
            f"zone_id,hourly_thermal_path,reporting_hours,source\nA,{zone_path},8760,test\n",
        "visualization/trace-zone-index.csv":
            f"zone_id,validation_trace_path,reporting_records,source\nA,{trace_path},8760,test\n",
        zone_path: zone_hourly.to_csv(index=False),
        trace_path: records.to_csv(index=False),
        "visualization/building-hourly.csv": building.to_csv(index=False),
        "visualization/signal-catalog.csv":
            "quantity_id,unit\ntrace.thermal.air_c,degC\n",
    }
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(raw)) as original, zipfile.ZipFile(
            out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in original.namelist():
            if name in append:
                continue
            # Empty incompatible legacy source to ensure a failed indirect
            # path would be observable in the test.
            data = original.read(name)
            if name == "visualization/hourly-thermal.csv":
                data = b"zone_id,hour_index\ninvalid,not-an-hour\n"
            z.writestr(name, data)
        for name, content in append.items():
            z.writestr(name, content)
    return out.getvalue()


def test_large_export_metadata_only_still_fast(indexed_export):
    bundle = read_bundle(indexed_export, metadata_only=True)
    assert bundle.hourly.empty and bundle.trace.empty


def test_building_hour_direct_with_no_legacy_bulk_read(indexed_export):
    result = select_series(indexed_export, source="thermal", scope="building",
                           quantities=["heating_load_w", "cooling_load_w"])
    assert result.scanned_rows == 8760
    assert result.n_zones == 2
    assert result.missing == {"heating_load_w": 0, "cooling_load_w": 0}
    assert result.frame.heating_load_w.sum() == pytest.approx(876000)
    assert result.frame.cooling_load_w.sum() == pytest.approx(438000)


def test_one_zone_direct_without_other_zone_legacy_csv(indexed_export):
    result = select_series(indexed_export, source="thermal", scope="zone", zone_id="A",
                           quantities=["air_temp_c", "heating_load_w"])
    assert result.scanned_rows == 8760
    assert result.frame.air_temp_c.mean() == 21
    assert (result.frame.heating_load_w == 100).all()


def test_trace_zone_direct_without_full_trace_scan(indexed_export):
    assert "thermal.air_c" in available_source_signals(indexed_export, "trace", "zone")
    result = select_series(indexed_export, source="trace", scope="zone", zone_id="A",
                           quantities=["thermal.air_c"])
    assert result.scanned_rows == 8760
    assert result.frame["thermal.air_c"].mean() == 21


def test_zone_partitions_reject_unlisted_zone(indexed_export):
    from epb_results_visualizer.bundle import BundleValidationError
    with pytest.raises(BundleValidationError, match="no captured source partition"):
        select_series(indexed_export, source="trace", scope="zone", zone_id="B",
                      quantities=["thermal.air_c"])
