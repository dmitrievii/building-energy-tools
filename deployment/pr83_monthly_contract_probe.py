from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Callable, TypeVar

import pandas as pd
import requests

from epw_climate_analyzer import geosphere
from epw_climate_analyzer.geosphere_monthly import (
    MONTHLY_RESOURCE_ID,
    ensure_monthly_resource_registered,
    fetch_monthly_dataset,
)
from epw_climate_analyzer.source_parity_contract_guard import install_contract_guards
from epw_climate_analyzer import source_parity_contract_closure as contract
from epw_climate_analyzer import source_parity_monthly_canonical as monthly_ui


OUTPUT = Path("artifacts/pr83-contract-smoke/monthly-provider.json")
REQUIRED = ("tl_mittel", "rf_mittel", "p")
OPTIONAL = ("tp_mittel", "rr", "so_h")
T = TypeVar("T")


def _network_retry(label: str, operation: Callable[[], T], attempts: int = 3) -> T:
    """Retry only transient HTTP transport failures; semantic failures stay immediate."""
    delays_s = (2.0, 6.0)
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except requests.RequestException as exc:
            if attempt >= attempts:
                raise
            delay = delays_s[min(attempt - 1, len(delays_s) - 1)]
            print(
                f"Transient GeoSphere network failure during {label} "
                f"(attempt {attempt}/{attempts}): {exc}. Retrying in {delay:g} s...",
                flush=True,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


def _station(metadata: dict) -> geosphere.GeoSphereStation:
    stations = geosphere.parse_stations(metadata)
    preferred = [station for station in stations if str(station.station_id) == "105"]
    if preferred:
        return preferred[0]
    for station in stations:
        if "wien" in station.name.lower() and "warte" in station.name.lower():
            return station
    raise RuntimeError("Could not resolve Wien Hohe Warte in klima-v2-1m metadata.")


def main() -> int:
    ensure_monthly_resource_registered()
    metadata = _network_retry(
        "monthly metadata",
        lambda: geosphere.fetch_metadata(resource_id=MONTHLY_RESOURCE_ID, timeout_s=30),
    )
    parsed = geosphere.parse_parameters(metadata)
    missing = [name for name in REQUIRED if name not in parsed]
    if missing:
        raise RuntimeError(f"Monthly metadata is missing required parameter(s): {missing}")

    station = _station(metadata)
    selected = list(REQUIRED) + [name for name in OPTIONAL if name in parsed]
    start = pd.Timestamp("2020-01-01T00:00:00Z")
    end = pd.Timestamp("2025-12-31T23:59:59Z")
    dataset = _network_retry(
        "monthly station data",
        lambda: fetch_monthly_dataset(
            station=station,
            start=start,
            end=end,
            metadata=metadata,
            provider_parameters=selected,
            timeout_s=60,
        ),
    )

    frame = monthly_ui.monthly_analysis_frame(dataset)
    frame = contract.monthly_psychrometric_frame(dataset, frame)
    install_contract_guards()

    valid_t = int(pd.to_numeric(frame["dry_bulb_temperature_c"], errors="coerce").notna().sum())
    valid_rh = int(pd.to_numeric(frame["relative_humidity_pct"], errors="coerce").notna().sum())
    if valid_t < 12 or valid_rh < 12:
        raise RuntimeError(f"Insufficient monthly T/RH observations: T={valid_t}, RH={valid_rh}")

    dew_point = pd.to_numeric(frame.get("dew_point_temperature_c"), errors="coerce").dropna()
    if dew_point.empty:
        raise RuntimeError("Derived monthly dew-point temperature is unavailable.")

    seasonal_t = contract.monthly_period_values(frame, "dry_bulb_temperature_c", "Seasonal")
    annual_t = contract.monthly_period_values(frame, "dry_bulb_temperature_c", "Annual")
    if seasonal_t.empty or annual_t.empty:
        raise RuntimeError("Seasonal/Annual temperature aggregation returned no values.")

    pressure = pd.to_numeric(frame.get("atmospheric_station_pressure_pa"), errors="coerce").dropna()
    if pressure.empty:
        raise RuntimeError("Measured monthly station pressure is unavailable.")
    fallback = float(pressure.mean())

    profile = contract.monthly_psychrometric_profile(frame, fallback)
    if profile.empty:
        raise RuntimeError("Monthly psychrometric profile is empty.")
    if len(profile) > 12:
        raise RuntimeError(f"Monthly psychrometric profile contains {len(profile)} points, expected <= 12.")
    for column in (
        "humidity_ratio_g_kg",
        "moist_air_enthalpy_kj_kg",
        "wet_bulb_temperature_c",
        "specific_volume_m3_kg",
        "moist_air_density_kg_m3",
    ):
        if column not in profile or not pd.to_numeric(profile[column], errors="coerce").notna().any():
            raise RuntimeError(f"Derived monthly psychrometric property unavailable: {column}")

    report = {
        "success": True,
        "resource_id": MONTHLY_RESOURCE_ID,
        "station_id": station.station_id,
        "station_name": station.name,
        "selected_provider_parameters": selected,
        "loaded_rows": int(len(dataset.data)),
        "valid_temperature_months": valid_t,
        "valid_relative_humidity_months": valid_rh,
        "valid_dew_point_months": int(len(dew_point)),
        "measured_station_pressure_months": int(len(pressure)),
        "seasonal_temperature_periods": int(len(seasonal_t)),
        "annual_temperature_periods": int(len(annual_t)),
        "psychrometric_profile_points": int(len(profile)),
        "psychrometric_months": [int(value) for value in profile["month_index"].tolist()],
        "reference_pressure_pa": fallback,
        "representative_state_note": frame.attrs.get("canonical_monthly_psychrometric_semantics", ""),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
