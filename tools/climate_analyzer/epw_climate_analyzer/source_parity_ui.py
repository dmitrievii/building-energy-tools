"""Thin Streamlit migration layer for canonical source parity.

The stable visual shell is intentionally preserved while provider-specific
branches are replaced by canonical engines. ``install_source_parity_ui`` patches
the legacy UI module at runtime; calculation code lives in the source-neutral
modules, while this file only performs Streamlit routing/state management.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from .analysis_clock import LOCAL_CIVIL_TIME, LOCAL_STANDARD_TIME, SOURCE_TIME, UTC_TIME, add_calendar_columns
from .climate_model import CANONICAL_VARIABLES, CanonicalClimateDataset, aggregation_semantics_for, canonical_from_epw
from .comparison_engine import (
    ComparisonClimate,
    climate_summary_metrics,
    comparison_interpretation,
    data_quality_matrix,
    difference_heatmap_chart,
    duration_comparison_chart,
    facade_radiation_comparison_chart,
    hdd_cdd_grouped_chart,
    heatmap_small_multiples,
    monthly_difference_chart,
    monthly_profile_table,
    natural_ventilation_difference_heatmap,
    natural_ventilation_monthly_table,
    orientation_tilt_small_multiples,
    overlay_monthly_chart,
    passive_strategy_calendar_small_multiples,
    passive_strategy_stacked_comparison,
    psychrometric_comparison_chart,
    ranked_metric_chart,
    solar_monthly_comparison,
    sun_path_comparison_chart,
    tilt_radiation_comparison_chart,
    wind_rose_small_multiples,
)
from .decisions import natural_ventilation_condition, night_flushing_condition
from .epw_extended import clean_extended_epw_fields
from .epw_header import ground_temperature_frame, parse_epw_header
from .geosphere import (
    GEOSPHERE_LOCAL_TIMEZONE,
    GEOSPHERE_RESOURCE_ID,
    GEOSPHERE_RESOURCES,
    GEOSPHERE_STANDARD_UTC_OFFSET_HOURS,
    available_resource_specs,
    estimate_request_datapoints,
    fetch_metadata,
    fetch_station_dataset,
    parse_parameters,
    parse_stations,
    plan_data_queries,
    provider_parameters_with_quality_flags,
    resource_spec,
    station_catalog,
    station_parameter_capability_index,
    supported_parameter_mapping,
)
from .ground_temperature import fit_annual_harmonic, monthly_ground_profile
from .historical import (
    prepare_historical_analysis_frame,
    prepare_historical_native_analysis_frame,
    prepare_historical_native_diagnostic_frame,
)
from .historical_capabilities import available_historical_pages, has_numeric_observations
from .psychrometrics import DEFAULT_PRESSURE_PA, pressure_from_altitude_m
from .quality_policy import (
    PROVIDER_TO_CANONICAL_ATTR,
    QUALITY_POLICY_ALL,
    QUALITY_POLICY_CHECKED,
    QUALITY_POLICY_MANUAL,
    apply_quality_policy,
    quality_policy_label,
)
from .solar import variable_origin


_COMPARISON_BASKET_KEY = "canonical_comparison_climates"
_GEOSPHERE_RESOURCE_KEY = "geosphere_resource_id"


@st.cache_data(show_spinner=False, ttl=18 * 60 * 60, max_entries=4)
def _cached_geosphere_resource_bundle(resource_id: str) -> tuple:
    metadata = fetch_metadata(resource_id=resource_id)
    return (
        metadata,
        supported_parameter_mapping(metadata, resource_id=resource_id),
        parse_stations(metadata),
        station_catalog(metadata),
        station_parameter_capability_index(metadata, resource_id=resource_id),
        parse_parameters(metadata),
    )


def _numeric(df: pd.DataFrame, column: str) -> bool:
    return column in df.columns and pd.to_numeric(df[column], errors="coerce").notna().any()


def _analysis_clock_contract(dataset: CanonicalClimateDataset) -> tuple[str, str | None, float | None]:
    local_timezone = str(dataset.data.attrs.get("canonical_analysis_timezone_name") or "").strip() or None
    standard_offset = dataset.data.attrs.get("canonical_standard_utc_offset_hours")
    try:
        standard_offset = float(standard_offset) if standard_offset is not None else None
    except (TypeError, ValueError):
        standard_offset = None
    if local_timezone:
        mode = st.sidebar.selectbox(
            "Analysis clock",
            [LOCAL_CIVIL_TIME, LOCAL_STANDARD_TIME, UTC_TIME],
            index=0,
            format_func=lambda value: {
                LOCAL_CIVIL_TIME: f"Station local civil time ({local_timezone})",
                LOCAL_STANDARD_TIME: f"Local standard time (UTC{standard_offset:+g})" if standard_offset is not None else "Local standard time",
                UTC_TIME: "UTC / provider time",
            }[value],
            key="historical_analysis_clock",
            help=(
                "Provider timestamps remain unchanged. This selection only defines the clock used for hour-of-day, "
                "occupancy, day/night, calendar heatmaps and other building-design analyses."
            ),
        )
        if mode == LOCAL_STANDARD_TIME and standard_offset is None:
            mode = LOCAL_CIVIL_TIME
        return mode, local_timezone, standard_offset
    return SOURCE_TIME, None, None


def _quality_dataset(dataset: CanonicalClimateDataset, policy: str) -> CanonicalClimateDataset:
    if policy == QUALITY_POLICY_ALL:
        return dataset
    data = dataset.data.copy()
    resource_id = str(data.attrs.get("geosphere_resource_id") or "").strip()
    if resource_id in GEOSPHERE_RESOURCES:
        provider_map = {
            provider: field.canonical_name
            for provider, field in resource_spec(resource_id).field_by_provider.items()
            if field.canonical_name in data.columns
        }
        data.attrs[PROVIDER_TO_CANONICAL_ATTR] = provider_map
    filtered = apply_quality_policy(data, policy)
    return replace(dataset, data=filtered)


def _quality_policy_control(dataset: CanonicalClimateDataset) -> str:
    flag_columns = [name for name in dataset.data.columns if str(name).startswith("quality_flag__")]
    if not flag_columns:
        return QUALITY_POLICY_ALL
    return st.sidebar.selectbox(
        "Observation quality",
        [QUALITY_POLICY_ALL, QUALITY_POLICY_CHECKED, QUALITY_POLICY_MANUAL],
        index=0,
        format_func=quality_policy_label,
        key="historical_quality_policy",
        help=(
            "All observations preserves the provider series. Restrictive modes mask only physical variables whose "
            "matching provider quality flag is not in the selected checked class; unrelated variables remain available."
        ),
    )


def _comparison_basket() -> list[ComparisonClimate]:
    value = st.session_state.get(_COMPARISON_BASKET_KEY, [])
    return value if isinstance(value, list) else []


def _save_comparison_basket(items: list[ComparisonClimate]) -> None:
    st.session_state[_COMPARISON_BASKET_KEY] = items


def _prepare_historical_comparison(
    dataset: CanonicalClimateDataset,
    *,
    quality_policy: str = QUALITY_POLICY_ALL,
    clock_mode: str = LOCAL_CIVIL_TIME,
    local_timezone: str | None = GEOSPHERE_LOCAL_TIMEZONE,
    standard_offset: float | None = GEOSPHERE_STANDARD_UTC_OFFSET_HOURS,
) -> ComparisonClimate:
    prepared_dataset = _quality_dataset(dataset, quality_policy)
    source_pressure = prepared_dataset.data.get("atmospheric_station_pressure_pa")
    valid_pressure = pd.to_numeric(source_pressure, errors="coerce").dropna() if source_pressure is not None else pd.Series(dtype=float)
    fallback = float(valid_pressure.median()) if not valid_pressure.empty else pressure_from_altitude_m(float(prepared_dataset.location.elevation_m or 0.0))
    has_psych = _numeric(prepared_dataset.data, "dry_bulb_temperature_c") and _numeric(prepared_dataset.data, "relative_humidity_pct")
    frame = prepare_historical_analysis_frame(
        prepared_dataset,
        include_psychrometrics=has_psych,
        include_solar=True,
        fallback_pressure_pa=fallback,
        analysis_clock_mode=clock_mode,
        local_timezone_name=local_timezone,
        standard_utc_offset_hours=standard_offset,
    )
    return ComparisonClimate(
        climate_id=prepared_dataset.climate_id,
        display_name=prepared_dataset.display_name,
        source=f"{prepared_dataset.provenance.provider} | {prepared_dataset.provenance.dataset}",
        location=prepared_dataset.location,
        data=frame,
        provenance=prepared_dataset.provenance,
        issues=(),
        calendar_mode=prepared_dataset.temporal.calendar_mode,
    )


def _calendar_mean_year(climate: ComparisonClimate) -> ComparisonClimate:
    df = climate.data
    if not isinstance(df.index, pd.DatetimeIndex) or len(set(pd.DatetimeIndex(df.index).year)) <= 1:
        return climate
    numeric_columns = [column for column in df.columns if pd.api.types.is_numeric_dtype(df[column])]
    if not numeric_columns:
        return climate
    keys = pd.MultiIndex.from_arrays(
        [df.index.month, df.index.day, df.index.hour],
        names=["month", "day", "hour"],
    )
    grouped = pd.DataFrame(index=keys)
    for column in numeric_columns:
        values = pd.to_numeric(df[column], errors="coerce")
        semantics = aggregation_semantics_for(column)
        if semantics == "circular mean":
            radians = np.deg2rad(values.astype(float))
            sin_mean = pd.Series(np.sin(radians), index=keys).groupby(level=[0, 1, 2]).mean()
            cos_mean = pd.Series(np.cos(radians), index=keys).groupby(level=[0, 1, 2]).mean()
            series = np.mod(np.rad2deg(np.arctan2(sin_mean, cos_mean)), 360.0)
        else:
            # For interval-extensive quantities, the mean across equivalent
            # calendar intervals creates a representative mean-year interval;
            # summing those intervals later yields a mean annual total.
            series = pd.Series(values.to_numpy(), index=keys).groupby(level=[0, 1, 2]).mean()
        grouped[column] = series
    records: list[pd.Timestamp] = []
    keep: list[tuple[int, int, int]] = []
    for month, day, hour in grouped.index:
        try:
            records.append(pd.Timestamp(year=2024, month=int(month), day=int(day), hour=int(hour)))
            keep.append((int(month), int(day), int(hour)))
        except ValueError:
            continue
    grouped = grouped.loc[keep].copy()
    grouped.index = pd.DatetimeIndex(records, name="timestamp")
    grouped = add_calendar_columns(grouped)
    grouped.attrs.update(df.attrs)
    grouped.attrs["comparison_historical_basis"] = "calendar mean year"
    grouped.attrs["canonical_native_interval_minutes"] = 60
    return replace(climate, data=grouped, display_name=f"{climate.display_name} · mean year")


def _latest_year(climate: ComparisonClimate) -> ComparisonClimate:
    df = climate.data
    years = sorted(set(pd.DatetimeIndex(df.index).year)) if isinstance(df.index, pd.DatetimeIndex) else []
    if len(years) <= 1:
        return climate
    year = years[-1]
    subset = df[pd.DatetimeIndex(df.index).year == year].copy()
    subset.attrs.update(df.attrs)
    subset.attrs["comparison_historical_basis"] = f"year {year}"
    return replace(climate, data=subset, display_name=f"{climate.display_name} · {year}")


def _common_numeric(climates: list[ComparisonClimate], column: str) -> bool:
    return bool(climates) and all(_numeric(climate.data, column) for climate in climates)


def _safe_render_plot(legacy: Any, builder: Callable[[], Any], text: str) -> None:
    try:
        legacy.render_plot(builder(), text)
    except (KeyError, ValueError, TypeError) as exc:
        st.info(f"This comparison view is unavailable for the current shared variable set: {exc}")


def _render_compare_ui(legacy: Any, active_file: Any, pressure_mode: str, custom_pressure_pa: float | None, active_pressure: float) -> None:
    legacy._ensure_analysis_dependencies(include_solar=True, include_comparison=True)
    st.header("Compare climates")
    st.caption(
        "Source-neutral comparison: EPW typical years and measured GeoSphere historical climates share the same canonical hourly engines. "
        "Measured and calculated quantities retain their provenance."
    )

    st.subheader("Comparison basket")
    # Preserve the mature EPW upload/catalog basket UI and add canonical measured
    # climates alongside it rather than duplicating the station browser.
    legacy.render_comparison_basket_manager(active_file)

    active_canonical = legacy.get_active_canonical_climate()
    canonical_basket = _comparison_basket()
    if active_canonical is not None:
        if st.button("Add current measured climate to comparison", key="add_current_canonical_compare"):
            if any(item.climate_id == active_canonical.climate_id for item in canonical_basket):
                st.info("The current measured climate is already in the comparison basket.")
            else:
                clock_mode, local_tz, standard_offset = _analysis_clock_contract(active_canonical)
                policy = _quality_policy_control(active_canonical)
                canonical_basket.append(
                    _prepare_historical_comparison(
                        active_canonical,
                        quality_policy=policy,
                        clock_mode=clock_mode,
                        local_timezone=local_tz,
                        standard_offset=standard_offset,
                    )
                )
                _save_comparison_basket(canonical_basket)
                st.rerun()

    if canonical_basket:
        st.caption("Measured/canonical climates in basket")
        for index, climate in enumerate(list(canonical_basket)):
            c1, c2 = st.columns([5, 1])
            c1.write(f"**{climate.display_name}** — {climate.source}")
            if c2.button("Remove", key=f"remove_canonical_compare_{climate.climate_id}_{index}"):
                _save_comparison_basket([item for item in canonical_basket if item.climate_id != climate.climate_id])
                st.rerun()

    climates: list[ComparisonClimate] = list(_comparison_basket())
    for item in legacy.get_comparison_payloads():
        try:
            epw_pressure_mode = pressure_mode
            if pressure_mode == "Measured station pressure with fallback median":
                epw_pressure_mode = "EPW station pressure with fallback median"
            epw, data, issues = legacy.load_epw_from_bytes(
                str(item["name"]),
                bytes(item["payload"]),
                epw_pressure_mode,
                custom_pressure_pa,
                include_psychrometrics=True,
                include_solar=True,
            )
            data = clean_extended_epw_fields(data)
            canonical = canonical_from_epw(
                epw,
                data=data,
                climate_id=str(item["climate_id"]),
                display_name=str(item.get("display_name") or item["name"]),
                source_reference=str(item.get("source", "")),
            )
            climates.append(
                ComparisonClimate(
                    climate_id=canonical.climate_id,
                    display_name=canonical.display_name,
                    source=str(item.get("source", "EPW")),
                    location=canonical.location,
                    data=data,
                    provenance=canonical.provenance,
                    issues=tuple(issues),
                    calendar_mode="typical_year",
                )
            )
        except Exception as exc:
            st.error(f"Failed to prepare EPW comparison climate `{item.get('display_name', item.get('name', 'unknown'))}`: {exc}")

    # Deduplicate by stable identity while preserving basket order.
    unique: list[ComparisonClimate] = []
    seen: set[str] = set()
    for climate in climates:
        if climate.climate_id in seen:
            continue
        seen.add(climate.climate_id)
        unique.append(climate)
    climates = unique
    if len(climates) < 2:
        st.warning("Add at least two climates (EPW and/or GeoSphere) to enable comparison charts.")
        return

    if any(climate.calendar_mode == "historical" and len(set(pd.DatetimeIndex(climate.data.index).year)) > 1 for climate in climates):
        basis = st.radio(
            "Historical comparison basis",
            ["Calendar mean year", "Latest available year"],
            horizontal=True,
            help=(
                "Calendar mean year averages equivalent calendar hours across real years before annual totals are calculated. "
                "Latest available year keeps one real year. EPW typical-year climates are unchanged."
            ),
        )
        climates = [
            _calendar_mean_year(climate) if basis == "Calendar mean year" else _latest_year(climate)
            if climate.calendar_mode == "historical" else climate
            for climate in climates
        ]

    reference_name = st.selectbox("Reference climate", [c.display_name for c in climates], index=0)
    c1, c2 = st.columns(2)
    selected_months = c1.multiselect("Comparison months", list(range(1, 13)), default=list(range(1, 13)))
    hour_range = c2.slider("Comparison hour range", 0, 23, (0, 23))
    filtered: list[ComparisonClimate] = []
    for climate in climates:
        frame = climate.data[
            climate.data["month_index"].isin(selected_months)
            & climate.data["hour_of_day"].between(hour_range[0], hour_range[1])
        ].copy()
        frame.attrs.update(climate.data.attrs)
        filtered.append(replace(climate, data=frame))
    climates = filtered
    if any(climate.data.empty for climate in climates):
        st.warning("The comparison filters remove all data for at least one climate.")
        return

    metrics = climate_summary_metrics(climates)
    tabs = st.tabs([
        "Summary", "Temperature", "Humidity / Psychrometrics", "Solar", "Wind",
        "Natural ventilation", "Passive / HVAC", "Difference to reference", "Data quality",
    ])
    interpretation = comparison_interpretation(metrics, reference_name)

    with tabs[0]:
        st.dataframe(metrics, hide_index=True, use_container_width=True)
        if {"HDD18 [K·h]", "CDD26 [K·h]"}.issubset(metrics.columns):
            legacy.render_plot(hdd_cdd_grouped_chart(metrics), interpretation)

    with tabs[1]:
        if not _common_numeric(climates, "dry_bulb_temperature_c"):
            st.info("Temperature comparison requires dry-bulb temperature in every climate.")
        else:
            chart = st.selectbox("Temperature chart", ["Monthly mean", "Duration curve", "Heatmap", "Ranking"], key="canonical_compare_temperature")
            if chart == "Monthly mean":
                table = monthly_profile_table(climates, "dry_bulb_temperature_c")
                legacy.render_plot(overlay_monthly_chart(table, "Monthly mean dry-bulb temperature", "°C"), interpretation)
            elif chart == "Duration curve":
                legacy.render_plot(duration_comparison_chart(climates, "dry_bulb_temperature_c", "Temperature duration curves", "°C"), interpretation)
            elif chart == "Heatmap":
                legacy.render_plot(heatmap_small_multiples(climates, "dry_bulb_temperature_c", "day", "Temperature heatmaps", "°C"), interpretation)
            else:
                legacy.render_plot(ranked_metric_chart(metrics, "Annual mean T [°C]"), interpretation)

    with tabs[2]:
        if not all(_common_numeric(climates, column) for column in ("dry_bulb_temperature_c", "relative_humidity_pct", "humidity_ratio_g_kg")):
            st.info("Psychrometric comparison requires T, RH and derived humidity ratio in every climate.")
        else:
            chart = st.selectbox("Moisture chart", ["Psychrometric chart", "Humidity-ratio ranking"], key="canonical_compare_humidity")
            if chart == "Psychrometric chart":
                reference = next(c for c in climates if c.display_name == reference_name)
                pressure = pd.to_numeric(reference.data.get("atmospheric_station_pressure_pa"), errors="coerce").dropna()
                common_pressure = float(pressure.median()) if not pressure.empty else pressure_from_altitude_m(float(reference.location.elevation_m or 0.0))
                representation = st.radio("Representation", ["Points", "Distribution grid", "Climate contour"], horizontal=True, key="canonical_compare_psych_repr")
                legacy.render_plot(
                    psychrometric_comparison_chart(
                        climates,
                        chart_type="T-d",
                        pressure_pa=common_pressure,
                        data_display=representation,
                        reference_pressure_pa=common_pressure,
                    ),
                    interpretation,
                )
            else:
                legacy.render_plot(ranked_metric_chart(metrics, "Mean humidity ratio [g/kg]"), interpretation)

    with tabs[3]:
        radiation_options = [
            ("GHI", "global_horizontal_radiation_wh_m2", "Annual GHI [kWh/m²]"),
            ("DNI", "direct_normal_radiation_wh_m2", "Annual DNI [kWh/m²]"),
            ("DHI", "diffuse_horizontal_radiation_wh_m2", "Annual DHI [kWh/m²]"),
        ]
        available = [item for item in radiation_options if _common_numeric(climates, item[1])]
        chart_options = ["Monthly radiation", "Sun path", "Façade orientation", "Orientation-tilt heatmap", "Solar ranking"]
        chart = st.selectbox("Solar chart", chart_options, key="canonical_compare_solar")
        if chart == "Monthly radiation":
            if not available:
                st.info("No common radiation component is available across all climates.")
            else:
                label, column, _metric = st.selectbox("Radiation component", available, format_func=lambda item: item[0], key="canonical_compare_rad_component")
                table = solar_monthly_comparison(climates, column)
                legacy.render_plot(overlay_monthly_chart(table, f"Monthly {label} irradiation", "kWh/m²"), interpretation)
        elif chart == "Sun path":
            if all(_numeric(c.data, "solar_elevation_deg") for c in climates):
                legacy.render_plot(sun_path_comparison_chart(climates, "Overlay", ["12-21", "03-21", "06-21"]), interpretation)
            else:
                st.info("Solar geometry is unavailable for at least one climate.")
        elif chart == "Façade orientation":
            if all(_common_numeric(climates, col) for col in ("global_horizontal_radiation_wh_m2", "diffuse_horizontal_radiation_wh_m2", "direct_normal_radiation_wh_m2")):
                legacy.render_plot(facade_radiation_comparison_chart(climates, 90.0), interpretation)
            else:
                st.info("Façade irradiation requires GHI, DHI and measured/calculated DNI in every climate.")
        elif chart == "Orientation-tilt heatmap":
            if all(_common_numeric(climates, col) for col in ("global_horizontal_radiation_wh_m2", "diffuse_horizontal_radiation_wh_m2", "direct_normal_radiation_wh_m2")):
                legacy.render_plot(orientation_tilt_small_multiples(climates), interpretation)
            else:
                st.info("Orientation-tilt analysis requires GHI, DHI and measured/calculated DNI in every climate.")
        else:
            metric_options = [metric for _label, _column, metric in available]
            if metric_options:
                metric = st.selectbox("Solar metric", metric_options, key="canonical_compare_solar_metric")
                legacy.render_plot(ranked_metric_chart(metrics, metric), interpretation)
            else:
                st.info("No common solar ranking metric is available.")

    with tabs[4]:
        if not all(_common_numeric(climates, col) for col in ("wind_speed_m_s", "wind_direction_deg")):
            st.info("Wind comparison requires paired wind speed and direction in every climate.")
        else:
            chart = st.selectbox("Wind chart", ["Monthly profile", "Duration curve", "Wind rose", "Ranking"], key="canonical_compare_wind")
            if chart == "Monthly profile":
                legacy.render_plot(overlay_monthly_chart(monthly_profile_table(climates, "wind_speed_m_s"), "Monthly mean wind speed", "m/s"), interpretation)
            elif chart == "Duration curve":
                legacy.render_plot(duration_comparison_chart(climates, "wind_speed_m_s", "Wind speed duration curves", "m/s"), interpretation)
            elif chart == "Wind rose":
                legacy.render_plot(wind_rose_small_multiples(climates), interpretation)
            else:
                legacy.render_plot(ranked_metric_chart(metrics, "Mean wind speed [m/s]"), interpretation)

    with tabs[5]:
        required = ("dry_bulb_temperature_c", "humidity_ratio_g_kg")
        if not all(_common_numeric(climates, col) for col in required):
            st.info("Natural-ventilation comparison requires temperature and humidity ratio in every climate.")
        else:
            c1, c2, c3 = st.columns(3)
            t_min = c1.number_input("NV Tmin [°C]", value=16.0, step=0.5, key="canonical_compare_nv_min")
            t_max = c2.number_input("NV Tmax [°C]", value=26.0, step=0.5, key="canonical_compare_nv_max")
            d_max = c3.number_input("NV dmax [g/kg]", value=9.0, step=0.5, key="canonical_compare_nv_d")
            chart = st.selectbox("NV chart", ["Monthly hours", "Difference heatmap"], key="canonical_compare_nv_chart")
            if chart == "Monthly hours":
                table = natural_ventilation_monthly_table(climates, t_min, t_max, d_max)
                legacy.render_plot(overlay_monthly_chart(table, "Monthly natural-ventilation suitable hours", "h"), interpretation)
            else:
                targets = [c for c in climates if c.display_name != reference_name]
                target = st.selectbox("Target climate", targets, format_func=lambda c: c.display_name, key="canonical_compare_nv_target")
                reference = next(c for c in climates if c.display_name == reference_name)
                legacy.render_plot(natural_ventilation_difference_heatmap(reference, target, t_min, t_max, d_max), interpretation)

    with tabs[6]:
        chart = st.selectbox("Passive/HVAC chart", ["Strategy totals", "Strategy calendar", "HVAC ranking"], key="canonical_compare_passive")
        if chart == "Strategy totals":
            _safe_render_plot(legacy, lambda: passive_strategy_stacked_comparison(climates), interpretation)
        elif chart == "Strategy calendar":
            _safe_render_plot(legacy, lambda: passive_strategy_calendar_small_multiples(climates), interpretation)
        else:
            available_metrics = [name for name in ["HDD18 [K·h]", "CDD26 [K·h]", "Economizer hours [h]", "Dehumidification hours [h]"] if name in metrics.columns and metrics[name].notna().any()]
            if available_metrics:
                metric = st.selectbox("HVAC metric", available_metrics, key="canonical_compare_hvac_metric")
                legacy.render_plot(ranked_metric_chart(metrics, metric), interpretation)

    with tabs[7]:
        variables = [
            ("Dry-bulb temperature", "dry_bulb_temperature_c", "°C", False),
            ("Humidity ratio", "humidity_ratio_g_kg", "g/kg", False),
            ("Relative humidity", "relative_humidity_pct", "%", False),
            ("Global horizontal irradiation", "global_horizontal_radiation_wh_m2", "Wh/m²", True),
            ("Wind speed", "wind_speed_m_s", "m/s", False),
        ]
        common = [item for item in variables if _common_numeric(climates, item[1])]
        if not common:
            st.info("No common difference variable is available.")
        else:
            label, column, unit, extensive = st.selectbox("Difference variable", common, format_func=lambda item: item[0], key="canonical_compare_diff_var")
            target = st.selectbox("Difference target", [c for c in climates if c.display_name != reference_name], format_func=lambda c: c.display_name, key="canonical_compare_diff_target")
            reference = next(c for c in climates if c.display_name == reference_name)
            mode = st.radio("Difference view", ["Monthly", "Day × hour heatmap"], horizontal=True, key="canonical_compare_diff_mode")
            if mode == "Monthly":
                table = monthly_profile_table([reference, target], column, extensive=extensive)
                legacy.render_plot(monthly_difference_chart(table, reference.display_name, f"{label} difference", unit), interpretation)
            else:
                legacy.render_plot(difference_heatmap_chart(reference, target, column, "day", f"{label}: {target.display_name} minus {reference.display_name}", f"Δ {unit}"), interpretation)

    with tabs[8]:
        matrix = data_quality_matrix(climates)
        st.dataframe(matrix, hide_index=True, use_container_width=True)


def _render_humidity_capability(legacy: Any, original: Callable, df: pd.DataFrame, pressure_pa: float, **kwargs: Any) -> None:
    original_metrics = legacy.PSYCHROMETRIC_COLOR_METRICS
    filtered = {}
    for label, (column, description) in original_metrics.items():
        if column is None or _numeric(df, column):
            filtered[label] = (column, description)
    legacy.PSYCHROMETRIC_COLOR_METRICS = filtered
    try:
        original(df, pressure_pa, **kwargs)
    finally:
        legacy.PSYCHROMETRIC_COLOR_METRICS = original_metrics


def _render_solar_capability(legacy: Any, original_full: Callable, original_horizontal: Callable, df: pd.DataFrame) -> None:
    complete = all(_numeric(df, column) for column in (
        "global_horizontal_radiation_wh_m2",
        "diffuse_horizontal_radiation_wh_m2",
        "direct_normal_radiation_wh_m2",
    )) and all(column in df.columns for column in ("solar_apparent_zenith_deg", "solar_azimuth_deg"))
    if complete:
        if "direct_normal_radiation_is_calculated" in df.columns and bool(pd.Series(df["direct_normal_radiation_is_calculated"]).fillna(False).any()):
            st.caption(
                "DNI is calculated where it was not measured: DNI = max(GHI − DHI, 0) / cos(zenith), with a near-horizon stability guard. "
                "Measured GHI/DHI remain unchanged."
            )
        original_full(df)
    else:
        original_horizontal(df)


def _render_sky_with_atmosphere(legacy: Any, original: Callable, df: pd.DataFrame, *, latitude: float | None = None) -> None:
    original(df, latitude=latitude)
    extras = [
        "Horizontal infrared radiation",
        "Extraterrestrial horizontal radiation",
        "Extraterrestrial direct normal radiation",
        "Zenith luminance",
        "Visibility",
        "Ceiling height",
        "Precipitable water",
        "Aerosol optical depth",
        "Albedo",
        "Days since last snowfall",
    ]
    available = [label for label in extras if label in legacy.VARIABLES and _numeric(df, legacy.VARIABLES[label][0])]
    if available:
        with st.expander("Additional atmospheric context", expanded=False):
            selected = st.selectbox("Atmospheric quantity", available, key="extended_atmospheric_quantity")
            legacy.render_generic_variable_page(df, [selected], selected, "Atmospheric context", None, fixed_variable_label=selected)


def _render_ground_with_epw_header(legacy: Any, original: Callable, df: pd.DataFrame, *, source_label: str, native_df: pd.DataFrame | None = None) -> None:
    original(df, source_label=source_label, native_df=native_df)
    active = legacy.get_active_climate_file()
    if active is None:
        return
    try:
        epw, _data, _issues = legacy.load_epw_from_bytes(active.name, active.payload, "EPW station pressure with fallback median", None, include_psychrometrics=False, include_solar=False)
        metadata = parse_epw_header(epw.header_lines)
        header_ground = ground_temperature_frame(metadata)
    except Exception as exc:
        st.caption(f"EPW ground-temperature header could not be parsed: {exc}")
        return
    if header_ground.empty:
        return
    st.markdown("#### EPW header ground temperatures")
    st.caption(
        "These values come from the EPW GROUND TEMPERATURES header. They are source metadata and may themselves be calculated by the weather-file producer; they are not labelled as measured observations."
    )
    plot = header_ground.copy()
    plot["depth"] = plot["depth_m"].map(lambda value: f"{float(value):g} m")
    fig = px.line(plot, x="month", y="temperature_c", color="depth", markers=True, title="EPW header ground temperatures")
    fig.update_layout(template="plotly_white", xaxis_title="Month", yaxis_title="Ground temperature [°C]", legend_title="Depth")
    legacy.render_plot(fig, "EPW header ground-temperature profiles at the depths supplied by the weather-file producer.")
    st.dataframe(header_ground, hide_index=True, use_container_width=True)

    if _numeric(df, "dry_bulb_temperature_c"):
        harmonic = fit_annual_harmonic(pd.to_numeric(df["dry_bulb_temperature_c"], errors="coerce"))
        comparison_rows: list[dict[str, object]] = []
        for profile in metadata.ground_temperatures:
            conductivity = float(profile.conductivity_w_mk or 2.0)
            density = float(profile.density_kg_m3 or 2000.0)
            heat_capacity = float(profile.specific_heat_j_kgk or 1000.0)
            calculated = monthly_ground_profile(harmonic, np.array([profile.depth_m]), conductivity, density, heat_capacity)
            for month in range(1, 13):
                observed = profile.monthly_temperature_c[month - 1]
                value = float(calculated.loc[profile.depth_m, month])
                comparison_rows.append({
                    "month": month,
                    "depth_m": profile.depth_m,
                    "epw_header_c": observed,
                    "periodic_model_c": value,
                    "difference_k": (value - float(observed)) if observed is not None else np.nan,
                })
        if comparison_rows:
            with st.expander("EPW header vs periodic model", expanded=False):
                comparison = pd.DataFrame(comparison_rows)
                st.dataframe(comparison, hide_index=True, use_container_width=True)


def _render_historical_overview_enhanced(legacy: Any, original: Callable, dataset: CanonicalClimateDataset, df: pd.DataFrame, coverage_df: pd.DataFrame | None = None) -> None:
    original(dataset, df, coverage_df)
    canonical_columns = [column for column in dataset.available_canonical_variables if _numeric(df, column)]
    if not canonical_columns:
        return
    st.subheader("Calculated climate statistics")
    st.caption("Source-neutral statistics below are calculated from the canonical hourly analysis frame and respect the active Data filter.")
    labels = {value[0]: label for label, value in legacy.VARIABLES.items()}
    selectable = [column for column in canonical_columns if column in labels]
    if selectable:
        column = st.selectbox("Overview statistic variable", selectable, format_func=lambda value: labels.get(value, value), key="historical_overview_stat_variable")
        semantics = aggregation_semantics_for(column)
        if semantics == "sum":
            monthly = pd.to_numeric(df[column], errors="coerce").groupby(df["month_index"]).sum(min_count=1)
        elif semantics == "min":
            monthly = pd.to_numeric(df[column], errors="coerce").groupby(df["month_index"]).min()
        elif semantics == "max":
            monthly = pd.to_numeric(df[column], errors="coerce").groupby(df["month_index"]).max()
        else:
            monthly = pd.to_numeric(df[column], errors="coerce").groupby(df["month_index"]).mean()
        table = monthly.reindex(range(1, 13)).rename_axis("month").reset_index(name="value")
        fig = px.bar(table, x="month", y="value", title=f"Monthly {labels.get(column, column)}")
        fig.update_layout(template="plotly_white", xaxis_title="Month", yaxis_title=CANONICAL_VARIABLES[column].unit)
        legacy.render_plot(fig, f"Monthly source-neutral {semantics} aggregation for {labels.get(column, column)}.")
    if _numeric(df, "dry_bulb_temperature_c"):
        daily = pd.to_numeric(df["dry_bulb_temperature_c"], errors="coerce").resample("D").agg(["mean", "min", "max"])
        c1, c2 = st.columns(2)
        c1.markdown("**Hottest days**")
        c1.dataframe(daily.sort_values("max", ascending=False).head(10), use_container_width=True)
        c2.markdown("**Coldest days**")
        c2.dataframe(daily.sort_values("min").head(10), use_container_width=True)


def _render_quality_decoded(legacy: Any, original: Callable, dataset: CanonicalClimateDataset, df: pd.DataFrame) -> None:
    original(dataset, df)
    codebooks = dataset.data.attrs.get("geosphere_quality_codebooks", {})
    if not isinstance(codebooks, dict) or not codebooks:
        return
    rows: list[dict[str, object]] = []
    for provider, codebook in codebooks.items():
        column = f"quality_flag__{provider}"
        if column not in df.columns:
            continue
        counts = pd.to_numeric(df[column], errors="coerce").value_counts(dropna=True).sort_index()
        for code, count in counts.items():
            numeric_code = int(code)
            rows.append({
                "Provider parameter": provider,
                "Code": numeric_code,
                "Meaning": codebook.get(numeric_code, "Unknown / not in current provider code list"),
                "Records": int(count),
            })
    if rows:
        st.subheader("Decoded provider quality flags")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("Flag meanings come from the live GeoSphere metadata code_list_ref/code_lists contract; unknown future codes remain explicit rather than being guessed.")


def _render_geosphere_resource_selector(legacy: Any, original: Callable) -> None:
    specs = available_resource_specs()
    selected = st.selectbox(
        "GeoSphere dataset",
        [spec.resource_id for spec in specs],
        index=0,
        format_func=lambda resource_id: resource_spec(resource_id).label,
        key=_GEOSPHERE_RESOURCE_KEY,
        help=(
            "10-minute data are best for recent event/detail analysis. The 1-hour resource provides the long-term historical series and enters the same canonical hourly engine without resampling."
        ),
    )
    spec = resource_spec(selected)
    st.caption(f"Selected resource: `{spec.resource_id}` · native cadence {spec.native_interval_minutes:g} min · {spec.doi}")

    legacy._ensure_geosphere_dependencies()
    legacy.cached_geosphere_metadata_bundle = lambda: _cached_geosphere_resource_bundle(selected)
    legacy.supported_geosphere_parameter_mapping = lambda metadata: supported_parameter_mapping(metadata, resource_id=selected)
    legacy.provider_parameters_with_quality_flags = lambda metadata, parameters: provider_parameters_with_quality_flags(metadata, parameters, resource_id=selected)
    legacy.estimate_geosphere_datapoints = lambda start, end, parameter_count, station_count=1: estimate_request_datapoints(start, end, parameter_count, station_count, resource_id=selected)
    legacy.plan_geosphere_queries = lambda station_id, start, end, parameters: plan_data_queries(station_id, start, end, parameters, resource_id=selected)

    def fetch_for_resource(**kwargs: Any) -> CanonicalClimateDataset:
        dataset = fetch_station_dataset(resource_id=selected, **kwargs)
        mapping = supported_parameter_mapping(kwargs.get("metadata") or _cached_geosphere_resource_bundle(selected)[0], resource_id=selected)
        dataset.data.attrs[PROVIDER_TO_CANONICAL_ATTR] = {name: field.canonical_name for name, field in mapping.items()}
        return dataset

    legacy.fetch_geosphere_station_dataset = fetch_for_resource

    original_caption = legacy.st.caption
    if selected != GEOSPHERE_RESOURCE_ID:
        def resource_caption(body: Any, *args: Any, **kwargs: Any):
            if isinstance(body, str):
                body = body.replace("`klima-v2-10min`", f"`{selected}`")
                body = body.replace("10-minute source data", "hourly source data")
                body = body.replace("10-minute", "hourly")
                body = body.replace("10 min", "1 h")
            return original_caption(body, *args, **kwargs)
        legacy.st.caption = resource_caption
    try:
        original()
    finally:
        legacy.st.caption = original_caption


def _render_canonical_analysis(legacy: Any, dataset: CanonicalClimateDataset) -> None:
    legacy._ensure_analysis_dependencies(include_solar=True, include_comparison=True)
    supported = set(available_historical_pages(dataset.data))
    supported.add("Sky and Daylight")  # geometry requires date + latitude only
    supported.add("Compare Climates")
    pages = tuple(page for page in legacy.NAVIGATION_PAGES if page in supported)
    if legacy.NAVIGATION_KEY not in st.session_state or st.session_state[legacy.NAVIGATION_KEY] not in pages:
        st.session_state[legacy.NAVIGATION_KEY] = "Overview"
    st.sidebar.markdown("### Explore")
    page = st.sidebar.radio("Analysis section", pages, format_func=legacy.navigation_label, key=legacy.NAVIGATION_KEY, label_visibility="collapsed")
    if page == "Climate File Source":
        legacy.render_climate_file_source()
        return

    with st.sidebar.expander("Advanced calculation settings", expanded=False):
        pressure_mode = st.selectbox(
            "Psychrometric pressure mode",
            ["Measured station pressure with fallback median", "Normal pressure: 101325 Pa", "Altitude-derived standard atmosphere pressure", "Custom constant pressure"],
            index=0,
            key="historical_pressure_mode",
        )
        custom_pressure = None
        if pressure_mode == "Custom constant pressure":
            custom_pressure = st.number_input("Custom pressure [Pa]", 30000.0, 120000.0, 101325.0, 100.0, key="historical_custom_pressure")

    clock_mode, local_timezone, standard_offset = _analysis_clock_contract(dataset)
    quality_policy = _quality_policy_control(dataset)
    prepared_dataset = _quality_dataset(dataset, quality_policy)

    source_pressure = prepared_dataset.data.get("atmospheric_station_pressure_pa")
    valid_pressure = pd.to_numeric(source_pressure, errors="coerce").dropna() if source_pressure is not None else pd.Series(dtype=float)
    measured_median = float(valid_pressure.median()) if not valid_pressure.empty else pressure_from_altitude_m(float(prepared_dataset.location.elevation_m or 0.0))
    if pressure_mode == "Measured station pressure with fallback median":
        fallback_pressure, pressure_override = measured_median, None
    elif pressure_mode == "Normal pressure: 101325 Pa":
        fallback_pressure = pressure_override = DEFAULT_PRESSURE_PA
    elif pressure_mode == "Altitude-derived standard atmosphere pressure":
        fallback_pressure = pressure_override = pressure_from_altitude_m(float(prepared_dataset.location.elevation_m or 0.0))
    else:
        fallback_pressure = pressure_override = float(custom_pressure or DEFAULT_PRESSURE_PA)

    if page == "Compare Climates":
        _render_compare_ui(legacy, None, pressure_mode, custom_pressure, fallback_pressure)
        return

    has_psych = _numeric(prepared_dataset.data, "dry_bulb_temperature_c") and _numeric(prepared_dataset.data, "relative_humidity_pct")
    include_psych = has_psych and page in {"Temperature", "Humidity and Psychrometrics", "Wind and Ventilation", "Time Series and Overlay", "Natural Ventilation", "HVAC and Passive Design", "Overview"}
    include_solar = page in {"Solar and Radiation", "Overview"}

    if page == "Data Quality":
        full_df = prepare_historical_native_diagnostic_frame(dataset)
        filtered_df = full_df
        st.session_state["_active_filtered_export_df"] = full_df
    elif page == "Time Series and Overlay":
        resolution = st.sidebar.radio(
            "Time-series resolution",
            ["Canonical hourly", f"Native source ({prepared_dataset.temporal.native_interval_minutes:g} min)"],
            index=0,
            key="historical_timeseries_resolution",
        )
        if resolution.startswith("Native"):
            include_native_derived = st.sidebar.checkbox("Derived psychrometrics / solar on native series", value=False, key="historical_native_derived")
            full_df = prepare_historical_native_analysis_frame(
                prepared_dataset,
                analysis_clock_mode=clock_mode,
                local_timezone_name=local_timezone,
                standard_utc_offset_hours=standard_offset,
                include_psychrometrics=include_native_derived and has_psych,
                include_solar=include_native_derived,
                fallback_pressure_pa=fallback_pressure,
            )
        else:
            full_df = prepare_historical_analysis_frame(
                prepared_dataset,
                include_psychrometrics=include_psych,
                include_solar=False,
                fallback_pressure_pa=fallback_pressure,
                pressure_override_pa=pressure_override,
                analysis_clock_mode=clock_mode,
                local_timezone_name=local_timezone,
                standard_utc_offset_hours=standard_offset,
            )
        filtered_df = legacy.sidebar_filters(full_df)
    else:
        full_df = prepare_historical_analysis_frame(
            prepared_dataset,
            include_psychrometrics=include_psych,
            include_solar=include_solar,
            fallback_pressure_pa=fallback_pressure,
            pressure_override_pa=pressure_override,
            analysis_clock_mode=clock_mode,
            local_timezone_name=local_timezone,
            standard_utc_offset_hours=standard_offset,
        )
        filtered_df = legacy.sidebar_filters(full_df)

    if filtered_df.empty:
        st.warning("The current filters remove all data. Adjust the date, month or hour filter.")
        return

    source_interval = float(prepared_dataset.temporal.native_interval_minutes)
    analysis_interval = float(full_df.attrs.get("canonical_analysis_interval_minutes", 60.0))
    st.sidebar.markdown("### Current climate")
    st.sidebar.write(f"**{prepared_dataset.location.city}, {prepared_dataset.location.country}**")
    st.sidebar.caption(f"{prepared_dataset.provenance.provider} · source {source_interval:g} min → analysis {analysis_interval:g} min")
    st.sidebar.write(f"Rows in current view: {len(filtered_df):,}")
    st.sidebar.caption(f"Analysis clock: {full_df.attrs.get('canonical_analysis_timezone_name', prepared_dataset.temporal.timezone_name)}")

    if page == "Overview":
        _render_historical_overview_enhanced(legacy, legacy._source_parity_original_historical_overview, prepared_dataset, filtered_df, full_df)
    elif page == "Temperature":
        native = prepare_historical_native_analysis_frame(
            prepared_dataset,
            analysis_clock_mode=clock_mode,
            local_timezone_name=local_timezone,
            standard_utc_offset_hours=standard_offset,
        )
        native = legacy.apply_active_global_filter(native)
        legacy.render_temperature(filtered_df, ground_source_label="GeoSphere measured", ground_native_df=native)
    elif page == "Humidity and Psychrometrics":
        _render_humidity_capability(legacy, legacy._source_parity_original_humidity, filtered_df, fallback_pressure)
    elif page == "Solar and Radiation":
        _render_solar_capability(legacy, legacy._source_parity_original_solar, legacy._source_parity_original_historical_solar, filtered_df)
    elif page == "Sky and Daylight":
        _render_sky_with_atmosphere(legacy, legacy._source_parity_original_sky, filtered_df, latitude=float(prepared_dataset.location.latitude))
    elif page == "Wind and Ventilation":
        legacy.render_wind(filtered_df)
    elif page == "Natural Ventilation":
        legacy.render_natural_ventilation(filtered_df, pressure_pa=fallback_pressure)
    elif page == "HVAC and Passive Design":
        legacy.render_hvac_passive(filtered_df)
    elif page == "Precipitation and Snow":
        native = prepare_historical_native_analysis_frame(
            prepared_dataset,
            analysis_clock_mode=clock_mode,
            local_timezone_name=local_timezone,
            standard_utc_offset_hours=standard_offset,
        )
        native = legacy.apply_active_global_filter(native)
        legacy.render_precipitation(filtered_df, native_df=native)
    elif page == "Time Series and Overlay":
        legacy.render_time_series_overlay(filtered_df)
    else:
        _render_quality_decoded(legacy, legacy._source_parity_original_quality, dataset, filtered_df)


def install_source_parity_ui(legacy: Any) -> None:
    """Install canonical source-parity routing into the stable Streamlit shell."""
    if getattr(legacy, "_SOURCE_PARITY_UI_INSTALLED", False):
        return
    legacy._SOURCE_PARITY_UI_INSTALLED = True

    # Extend the shared variable vocabulary rather than create EPW-only pages.
    legacy.VARIABLES.update({
        "Extraterrestrial horizontal radiation": ("extraterrestrial_horizontal_radiation_wh_m2", "Wh/m²"),
        "Extraterrestrial direct normal radiation": ("extraterrestrial_direct_normal_radiation_wh_m2", "Wh/m²"),
        "Horizontal infrared radiation": ("horizontal_infrared_radiation_intensity_wh_m2", "Wh/m²"),
        "Zenith luminance": ("zenith_luminance_cd_m2", "cd/m²"),
        "Visibility": ("visibility_km", "km"),
        "Ceiling height": ("ceiling_height_m", "m"),
        "Precipitable water": ("precipitable_water_mm", "mm"),
        "Aerosol optical depth": ("aerosol_optical_depth_thousandths", "0.001"),
        "Albedo": ("albedo", "-"),
        "Days since last snowfall": ("days_since_last_snowfall", "d"),
    })

    original_load_epw = legacy.load_epw_from_bytes
    def load_epw_extended(*args: Any, **kwargs: Any):
        epw, data, issues = original_load_epw(*args, **kwargs)
        clean_source = clean_extended_epw_fields(epw.data)
        clean_data = clean_extended_epw_fields(data)
        epw = replace(epw, data=clean_source)
        return epw, clean_data, issues
    legacy.load_epw_from_bytes = load_epw_extended

    legacy._source_parity_original_humidity = legacy.render_humidity
    legacy._source_parity_original_solar = legacy.render_solar
    legacy._source_parity_original_historical_solar = legacy.render_historical_solar
    legacy._source_parity_original_sky = legacy.render_sky_daylight
    legacy._source_parity_original_ground = legacy.render_ground_temperature_page
    legacy._source_parity_original_historical_overview = legacy.render_historical_overview
    legacy._source_parity_original_quality = legacy.render_canonical_data_quality
    legacy._source_parity_original_geosphere = legacy.render_geosphere_source

    legacy.render_humidity = lambda df, pressure_pa, **kwargs: _render_humidity_capability(legacy, legacy._source_parity_original_humidity, df, pressure_pa, **kwargs)
    legacy.render_solar = lambda df: _render_solar_capability(legacy, legacy._source_parity_original_solar, legacy._source_parity_original_historical_solar, df)
    legacy.render_sky_daylight = lambda df, latitude=None: _render_sky_with_atmosphere(legacy, legacy._source_parity_original_sky, df, latitude=latitude)
    legacy.render_ground_temperature_page = lambda df, source_label, native_df=None: _render_ground_with_epw_header(legacy, legacy._source_parity_original_ground, df, source_label=source_label, native_df=native_df)
    legacy.render_canonical_data_quality = lambda dataset, df: _render_quality_decoded(legacy, legacy._source_parity_original_quality, dataset, df)
    legacy.render_geosphere_source = lambda: _render_geosphere_resource_selector(legacy, legacy._source_parity_original_geosphere)
    legacy.render_canonical_climate_analysis = lambda dataset: _render_canonical_analysis(legacy, dataset)
    legacy.render_compare_climates = lambda active_file, pressure_mode, custom_pressure_pa, active_pressure: _render_compare_ui(legacy, active_file, pressure_mode, custom_pressure_pa, active_pressure)
