"""Canonical multi-source climate comparison facade.

Comparison is defined over normalized analysis DataFrames plus canonical location
and provenance metadata.  It is not defined over EPW files. Existing plotting
builders that already consume only ``.data``/identity fields are reused behind
this facade; the remaining EPW-specific summary/location assumptions are
implemented here in source-neutral form.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .aggregations import native_interval_hours
from .climate_model import CanonicalClimateDataset, ClimateLocation, ClimateProvenance
from .decisions import (
    comfort_condition,
    dehumidification_condition,
    economizer_condition,
    humidification_condition,
    natural_ventilation_condition,
    night_flushing_condition,
    shading_condition,
)
from .historical import prepare_historical_analysis_frame
from .comparison import (
    choose_display_mode,
    data_quality_matrix,
    difference_heatmap_chart,
    duration_comparison_chart,
    facade_radiation_comparison_chart,
    hdd_cdd_grouped_chart,
    heatmap_small_multiples,
    heating_cooling_season_timeline,
    monthly_box_compare_chart,
    monthly_difference_chart,
    monthly_profile_table,
    natural_ventilation_monthly_table,
    orientation_tilt_small_multiples,
    overlay_monthly_chart,
    passive_strategy_calendar_small_multiples,
    passive_strategy_stacked_comparison,
    psychrometric_comparison_chart,
    ranked_metric_chart,
    small_multiple_monthly_chart,
    solar_monthly_comparison,
    sun_path_comparison_chart,
    tilt_radiation_comparison_chart,
    wind_rose_small_multiples,
)


@dataclass(frozen=True)
class ComparisonClimate:
    climate_id: str
    display_name: str
    source: str
    location: ClimateLocation
    data: pd.DataFrame
    provenance: ClimateProvenance | None = None
    issues: tuple[object, ...] = ()
    calendar_mode: str = "unknown"


def comparison_from_canonical(
    dataset: CanonicalClimateDataset,
    *,
    data: pd.DataFrame | None = None,
    source: str | None = None,
) -> ComparisonClimate:
    return ComparisonClimate(
        climate_id=dataset.climate_id,
        display_name=dataset.display_name,
        source=source or f"{dataset.provenance.provider} | {dataset.provenance.dataset}",
        location=dataset.location,
        data=(dataset.data if data is None else data),
        provenance=dataset.provenance,
        issues=(),
        calendar_mode=dataset.temporal.calendar_mode,
    )


def prepare_canonical_comparison_climate(
    dataset: CanonicalClimateDataset,
    *,
    fallback_pressure_pa: float,
    pressure_override_pa: float | None = None,
    analysis_clock_mode: str = "source",
    local_timezone_name: str | None = None,
    standard_utc_offset_hours: float | None = None,
) -> ComparisonClimate:
    """Build the complete hourly comparison state from any canonical source."""
    frame = prepare_historical_analysis_frame(
        dataset,
        include_psychrometrics=True,
        include_solar=True,
        fallback_pressure_pa=float(fallback_pressure_pa),
        pressure_override_pa=pressure_override_pa,
        analysis_clock_mode=analysis_clock_mode,
        local_timezone_name=local_timezone_name,
        standard_utc_offset_hours=standard_utc_offset_hours,
    )
    return comparison_from_canonical(dataset, data=frame)


def _series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def _duration_hours(mask: pd.Series, df: pd.DataFrame) -> float:
    return float(mask.fillna(False).sum()) * float(native_interval_hours(df))


def climate_summary_metrics(climates: list[ComparisonClimate]) -> pd.DataFrame:
    """Calculate capability-aware comparison metrics without source assumptions."""
    rows: list[dict[str, object]] = []
    for climate in climates:
        df = climate.data
        t = _series(df, "dry_bulb_temperature_c")
        ghi = _series(df, "global_horizontal_radiation_wh_m2")
        dni = _series(df, "direct_normal_radiation_wh_m2")
        dhi = _series(df, "diffuse_horizontal_radiation_wh_m2")
        d = _series(df, "humidity_ratio_g_kg")
        h = _series(df, "moist_air_enthalpy_kj_kg")
        twb = _series(df, "wet_bulb_temperature_c")
        wind = _series(df, "wind_speed_m_s")
        interval_h = float(native_interval_hours(df))
        daily_min = t.resample("D").min() if t.notna().any() else pd.Series(dtype=float)
        diffuse_share = float(dhi.sum(min_count=1) / ghi.sum(min_count=1) * 100.0) if float(ghi.sum(min_count=1) or 0.0) > 0 else np.nan

        def decision_hours(function) -> float:
            try:
                return _duration_hours(function(df), df)
            except (KeyError, ValueError, TypeError):
                return np.nan

        rows.append(
            {
                "Climate": climate.display_name,
                "Provider": climate.provenance.provider if climate.provenance else climate.source,
                "Calendar mode": climate.calendar_mode,
                "City": climate.location.city,
                "Country": climate.location.country,
                "Latitude [deg]": climate.location.latitude,
                "Longitude [deg]": climate.location.longitude,
                "Elevation [m]": climate.location.elevation_m,
                "Annual mean T [°C]": float(t.mean()) if t.notna().any() else np.nan,
                "Annual min T [°C]": float(t.min()) if t.notna().any() else np.nan,
                "Annual max T [°C]": float(t.max()) if t.notna().any() else np.nan,
                "T P01 [°C]": float(t.quantile(0.01)) if t.notna().any() else np.nan,
                "T P99 [°C]": float(t.quantile(0.99)) if t.notna().any() else np.nan,
                "HDD18 [K·h]": float((18.0 - t).clip(lower=0).sum(min_count=1) * interval_h) if t.notna().any() else np.nan,
                "CDD26 [K·h]": float((t - 26.0).clip(lower=0).sum(min_count=1) * interval_h) if t.notna().any() else np.nan,
                "Frost hours [h]": _duration_hours(t < 0.0, df) if t.notna().any() else np.nan,
                "Hot hours >30 °C [h]": _duration_hours(t > 30.0, df) if t.notna().any() else np.nan,
                "Tropical nights [d]": int((daily_min > 20.0).sum()) if not daily_min.empty else np.nan,
                "Mean humidity ratio [g/kg]": float(d.mean()) if d.notna().any() else np.nan,
                "Humidity ratio P95 [g/kg]": float(d.quantile(0.95)) if d.notna().any() else np.nan,
                "Hours d >10 g/kg [h]": _duration_hours(d > 10.0, df) if d.notna().any() else np.nan,
                "Hours d <3 g/kg [h]": _duration_hours(d < 3.0, df) if d.notna().any() else np.nan,
                "Enthalpy P95 [kJ/kg]": float(h.quantile(0.95)) if h.notna().any() else np.nan,
                "Maximum wet-bulb [°C]": float(twb.max()) if twb.notna().any() else np.nan,
                "Annual GHI [kWh/m²]": float(ghi.sum(min_count=1) / 1000.0) if ghi.notna().any() else np.nan,
                "Annual DNI [kWh/m²]": float(dni.sum(min_count=1) / 1000.0) if dni.notna().any() else np.nan,
                "Annual DHI [kWh/m²]": float(dhi.sum(min_count=1) / 1000.0) if dhi.notna().any() else np.nan,
                "Diffuse share [%]": diffuse_share,
                "Mean wind speed [m/s]": float(wind.mean()) if wind.notna().any() else np.nan,
                "Wind speed P95 [m/s]": float(wind.quantile(0.95)) if wind.notna().any() else np.nan,
                "Calm hours <1 m/s [h]": _duration_hours(wind < 1.0, df) if wind.notna().any() else np.nan,
                "Strong wind hours >8 m/s [h]": _duration_hours(wind > 8.0, df) if wind.notna().any() else np.nan,
                "Comfort hours [h]": decision_hours(comfort_condition),
                "Natural ventilation hours [h]": decision_hours(natural_ventilation_condition),
                "Night flushing hours [h]": decision_hours(night_flushing_condition),
                "Shading indicator hours [h]": decision_hours(shading_condition),
                "Economizer hours [h]": decision_hours(economizer_condition),
                "Dehumidification hours [h]": decision_hours(dehumidification_condition),
                "Humidification hours [h]": decision_hours(humidification_condition),
                "Data-quality issue count": len(climate.issues),
            }
        )
    return pd.DataFrame(rows)


def comparison_interpretation(metrics: pd.DataFrame, reference: str | None = None) -> str:
    """Create a compact interpretation using only metrics available to all rows."""
    if metrics.empty:
        return "No comparison metrics are available."
    parts: list[str] = []
    temperature = metrics.dropna(subset=["Annual mean T [°C]"])
    if not temperature.empty:
        warm = temperature.loc[temperature["Annual mean T [°C]"].idxmax()]
        cold = temperature.loc[temperature["Annual mean T [°C]"].idxmin()]
        parts.append(
            f"{warm['Climate']} has the highest mean dry-bulb temperature ({warm['Annual mean T [°C]']:.1f} °C); "
            f"{cold['Climate']} has the lowest ({cold['Annual mean T [°C]']:.1f} °C)."
        )
    solar = metrics.dropna(subset=["Annual GHI [kWh/m²]"])
    if not solar.empty:
        leader = solar.loc[solar["Annual GHI [kWh/m²]"].idxmax()]
        parts.append(f"Highest represented-period GHI: {leader['Climate']} ({leader['Annual GHI [kWh/m²]']:.0f} kWh/m²).")
    if reference and reference in set(metrics["Climate"]) and not temperature.empty:
        ref_rows = temperature[temperature["Climate"] == reference]
        if not ref_rows.empty:
            ref_value = float(ref_rows.iloc[0]["Annual mean T [°C]"])
            other = temperature[temperature["Climate"] != reference].copy()
            if not other.empty:
                other["delta"] = other["Annual mean T [°C]"] - ref_value
                largest = other.loc[other["delta"].abs().idxmax()]
                parts.append(f"Largest mean-temperature offset from {reference}: {largest['Climate']} ({largest['delta']:+.1f} K).")
    return " ".join(parts) if parts else "The selected climates do not share enough variables for an automatic summary."


def natural_ventilation_difference_heatmap(
    reference: ComparisonClimate,
    target: ComparisonClimate,
    t_min_c: float,
    t_max_c: float,
    d_max_g_kg: float,
):
    ref = reference.data.copy()
    tgt = target.data.copy()
    ref["nv"] = natural_ventilation_condition(ref, t_min_c=t_min_c, t_max_c=t_max_c, d_max_g_kg=d_max_g_kg).astype(int)
    tgt["nv"] = natural_ventilation_condition(tgt, t_min_c=t_min_c, t_max_c=t_max_c, d_max_g_kg=d_max_g_kg).astype(int)
    return difference_heatmap_chart(
        replace(reference, data=ref),
        replace(target, data=tgt),
        "nv",
        "day",
        f"Natural-ventilation eligibility difference: {target.display_name} minus {reference.display_name}",
        "Δ eligibility",
    )


__all__ = [
    "ComparisonClimate",
    "comparison_from_canonical",
    "prepare_canonical_comparison_climate",
    "climate_summary_metrics",
    "comparison_interpretation",
    "choose_display_mode",
    "data_quality_matrix",
    "difference_heatmap_chart",
    "duration_comparison_chart",
    "facade_radiation_comparison_chart",
    "hdd_cdd_grouped_chart",
    "heatmap_small_multiples",
    "heating_cooling_season_timeline",
    "monthly_box_compare_chart",
    "monthly_difference_chart",
    "monthly_profile_table",
    "natural_ventilation_difference_heatmap",
    "natural_ventilation_monthly_table",
    "orientation_tilt_small_multiples",
    "overlay_monthly_chart",
    "passive_strategy_calendar_small_multiples",
    "passive_strategy_stacked_comparison",
    "psychrometric_comparison_chart",
    "ranked_metric_chart",
    "small_multiple_monthly_chart",
    "solar_monthly_comparison",
    "sun_path_comparison_chart",
    "tilt_radiation_comparison_chart",
    "wind_rose_small_multiples",
]
