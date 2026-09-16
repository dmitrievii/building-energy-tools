"""Streamlit browser app for interactive EPW climate analysis."""

from __future__ import annotations

from io import BytesIO
from typing import Callable
import html
from uuid import uuid4


import streamlit as st

from epw_climate_analyzer.ui_contract import (
    APP_BROWSER_TITLE,
    APP_ENGINEERING_DISCLAIMER,
    APP_INDEPENDENCE_NOTICE,
    APP_INTRO,
    APP_NAME,
    APP_RELEASE_LABEL,
    APP_TAGLINE,
    NAVIGATION_KEY,
    NAVIGATION_PAGES,
    apply_queued_navigation,
    navigation_label,
    queue_navigation,
    queue_navigation_reset,
)
from epw_climate_analyzer.chart_theme import metric_color
from epw_climate_analyzer.runtime_identity import RUNTIME_BUILD_ID


_MAP_DEPENDENCIES_LOADED = False
_GEOSPHERE_DEPENDENCIES_LOADED = False
_ANALYSIS_DEPENDENCIES_LOADED = False
_SOLAR_DEPENDENCIES_LOADED = False
_COMPARISON_DEPENDENCIES_LOADED = False


def _ensure_map_dependencies() -> None:
    """Load map/catalog dependencies only after the user selects Find climate."""
    global _MAP_DEPENDENCIES_LOADED
    global pd, folium, FastMarkerCluster, MarkerCluster, st_folium
    global download_station_epw, filter_station_catalog
    global catalog_runtime_summary, load_production_station_catalog, load_station_catalog_manifest, station_provenance_text
    global load_station_group_snapshot

    if _MAP_DEPENDENCIES_LOADED:
        return

    import pandas as pd
    import folium
    from folium.plugins import FastMarkerCluster, MarkerCluster
    from streamlit_folium import st_folium
    from epw_climate_analyzer.climate_sources import download_station_epw, filter_station_catalog
    from epw_climate_analyzer.catalog_runtime import (
        catalog_runtime_summary,
        load_production_station_catalog,
        load_station_catalog_manifest,
        station_provenance_text,
    )
    from epw_climate_analyzer.station_group_snapshot import load_station_group_snapshot
    _MAP_DEPENDENCIES_LOADED = True


def _ensure_geosphere_dependencies() -> None:
    """Load GeoSphere adapter dependencies only when that source is selected."""
    global _GEOSPHERE_DEPENDENCIES_LOADED
    global pd
    global fetch_geosphere_metadata, geosphere_station_catalog, parse_geosphere_stations
    global supported_geosphere_parameter_mapping, fetch_geosphere_station_dataset
    global plan_geosphere_queries, estimate_geosphere_datapoints

    if _GEOSPHERE_DEPENDENCIES_LOADED:
        return

    import pandas as pd
    from epw_climate_analyzer.geosphere import (
        estimate_request_datapoints as estimate_geosphere_datapoints,
        fetch_metadata as fetch_geosphere_metadata,
        fetch_station_dataset as fetch_geosphere_station_dataset,
        parse_stations as parse_geosphere_stations,
        plan_data_queries as plan_geosphere_queries,
        station_catalog as geosphere_station_catalog,
        supported_parameter_mapping as supported_geosphere_parameter_mapping,
    )
    _GEOSPHERE_DEPENDENCIES_LOADED = True


def _ensure_analysis_dependencies(*, include_solar: bool, include_comparison: bool) -> None:
    """Load scientific/plotting dependencies only after an EPW analysis is requested."""
    global _ANALYSIS_DEPENDENCIES_LOADED, _SOLAR_DEPENDENCIES_LOADED, _COMPARISON_DEPENDENCIES_LOADED
    global pd, px
    global aggregate_sum, duration_curve, filter_by_months_and_hours, native_interval_hours, threshold_count_by_period
    global duration_chart, heatmap_chart, histogram_chart, GIVONI_MILNE_ZONES
    global matrix_heatmap, month_hour_heatmap, givoni_milne_zone_table, monthly_box_chart
    global multi_line_monthly, orientation_bar_chart, percentile_band_chart, profile_ribbon_chart
    global psychrometric_chart, scatter_chart, stacked_monthly_bar, sun_path_chart
    global sun_position_diagram, threshold_bar_chart, wind_rose_chart
    global add_degree_metrics, comfort_condition, dehumidification_condition, economizer_condition
    global humidification_condition, natural_ventilation_condition, night_flushing_condition
    global degree_metric_table, degree_metric_interpretation
    global passive_strategy_monthly, passive_strategy_table, rejection_reasons_for_nv, shading_condition
    global location_summary, parse_epw, quality_issues
    global data_quality_interpretation, degree_day_interpretation, hvac_interpretation
    global natural_ventilation_interpretation, psychrometric_interpretation, sky_interpretation
    global solar_interpretation, temperature_interpretation, variable_interpretation, wind_interpretation
    global DEFAULT_PRESSURE_PA, add_psychrometric_properties, pressure_from_altitude_m
    global aggregate_liquid_precipitation, occurrence_hours
    global calculated_statistics_tables, climate_statistics_interpretation, extreme_day_summary
    global monthly_climate_summary, seasonal_climate_summary
    global add_solar_position, monthly_orientation_radiation, orientation_annual_radiation
    global orientation_tilt_matrix, surface_irradiance_series
    global ClimateDataset, choose_display_mode, climate_summary_metrics, comparison_interpretation
    global data_quality_matrix, difference_heatmap_chart, duration_comparison_chart
    global facade_radiation_comparison_chart, hdd_cdd_grouped_chart, heatmap_small_multiples
    global heating_cooling_season_timeline, monthly_box_compare_chart, monthly_difference_chart
    global monthly_profile_table, natural_ventilation_difference_heatmap, natural_ventilation_monthly_table
    global orientation_tilt_small_multiples, overlay_monthly_chart
    global passive_strategy_calendar_small_multiples, passive_strategy_stacked_comparison
    global psychrometric_comparison_chart, ranked_metric_chart, small_multiple_monthly_chart
    global solar_monthly_comparison, sun_path_comparison_chart, tilt_radiation_comparison_chart
    global wind_rose_small_multiples
    global OverlaySeries, available_resolution_labels, build_overlay_figure
    global native_resolution_minutes, validate_unit_families

    if not _ANALYSIS_DEPENDENCIES_LOADED:
        import pandas as pd
        import plotly.express as px
        from epw_climate_analyzer.aggregations import (
            aggregate_sum,
            duration_curve,
            filter_by_months_and_hours,
            native_interval_hours,
            threshold_count_by_period,
        )
        from epw_climate_analyzer.charts import (
            duration_chart,
            heatmap_chart,
            histogram_chart,
            GIVONI_MILNE_ZONES,
            matrix_heatmap,
            month_hour_heatmap,
            givoni_milne_zone_table,
            monthly_box_chart,
            multi_line_monthly,
            orientation_bar_chart,
            percentile_band_chart,
            profile_ribbon_chart,
            psychrometric_chart,
            scatter_chart,
            stacked_monthly_bar,
            sun_path_chart,
            sun_position_diagram,
            threshold_bar_chart,
            wind_rose_chart,
        )
        from epw_climate_analyzer.decisions import (
            add_degree_metrics,
            comfort_condition,
            dehumidification_condition,
            economizer_condition,
            humidification_condition,
            natural_ventilation_condition,
            night_flushing_condition,
            passive_strategy_monthly,
            passive_strategy_table,
            rejection_reasons_for_nv,
            shading_condition,
        )
        from epw_climate_analyzer.degree_metrics import degree_metric_interpretation, degree_metric_table
        from epw_climate_analyzer.epw_parser import location_summary, parse_epw, quality_issues
        from epw_climate_analyzer.interpretations import (
            data_quality_interpretation,
            degree_day_interpretation,
            hvac_interpretation,
            natural_ventilation_interpretation,
            psychrometric_interpretation,
            sky_interpretation,
            solar_interpretation,
            temperature_interpretation,
            variable_interpretation,
            wind_interpretation,
        )
        from epw_climate_analyzer.psychrometrics import (
            DEFAULT_PRESSURE_PA,
            add_psychrometric_properties,
            pressure_from_altitude_m,
        )
        from epw_climate_analyzer.statistics import (
            calculated_statistics_tables,
            climate_statistics_interpretation,
            extreme_day_summary,
            monthly_climate_summary,
            seasonal_climate_summary,
        )
        from epw_climate_analyzer.precipitation import (
            aggregate_liquid_precipitation,
            occurrence_hours,
        )
        from epw_climate_analyzer.timeseries import (
            OverlaySeries,
            available_resolution_labels,
            build_overlay_figure,
            native_resolution_minutes,
            validate_unit_families,
        )
        _ANALYSIS_DEPENDENCIES_LOADED = True

    if include_solar and not _SOLAR_DEPENDENCIES_LOADED:
        from epw_climate_analyzer.solar import (
            add_solar_position,
            monthly_orientation_radiation,
            orientation_annual_radiation,
            orientation_tilt_matrix,
            surface_irradiance_series,
        )
        _SOLAR_DEPENDENCIES_LOADED = True

    if include_comparison and not _COMPARISON_DEPENDENCIES_LOADED:
        from epw_climate_analyzer.comparison import (
            ClimateDataset,
            choose_display_mode,
            climate_summary_metrics,
            comparison_interpretation,
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
            natural_ventilation_difference_heatmap,
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
        _COMPARISON_DEPENDENCIES_LOADED = True


VARIABLES = {
    "Dry-bulb temperature": ("dry_bulb_temperature_c", "°C"),
    "Dew-point temperature": ("dew_point_temperature_c", "°C"),
    "Relative humidity": ("relative_humidity_pct", "%"),
    "Humidity ratio": ("humidity_ratio_g_kg", "g/kg dry air"),
    "Moist-air enthalpy": ("moist_air_enthalpy_kj_kg", "kJ/kg dry air"),
    "Wet-bulb temperature": ("wet_bulb_temperature_c", "°C"),
    "Specific volume": ("specific_volume_m3_kg", "m³/kg dry air"),
    "Moist-air density": ("moist_air_density_kg_m3", "kg/m³"),
    "Station pressure": ("atmospheric_station_pressure_pa", "Pa"),
    "Global horizontal radiation": ("global_horizontal_radiation_wh_m2", "Wh/m²"),
    "Direct normal radiation": ("direct_normal_radiation_wh_m2", "Wh/m²"),
    "Diffuse horizontal radiation": ("diffuse_horizontal_radiation_wh_m2", "Wh/m²"),
    "Global horizontal illuminance": ("global_horizontal_illuminance_lux", "lux"),
    "Direct normal illuminance": ("direct_normal_illuminance_lux", "lux"),
    "Diffuse horizontal illuminance": ("diffuse_horizontal_illuminance_lux", "lux"),
    "Wind speed": ("wind_speed_m_s", "m/s"),
    "Wind direction": ("wind_direction_deg", "deg"),
    "Total sky cover": ("total_sky_cover_tenths", "tenths"),
    "Opaque sky cover": ("opaque_sky_cover_tenths", "tenths"),
    "Liquid precipitation depth": ("liquid_precipitation_depth_mm", "mm"),
    "Snow depth": ("snow_depth_cm", "cm"),
}


PSYCHROMETRIC_COLOR_METRICS = {
    "Month": (None, "Month"),
    "Frequency": (None, "Frequency [h]"),
    "Dry-bulb temperature": ("dry_bulb_temperature_c", "Dry-bulb temperature [°C]"),
    "Relative humidity": ("relative_humidity_pct", "Relative humidity [%]"),
    "Humidity ratio": ("humidity_ratio_g_kg", "Moisture content [g/kg]"),
    "Moist-air enthalpy": ("moist_air_enthalpy_kj_kg", "Enthalpy [kJ/kg]"),
    "Wet-bulb temperature": ("wet_bulb_temperature_c", "Wet-bulb temperature [°C]"),
    "Global horizontal radiation": ("global_horizontal_radiation_wh_m2", "GHI [Wh/m²]"),
    "Direct normal radiation": ("direct_normal_radiation_wh_m2", "DNI [Wh/m²]"),
    "Diffuse horizontal radiation": ("diffuse_horizontal_radiation_wh_m2", "DHI [Wh/m²]"),
    "Wind speed": ("wind_speed_m_s", "Wind speed [m/s]"),
    "Wind direction": ("wind_direction_deg", "Wind direction [deg]"),
    "Total sky cover": ("total_sky_cover_tenths", "Total sky cover [tenths]"),
    "Opaque sky cover": ("opaque_sky_cover_tenths", "Opaque sky cover [tenths]"),
}

PSYCHROMETRIC_METRIC_LINES = [
    "Dry-bulb temperature",
    "Humidity ratio",
    "Relative humidity",
    "Wet-bulb temperature",
    "Vapour pressure",
    "Specific volume",
    "Enthalpy",
]

MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


st.set_page_config(page_title=APP_BROWSER_TITLE, layout="wide", page_icon="🌦️")

# Hidden machine-readable deployment identity.  The live browser audit compares
# this source-derived fingerprint with the exact checked-out source set before a
# deployment is considered current.  The semantic GHI colour is included as a
# direct visual-contract sentinel for VIS-0.1.
_RUNTIME_GHI_COLOR = metric_color("global_horizontal_radiation_wh_m2")
st.markdown(
    (
        '<span id="climate-analyzer-runtime-build" '
        f'data-runtime-build="{html.escape(RUNTIME_BUILD_ID, quote=True)}" '
        f'data-ghi-color="{html.escape(_RUNTIME_GHI_COLOR, quote=True)}" '
        'aria-hidden="true" style="display:none"></span>'
    ),
    unsafe_allow_html=True,
)

# Streamlit 1.63 renders the file-uploader size/type hint with a 0.6-alpha
# foreground color that fails WCAG AA contrast on the default light background.
# Inherit the surrounding instruction color through a stable Streamlit test id;
# do not bind this override to generated Emotion class names.
st.markdown(
    """
    <style>
    [data-testid="stFileUploaderDropzoneInstructions"] span {
        color: inherit !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=True)
def load_epw_from_bytes(
    file_name: str,
    payload: bytes,
    pressure_mode: str,
    custom_pressure_pa: float | None,
    include_psychrometrics: bool = True,
    include_solar: bool = True,
) -> tuple[object, pd.DataFrame, list[object]]:
    """Load an EPW file, calculate only needed derived variables and return cached objects.

    Expensive calculations are controlled by page-level flags. This keeps wind,
    sky and data-quality pages responsive by skipping optional derivations they
    do not need. The Temperature page opts into psychrometrics because its
    variable explorer exposes wet-bulb temperature.
    """
    epw = parse_epw(BytesIO(payload))
    data = add_degree_metrics(epw.data)

    if pressure_mode == "Normal pressure: 101325 Pa":
        fallback_pressure = DEFAULT_PRESSURE_PA
    elif pressure_mode == "Altitude-derived standard atmosphere pressure":
        fallback_pressure = pressure_from_altitude_m(epw.location.elevation_m)
    elif pressure_mode == "Custom constant pressure":
        fallback_pressure = float(custom_pressure_pa or DEFAULT_PRESSURE_PA)
    else:
        valid = data["atmospheric_station_pressure_pa"].dropna()
        fallback_pressure = float(valid.median()) if not valid.empty else DEFAULT_PRESSURE_PA

    if include_psychrometrics:
        data = add_psychrometric_properties(data, fallback_pressure_pa=fallback_pressure)
    if include_solar:
        data = add_solar_position(data, epw.location)

    issues = quality_issues(data)
    return epw, data, issues


def page_derivation_flags(page: str) -> tuple[bool, bool]:
    """Return whether the selected page needs psychrometric and solar columns."""
    pages_requiring_psychrometrics = {
        "Overview",
        "Temperature",
        "Humidity and Psychrometrics",
        "Time Series and Overlay",
        "Natural Ventilation",
        "HVAC and Passive Design",
        "Compare Climates",
    }
    pages_requiring_solar = {
        "Overview",
        "Solar and Radiation",
        "Compare Climates",
    }
    return page in pages_requiring_psychrometrics, page in pages_requiring_solar




def set_active_climate_file(name: str, payload: bytes, source: str) -> None:
    """Store the selected EPW payload and open the summary view."""
    from epw_climate_analyzer.climate_sources import ClimateFilePayload

    st.session_state["active_climate_file"] = ClimateFilePayload(name=name, payload=payload, source=source)
    st.session_state.pop("active_canonical_climate", None)
    queue_navigation(st.session_state, "Overview")


def set_active_canonical_climate(dataset: object) -> None:
    """Store a provider-neutral canonical historical dataset for analysis."""
    from epw_climate_analyzer.climate_model import CanonicalClimateDataset

    if not isinstance(dataset, CanonicalClimateDataset):
        raise TypeError("Expected CanonicalClimateDataset for historical climate activation.")
    st.session_state["active_canonical_climate"] = dataset
    st.session_state.pop("active_climate_file", None)
    queue_navigation(st.session_state, "Temperature")


def get_active_climate_file() -> ClimateFilePayload | None:
    """Return the currently selected EPW payload from Streamlit session state."""
    value = st.session_state.get("active_climate_file")
    if value is None:
        return None
    from epw_climate_analyzer.climate_sources import ClimateFilePayload

    return value if isinstance(value, ClimateFilePayload) else None


def get_active_canonical_climate():
    """Return the active provider-neutral historical dataset, if any."""
    value = st.session_state.get("active_canonical_climate")
    if value is None:
        return None
    from epw_climate_analyzer.climate_model import CanonicalClimateDataset

    return value if isinstance(value, CanonicalClimateDataset) else None


def clear_active_climate_file() -> None:
    """Remove every active climate source and reset navigation."""
    st.session_state.pop("active_climate_file", None)
    st.session_state.pop("active_canonical_climate", None)
    queue_navigation_reset(st.session_state)



@st.cache_data(show_spinner=False, ttl=3600)
def cached_geosphere_metadata() -> dict:
    """Cache current GeoSphere metadata for one hour within a user session/runtime."""
    from epw_climate_analyzer.geosphere import fetch_metadata

    return fetch_metadata()


@st.cache_resource(show_spinner=False, max_entries=1)
def _cached_station_catalog_by_identity(catalog_version: str, catalog_sha256: str) -> pd.DataFrame:
    """Load one reviewed catalog snapshot under an immutable cache identity."""
    from epw_climate_analyzer.catalog_runtime import load_production_station_catalog

    catalog = load_production_station_catalog()
    if catalog.empty:
        return catalog

    actual_version = str(catalog["catalog_version"].iloc[0])
    actual_sha256 = str(catalog["catalog_sha256"].iloc[0])
    if actual_version != catalog_version or actual_sha256 != catalog_sha256:
        raise RuntimeError(
            "Station catalog cache identity mismatch: "
            f"expected {catalog_version}/{catalog_sha256}, "
            f"loaded {actual_version}/{actual_sha256}."
        )
    return catalog


def cached_station_catalog() -> pd.DataFrame:
    """Return the current reviewed catalog through a call-site-safe public API.

    The public helper is intentionally uncached and has no cache-key arguments.
    It reads the current manifest on every rerun and delegates to the internal
    cached function keyed by catalog version and byte-level SHA. This preserves
    stale-cache protection across redeploys without leaking cache mechanics into
    Find climate, Compare climates, or future UI call-sites.
    """
    from epw_climate_analyzer.catalog_runtime import load_station_catalog_manifest

    manifest = load_station_catalog_manifest()
    return _cached_station_catalog_by_identity(manifest.catalog_version, manifest.csv_sha256)


def _onebuilding_map_cache_key(
    catalog_identity: str,
    search_text: str,
    countries: list[str],
    datasets: list[str],
) -> str:
    """Return a deterministic identity for one immutable OneBuilding map/filter state."""
    country_key = ",".join(sorted(str(value).strip() for value in countries if str(value).strip()))
    dataset_key = ",".join(sorted(str(value).strip() for value in datasets if str(value).strip()))
    return f"{catalog_identity}|q={search_text.strip().casefold()}|c={country_key}|d={dataset_key}"


@st.cache_resource(show_spinner=False, max_entries=4)
def _cached_station_group_snapshot(catalog_version: str, catalog_sha256: str) -> pd.DataFrame:
    """Load the release-time physical-station snapshot once per immutable catalog identity."""
    return load_station_group_snapshot(catalog_version, catalog_sha256)


@st.cache_resource(show_spinner=False, max_entries=4)
def _cached_catalog_filter_options(catalog_identity: str, _catalog: pd.DataFrame) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Cache stable country/dataset selector values for one reviewed catalog snapshot."""
    countries = tuple(sorted(value for value in _catalog["country"].dropna().unique().tolist() if str(value).strip()))
    datasets = tuple(sorted(value for value in _catalog["dataset"].dropna().unique().tolist() if str(value).strip()))
    return countries, datasets


@st.cache_resource(show_spinner=False, max_entries=8)
def _cached_grouped_station_catalog(map_cache_key: str, _catalog: pd.DataFrame) -> pd.DataFrame:
    """Cache filtered physical-station grouping; the unfiltered route uses the release snapshot."""
    return grouped_station_catalog(_catalog)



@st.cache_data(show_spinner=False, max_entries=8)
def _cached_station_group_options(
    map_cache_key: str,
    limit: int,
    _station_groups: pd.DataFrame,
) -> dict[str, str]:
    """Cache the manual station-group selector derived from the same immutable groups."""
    return station_group_options_from_groups(_station_groups, limit=limit)


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_station_marker_payload(
    map_cache_key: str,
    _station_groups: pd.DataFrame,
) -> list[list[object]]:
    """Cache the compact browser marker payload for one immutable map/filter state."""
    return station_marker_payload(_station_groups)


@st.cache_data(show_spinner=False, max_entries=512)
def _cached_catalog_rows_for_station_group(
    map_cache_key: str,
    station_group_id: str,
    _catalog: pd.DataFrame,
    _station_group: object,
) -> pd.DataFrame:
    """Cache one station group's climate rows for the exact catalog/filter identity."""
    return catalog_rows_for_station_group(_catalog, _station_group)


def station_options_from_catalog(catalog: pd.DataFrame, limit: int = 10000) -> dict[str, str]:
    """Return cached station-list labels for the right-panel selectors."""
    options: dict[str, str] = {}
    for _, row in catalog.head(limit).iterrows():
        options[station_label(row)] = str(row["station_id"])
    return options


def station_label(row: pd.Series) -> str:
    """Return a compact human-readable label for a weather station."""
    region = f", {row.get('region', '')}" if str(row.get("region", "")).strip() else ""
    dataset = f" [{row.get('dataset', '')}]" if str(row.get("dataset", "")).strip() else ""
    return f"{row['name']} — {row['country']}{region}{dataset}"


def station_tooltip(row: pd.Series) -> str:
    """Return a stable tooltip that can be parsed after a map marker click."""
    return f"station_id={row['station_id']} | {station_label(row)}"



def station_group_id(row: pd.Series) -> str:
    """Return a stable group identifier for all climates belonging to one physical station.

    Climate.OneBuilding may contain several EPW climates for the same physical
    station, for example from different source datasets or periods. The map must
    show one station bubble and let the user choose the climate after selecting
    that bubble. The grouping key therefore combines the normalized station name,
    country, and rounded coordinates.
    """
    name = str(row.get("name", "")).strip().lower()
    country = str(row.get("country", "")).strip().lower()
    try:
        lat = round(float(row.get("latitude")), 4)
        lon = round(float(row.get("longitude")), 4)
    except Exception:
        lat, lon = 0.0, 0.0
    return f"{country}|{name}|{lat:.4f}|{lon:.4f}"


def _limited_distinct_text(values: pd.Series, limit: int) -> str:
    items = sorted({str(value).strip() for value in values.dropna().tolist() if str(value).strip()})
    return ", ".join(items[:limit])


def grouped_station_catalog(catalog: pd.DataFrame) -> pd.DataFrame:
    """Return one compact row per physical station without copying the full catalog."""
    if catalog.empty:
        return pd.DataFrame()

    lat_key = pd.to_numeric(catalog["latitude"], errors="coerce").round(4).rename("_lat_key")
    lon_key = pd.to_numeric(catalog["longitude"], errors="coerce").round(4).rename("_lon_key")
    country_key = catalog["country"].astype("string").fillna("").str.strip().str.lower().rename("_country_key")
    name_key = catalog["name"].astype("string").fillna("").str.strip().str.lower().rename("_name_key")
    valid = lat_key.notna() & lon_key.notna()
    if not bool(valid.any()):
        return pd.DataFrame()

    # Project only the seven columns needed for grouping. This bounds the
    # temporary table even when the reviewed catalog contains 98k climate rows.
    base = catalog.loc[
        valid,
        ["name", "country", "region", "dataset", "latitude", "longitude", "elevation_m"],
    ]
    grouped = base.groupby(
        [
            country_key.loc[valid],
            name_key.loc[valid],
            lat_key.loc[valid],
            lon_key.loc[valid],
        ],
        sort=False,
        observed=True,
        dropna=False,
    )
    summary = grouped.agg(
        name=("name", "first"),
        country=("country", "first"),
        region=("region", lambda values: _limited_distinct_text(values, 3)),
        dataset=("dataset", lambda values: _limited_distinct_text(values, 4)),
        latitude=("latitude", "first"),
        longitude=("longitude", "first"),
        elevation_m=("elevation_m", "first"),
        climate_count=("name", "size"),
    ).reset_index()

    summary["station_group_id"] = (
        summary["_country_key"].astype(str)
        + "|"
        + summary["_name_key"].astype(str)
        + "|"
        + summary["_lat_key"].map(lambda value: f"{float(value):.4f}")
        + "|"
        + summary["_lon_key"].map(lambda value: f"{float(value):.4f}")
    )
    return summary[
        [
            "station_group_id",
            "name",
            "country",
            "region",
            "dataset",
            "latitude",
            "longitude",
            "elevation_m",
            "climate_count",
            "_country_key",
            "_name_key",
            "_lat_key",
            "_lon_key",
        ]
    ]


def station_group_options_from_groups(groups: pd.DataFrame, limit: int = 10000) -> dict[str, str]:
    """Return manual-selector labels from an already grouped station table."""
    options: dict[str, str] = {}
    for _, row in groups.head(limit).iterrows():
        count = int(row.get("climate_count", 1))
        suffix = f" ({count} climates)" if count != 1 else " (1 climate)"
        region = f", {row.get('region', '')}" if str(row.get("region", "")).strip() else ""
        options[f"{row['name']} — {row['country']}{region}{suffix}"] = str(row["station_group_id"])
    return options


def station_group_options_from_catalog(catalog: pd.DataFrame, limit: int = 10000) -> dict[str, str]:
    """Compatibility wrapper for callers that have not already grouped the catalog."""
    return station_group_options_from_groups(grouped_station_catalog(catalog), limit=limit)


def climate_option_label(row: pd.Series) -> str:
    """Return a label for one available climate within a selected station group."""
    dataset = str(row.get("dataset", "")).strip() or "Unknown dataset"
    source = str(row.get("source", "")).strip() or "Climate.OneBuilding"
    region = str(row.get("region", "")).strip()
    elevation = row.get("elevation_m", "")
    try:
        elevation_text = f", {float(elevation):.0f} m"
    except Exception:
        elevation_text = ""
    region_text = f", {region}" if region else ""
    return f"{dataset}{region_text}{elevation_text} — {source}"


def station_group_tooltip(row: pd.Series) -> str:
    """Return a tooltip that can be parsed after a grouped station marker click."""
    return f"station_group_id={row['station_group_id']} | {row['name']} — {row['country']}"


def station_catalog_grouped_map(
    station_groups: pd.DataFrame,
    selected_group_id: str | None = None,
    center: list[float] | None = None,
    zoom: int = 8,
) -> folium.Map:
    """Build the close-zoom map with one clickable violet bubble per station.

    Each bubble represents one physical station. If that station has several
    climate files, the bubble remains single and the climate list is shown in the
    right-hand panel after clicking it.
    """
    center_lat = float(station_groups["latitude"].mean()) if center is None and not station_groups.empty else (center[0] if center else 20.0)
    center_lon = float(station_groups["longitude"].mean()) if center is None and not station_groups.empty else (center[1] if center else 0.0)
    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=int(zoom), tiles="OpenStreetMap", control_scale=True)

    for _, row in station_groups.iterrows():
        group_id = str(row["station_group_id"])
        is_selected = group_id == str(selected_group_id)
        color = "#ef4444" if is_selected else "#7c3aed"
        radius = 9 if is_selected else 6
        count = int(row.get("climate_count", 1))
        popup_html = (
            f"<b>{row['name']}</b><br>"
            f"Country: {row.get('country', '')}<br>"
            f"Region: {row.get('region', '')}<br>"
            f"Available climates: {count}<br>"
            f"<small>Click this station bubble, then choose the required climate in the right panel.</small>"
        )
        folium.CircleMarker(
            location=[float(row["latitude"]), float(row["longitude"])],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            weight=2 if is_selected else 1,
            popup=folium.Popup(popup_html, max_width=360),
            tooltip=station_group_tooltip(row),
        ).add_to(fmap)

    return fmap


def _map_text(value: object) -> str:
    """Return HTML-safe text for station-map popups and JavaScript payloads."""
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value), quote=True)


def station_catalog_fast_map(catalog: pd.DataFrame, center: list[float] | None = None, zoom: int = 2) -> folium.Map:
    """Build the original fast aggregated overview for station catalogs.

    This function is retained for compatibility, but the UI now uses
    ``station_catalog_fast_selectable_map`` so that the same clustered visual
    style also supports clickable station bubbles at close zoom levels.
    """
    center_lat = float(catalog["latitude"].mean()) if center is None and not catalog.empty else (center[0] if center else 20.0)
    center_lon = float(catalog["longitude"].mean()) if center is None and not catalog.empty else (center[1] if center else 0.0)
    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=int(zoom), tiles="OpenStreetMap", control_scale=True)
    points = (
        catalog[["latitude", "longitude"]]
        .dropna()
        .astype(float)
        .values
        .tolist()
    )
    if points:
        FastMarkerCluster(points, name=f"Station clusters ({len(points):,})").add_to(fmap)
    folium.LayerControl().add_to(fmap)
    return fmap


def station_marker_payload(station_groups: pd.DataFrame) -> list[list[object]]:
    """Return the minimal stable marker payload needed by the browser map.

    The right-hand station panel owns rich metadata.  The map therefore sends
    only coordinates, a positional station index and a short label.  This keeps
    the world-map transfer bounded while preserving exact click resolution.
    """
    payload: list[list[object]] = []
    if station_groups.empty:
        return payload
    columns = list(station_groups.columns)
    lat_idx = columns.index("latitude")
    lon_idx = columns.index("longitude")
    name_idx = columns.index("name")
    country_idx = columns.index("country")
    for station_idx, row in enumerate(station_groups.itertuples(index=False, name=None)):
        try:
            lat = float(row[lat_idx])
            lon = float(row[lon_idx])
        except (TypeError, ValueError):
            continue
        if pd.isna(lat) or pd.isna(lon):
            continue
        name = _map_text(row[name_idx])
        country = _map_text(row[country_idx])
        label = f"{name} — {country}" if country else name
        payload.append([lat, lon, int(station_idx), label])
    return payload


def station_catalog_persistent_map_layers(
    station_groups: pd.DataFrame,
    marker_payload: list[list[object]] | None = None,
    center: list[float] | None = None,
    zoom: int = 2,
    detail_zoom_threshold: int = 8,
) -> tuple[folium.Map, folium.FeatureGroup]:
    """Build a lightweight base map plus a dynamically managed marker layer.

    ``streamlit-folium`` keeps the mounted Leaflet map alive when marker data are
    supplied via ``feature_group_to_add``.  The feature-group string is compared
    in the browser, so an unchanged station layer is not recreated after a
    station click.  A fresh Python Folium base object is still used on every
    rerun to avoid mutable-JS identifier reuse.
    """
    center_lat = float(station_groups["latitude"].mean()) if center is None and not station_groups.empty else (center[0] if center else 20.0)
    center_lon = float(station_groups["longitude"].mean()) if center is None and not station_groups.empty else (center[1] if center else 0.0)
    fmap = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=int(zoom),
        tiles="OpenStreetMap",
        control_scale=True,
        prefer_canvas=True,
    )
    feature_group = folium.FeatureGroup(name="Climate stations", overlay=True, control=False)
    data = marker_payload if marker_payload is not None else station_marker_payload(station_groups)
    callback = """
    function (row) {
        var marker = L.circleMarker(new L.LatLng(row[0], row[1]), {
            radius: 6,
            color: '#7c3aed',
            fillColor: '#7c3aed',
            fillOpacity: 0.86,
            weight: 1
        });
        marker.bindTooltip('station_idx=' + row[2] + ' | ' + row[3], {sticky: true});
        return marker;
    }
    """
    if data:
        FastMarkerCluster(
            data,
            callback=callback,
            name=f"Station clusters ({len(data):,})",
            disableClusteringAtZoom=int(detail_zoom_threshold),
            spiderfyOnMaxZoom=True,
            showCoverageOnHover=False,
            chunkedLoading=True,
        ).add_to(feature_group)
    return fmap, feature_group


def station_catalog_fast_selectable_map(
    station_groups: pd.DataFrame,
    selected_group_id: str | None = None,
    center: list[float] | None = None,
    zoom: int = 2,
    detail_zoom_threshold: int = 8,
) -> folium.Map:
    """Compatibility wrapper returning a standalone selectable Folium map."""
    fmap, marker_group = station_catalog_persistent_map_layers(
        station_groups,
        center=center,
        zoom=zoom,
        detail_zoom_threshold=detail_zoom_threshold,
    )
    marker_group.add_to(fmap)
    return fmap


def station_group_from_tooltip(station_groups: pd.DataFrame, tooltip: str | None) -> pd.Series | None:
    """Resolve a clicked grouped station tooltip to a station-group row."""
    if not tooltip:
        return None
    if "station_idx=" in tooltip:
        raw = tooltip.split("station_idx=", 1)[1].split(" | ", 1)[0].strip()
        try:
            station_idx = int(raw)
        except ValueError:
            return None
        if 0 <= station_idx < len(station_groups):
            return station_groups.iloc[station_idx]
        return None
    if "station_group_id=" not in tooltip:
        return None
    group_id = tooltip.split("station_group_id=", 1)[1].split(" | ", 1)[0].strip()
    matches = station_groups[station_groups["station_group_id"].astype(str) == group_id]
    if matches.empty:
        return None
    return matches.iloc[0]


def catalog_rows_for_station_group(catalog: pd.DataFrame, station_group: object) -> pd.DataFrame:
    """Return climates for one station using coordinate-first bounded filtering."""
    if catalog.empty or station_group is None:
        return pd.DataFrame()

    if isinstance(station_group, pd.Series):
        group = station_group
    elif isinstance(station_group, dict):
        group = pd.Series(station_group)
    else:
        # Compatibility path for an old textual group id. It is not used by the
        # production UI; resolve it once through the compact grouped table.
        groups = grouped_station_catalog(catalog)
        matches = groups[groups["station_group_id"].astype(str) == str(station_group)]
        if matches.empty:
            return pd.DataFrame()
        group = matches.iloc[0]

    target_lat = float(group.get("_lat_key", round(float(group.get("latitude")), 4)))
    target_lon = float(group.get("_lon_key", round(float(group.get("longitude")), 4)))
    lat = pd.to_numeric(catalog["latitude"], errors="coerce").round(4)
    lon = pd.to_numeric(catalog["longitude"], errors="coerce").round(4)
    candidates = catalog.loc[lat.eq(target_lat) & lon.eq(target_lon)]
    if candidates.empty:
        return pd.DataFrame()

    target_name = str(group.get("_name_key", group.get("name", ""))).strip().lower()
    target_country = str(group.get("_country_key", group.get("country", ""))).strip().lower()
    names = candidates["name"].astype("string").fillna("").str.strip().str.lower()
    countries = candidates["country"].astype("string").fillna("").str.strip().str.lower()
    return candidates.loc[names.eq(target_name) & countries.eq(target_country)].copy()


def _map_state_center(map_state: dict | None) -> list[float] | None:
    """Extract a [lat, lon] center from a streamlit-folium state dictionary."""
    if not isinstance(map_state, dict):
        return None
    center = map_state.get("center")
    if isinstance(center, dict) and "lat" in center and "lng" in center:
        return [float(center["lat"]), float(center["lng"])]
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        return [float(center[0]), float(center[1])]
    return None


def _map_state_zoom(map_state: dict | None) -> int | None:
    """Extract the current zoom level from a streamlit-folium state dictionary."""
    if not isinstance(map_state, dict):
        return None
    zoom = map_state.get("zoom")
    if zoom is None:
        return None
    try:
        return int(zoom)
    except Exception:
        return None


def _map_state_bounds(map_state: dict | None) -> tuple[float, float, float, float] | None:
    """Extract south, west, north and east bounds from streamlit-folium state."""
    if not isinstance(map_state, dict):
        return None
    bounds = map_state.get("bounds")
    if not bounds:
        return None
    try:
        if isinstance(bounds, dict):
            sw = bounds.get("_southWest") or bounds.get("southWest") or bounds.get("southwest")
            ne = bounds.get("_northEast") or bounds.get("northEast") or bounds.get("northeast")
            if isinstance(sw, dict) and isinstance(ne, dict):
                return float(sw["lat"]), float(sw["lng"]), float(ne["lat"]), float(ne["lng"])
        if isinstance(bounds, (list, tuple)) and len(bounds) >= 2:
            sw, ne = bounds[0], bounds[1]
            return float(sw[0]), float(sw[1]), float(ne[0]), float(ne[1])
    except Exception:
        return None
    return None


def update_station_map_view_state(map_state: dict | None) -> None:
    """Persist the current map center, zoom and bounds across reruns.

    This prevents the map from jumping back to the world view after a station is
    clicked or after switching between fast overview and detailed markers.
    """
    center = _map_state_center(map_state)
    zoom = _map_state_zoom(map_state)
    bounds = _map_state_bounds(map_state)
    if center is not None:
        st.session_state["station_map_center"] = center
    if zoom is not None:
        st.session_state["station_map_zoom"] = zoom
    if bounds is not None:
        st.session_state["station_map_bounds"] = bounds


def filter_groups_to_bounds(
    station_groups: pd.DataFrame,
    bounds: tuple[float, float, float, float] | None,
    margin_fraction: float = 0.15,
) -> pd.DataFrame:
    """Return station groups within the current map bounds plus a margin."""
    if station_groups.empty or bounds is None:
        return station_groups
    south, west, north, east = bounds
    lat_margin = max((north - south) * margin_fraction, 0.05)
    lon_margin = max((east - west) * margin_fraction, 0.05)
    south -= lat_margin
    north += lat_margin
    west -= lon_margin
    east += lon_margin
    mask = (
        station_groups["latitude"].astype(float).between(south, north)
        & station_groups["longitude"].astype(float).between(west, east)
    )
    return station_groups[mask].copy()

def render_geosphere_source() -> None:
    """Render GeoSphere Austria historical station selection and bounded loading."""
    _ensure_geosphere_dependencies()
    st.subheader("GeoSphere Austria — measured historical station data")
    st.caption(
        "Quality-checked `klima-v2-10min` observations are loaded directly from the official GeoSphere Austria Dataset API. "
        "Timestamps remain real UTC historical timestamps; the data are not converted to an EPW typical year."
    )
    try:
        metadata = cached_geosphere_metadata()
        supported = supported_geosphere_parameter_mapping(metadata)
        stations = parse_geosphere_stations(metadata)
        catalog = geosphere_station_catalog(metadata)
    except Exception as exc:
        st.error(f"GeoSphere metadata could not be loaded or validated: {exc}")
        return

    search = st.text_input("Search GeoSphere station", value="", key="geosphere_station_search")
    states = sorted(value for value in catalog["state"].dropna().astype(str).unique().tolist() if value.strip())
    selected_states = st.multiselect("Federal states / regions", states, default=[], key="geosphere_station_states")
    filtered = catalog.copy()
    if search.strip():
        needle = search.strip().lower()
        mask = (
            filtered["name"].astype(str).str.lower().str.contains(needle, regex=False)
            | filtered["station_id"].astype(str).str.lower().str.contains(needle, regex=False)
            | filtered["state"].astype(str).str.lower().str.contains(needle, regex=False)
        )
        filtered = filtered[mask]
    if selected_states:
        filtered = filtered[filtered["state"].isin(selected_states)]
    if filtered.empty:
        st.warning("No GeoSphere stations match the current filter.")
        return

    station_by_id = {station.station_id: station for station in stations}
    option_ids = [str(value) for value in filtered["station_id"].tolist() if str(value) in station_by_id]
    if not option_ids:
        st.error("GeoSphere metadata contain no selectable stations after normalization.")
        return

    def station_label(station_id: str) -> str:
        station = station_by_id[station_id]
        state = f" — {station.state}" if station.state else ""
        return f"{station.name}{state} — ID {station.station_id}"

    selected_id = st.selectbox(
        "Station",
        option_ids,
        format_func=station_label,
        key="geosphere_station_id",
    )
    station = station_by_id[selected_id]
    st.dataframe(
        pd.DataFrame(
            {
                "Field": ["Station", "ID", "Region", "Latitude", "Longitude", "Elevation", "Provider validity"],
                "Value": [
                    station.name, station.station_id, station.state,
                    f"{station.latitude:.5f}", f"{station.longitude:.5f}",
                    f"{station.elevation_m:.0f} m" if station.elevation_m is not None else "",
                    f"{station.valid_from or 'unknown'} … {station.valid_to or 'unknown'}",
                ],
            }
        ),
        hide_index=True,
        use_container_width=True,
    )

    today = pd.Timestamp.now(tz="UTC").date()
    parsed_from = pd.to_datetime(station.valid_from, errors="coerce")
    parsed_to = pd.to_datetime(station.valid_to, errors="coerce")
    min_date = parsed_from.date() if pd.notna(parsed_from) else pd.Timestamp("1900-01-01").date()
    provider_max = parsed_to.date() if pd.notna(parsed_to) else today
    max_date = min(provider_max, today)
    if max_date < min_date:
        st.error("The station validity interval does not overlap the available historical date range.")
        return
    default_end = max_date
    default_start = max(min_date, (pd.Timestamp(default_end) - pd.Timedelta(days=30)).date())
    c1, c2 = st.columns(2)
    start_date = c1.date_input(
        "From date (UTC)", value=default_start, min_value=min_date, max_value=max_date, key="geosphere_start_date"
    )
    end_date = c2.date_input(
        "Through date (UTC)", value=default_end, min_value=min_date, max_value=max_date, key="geosphere_end_date"
    )
    if end_date < start_date:
        st.error("GeoSphere end date must not be earlier than start date.")
        return
    selected_days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days + 1
    if selected_days > 366:
        st.error("The public beta currently allows at most 366 days per GeoSphere load. Choose a shorter interval.")
        return

    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(hours=23, minutes=50)
    provider_parameters = tuple(supported.keys())
    if "tl" not in provider_parameters:
        st.error("Current GeoSphere metadata do not expose the required air-temperature parameter `tl`.")
        return
    canonical_variables = tuple(spec.canonical_name for spec in supported.values())
    estimated = estimate_geosphere_datapoints(start_ts, end_ts, len(provider_parameters), 1)
    batches = plan_geosphere_queries(station.station_id, start_ts, end_ts, provider_parameters)
    st.caption(
        f"Requested interval: {selected_days} day(s), 10-minute source data, {len(provider_parameters)} supported measured variables. "
        f"Estimated provider datapoints: {estimated:,}; bounded API batches: {len(batches)}."
    )
    with st.expander("Measured variables and provenance", expanded=False):
        variable_rows = [
            {"Provider": name, "Canonical field": spec.canonical_name, "Description": spec.description}
            for name, spec in supported.items()
        ]
        st.dataframe(pd.DataFrame(variable_rows), hide_index=True, use_container_width=True)
        st.caption("Source: GeoSphere Austria `klima-v2-10min` · CC BY 4.0 · DOI 10.60669/8fya-7x87")

    if st.button("Load measured GeoSphere interval", type="primary", key="load_geosphere_interval"):
        try:
            with st.spinner(f"Loading {len(batches)} bounded GeoSphere request batch(es)..."):
                dataset = fetch_geosphere_station_dataset(
                    station=station,
                    start=start_ts,
                    end=end_ts,
                    metadata=metadata,
                    canonical_variables=canonical_variables,
                )
            set_active_canonical_climate(dataset)
            st.rerun()
        except Exception as exc:
            st.error(f"GeoSphere station-data load failed: {exc}")


def render_climate_file_source() -> None:
    """Render the product entry page for local or catalog climate selection."""
    st.title(APP_NAME)
    st.markdown(f"#### {APP_TAGLINE}")
    st.write(APP_INTRO)
    st.write(APP_RELEASE_LABEL)
    with st.expander("About this beta", expanded=False):
        st.write(APP_ENGINEERING_DISCLAIMER)
        st.caption(APP_INDEPENDENCE_NOTICE)
    st.write(
        "Start with an EPW weather file, select a reviewed Climate.OneBuilding climate, or load measured "
        "historical station observations from GeoSphere Austria. No building model is required."
    )

    active = get_active_climate_file()
    active_historical = get_active_canonical_climate()
    if active is not None or active_historical is not None:
        active_name = active.name if active is not None else active_historical.display_name
        st.success(f"Current climate: {active_name}")
        with st.expander("Data source details", expanded=False):
            if active is not None:
                st.caption(active.source)
            else:
                st.caption(f"{active_historical.provenance.provider} | {active_historical.provenance.dataset}")
                st.caption(active_historical.provenance.source_reference)
        if st.button("Choose a different climate"):
            clear_active_climate_file()
            st.rerun()

    st.divider()
    source_mode = st.radio(
        "Climate source",
        ["Upload EPW", "Find climate", "GeoSphere Austria"],
        horizontal=True,
        label_visibility="collapsed",
        key="climate_source_mode",
    )

    if source_mode == "Upload EPW":
        st.subheader("Upload an EPW weather file")
        st.write("Use an EnergyPlus Weather (EPW) file that you already have. The file is processed for the current session.")
        local_file = st.file_uploader("Choose EPW file", type=["epw"], key="local_epw_upload")
        if local_file is not None:
            st.write(f"Selected file: `{local_file.name}`")
            if st.button("Analyze this EPW", type="primary"):
                set_active_climate_file(local_file.name, local_file.getvalue(), "Local upload | user-provided EPW | transient session")
                st.rerun()
        return

    if source_mode == "GeoSphere Austria":
        render_geosphere_source()
        return

    _ensure_map_dependencies()
    st.subheader("Find a climate from Climate.OneBuilding")
    st.caption(
        "Search or zoom to a station, choose one of its available climate datasets, then load the EPW for analysis."
    )
    try:
        catalog = cached_station_catalog()
    except Exception as exc:
        st.error(f"The versioned station catalog failed integrity/provenance validation: {exc}")
        return
    st.caption(catalog_runtime_summary(catalog))
    if catalog.empty:
        st.error("The versioned station catalog is empty. A reviewed catalog update is required before online station selection can be used.")
        return

    col_filter1, col_filter2, col_filter3 = st.columns([2, 1, 1])
    search_text = col_filter1.text_input("Search station, country, region, dataset or ID", value="")
    catalog_version = str(catalog["catalog_version"].iloc[0])
    catalog_sha256 = str(catalog["catalog_sha256"].iloc[0])
    catalog_identity = f"{catalog_version}:{catalog_sha256}"
    countries, datasets = _cached_catalog_filter_options(catalog_identity, catalog)
    selected_countries = col_filter2.multiselect("Countries", countries, default=[])
    selected_datasets = col_filter3.multiselect("Datasets", datasets, default=[])
    map_cache_key = _onebuilding_map_cache_key(catalog_identity, search_text, selected_countries, selected_datasets)
    uses_full_catalog_snapshot = not search_text.strip() and not selected_countries and not selected_datasets
    if uses_full_catalog_snapshot:
        # Common world-map route: reuse the immutable reviewed catalog and a release-time
        # physical-station snapshot. No 98k-row copy or live grouping is required.
        filtered_catalog = catalog
    else:
        filtered_catalog = filter_station_catalog(
            catalog,
            search_text=search_text,
            countries=selected_countries if selected_countries else None,
            datasets=selected_datasets if selected_datasets else None,
        )

    st.caption(f"Visible catalog records after filters: {len(filtered_catalog):,} of {len(catalog):,}")
    if filtered_catalog.empty:
        st.warning("No stations match the current filters.")
        return

    if uses_full_catalog_snapshot:
        try:
            station_groups_all = _cached_station_group_snapshot(catalog_version, catalog_sha256)
        except Exception as exc:
            st.warning(f"Pre-grouped station snapshot is unavailable; rebuilding the map index once: {exc}")
            station_groups_all = _cached_grouped_station_catalog(map_cache_key, filtered_catalog)
    else:
        station_groups_all = _cached_grouped_station_catalog(map_cache_key, filtered_catalog)
    if station_groups_all.empty:
        st.warning("No grouped station records are available for the current filters.")
        return

    # Leaflet/browser owns ordinary pan and zoom state. Do not return center,
    # zoom or bounds to Streamlit: those values change continuously and used to
    # trigger Python reruns that could race with a freshly rendered Leaflet view.
    # A reset is explicit and remounts only the map component via a view epoch.
    default_center = [float(station_groups_all["latitude"].mean()), float(station_groups_all["longitude"].mean())]
    initial_zoom = 2 if len(station_groups_all) > 25 else 6
    if "station_map_view_epoch" not in st.session_state:
        st.session_state["station_map_view_epoch"] = 0

    if st.button("Reset map view to filtered stations"):
        st.session_state["station_map_view_epoch"] = int(st.session_state.get("station_map_view_epoch", 0)) + 1
        st.rerun()

    with st.expander("Advanced map settings", expanded=False):
        detail_zoom_threshold = st.slider(
            "Show individual stations from zoom level",
            min_value=5,
            max_value=12,
            value=int(st.session_state.get("station_detail_zoom_threshold", 8)),
            help=(
                "The clustered overview remains visible at lower zoom levels. "
                "At this zoom level or closer, Leaflet disables clustering and shows "
                "clickable violet station bubbles. This is handled inside one stable map, "
                "not by switching between two Streamlit map components."
            ),
        )
        st.session_state["station_detail_zoom_threshold"] = detail_zoom_threshold
        selectable_limit = st.slider(
            "Maximum station groups rendered on map",
            min_value=1000,
            max_value=100000,
            value=int(st.session_state.get("station_selectable_cluster_limit", 50000)),
            step=5000,
            help=(
                "The map renders one browser-side clustered marker per physical station group. "
                "If the filtered catalog is larger than this limit, refine the country, dataset, or search filters."
            ),
        )
        st.session_state["station_selectable_cluster_limit"] = selectable_limit

    selected_group_id = st.session_state.get("selected_station_group_id")
    group_ids = set(station_groups_all["station_group_id"].astype(str))
    if selected_group_id not in group_ids:
        selected_group_id = str(station_groups_all.iloc[0]["station_group_id"])
        st.session_state["selected_station_group_id"] = selected_group_id

    station_groups_for_map = station_groups_all
    if len(station_groups_for_map) > int(st.session_state.get("station_selectable_cluster_limit", 50000)):
        st.warning(
            f"The current filter returns {len(station_groups_for_map):,} physical station groups. "
            "This is too many for a responsive selectable browser map. Refine the country, dataset, or search filters. "
            "The table selector on the right remains available for filtered results."
        )
        station_groups_for_map = station_groups_for_map.head(0)

    left, right = st.columns([2, 1])
    with left:
        st.caption(
            f"Clustered overview is active. At zoom {int(st.session_state.get('station_detail_zoom_threshold', 8))} "
            "or closer, the same map reveals clickable violet station bubbles. "
            "Pan and zoom stay in the browser and do not trigger a Streamlit rerun; only station selection or an explicit reset returns control to the app."
        )
        marker_payload = _cached_station_marker_payload(map_cache_key, station_groups_for_map)
        base_map, marker_group = station_catalog_persistent_map_layers(
            station_groups_for_map,
            marker_payload=marker_payload,
            center=[20.0, 0.0],
            zoom=2,
            detail_zoom_threshold=int(st.session_state.get("station_detail_zoom_threshold", 8)),
        )
        map_state = st_folium(
            base_map,
            feature_group_to_add=marker_group,
            height=620,
            use_container_width=True,
            returned_objects=["last_object_clicked_tooltip"],
            center=tuple(default_center),
            zoom=initial_zoom,
            key=f"climate_onebuilding_selectable_cluster_map_{int(st.session_state.get('station_map_view_epoch', 0))}",
        )

    clicked_group = None
    if isinstance(map_state, dict):
        clicked_group = station_group_from_tooltip(station_groups_all, map_state.get("last_object_clicked_tooltip"))
    if clicked_group is not None:
        selected_group_id = str(clicked_group["station_group_id"])
        st.session_state["selected_station_group_id"] = selected_group_id

    selected_group_matches = station_groups_all[station_groups_all["station_group_id"].astype(str) == str(selected_group_id)]
    selected_group = selected_group_matches.iloc[0] if not selected_group_matches.empty else station_groups_all.iloc[0]
    selected_climates = _cached_catalog_rows_for_station_group(
        map_cache_key,
        str(selected_group.get("station_group_id", "")),
        filtered_catalog,
        selected_group,
    )
    if selected_climates.empty:
        selected_climates = filtered_catalog.head(1).copy()

    with right:
        st.markdown("#### Selected station")
        st.dataframe(
            pd.DataFrame(
                {
                    "Field": ["Name", "Country", "Region", "Datasets", "Latitude", "Longitude", "Elevation", "Available climates"],
                    "Value": [
                        selected_group.get("name", ""),
                        selected_group.get("country", ""),
                        selected_group.get("region", ""),
                        selected_group.get("dataset", ""),
                        f"{float(selected_group['latitude']):.5f}",
                        f"{float(selected_group['longitude']):.5f}",
                        f"{float(selected_group.get('elevation_m', 0)):.0f} m" if pd.notna(selected_group.get("elevation_m", None)) else "",
                        int(selected_group.get("climate_count", len(selected_climates))),
                    ],
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

        st.markdown("#### Available climates at this station")
        climate_labels = [climate_option_label(row) for _, row in selected_climates.iterrows()]
        if not climate_labels:
            st.warning("No downloadable climates were found for this station.")
            selected = filtered_catalog.iloc[0]
        else:
            climate_index = st.selectbox(
                "Choose climate file",
                list(range(len(climate_labels))),
                format_func=lambda i: climate_labels[i],
                key=f"station_climate_choice_{selected_group['station_group_id']}",
            )
            selected = selected_climates.iloc[int(climate_index)]

        st.dataframe(
            pd.DataFrame(
                {
                    "Field": ["Station ID", "Dataset", "Source", "Region", "Catalog version", "Catalog snapshot", "Download URL"],
                    "Value": [
                        selected.get("station_id", ""),
                        selected.get("dataset", ""),
                        selected.get("source", ""),
                        selected.get("region", ""),
                        selected.get("catalog_version", ""),
                        selected.get("catalog_source_snapshot_date", ""),
                        selected.get("download_url", ""),
                    ],
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

        if st.button("Select and download this climate EPW", type="primary"):
            try:
                with st.spinner("Downloading and extracting EPW file..."):
                    result = download_station_epw(selected)
                source_text = station_provenance_text(
                    selected,
                    final_download_url=result.source_url,
                    archive_name=result.extracted_from,
                )
                set_active_climate_file(result.file_name, result.payload, source_text)
                st.rerun()
            except Exception as exc:
                st.error(f"Station download failed: {exc}")

        st.markdown("#### Manual station selection")
        station_group_options = _cached_station_group_options(map_cache_key, 10000, station_groups_all)
        if station_group_options:
            selected_label = st.selectbox("Search-result station groups", list(station_group_options.keys()))
            if st.button("Use station group from list"):
                st.session_state["selected_station_group_id"] = station_group_options[selected_label]
                st.rerun()
    st.info(
        "Source note: the public app reads a reviewed, versioned station catalog bundled with this release. "
        "Catalog crawling and refresh are maintenance operations outside user sessions. Selected EPW files are "
        "downloaded on demand from Climate.OneBuilding and are not bundled with this repository."
    )

def render_interpretation(text: str) -> None:
    """Render an automatic interpretation block below a chart."""
    st.markdown("#### Automatic interpretation")
    st.info(text)


def next_plot_key(prefix: str = "plot") -> str:
    """Return a unique key for Plotly elements within one Streamlit rerun."""
    st.session_state["_plotly_element_counter"] = int(st.session_state.get("_plotly_element_counter", 0)) + 1
    return f"{prefix}_{st.session_state['_plotly_element_counter']}"


def render_chart_export_controls(fig) -> None:
    """Render a compact local export control without reducing chart width."""
    from epw_climate_analyzer.exporting import (
        dataframe_to_csv_bytes,
        figure_export_stem,
        figure_to_csv_bytes,
        safe_export_stem,
    )

    # Keep the chart itself full-width. The tiny control occupies its own row
    # immediately above the figure instead of stealing horizontal chart space.
    _, export_col = st.columns([24, 1], gap="small")
    with export_col:
        with st.popover("⇩"):
            st.caption("Export this chart")
            stem = figure_export_stem(fig)
            chart_csv = figure_to_csv_bytes(fig)
            if chart_csv:
                st.download_button(
                    "Chart data · CSV",
                    data=chart_csv,
                    file_name=f"{stem}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.caption("No tabular trace data are available for this figure.")

            # A comparison figure can combine several independent EPW files, so
            # offering one arbitrary active source/filtered table there would be
            # misleading. Its trace-level CSV remains available above.
            if st.session_state.get(NAVIGATION_KEY) != "Compare Climates":
                filtered = st.session_state.get("_active_filtered_export_df")
                if hasattr(filtered, "to_csv"):
                    st.download_button(
                        "Filtered data · CSV",
                        data=dataframe_to_csv_bytes(filtered),
                        file_name=f"{stem}_filtered.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

                active = get_active_climate_file()
                if active is not None:
                    source_name = safe_export_stem(active.name, default="source_weather")
                    st.download_button(
                        "Source weather · EPW",
                        data=active.payload,
                        file_name=f"{source_name}.epw",
                        mime="application/octet-stream",
                        use_container_width=True,
                    )


def render_plot(fig, text: str) -> None:
    """Render a Plotly figure, local export control and interpretation."""
    render_chart_export_controls(fig)
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displaylogo": False, "scrollZoom": True},
        key=next_plot_key(),
    )
    render_interpretation(text)




def render_bioclimatic_report(df: pd.DataFrame) -> None:
    """Render a concise report for the Givoni-Milne bioclimatic overlay."""
    table = givoni_milne_zone_table(df)
    st.markdown("#### Bioclimatic-zone report")
    if table.empty:
        st.info("No valid dry-bulb temperature and humidity-ratio data are available for the bioclimatic-zone report.")
        return
    top = table.head(3)
    total_tagged = float(table["hours"].sum())
    valid_records = len(df.dropna(subset=["dry_bulb_temperature_c", "humidity_ratio_g_kg"]))
    total_hours = float(valid_records) * native_interval_hours(df)
    leader = top.iloc[0]

    def format_hours(value: float) -> str:
        numeric = float(value)
        if abs(numeric - round(numeric)) < 1e-9:
            return f"{int(round(numeric)):,}"
        return f"{numeric:,.2f}".rstrip("0").rstrip(".")

    st.info(
        f"The largest Givoni-Milne-style strategy region is **{leader['zone']}** "
        f"with {format_hours(float(leader['hours']))} hours ({float(leader['share_pct']):.1f}% of valid psychrometric duration). "
        f"The reported zones are overlapping design-potential regions, so their hour totals should be interpreted as strategy opportunities rather than mutually exclusive classes. "
        f"Across all displayed strategy regions, {format_hours(total_tagged)} zone-hours were detected over {format_hours(total_hours)} valid climate-data hours."
    )
    st.dataframe(table, hide_index=True, use_container_width=True)

def sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Create global month and hour filters in the sidebar."""
    st.sidebar.markdown("### Data filter")
    selected_month_names = st.sidebar.multiselect("Months", list(MONTHS.keys()), default=list(MONTHS.keys()))
    selected_hours = st.sidebar.slider("Hour range", min_value=0, max_value=23, value=(0, 23))
    months = [MONTHS[m] for m in selected_month_names]
    hours = list(range(selected_hours[0], selected_hours[1] + 1))
    filtered = filter_by_months_and_hours(df, months=months, hours=hours)
    # Export uses exactly the dataframe after the active global filters. Keeping
    # it in transient Streamlit session state avoids duplicating filter logic in
    # every chart renderer.
    st.session_state["_active_filtered_export_df"] = filtered
    return filtered


def metric_cards(df: pd.DataFrame) -> None:
    """Render top-level climate summary metrics."""
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Mean dry-bulb temperature", f"{df['dry_bulb_temperature_c'].mean():.1f} °C")
    col2.metric("Annual GHI", f"{df['global_horizontal_radiation_wh_m2'].sum() / 1000:.0f} kWh/m²")
    col3.metric("Mean humidity ratio", f"{df['humidity_ratio_g_kg'].mean():.1f} g/kg")
    col4.metric("Mean wind speed", f"{df['wind_speed_m_s'].mean():.1f} m/s")


def render_generic_variable_page(
    df: pd.DataFrame,
    variable_labels: list[str],
    default_variable: str,
    title_prefix: str,
    interpretation_factory: Callable[[pd.DataFrame, str, str, str], str] | None = None,
    temperature_thresholds: tuple[float, float] | None = None,
) -> None:
    """Render a generic variable explorer with chart-type and aggregation controls."""
    variable_label = st.selectbox("Variable", variable_labels, index=variable_labels.index(default_variable))
    column, unit = VARIABLES[variable_label]
    chart_types = [
        "Profile with min-mean-max ribbon",
        "Percentile band P05-P50-P95",
        "Heat map",
        "Duration curve",
        "Histogram",
        "Monthly boxplot",
        "Monthly violin plot",
    ]
    if column == "liquid_precipitation_depth_mm":
        # Accumulated precipitation belongs to the dedicated totals analysis.
        # A min/mean/max ribbon cannot use a period sum as its centre line while
        # its bounds remain per-record extrema, so that chart is deliberately
        # unavailable for this extensive variable.
        chart_types.remove("Profile with min-mean-max ribbon")
    chart_type = st.selectbox("Chart type", chart_types)
    if chart_type == "Heat map":
        heatmap_period = st.selectbox("Heat-map aggregation", ["Day", "Week", "Month"], index=0)
        if column == "dry_bulb_temperature_c":
            st.caption("Temperature heatmap colours use the current heating and cooling thresholds: blue = cold, green = neutral band, red = hot.")
        if heatmap_period == "Month":
            fig = month_hour_heatmap(
                df,
                column,
                f"{title_prefix}: {variable_label} month-hour heat map",
                unit,
                temperature_thresholds=temperature_thresholds if column == "dry_bulb_temperature_c" else None,
            )
        else:
            fig = heatmap_chart(
                df,
                column,
                heatmap_period.lower(),
                f"{title_prefix}: {variable_label} {heatmap_period.lower()}-hour heat map",
                unit,
                temperature_thresholds=temperature_thresholds if column == "dry_bulb_temperature_c" else None,
            )
    else:
        # Only charts that actually aggregate a time series expose the
        # aggregation selector. Distribution and monthly-distribution charts do
        # not need it.
        aggregation = None
        if chart_type in {"Profile with min-mean-max ribbon", "Percentile band P05-P50-P95"}:
            aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Hourly", "Seasonal"], index=0)
        # Radiation and illuminance are visualized as mean intensities in the generic explorer.
        # Monthly/annual energy sums are available in the dedicated solar component charts.
        if chart_type == "Profile with min-mean-max ribbon":
            fig = profile_ribbon_chart(df, column, aggregation or "Monthly", f"{title_prefix}: {variable_label}", unit)
        elif chart_type == "Percentile band P05-P50-P95":
            fig = percentile_band_chart(df, column, aggregation or "Monthly", f"{title_prefix}: {variable_label} percentiles", unit)
        elif chart_type == "Duration curve":
            ascending = st.checkbox("Ascending order", value=False)
            direction = "ascending" if ascending else "descending"
            fig = duration_chart(df, column, f"{title_prefix}: {variable_label} {direction} duration curve", unit, ascending=ascending)
        elif chart_type == "Histogram":
            bins = st.slider("Histogram bins", 10, 120, 40)
            fig = histogram_chart(df, column, f"{title_prefix}: {variable_label} histogram", unit, bins=bins)
        elif chart_type == "Monthly violin plot":
            fig = monthly_box_chart(df, column, f"{title_prefix}: {variable_label} monthly violin plot", unit, violin=True)
        else:
            fig = monthly_box_chart(df, column, f"{title_prefix}: {variable_label} monthly boxplot", unit, violin=False)

    if interpretation_factory:
        text = interpretation_factory(df, column, variable_label.lower(), unit)
    else:
        text = variable_interpretation(df, column, variable_label.lower(), unit)
    render_plot(fig, text)


def get_comparison_payloads() -> list[dict[str, object]]:
    """Return EPW payloads currently stored in the comparison basket."""
    payloads = st.session_state.get("comparison_climate_payloads", [])
    return payloads if isinstance(payloads, list) else []


def save_comparison_payloads(payloads: list[dict[str, object]]) -> None:
    """Store comparison-basket payloads in Streamlit session state."""
    st.session_state["comparison_climate_payloads"] = payloads


def add_to_comparison_basket(name: str, payload: bytes, source: str, display_name: str | None = None) -> None:
    """Add an EPW file payload to the multi-climate comparison basket."""
    payloads = get_comparison_payloads()
    display = (display_name or name).strip() or name
    duplicate = any(item.get("name") == name and item.get("source") == source for item in payloads)
    if duplicate:
        st.info(f"`{display}` is already in the comparison basket.")
        return
    payloads.append(
        {
            "climate_id": str(uuid4()),
            "name": name,
            "display_name": display,
            "payload": payload,
            "source": source,
        }
    )
    save_comparison_payloads(payloads)


def clear_comparison_basket() -> None:
    """Remove all climates from the comparison basket."""
    st.session_state.pop("comparison_climate_payloads", None)


def remove_from_comparison_basket(climate_id: str) -> None:
    """Remove one climate from the comparison basket by its internal ID."""
    payloads = [item for item in get_comparison_payloads() if item.get("climate_id") != climate_id]
    save_comparison_payloads(payloads)


def load_comparison_datasets(
    payloads: list[dict[str, object]],
    pressure_mode: str,
    custom_pressure_pa: float | None,
) -> list[ClimateDataset]:
    """Parse comparison EPW payloads and return normalized climate datasets."""
    datasets: list[ClimateDataset] = []
    for item in payloads:
        try:
            epw, data, issues = load_epw_from_bytes(
                str(item["name"]),
                bytes(item["payload"]),
                pressure_mode,
                custom_pressure_pa,
                include_psychrometrics=True,
                include_solar=True,
            )
            datasets.append(
                ClimateDataset(
                    climate_id=str(item["climate_id"]),
                    display_name=str(item.get("display_name") or item["name"]),
                    source=str(item.get("source", "")),
                    epw=epw,
                    data=data,
                    issues=issues,
                )
            )
        except Exception as exc:
            st.error(f"Failed to load comparison climate `{item.get('display_name', item.get('name', 'unknown'))}`: {exc}")
    return datasets


def render_comparison_basket_manager(active_file: ClimateFilePayload | None) -> None:
    """Render controls for adding, renaming and removing comparison climates."""
    # Compare Climates must not depend on the Find climate map dependency gate.
    # Keep all catalog/download helpers page-local so direct navigation to this
    # page is safe in a fresh Streamlit process.
    from epw_climate_analyzer.catalog_runtime import catalog_runtime_summary, station_provenance_text
    from epw_climate_analyzer.climate_sources import download_station_epw, filter_station_catalog

    st.subheader("Comparison basket")
    st.caption("Add two or more EPW climates. All comparison metrics are calculated from EPW hourly data only.")

    col_a, col_b, col_c = st.columns([1, 1, 1])
    with col_a:
        if active_file is not None and st.button("Add active climate to comparison", type="secondary"):
            add_to_comparison_basket(active_file.name, active_file.payload, active_file.source, active_file.name)
            st.rerun()
    with col_b:
        if st.button("Clear comparison basket", type="secondary"):
            clear_comparison_basket()
            st.rerun()
    with col_c:
        st.write(f"Selected climates: **{len(get_comparison_payloads())}**")

    uploaded = st.file_uploader(
        "Add local EPW files to comparison",
        type=["epw"],
        accept_multiple_files=True,
        key="comparison_local_epw_upload",
    )
    if uploaded:
        if st.button("Add uploaded EPW files", type="primary"):
            for file in uploaded:
                add_to_comparison_basket(file.name, file.getvalue(), "Local comparison upload | user-provided EPW | transient session", file.name)
            st.rerun()

    with st.expander("Add Climate.OneBuilding station to comparison", expanded=False):
        try:
            catalog = cached_station_catalog()
        except Exception as exc:
            st.error(f"The versioned station catalog failed integrity/provenance validation: {exc}")
            catalog = pd.DataFrame()
        if catalog.empty:
            st.warning("No reviewed Climate.OneBuilding station catalog is available in this release.")
        else:
            st.caption(catalog_runtime_summary(catalog))
            c1, c2, c3 = st.columns([2, 1, 1])
            search_text = c1.text_input("Station search", value="", key="comparison_station_search")
            countries = sorted([value for value in catalog["country"].dropna().unique().tolist() if str(value).strip()])
            datasets = sorted([value for value in catalog["dataset"].dropna().unique().tolist() if str(value).strip()])
            selected_countries = c2.multiselect("Station countries", countries, default=[], key="comparison_station_countries")
            selected_datasets = c3.multiselect("Station datasets", datasets, default=[], key="comparison_station_datasets")
            filtered_catalog = filter_station_catalog(
                catalog,
                search_text=search_text,
                countries=selected_countries if selected_countries else None,
                datasets=selected_datasets if selected_datasets else None,
            )
            st.caption(f"Matching stations: {len(filtered_catalog):,}")
            if not filtered_catalog.empty:
                station_options = station_options_from_catalog(filtered_catalog, limit=10000)
                label = st.selectbox("Station", list(station_options.keys()), key="comparison_station_select")
                selected = filtered_catalog[filtered_catalog["station_id"] == station_options[label]].iloc[0]
                if st.button("Download and add selected station", type="primary"):
                    try:
                        with st.spinner("Downloading and extracting station EPW..."):
                            result = download_station_epw(selected)
                        display = f"{selected.get('name', result.file_name)} — {selected.get('country', '')}"
                        source_text = station_provenance_text(
                            selected,
                            final_download_url=result.source_url,
                            archive_name=result.extracted_from,
                        )
                        add_to_comparison_basket(result.file_name, result.payload, source_text, display)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Station download failed: {exc}")

    payloads = get_comparison_payloads()
    if payloads:
        st.markdown("#### Basket contents")
        for item in payloads:
            cols = st.columns([3, 4, 1])
            current_name = str(item.get("display_name", item.get("name", "Climate")))
            new_name = cols[0].text_input("Display name", value=current_name, key=f"rename_{item['climate_id']}")
            item["display_name"] = new_name
            cols[1].caption(f"File: `{item.get('name')}`  \\nSource: {item.get('source', '')}")
            if cols[2].button("Remove", key=f"remove_{item['climate_id']}"):
                remove_from_comparison_basket(str(item["climate_id"]))
                st.rerun()
        save_comparison_payloads(payloads)


def filter_comparison_climates(climates: list[ClimateDataset], months: list[int], hours: list[int]) -> list[ClimateDataset]:
    """Apply comparison-specific month and hour filters to each climate dataset."""
    filtered: list[ClimateDataset] = []
    for climate in climates:
        data = filter_by_months_and_hours(climate.data, months=months, hours=hours)
        filtered.append(ClimateDataset(climate.climate_id, climate.display_name, climate.source, climate.epw, data, climate.issues))
    return filtered


def comparison_controls(climates: list[ClimateDataset]) -> tuple[str, str, list[int], list[int]]:
    """Render common comparison controls and return reference, mode, months and hours."""
    climate_names = [climate.display_name for climate in climates]
    c1, c2, c3 = st.columns([1, 1, 2])
    reference = c1.selectbox("Reference climate", climate_names, index=0)
    display_mode = c2.selectbox("Display mode", ["Auto", "Overlay", "Small multiples", "Difference to reference", "Ranked summary"], index=0)
    selected_month_names = c3.multiselect("Comparison months", list(MONTHS.keys()), default=list(MONTHS.keys()))
    hour_range = st.slider("Comparison hour range", min_value=0, max_value=23, value=(0, 23), key="comparison_hour_range")
    months = [MONTHS[m] for m in selected_month_names]
    hours = list(range(hour_range[0], hour_range[1] + 1))
    return reference, display_mode, months, hours


def get_reference_and_target(climates: list[ClimateDataset], reference_name: str, target_name: str | None = None) -> tuple[ClimateDataset, ClimateDataset]:
    """Return reference and target climate datasets for difference charts."""
    reference = next((climate for climate in climates if climate.display_name == reference_name), climates[0])
    candidates = [climate for climate in climates if climate.display_name != reference_name]
    if target_name:
        target = next((climate for climate in climates if climate.display_name == target_name), candidates[0] if candidates else reference)
    else:
        target = candidates[0] if candidates else reference
    return reference, target


def render_compare_summary(climates: list[ClimateDataset], reference_name: str) -> None:
    """Render summary tables and ranked metrics for climate comparison."""
    metrics = climate_summary_metrics(climates)
    st.subheader("Summary metrics")
    st.dataframe(metrics, hide_index=True, use_container_width=True)
    st.download_button(
        "Download comparison summary as CSV",
        data=metrics.to_csv(index=False).encode("utf-8"),
        file_name="climate_comparison_summary.csv",
        mime="text/csv",
    )
    numeric_columns = [col for col in metrics.columns if pd.api.types.is_numeric_dtype(metrics[col])]
    default_metric = "HDD18 [K·h]" if "HDD18 [K·h]" in numeric_columns else numeric_columns[0]
    metric = st.selectbox("Ranked metric", numeric_columns, index=numeric_columns.index(default_metric))
    fig = ranked_metric_chart(metrics, metric)
    render_plot(fig, comparison_interpretation(metrics, reference_name))
    fig2 = hdd_cdd_grouped_chart(metrics)
    render_plot(fig2, comparison_interpretation(metrics, reference_name))


def render_compare_temperature(climates: list[ClimateDataset], reference_name: str, display_mode: str) -> None:
    """Render temperature comparison charts."""
    st.subheader("Temperature comparison")
    chart = st.selectbox(
        "Temperature chart",
        [
            "Monthly temperature profile",
            "Temperature duration curve",
            "Monthly temperature boxplots",
            "Temperature heatmap",
            "Temperature difference heatmap",
            "HDD/CDD comparison",
            "Heating and cooling season timeline",
            "Extreme temperature ranking",
        ],
    )
    mode = choose_display_mode(chart, display_mode, len(climates))
    if chart == "Monthly temperature profile":
        statistic = st.selectbox("Monthly statistic", ["mean", "p05", "p95", "min", "max"], index=0)
        table = monthly_profile_table(climates, "dry_bulb_temperature_c", statistic=statistic)
        if mode == "Difference to reference":
            fig = monthly_difference_chart(table, reference_name, "Monthly dry-bulb temperature profile", "Temperature [°C]")
        elif mode == "Small multiples":
            fig = small_multiple_monthly_chart(table, "Monthly dry-bulb temperature profile", "Temperature [°C]")
        elif mode == "Ranked summary":
            metrics = climate_summary_metrics(climates)
            fig = ranked_metric_chart(metrics, "Annual mean T [°C]")
        else:
            fig = overlay_monthly_chart(table, "Monthly dry-bulb temperature profile", "Temperature [°C]")
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Temperature duration curve":
        ascending = st.checkbox("Ascending sort", value=False)
        fig = duration_comparison_chart(climates, "dry_bulb_temperature_c", "Dry-bulb temperature duration curves", "Temperature [°C]", ascending=ascending)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Monthly temperature boxplots":
        mode_box = st.radio("Boxplot mode", ["Compare climates for selected month", "Compare months for selected climate"], horizontal=True)
        selected_month = st.slider("Selected month", 1, 12, 7)
        selected_climate = st.selectbox("Selected climate", [c.display_name for c in climates])
        fig = monthly_box_compare_chart(climates, "dry_bulb_temperature_c", mode_box, selected_month, selected_climate, "Monthly temperature boxplot", "Temperature [°C]")
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Temperature heatmap":
        row_group = st.radio("Heatmap period axis", ["day", "week", "month"], horizontal=True)
        heat_threshold = st.slider("Heatmap heating threshold [°C]", -5.0, 25.0, 18.0, 0.5, key="compare_temp_heat_threshold")
        cool_threshold = st.slider("Heatmap cooling threshold [°C]", 15.0, 40.0, 26.0, 0.5, key="compare_temp_cool_threshold")
        fig = heatmap_small_multiples(climates, "dry_bulb_temperature_c", row_group, "Dry-bulb temperature heatmap comparison", "°C", temperature_thresholds=(heat_threshold, cool_threshold))
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Temperature difference heatmap":
        targets = [c.display_name for c in climates if c.display_name != reference_name]
        if not targets:
            st.warning("Difference mode requires at least one non-reference climate.")
            return
        target_name = st.selectbox("Target climate", targets)
        row_group = st.radio("Difference heatmap rows", ["day", "week", "month"], horizontal=True, key="temp_diff_rows")
        reference, target = get_reference_and_target(climates, reference_name, target_name)
        fig = difference_heatmap_chart(reference, target, "dry_bulb_temperature_c", row_group, f"Dry-bulb temperature difference: {target.display_name} minus {reference.display_name}", "Δ °C")
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "HDD/CDD comparison":
        fig = hdd_cdd_grouped_chart(climate_summary_metrics(climates))
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Heating and cooling season timeline":
        heat_base = st.slider("Heating base temperature [°C]", 5.0, 25.0, 18.0, 0.5)
        cool_base = st.slider("Cooling base temperature [°C]", 18.0, 35.0, 26.0, 0.5)
        fig = heating_cooling_season_timeline(climates, heat_base, cool_base)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    else:
        metric = st.selectbox("Extreme metric", ["Annual min T [°C]", "Annual max T [°C]", "T P01 [°C]", "T P99 [°C]", "Frost hours [h]", "Hot hours >30 °C [h]", "Tropical nights [d]"])
        fig = ranked_metric_chart(climate_summary_metrics(climates), metric)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))


def render_compare_humidity(climates: list[ClimateDataset], reference_name: str, display_mode: str, pressure_pa: float) -> None:
    """Render humidity and psychrometric comparison charts."""
    st.subheader("Humidity and psychrometric comparison")
    chart = st.selectbox(
        "Humidity chart",
        [
            "Humidity ratio monthly profile",
            "Humidity ratio duration curve",
            "Outdoor-air enthalpy duration curve",
            "Psychrometric density",
            "Moisture and latent-load ranking",
        ],
    )
    mode = choose_display_mode(chart, display_mode, len(climates))
    if chart == "Humidity ratio monthly profile":
        table = monthly_profile_table(climates, "humidity_ratio_g_kg", statistic="mean")
        if mode == "Difference to reference":
            fig = monthly_difference_chart(table, reference_name, "Monthly humidity ratio", "Humidity ratio [g/kg]")
        elif mode == "Small multiples":
            fig = small_multiple_monthly_chart(table, "Monthly humidity ratio", "Humidity ratio [g/kg]")
        else:
            fig = overlay_monthly_chart(table, "Monthly humidity ratio", "Humidity ratio [g/kg]")
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Humidity ratio duration curve":
        fig = duration_comparison_chart(climates, "humidity_ratio_g_kg", "Humidity ratio duration curves", "Humidity ratio [g/kg]", ascending=False)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Outdoor-air enthalpy duration curve":
        fig = duration_comparison_chart(climates, "moist_air_enthalpy_kj_kg", "Outdoor-air enthalpy duration curves", "Enthalpy [kJ/kg dry air]", ascending=False)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Psychrometric density":
        chart_type = st.radio("Psychrometric axes", ["T-d", "i-d"], horizontal=True)
        fig = psychrometric_comparison_chart(climates, chart_type=chart_type, mode=mode, pressure_pa=pressure_pa)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    else:
        metric = st.selectbox("Moisture metric", ["Mean humidity ratio [g/kg]", "Humidity ratio P95 [g/kg]", "Hours d >10 g/kg [h]", "Hours d <3 g/kg [h]", "Enthalpy P95 [kJ/kg]", "Maximum wet-bulb [°C]", "Dehumidification hours [h]", "Humidification hours [h]"])
        fig = ranked_metric_chart(climate_summary_metrics(climates), metric)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))


def render_compare_solar(climates: list[ClimateDataset], reference_name: str, display_mode: str) -> None:
    """Render solar and radiation comparison charts."""
    st.subheader("Solar and radiation comparison")
    chart = st.selectbox(
        "Solar chart",
        [
            "Monthly GHI/DNI/DHI comparison",
            "Radiation duration curve",
            "Sun path",
            "Façade radiation by orientation",
            "Tilt sensitivity",
            "Orientation-tilt heatmap",
            "Solar and shading ranking",
        ],
    )
    mode = choose_display_mode(chart, display_mode, len(climates))
    if chart == "Monthly GHI/DNI/DHI comparison":
        radiation_label = st.selectbox("Radiation variable", ["GHI", "DNI", "DHI"], index=0)
        column = {"GHI": "global_horizontal_radiation_wh_m2", "DNI": "direct_normal_radiation_wh_m2", "DHI": "diffuse_horizontal_radiation_wh_m2"}[radiation_label]
        table = solar_monthly_comparison(climates, column)
        if mode == "Difference to reference":
            fig = monthly_difference_chart(table, reference_name, f"Monthly {radiation_label} irradiation", "Irradiation [kWh/m²]")
        elif mode == "Small multiples":
            fig = small_multiple_monthly_chart(table, f"Monthly {radiation_label} irradiation", "Irradiation [kWh/m²]")
        else:
            fig = overlay_monthly_chart(table, f"Monthly {radiation_label} irradiation", "Irradiation [kWh/m²]")
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Radiation duration curve":
        variable = st.selectbox("Radiation variable", ["Global horizontal radiation", "Direct normal radiation", "Diffuse horizontal radiation"])
        column = VARIABLES[variable][0]
        fig = duration_comparison_chart(climates, column, f"{variable} duration curves", "Radiation [Wh/m²]", ascending=False)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Sun path":
        date_options = {"Winter solstice": "12-21", "Equinox": "03-21", "Summer solstice": "06-21"}
        selected = st.multiselect("Selected sun-path dates", list(date_options.keys()), default=list(date_options.keys()))
        dates = [date_options[item] for item in selected]
        fig = sun_path_comparison_chart(climates, mode=mode, selected_dates=dates)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Façade radiation by orientation":
        tilt = st.slider("Surface tilt [deg]", 0.0, 90.0, 90.0, 5.0)
        fig = facade_radiation_comparison_chart(climates, tilt)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Tilt sensitivity":
        azimuth = st.slider("Surface azimuth [deg]", 0.0, 359.0, 180.0, 5.0)
        fig = tilt_radiation_comparison_chart(climates, azimuth)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Orientation-tilt heatmap":
        fig = orientation_tilt_small_multiples(climates)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    else:
        metric = st.selectbox("Solar metric", ["Annual GHI [kWh/m²]", "Annual DNI [kWh/m²]", "Annual DHI [kWh/m²]", "Diffuse share [%]", "Shading indicator hours [h]"])
        fig = ranked_metric_chart(climate_summary_metrics(climates), metric)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))


def render_compare_wind(climates: list[ClimateDataset], reference_name: str, display_mode: str) -> None:
    """Render wind comparison charts."""
    st.subheader("Wind comparison")
    chart = st.selectbox("Wind chart", ["Wind speed monthly profile", "Wind speed duration curve", "Wind rose", "Wind ranking"])
    mode = choose_display_mode(chart, display_mode, len(climates))
    if chart == "Wind speed monthly profile":
        table = monthly_profile_table(climates, "wind_speed_m_s", statistic="mean")
        if mode == "Difference to reference":
            fig = monthly_difference_chart(table, reference_name, "Monthly mean wind speed", "Wind speed [m/s]")
        elif mode == "Small multiples":
            fig = small_multiple_monthly_chart(table, "Monthly mean wind speed", "Wind speed [m/s]")
        else:
            fig = overlay_monthly_chart(table, "Monthly mean wind speed", "Wind speed [m/s]")
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Wind speed duration curve":
        fig = duration_comparison_chart(climates, "wind_speed_m_s", "Wind speed duration curves", "Wind speed [m/s]", ascending=False)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Wind rose":
        fig = wind_rose_small_multiples(climates)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    else:
        metric = st.selectbox("Wind metric", ["Mean wind speed [m/s]", "Wind speed P95 [m/s]", "Calm hours <1 m/s [h]", "Strong wind hours >8 m/s [h]"])
        fig = ranked_metric_chart(climate_summary_metrics(climates), metric)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))


def render_compare_natural_ventilation(climates: list[ClimateDataset], reference_name: str, display_mode: str) -> None:
    """Render natural-ventilation and night-flushing comparison charts."""
    st.subheader("Natural ventilation comparison")
    c1, c2, c3 = st.columns(3)
    t_min = c1.slider("NV minimum outdoor temperature [°C]", 0.0, 30.0, 16.0, 0.5)
    t_max = c2.slider("NV maximum outdoor temperature [°C]", 10.0, 40.0, 26.0, 0.5)
    d_max = c3.slider("NV maximum humidity ratio [g/kg]", 3.0, 20.0, 9.0, 0.5)
    chart = st.selectbox("Natural ventilation chart", ["Monthly NV hours", "NV heatmap", "NV difference heatmap", "Night flushing monthly hours", "NV and comfort ranking"])
    if chart == "Monthly NV hours":
        table = natural_ventilation_monthly_table(climates, t_min, t_max, d_max)
        if display_mode == "Difference to reference":
            fig = monthly_difference_chart(table, reference_name, "Monthly natural-ventilation suitable hours", "Hours")
        else:
            fig = overlay_monthly_chart(table, "Monthly natural-ventilation suitable hours", "Hours")
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "NV heatmap":
        nv_climates = []
        for climate in climates:
            data = climate.data.copy()
            data["nv_eligible"] = natural_ventilation_condition(data, t_min_c=t_min, t_max_c=t_max, d_max_g_kg=d_max).astype(int)
            nv_climates.append(ClimateDataset(climate.climate_id, climate.display_name, climate.source, climate.epw, data, climate.issues))
        fig = heatmap_small_multiples(nv_climates, "nv_eligible", "day", "Natural-ventilation eligibility heatmap comparison", "0/1")
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "NV difference heatmap":
        targets = [c.display_name for c in climates if c.display_name != reference_name]
        if not targets:
            st.warning("Difference mode requires at least one non-reference climate.")
            return
        target_name = st.selectbox("Target climate", targets, key="nv_diff_target")
        reference, target = get_reference_and_target(climates, reference_name, target_name)
        fig = natural_ventilation_difference_heatmap(reference, target, t_min, t_max, d_max)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Night flushing monthly hours":
        table = pd.DataFrame(index=range(1, 13))
        for climate in climates:
            mask = night_flushing_condition(climate.data)
            table[climate.display_name] = pd.Series(mask.astype(int).values, index=climate.data.index).groupby(climate.data["month_index"]).sum()
        table.index.name = "Month"
        fig = overlay_monthly_chart(table.fillna(0), "Monthly night-flushing potential", "Hours")
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    else:
        metric = st.selectbox("Ventilation/comfort metric", ["Natural ventilation hours [h]", "Night flushing hours [h]", "Comfort hours [h]", "Economizer hours [h]"])
        fig = ranked_metric_chart(climate_summary_metrics(climates), metric)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))


def render_compare_passive_hvac(climates: list[ClimateDataset], reference_name: str, display_mode: str) -> None:
    """Render passive-design and HVAC indicator comparison charts."""
    st.subheader("Passive and HVAC comparison")
    chart = st.selectbox("Passive/HVAC chart", ["Passive strategy stacked bars", "Passive strategy calendar", "HVAC indicator ranking"])
    if chart == "Passive strategy stacked bars":
        fig = passive_strategy_stacked_comparison(climates)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Passive strategy calendar":
        fig = passive_strategy_calendar_small_multiples(climates)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    else:
        metric = st.selectbox("HVAC indicator", ["HDD18 [K·h]", "CDD26 [K·h]", "Economizer hours [h]", "Dehumidification hours [h]", "Humidification hours [h]", "Shading indicator hours [h]"])
        fig = ranked_metric_chart(climate_summary_metrics(climates), metric)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))


def render_compare_difference(climates: list[ClimateDataset], reference_name: str) -> None:
    """Render explicit difference-to-reference comparison charts."""
    st.subheader("Difference to reference")
    targets = [c.display_name for c in climates if c.display_name != reference_name]
    if not targets:
        st.warning("Difference charts require at least one non-reference climate.")
        return
    target_name = st.selectbox("Target climate", targets, key="difference_target")
    variable_label = st.selectbox(
        "Difference variable",
        [
            "Dry-bulb temperature",
            "Humidity ratio",
            "Moist-air enthalpy",
            "Global horizontal radiation",
            "Wind speed",
            "Relative humidity",
        ],
    )
    column, unit = VARIABLES[variable_label]
    chart_type = st.radio("Difference chart type", ["Monthly difference", "Day/week/month × hour heatmap"], horizontal=True)
    reference, target = get_reference_and_target(climates, reference_name, target_name)
    if chart_type == "Monthly difference":
        table = monthly_profile_table([reference, target], column, extensive=column.endswith("_wh_m2"))
        fig = monthly_difference_chart(table, reference.display_name, f"Monthly difference: {variable_label}", unit)
    else:
        row_group = st.radio("Heatmap rows", ["day", "week", "month"], horizontal=True, key="generic_diff_rows")
        fig = difference_heatmap_chart(reference, target, column, row_group, f"{variable_label} difference: {target.display_name} minus {reference.display_name}", f"Δ {unit}")
    render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))


def render_compare_data_quality(climates: list[ClimateDataset], reference_name: str) -> None:
    """Render data-quality comparison matrices."""
    st.subheader("Data-quality comparison")
    matrix = data_quality_matrix(climates)
    st.dataframe(matrix, hide_index=True, use_container_width=True)
    st.download_button(
        "Download data-quality comparison as CSV",
        data=matrix.to_csv(index=False).encode("utf-8"),
        file_name="climate_comparison_data_quality.csv",
        mime="text/csv",
    )
    metric = st.selectbox("Data-quality metric", [col for col in matrix.columns if col != "Climate"])
    fig = px.bar(matrix.sort_values(metric, ascending=True), x=metric, y="Climate", orientation="h", title=f"Data-quality comparison: {metric}")
    fig.update_layout(template="plotly_white", xaxis_title=metric, yaxis_title="Climate")
    render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))


def render_compare_climates(active_file: ClimateFilePayload | None, pressure_mode: str, custom_pressure_pa: float | None, active_pressure: float) -> None:
    """Render the complete multi-climate comparison UI."""
    st.header("Compare climates")
    st.write(
        "Compare several EPW climates with overlay, small-multiple, ranked and difference-to-reference modes. "
        "All calculations use only EPW hourly data and EPW-derived indicators."
    )
    render_comparison_basket_manager(active_file)

    payloads = get_comparison_payloads()
    if len(payloads) < 2:
        st.warning("Add at least two EPW climates to enable comparison charts.")
        return

    climates = load_comparison_datasets(payloads, pressure_mode, custom_pressure_pa)
    if len(climates) < 2:
        st.warning("At least two valid climates are required after loading.")
        return

    reference_name, display_mode, months, hours = comparison_controls(climates)
    climates = filter_comparison_climates(climates, months=months, hours=hours)
    if any(climate.data.empty for climate in climates):
        st.warning("The current comparison filters remove all data for at least one climate. Adjust the month or hour filter.")
        return

    tabs = st.tabs(
        [
            "Summary",
            "Temperature",
            "Humidity / Psychrometrics",
            "Solar",
            "Wind",
            "Natural ventilation",
            "Passive / HVAC",
            "Difference to reference",
            "Data quality",
        ]
    )
    with tabs[0]:
        render_compare_summary(climates, reference_name)
    with tabs[1]:
        render_compare_temperature(climates, reference_name, display_mode)
    with tabs[2]:
        render_compare_humidity(climates, reference_name, display_mode, pressure_pa=active_pressure)
    with tabs[3]:
        render_compare_solar(climates, reference_name, display_mode)
    with tabs[4]:
        render_compare_wind(climates, reference_name, display_mode)
    with tabs[5]:
        render_compare_natural_ventilation(climates, reference_name, display_mode)
    with tabs[6]:
        render_compare_passive_hvac(climates, reference_name, display_mode)
    with tabs[7]:
        render_compare_difference(climates, reference_name)
    with tabs[8]:
        render_compare_data_quality(climates, reference_name)

def render_calculated_epw_statistics(df: pd.DataFrame) -> None:
    """Render calculated EPW-derived statistics inside the Overview page.

    The section uses only the active EPW hourly table and columns derived from
    that EPW file. It does not parse or depend on companion weather-package
    files such as DDY, STAT, RAIN, CLM, WEA or PVSyst.
    """
    st.subheader("Calculated EPW statistics")
    st.caption(
        "All metrics below are calculated from the active EPW hourly data and the "
        "derived psychrometric, solar-position and decision-indicator columns."
    )

    tables = calculated_statistics_tables(df)
    tab_names = [
        "Dataset",
        "Temperature",
        "Humidity and psychrometrics",
        "Solar and daylight",
        "Wind",
        "Sky, precipitation and snow",
        "Decision indicators",
        "Monthly summary",
        "Seasonal summary",
        "Extreme days",
    ]
    tabs = st.tabs(tab_names)

    for tab, name in zip(tabs[:7], tab_names[:7], strict=False):
        with tab:
            table = tables[name]
            st.dataframe(table, hide_index=True, use_container_width=True)
            st.download_button(
                f"Download {name.lower()} statistics as CSV",
                data=table.to_csv(index=False).encode("utf-8"),
                file_name=f"epw_{name.lower().replace(' ', '_').replace(',', '')}_statistics.csv",
                mime="text/csv",
            )

    with tabs[7]:
        monthly = monthly_climate_summary(df)
        st.dataframe(monthly, hide_index=True, use_container_width=True)
        numeric_columns = [col for col in monthly.columns if col != "Month" and pd.api.types.is_numeric_dtype(monthly[col])]
        if numeric_columns:
            metric = st.selectbox("Monthly chart metric", numeric_columns, index=numeric_columns.index("Mean dry-bulb [°C]") if "Mean dry-bulb [°C]" in numeric_columns else 0)
            fig = px.bar(monthly, x="Month", y=metric, title=f"Monthly summary: {metric}")
            fig.update_layout(template="plotly_white", xaxis_title="Month", yaxis_title=metric)
            st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True}, key=next_plot_key())
        st.download_button(
            "Download monthly summary as CSV",
            data=monthly.to_csv(index=False).encode("utf-8"),
            file_name="epw_monthly_summary.csv",
            mime="text/csv",
        )

    with tabs[8]:
        seasonal = seasonal_climate_summary(df)
        st.dataframe(seasonal, hide_index=True, use_container_width=True)
        numeric_columns = [col for col in seasonal.columns if col != "Season" and pd.api.types.is_numeric_dtype(seasonal[col])]
        if numeric_columns:
            metric = st.selectbox("Seasonal chart metric", numeric_columns, index=numeric_columns.index("Mean dry-bulb [°C]") if "Mean dry-bulb [°C]" in numeric_columns else 0)
            fig = px.bar(seasonal, x="Season", y=metric, title=f"Seasonal summary: {metric}")
            fig.update_layout(template="plotly_white", xaxis_title="Season", yaxis_title=metric)
            st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True}, key=next_plot_key())
        st.download_button(
            "Download seasonal summary as CSV",
            data=seasonal.to_csv(index=False).encode("utf-8"),
            file_name="epw_seasonal_summary.csv",
            mime="text/csv",
        )

    with tabs[9]:
        extremes = extreme_day_summary(df)
        mode = st.selectbox("Extreme-day ranking", list(extremes.keys()))
        table = extremes[mode].reset_index().rename(columns={"index": "Date"})
        st.dataframe(table, hide_index=True, use_container_width=True)
        st.download_button(
            "Download selected extreme-day table as CSV",
            data=table.to_csv(index=False).encode("utf-8"),
            file_name=f"epw_{mode.lower().replace('-', '_').replace(' ', '_')}.csv",
            mime="text/csv",
        )

    render_interpretation(climate_statistics_interpretation(df))


def render_overview(epw, df: pd.DataFrame, full_df: pd.DataFrame, issues: list[object]) -> None:
    """Render the landing dashboard."""
    st.header("EPW Climate Analyzer")
    st.write("Interactive climate-analysis dashboard for architecture and HVAC decision support.")
    statistics_scope = st.radio("Statistics scope", ["Full EPW file", "Current sidebar filter"], horizontal=True)
    stats_df = full_df if statistics_scope == "Full EPW file" else df
    metric_cards(stats_df)

    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("Location")
        st.dataframe(pd.DataFrame(location_summary(epw.location).items(), columns=["Field", "Value"]), hide_index=True)
    with col2:
        st.subheader("Supported chart families")
        st.markdown(
            """
            - Time-series profiles with hourly, daily, weekly, monthly and seasonal aggregation
            - Min/mean/max ribbons and percentile bands
            - Day-hour, week-hour and month-hour heatmaps
            - Duration curves, histograms, boxplots and violin plots
            - Psychrometric T-d and i-d charts
            - Wind roses, sun-path plots and façade-radiation charts
            - Precipitation totals, precipitation-record occurrence, snow depth and snow-cover occurrence
            - Natural-ventilation, night-flushing, shading, economizer and latent-load indicators
            - EPW data-quality diagnostics
            """
        )

    fig = profile_ribbon_chart(stats_df, "dry_bulb_temperature_c", "Monthly", "Monthly outdoor temperature profile", "°C")
    render_plot(fig, temperature_interpretation(stats_df, heat_threshold=18.0, cool_threshold=26.0))

    render_calculated_epw_statistics(stats_df)

    issue_count = len(issues)
    error_count = sum(1 for issue in issues if getattr(issue, "severity", "") == "error")
    st.info(data_quality_interpretation(issue_count, error_count))


def render_temperature(df: pd.DataFrame, *, interval_count_metrics: bool = True) -> None:
    """Render temperature-analysis charts."""
    st.header("Temperature and extremes")
    chart_options = ["Temperature variable explorer", "Threshold hours", "Degree days", "Extreme days"]
    if not interval_count_metrics:
        chart_options.remove("Threshold hours")
    chart_group = st.selectbox("Analysis type", chart_options)

    if chart_group == "Degree days":
        st.caption(
            "HGT/KGT use two independent temperatures each: the limit selects the heating/cooling period, "
            "while the temperature difference is measured to the corresponding indoor-air reference."
        )
        st.markdown("**Heating degree metric (HGT)**")
        heat_col1, heat_col2 = st.columns(2)
        heating_indoor = heat_col1.slider(
            "Heating indoor air temperature [°C]",
            10.0,
            30.0,
            20.0,
            0.5,
            key="degree_heating_indoor_c",
            help="Indoor-air reference used for the HGT temperature difference.",
        )
        heating_limit = heat_col2.slider(
            "Heating limit [°C]",
            -5.0,
            25.0,
            12.0,
            0.5,
            key="degree_heating_limit_c",
            help="Only intervals/days with mean outdoor temperature below this limit contribute to HGT.",
        )
        if heating_limit > heating_indoor:
            st.error("Heating limit must not exceed heating indoor air temperature.")
            return

        st.markdown("**Cooling degree metric (KGT)**")
        cool_col1, cool_col2 = st.columns(2)
        cooling_indoor = cool_col1.slider(
            "Cooling indoor air temperature [°C]",
            10.0,
            30.0,
            20.0,
            0.5,
            key="degree_cooling_indoor_c",
            help="Indoor-air reference used for the KGT temperature difference.",
        )
        cooling_limit = cool_col2.slider(
            "Cooling limit [°C]",
            10.0,
            35.0,
            18.3,
            0.1,
            key="degree_cooling_limit_c",
            help="Only intervals/days with mean outdoor temperature above this limit contribute to KGT.",
        )
        st.caption(
            f"Current definitions: HGT {heating_indoor:g}/{heating_limit:g} and "
            f"KGT {cooling_indoor:g}/{cooling_limit:g}."
        )

        method_col, aggregation_col = st.columns(2)
        metric = method_col.radio(
            "Degree metric",
            ["Degree-hours", "Degree-days"],
            horizontal=True,
            help=(
                "Degree-hours use every source interval. Degree-days first calculate the daily mean outdoor temperature; "
                "they are not obtained by simply dividing degree-hours by 24."
            ),
        )
        aggregation = aggregation_col.selectbox(
            "Aggregation",
            ["Daily", "Weekly", "Monthly", "Seasonal", "Annual"],
            index=2,
            key="degree_metric_aggregation",
        )
        table = degree_metric_table(
            df,
            heating_indoor_c=heating_indoor,
            heating_limit_c=heating_limit,
            cooling_indoor_c=cooling_indoor,
            cooling_limit_c=cooling_limit,
            metric=metric,
            aggregation=aggregation,
        )
        unit = str(table.attrs.get("unit", "K·h" if metric == "Degree-hours" else "K·d"))

        plot_data = table.reset_index()
        plot_data = plot_data.rename(columns={plot_data.columns[0]: "Period"})
        if aggregation == "Monthly":
            plot_data["Period"] = pd.to_datetime(plot_data["Period"]).dt.strftime("%b")
        elif aggregation == "Weekly":
            timestamps = pd.to_datetime(plot_data["Period"])
            plot_data["Period"] = [f"W{int(ts.isocalendar().week):02d}" for ts in timestamps]
        elif aggregation == "Daily":
            plot_data["Period"] = pd.to_datetime(plot_data["Period"]).dt.strftime("%d %b")
        elif aggregation == "Annual":
            plot_data["Period"] = pd.to_datetime(plot_data["Period"]).dt.strftime("%Y")

        series_names = [str(column) for column in table.columns]
        long = plot_data.melt(id_vars="Period", var_name="Series", value_name="Value")
        fig = px.bar(
            long,
            x="Period",
            y="Value",
            color="Series",
            barmode="group",
            title=(
                f"{aggregation} heating and cooling {metric.lower()} "
                f"(HGT {heating_indoor:g}/{heating_limit:g}; KGT {cooling_indoor:g}/{cooling_limit:g})"
            ),
            color_discrete_map={name: metric_color(name) for name in series_names},
        )
        fig.update_layout(
            template="plotly_white",
            xaxis_title="Period",
            yaxis_title=unit,
            legend_title_text="Indicator",
            margin=dict(l=40, r=20, t=70, b=45),
        )
        fig.update_yaxes(rangemode="tozero")
        st.caption(
            "Degree-hours integrate the temperature difference at each source interval. "
            "Degree-days use daily mean outdoor temperature before applying the heating/cooling base. "
            "Heating and cooling bars are grouped because they are separate indicators, not additive components of one total."
        )
        render_plot(
            fig,
            degree_metric_interpretation(
                table,
                heating_indoor_c=heating_indoor,
                heating_limit_c=heating_limit,
                cooling_indoor_c=cooling_indoor,
                cooling_limit_c=cooling_limit,
                metric=metric,
            ),
        )
        return

    if chart_group in {"Temperature variable explorer", "Threshold hours"}:
        threshold_col1, threshold_col2 = st.columns(2)
        heat_threshold = threshold_col1.slider("Heating threshold [°C]", -5.0, 25.0, 18.0, 0.5)
        cool_threshold = threshold_col2.slider("Cooling threshold [°C]", 15.0, 40.0, 26.0, 0.5)
        if heat_threshold > cool_threshold:
            st.error("Heating threshold must not exceed cooling threshold.")
            return
    else:
        heat_threshold = 18.0
        cool_threshold = 26.0

    if chart_group == "Temperature variable explorer":
        render_generic_variable_page(
            df,
            ["Dry-bulb temperature", "Dew-point temperature", "Wet-bulb temperature"],
            "Dry-bulb temperature",
            "Temperature",
            lambda data, column, label, unit: variable_interpretation(data, column, label, unit, high_threshold=cool_threshold, low_threshold=heat_threshold),
            temperature_thresholds=(heat_threshold, cool_threshold),
        )
    elif chart_group == "Threshold hours":
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        mode = st.radio("Condition", ["Below heating threshold", "Above cooling threshold", "Frost hours", "Tropical nights proxy"])
        if mode == "Below heating threshold":
            condition = df["dry_bulb_temperature_c"] < heat_threshold
        elif mode == "Above cooling threshold":
            condition = df["dry_bulb_temperature_c"] > cool_threshold
        elif mode == "Frost hours":
            condition = df["dry_bulb_temperature_c"] < 0.0
        else:
            condition = (df["hour_of_day"].isin(list(range(20, 24)) + list(range(0, 7)))) & (df["dry_bulb_temperature_c"] > 20.0)
        counts = threshold_count_by_period(df, condition, aggregation, label="hours")
        fig = threshold_bar_chart(counts, f"Temperature threshold hours: {mode}")
        render_plot(fig, temperature_interpretation(df, heat_threshold, cool_threshold))
    else:
        st.subheader("Extreme daily conditions")
        daily = df["dry_bulb_temperature_c"].resample("D").agg(mean="mean", min="min", max="max")
        hottest = daily.sort_values("max", ascending=False).head(10)
        coldest = daily.sort_values("min", ascending=True).head(10)
        col1, col2 = st.columns(2)
        col1.dataframe(hottest, use_container_width=True)
        col2.dataframe(coldest, use_container_width=True)
        fig = profile_ribbon_chart(df, "dry_bulb_temperature_c", "Daily", "Daily temperature extremes", "°C")
        render_plot(fig, temperature_interpretation(df, heat_threshold, cool_threshold))


def render_humidity(df: pd.DataFrame, pressure_pa: float, *, interval_count_metrics: bool = True) -> None:
    """Render humidity and psychrometric charts."""
    st.header("Humidity and psychrometrics")
    chart_options = ["Humidity variable explorer", "Psychrometric chart", "Moisture thresholds", "Psychrometric scatter relationships"]
    if not interval_count_metrics:
        chart_options.remove("Moisture thresholds")
    chart_group = st.selectbox("Analysis type", chart_options)
    if chart_group == "Humidity variable explorer":
        render_generic_variable_page(
            df,
            ["Relative humidity", "Humidity ratio", "Dew-point temperature", "Wet-bulb temperature", "Moist-air enthalpy", "Specific volume", "Moist-air density"],
            "Humidity ratio",
            "Humidity",
            None,
        )
    elif chart_group == "Psychrometric chart":
        chart_type = st.radio("Psychrometric axes", ["T-d", "i-d"], horizontal=True)
        source_interval_mode = "Hourly values" if abs(native_interval_hours(df) - 1.0) < 1e-9 else "Source interval values"
        data_mode = st.radio("Loaded climate data mode", [source_interval_mode, "Distributive grid"], horizontal=True)
        st.caption("Distributive grid uses 1 °C × 5 %RH cells drawn on the real psychrometric chart geometry.")

        col_a, col_b, col_c = st.columns(3)
        t_min = float(df["dry_bulb_temperature_c"].min())
        t_max = float(df["dry_bulb_temperature_c"].max())
        d_max_default = max(20.0, float(df["humidity_ratio_g_kg"].quantile(0.995)) * 1.1)
        h_min = float(df["moist_air_enthalpy_kj_kg"].quantile(0.005))
        h_max = float(df["moist_air_enthalpy_kj_kg"].quantile(0.995))
        t_limits = col_a.slider(
            "Dry-bulb temperature range [°C]",
            -40.0,
            60.0,
            (float(max(-40, int(t_min // 5 * 5))), float(min(60, int(t_max // 5 * 5 + 10)))),
            1.0,
        )
        d_limits = col_b.slider("Moisture content range [g/kg]", 0.0, 40.0, (0.0, float(min(40.0, d_max_default))), 0.5)
        h_limits = col_c.slider(
            "Enthalpy range [kJ/kg dry air]",
            -30.0,
            140.0,
            (float(max(-30, int(h_min // 10 * 10))), float(min(140, int(h_max // 10 * 10 + 20)))),
            1.0,
        )

        with st.expander("Chart metrics and overlays", expanded=True):
            metric_layers = st.multiselect(
                "Metric lines",
                PSYCHROMETRIC_METRIC_LINES,
                default=["Dry-bulb temperature", "Humidity ratio", "Relative humidity"],
                help="Turn psychrometric metric lines on or off. Lines are intentionally grey and low-emphasis.",
            )
            show_givoni = st.checkbox("Show Givoni-Milne bioclimatic overlay", value=True)
            selected_zones: list[str] | None = None
            show_heat_index = st.checkbox("Show heat-index overlay", value=False)

        with st.expander("Loaded data mapping", expanded=True):
            months = st.multiselect("Displayed months", list(MONTHS.keys()), default=list(MONTHS.keys()), key="psych_month_filter")
            selected_months = [MONTHS[m] for m in months]
            metric_options = list(PSYCHROMETRIC_COLOR_METRICS.keys())
            default_metric = "Frequency" if data_mode == "Distributive grid" else "Month"
            color_mode = st.selectbox("Colour mapped metric", metric_options, index=metric_options.index(default_metric))
            color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]
            if data_mode != "Distributive grid" and color_mode == "Frequency":
                st.caption("Frequency is only meaningful for the distributive grid. Source interval values will be shown by month.")
                color_mode = "Month"
                color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]

        fig = psychrometric_chart(
            df,
            chart_type=chart_type,
            pressure_pa=pressure_pa,
            show_rh_curves="Relative humidity" in metric_layers,
            show_comfort_zone=show_givoni,
            data_mode=data_mode,
            t_range=t_limits,
            d_range=d_limits,
            h_range=h_limits,
            metric_layers=metric_layers,
            shown_bioclimatic_zones=selected_zones,
            show_heat_index_overlay=show_heat_index,
            selected_months=selected_months,
            color_metric_column=color_metric_column,
            color_metric_label=color_metric_label,
            color_mode=color_mode,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True}, key=next_plot_key("psychrometric"))
        if show_givoni:
            render_bioclimatic_report(df[df["month_index"].isin(selected_months)])
    elif chart_group == "Moisture thresholds":
        d_low = st.slider("Dry-air threshold [g/kg]", 0.0, 8.0, 3.0, 0.25)
        d_high = st.slider("Humid-air threshold [g/kg]", 5.0, 25.0, 10.0, 0.25)
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        mode = st.radio("Condition", ["Below dry-air threshold", "Above humid-air threshold", "Relative humidity above 80%"])
        if mode == "Below dry-air threshold":
            condition = df["humidity_ratio_g_kg"] < d_low
        elif mode == "Above humid-air threshold":
            condition = df["humidity_ratio_g_kg"] > d_high
        else:
            condition = df["relative_humidity_pct"] > 80.0
        counts = threshold_count_by_period(df, condition, aggregation, label="hours")
        fig = threshold_bar_chart(counts, f"Moisture threshold hours: {mode}")
        render_plot(fig, psychrometric_interpretation(df))
    else:
        x_label = st.selectbox("X variable", ["Dry-bulb temperature", "Dew-point temperature", "Humidity ratio", "Moist-air enthalpy"])
        y_label = st.selectbox("Y variable", ["Humidity ratio", "Relative humidity", "Moist-air enthalpy", "Wet-bulb temperature"])
        x, x_unit = VARIABLES[x_label]
        y, y_unit = VARIABLES[y_label]
        fig = scatter_chart(df, x, y, "month_index", f"{x_label} vs {y_label}", f"{x_label} [{x_unit}]", f"{y_label} [{y_unit}]")
        render_plot(fig, psychrometric_interpretation(df))


def render_solar(df: pd.DataFrame) -> None:
    """Render solar, radiation and façade-decision charts."""
    st.header("Solar, radiation and façade analysis")
    chart_group = st.selectbox(
        "Analysis type",
        [
            "Radiation variable explorer",
            "Monthly radiation components",
            "Sun path with radiation",
            "Sun-path diagram",
            "Radiation by façade orientation",
            "Orientation-tilt heatmap",
            "Monthly façade radiation",
            "Cooling-risk solar hours",
            "Solar scatter relationships",
        ],
    )

    if chart_group == "Radiation variable explorer":
        render_generic_variable_page(
            df,
            ["Global horizontal radiation", "Direct normal radiation", "Diffuse horizontal radiation"],
            "Global horizontal radiation",
            "Solar radiation",
            None,
        )
    elif chart_group == "Monthly radiation components":
        monthly = pd.DataFrame(index=range(1, 13))
        for label in ["Global horizontal radiation", "Direct normal radiation", "Diffuse horizontal radiation"]:
            col, _ = VARIABLES[label]
            monthly[label] = df[col].clip(lower=0).groupby(df["month_index"]).sum() / 1000.0
        fig = stacked_monthly_bar(monthly, "Monthly solar radiation components", "kWh/m²")
        render_plot(fig, solar_interpretation(df))
    elif chart_group == "Sun path with radiation":
        col_a, col_b = st.columns(2)
        invert_zenith_axis = col_a.checkbox("Invert zenith-angle axis (90° → 0°)", value=False)
        hide_zero_radiation = col_b.checkbox("Hide zero radiation values", value=False)
        fig = sun_path_chart(
            df,
            invert_zenith_axis=invert_zenith_axis,
            hide_zero_radiation=hide_zero_radiation,
        )
        render_plot(fig, solar_interpretation(df))
    elif chart_group == "Sun-path diagram":
        fig = sun_position_diagram(df)
        render_plot(fig, solar_interpretation(df))
    elif chart_group == "Radiation by façade orientation":
        tilt = st.slider("Surface tilt [deg]", 0.0, 90.0, 90.0, 5.0)
        data = orientation_annual_radiation(df, tilt_deg=tilt)
        fig = orientation_bar_chart(data, f"Annual irradiation by orientation at {tilt:.0f}° tilt")
        render_plot(fig, solar_interpretation(df))
    elif chart_group == "Orientation-tilt heatmap":
        st.caption("This chart may take a few seconds because it calculates many plane-of-array irradiance variants.")
        matrix = orientation_tilt_matrix(df)
        fig = matrix_heatmap(matrix, "Annual irradiation by orientation and tilt", "Surface azimuth [deg]", "Surface tilt [deg]", "kWh/m²")
        render_plot(fig, solar_interpretation(df))
    elif chart_group == "Monthly façade radiation":
        tilt = st.slider("Façade tilt [deg]", 0.0, 90.0, 90.0, 5.0)
        monthly = monthly_orientation_radiation(df, tilt_deg=tilt)
        fig = multi_line_monthly(monthly, f"Monthly façade irradiation at {tilt:.0f}° tilt", "kWh/m²")
        render_plot(fig, solar_interpretation(df))
    elif chart_group == "Cooling-risk solar hours":
        t_threshold = st.slider("Temperature threshold [°C]", 15.0, 35.0, 24.0, 0.5)
        ghi_threshold = st.slider("GHI threshold [Wh/m²]", 50.0, 800.0, 300.0, 25.0)
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        condition = (df["dry_bulb_temperature_c"] > t_threshold) & (df["global_horizontal_radiation_wh_m2"] > ghi_threshold)
        counts = threshold_count_by_period(df, condition, aggregation, label="hours")
        fig = threshold_bar_chart(counts, "Cooling-risk solar hours")
        render_plot(fig, solar_interpretation(df))
    else:
        fig = scatter_chart(
            df,
            "dry_bulb_temperature_c",
            "global_horizontal_radiation_wh_m2",
            "month_index",
            "Outdoor temperature vs global horizontal radiation",
            "Dry-bulb temperature [°C]",
            "GHI [Wh/m²]",
        )
        render_plot(fig, solar_interpretation(df))


def render_wind(df: pd.DataFrame) -> None:
    """Render wind and ventilation-wind charts."""
    st.header("Wind and natural-ventilation wind context")
    chart_group = st.selectbox(
        "Analysis type",
        [
            "Wind variable explorer",
            "Wind rose",
            "Monthly wind rose",
            "Day-night wind rose",
            "Wind during natural-ventilation hours",
            "Wind direction histogram",
        ],
    )
    if chart_group == "Wind variable explorer":
        render_generic_variable_page(df, ["Wind speed", "Wind direction"], "Wind speed", "Wind", None)
    elif chart_group == "Wind rose":
        fig = wind_rose_chart(df, "Annual wind rose")
        render_plot(fig, wind_interpretation(df))
    elif chart_group == "Monthly wind rose":
        month = st.selectbox("Month", list(MONTHS.keys()))
        data = df[df["month_index"] == MONTHS[month]]
        fig = wind_rose_chart(data, f"Wind rose: {month}")
        render_plot(fig, wind_interpretation(data))
    elif chart_group == "Day-night wind rose":
        period = st.radio("Period", ["Day", "Night"], horizontal=True)
        if period == "Day":
            data = df[df["hour_of_day"].between(7, 19)]
        else:
            data = df[(df["hour_of_day"] < 7) | (df["hour_of_day"] > 19)]
        fig = wind_rose_chart(data, f"{period} wind rose")
        render_plot(fig, wind_interpretation(data))
    elif chart_group == "Wind during natural-ventilation hours":
        mask = natural_ventilation_condition(df)
        data = df[mask]
        fig = wind_rose_chart(data, "Wind rose during natural-ventilation-suitable hours")
        render_plot(fig, natural_ventilation_interpretation(df, mask))
    else:
        fig = histogram_chart(df, "wind_direction_deg", "Wind direction histogram", "deg", bins=36)
        render_plot(fig, wind_interpretation(df))



def render_precipitation(df: pd.DataFrame) -> None:
    """Render liquid-precipitation and snow-cover analysis from EPW fields."""
    st.header("Precipitation and snow")
    liquid_available = (
        "liquid_precipitation_depth_mm" in df.columns
        and pd.to_numeric(df["liquid_precipitation_depth_mm"], errors="coerce").notna().any()
    )
    snow_available = (
        "snow_depth_cm" in df.columns
        and pd.to_numeric(df["snow_depth_cm"], errors="coerce").notna().any()
    )

    options: list[str] = []
    if liquid_available:
        options.extend(["Precipitation totals", "Precipitation-record occurrence", "Liquid precipitation explorer"])
    if snow_available:
        options.extend(["Snow depth explorer", "Snow-cover occurrence"])
    if not options:
        st.info("This EPW file does not contain usable liquid-precipitation or snow-depth data.")
        return

    chart_group = st.selectbox("Analysis type", options)

    if chart_group == "Precipitation totals":
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        totals = aggregate_liquid_precipitation(df, aggregation)
        plot_data = totals.reset_index()
        x_column = plot_data.columns[0]
        fig = px.bar(
            plot_data,
            x=x_column,
            y="precipitation_mm",
            title=f"Liquid precipitation totals — {aggregation.lower()}",
            labels={x_column: "Period", "precipitation_mm": "Precipitation [mm]"},
        )
        fig.update_traces(marker_color=metric_color("liquid_precipitation_depth_mm"))
        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Precipitation [mm]")
        render_plot(
            fig,
            "Period totals sum valid EPW liquid-precipitation depth records. Missing EPW values are excluded rather than treated as zero.",
        )
    elif chart_group == "Precipitation-record occurrence":
        threshold = st.number_input("Precipitation-record threshold [mm]", min_value=0.0, value=0.1, step=0.1)
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        counts = occurrence_hours(
            df,
            "liquid_precipitation_depth_mm",
            float(threshold),
            aggregation,
            inclusive=True,
        )
        plot_data = counts.reset_index()
        x_column = plot_data.columns[0]
        fig = px.bar(
            plot_data,
            x=x_column,
            y="hours",
            title=f"Precipitation-record occurrence ≥ {threshold:g} mm",
            labels={x_column: "Period", "hours": "Records meeting threshold"},
        )
        fig.update_traces(marker_color=metric_color("liquid_precipitation_depth_mm"))
        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Records meeting threshold")
        render_plot(
            fig,
            "Counts EPW precipitation records meeting the selected depth threshold. This is an observation-record occurrence metric, not exact rainfall duration: EPW liquid precipitation depth may refer to the measurement interval reported by Liquid Precipitation Quantity.",
        )
    elif chart_group == "Liquid precipitation explorer":
        render_generic_variable_page(
            df,
            ["Liquid precipitation depth"],
            "Liquid precipitation depth",
            "Precipitation",
            None,
        )
    elif chart_group == "Snow depth explorer":
        render_generic_variable_page(df, ["Snow depth"], "Snow depth", "Snow cover", None)
    else:
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        counts = occurrence_hours(df, "snow_depth_cm", 0.0, aggregation, inclusive=False)
        plot_data = counts.reset_index()
        x_column = plot_data.columns[0]
        fig = px.bar(
            plot_data,
            x=x_column,
            y="hours",
            title="Snow-cover occurrence",
            labels={x_column: "Period", "hours": "Hours with snow depth > 0 cm"},
        )
        fig.update_traces(marker_color=metric_color("snow_depth_cm"))
        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Snow-cover hours")
        render_plot(fig, "Snow depth is a state variable; this chart counts valid EPW records with snow depth greater than zero.")


def render_sky_daylight(df: pd.DataFrame) -> None:
    """Render sky-cover and daylight charts."""
    st.header("Sky cover and daylight")
    chart_group = st.selectbox("Analysis type", ["Sky-cover variable explorer", "Illuminance variable explorer", "Clear and overcast hours", "Daylight scatter"])
    if chart_group == "Sky-cover variable explorer":
        render_generic_variable_page(df, ["Total sky cover", "Opaque sky cover"], "Total sky cover", "Sky cover", None)
    elif chart_group == "Illuminance variable explorer":
        render_generic_variable_page(
            df,
            ["Global horizontal illuminance", "Direct normal illuminance", "Diffuse horizontal illuminance"],
            "Global horizontal illuminance",
            "Illuminance",
            None,
        )
    elif chart_group == "Clear and overcast hours":
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        mode = st.radio("Condition", ["Clear sky cover <= 2", "Overcast sky cover >= 8", "Illuminance > 10000 lux"])
        if mode == "Clear sky cover <= 2":
            condition = df["total_sky_cover_tenths"] <= 2
        elif mode == "Overcast sky cover >= 8":
            condition = df["total_sky_cover_tenths"] >= 8
        else:
            condition = df["global_horizontal_illuminance_lux"] > 10000
        counts = threshold_count_by_period(df, condition, aggregation, label="hours")
        fig = threshold_bar_chart(counts, mode)
        render_plot(fig, sky_interpretation(df))
    else:
        fig = scatter_chart(
            df,
            "total_sky_cover_tenths",
            "global_horizontal_radiation_wh_m2",
            "month_index",
            "Sky cover vs global horizontal radiation",
            "Total sky cover [tenths]",
            "GHI [Wh/m²]",
        )
        render_plot(fig, sky_interpretation(df))


def render_natural_ventilation(df: pd.DataFrame, pressure_pa: float) -> None:
    """Render natural-ventilation and night-flushing charts."""
    st.header("Natural ventilation and night flushing")
    st.markdown("Adjust the outdoor-air suitability limits and inspect when window ventilation is climatically possible.")
    col1, col2, col3, col4 = st.columns(4)
    t_min = col1.number_input("Minimum outdoor temperature [°C]", value=16.0, step=0.5)
    t_max = col2.number_input("Maximum outdoor temperature [°C]", value=26.0, step=0.5)
    d_max = col3.number_input("Maximum humidity ratio [g/kg]", value=9.0, step=0.5)
    occupied_only = col4.checkbox("Occupied hours only", value=False)
    occupied_start = 8
    occupied_end = 18
    weekdays_only = False
    if occupied_only:
        occ1, occ2, occ3 = st.columns(3)
        occupied_start = int(occ1.number_input("Occupied start hour", min_value=0, max_value=23, value=8, step=1))
        occupied_end = int(occ2.number_input("Occupied end hour", min_value=0, max_value=23, value=18, step=1))
        weekdays_only = occ3.checkbox("Weekdays only", value=False)
        st.caption("Occupied-hour filtering uses local EPW clock time. Intervals crossing midnight are supported, for example 22...6.")
    wind_filter = st.checkbox("Use wind-speed limits", value=False)
    wind_min = wind_max = None
    if wind_filter:
        wind_min = st.number_input("Minimum wind speed [m/s]", value=0.5, step=0.1)
        wind_max = st.number_input("Maximum wind speed [m/s]", value=6.0, step=0.1)

    mask = natural_ventilation_condition(
        df,
        t_min,
        t_max,
        d_max,
        wind_min_m_s=wind_min,
        wind_max_m_s=wind_max,
        occupied_only=occupied_only,
        occupied_start_hour=occupied_start,
        occupied_end_hour=occupied_end,
        weekdays_only=weekdays_only,
    )
    df_nv = df.copy()
    df_nv["natural_ventilation_suitable"] = mask.astype(int)

    chart_group = st.selectbox(
        "Analysis type",
        [
            "Heat map",
            "Suitable hours by aggregation",
            "Month × hour suitability",
            "Daily suitable-hours duration curve",
            "Rejected reasons",
            "Psychrometric NV overlay",
            "Night-flushing potential",
        ],
    )
    if chart_group == "Heat map":
        row_group = st.radio("Heat-map aggregation", ["day", "week", "month"], horizontal=True)
        fig = heatmap_chart(df_nv, "natural_ventilation_suitable", row_group, "Natural ventilation eligibility", "0/1")
        render_plot(fig, natural_ventilation_interpretation(df, mask))
    elif chart_group == "Suitable hours by aggregation":
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        counts = threshold_count_by_period(df, mask, aggregation, label="suitable_hours")
        fig = threshold_bar_chart(counts, "Natural-ventilation suitable hours", "hours")
        render_plot(fig, natural_ventilation_interpretation(df, mask))
    elif chart_group == "Month × hour suitability":
        fig = month_hour_heatmap(df_nv, "natural_ventilation_suitable", "Mean natural-ventilation eligibility by month and hour", "share", aggfunc="mean")
        render_plot(fig, natural_ventilation_interpretation(df, mask))
    elif chart_group == "Daily suitable-hours duration curve":
        daily = df_nv["natural_ventilation_suitable"].resample("D").sum().to_frame("suitable_hours")
        fig = duration_chart(daily, "suitable_hours", "Daily natural-ventilation suitable-hours duration curve", "hours/day", ascending=False)
        render_plot(fig, natural_ventilation_interpretation(df, mask))
    elif chart_group == "Rejected reasons":
        reasons = rejection_reasons_for_nv(df, t_min, t_max, d_max, wind_min_m_s=wind_min, wind_max_m_s=wind_max)
        fig = px.bar(reasons, x="reason", y="hours", title="Natural-ventilation rejected reasons")
        fig.update_layout(template="plotly_white", xaxis_title="Reason", yaxis_title="Hours")
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True}, key=next_plot_key())
        st.dataframe(reasons, hide_index=True, use_container_width=True)
        render_interpretation(natural_ventilation_interpretation(df, mask))
    elif chart_group == "Psychrometric NV overlay":
        fig = psychrometric_chart(df, chart_type="T-d", pressure_pa=pressure_pa, show_rh_curves=True, show_comfort_zone=False)
        fig.add_shape(type="rect", x0=t_min, x1=t_max, y0=0, y1=d_max, line=dict(dash="dash"), fillcolor="rgba(0,150,0,0.08)")
        render_plot(fig, natural_ventilation_interpretation(df, mask))
    else:
        night_mask = night_flushing_condition(df)
        df_nf = df.copy()
        df_nf["night_flushing_suitable"] = night_mask.astype(int)
        fig = heatmap_chart(df_nf, "night_flushing_suitable", "day", "Night-flushing potential", "0/1")
        render_plot(fig, natural_ventilation_interpretation(df, night_mask))


def render_hvac_passive(df: pd.DataFrame) -> None:
    """Render HVAC and passive-design decision-support charts."""
    st.header("HVAC operation and passive strategies")
    chart_group = st.selectbox(
        "Analysis type",
        [
            "Passive strategy annual table",
            "Passive strategy monthly stacked bars",
            "Economizer availability",
            "Dehumidification and humidification",
            "Outdoor-air enthalpy duration curve",
            "Heating and cooling degree-hours",
            "Design-day candidates",
            "Ventilation load proxy",
        ],
    )
    if chart_group == "Passive strategy annual table":
        table = passive_strategy_table(df)
        fig = px.bar(table, x="hours", y="strategy", orientation="h", title="Annual passive and HVAC strategy hours")
        fig.update_layout(template="plotly_white", xaxis_title="Hours", yaxis_title="Strategy")
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True}, key=next_plot_key())
        st.dataframe(table, hide_index=True, use_container_width=True)
        render_interpretation(hvac_interpretation(df))
    elif chart_group == "Passive strategy monthly stacked bars":
        monthly = passive_strategy_monthly(df)
        fig = stacked_monthly_bar(monthly, "Monthly passive and HVAC strategy hours", "hours")
        render_plot(fig, hvac_interpretation(df))
    elif chart_group == "Economizer availability":
        h_return = st.slider("Return-air enthalpy limit [kJ/kg]", 30.0, 80.0, 50.0, 1.0)
        mask = economizer_condition(df, return_air_enthalpy_kj_kg=h_return)
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        counts = threshold_count_by_period(df, mask, aggregation, label="hours")
        fig = threshold_bar_chart(counts, "Air-side economizer availability", "hours")
        render_plot(fig, hvac_interpretation(df))
    elif chart_group == "Dehumidification and humidification":
        d_high = st.slider("Dehumidification threshold [g/kg]", 5.0, 20.0, 10.0, 0.5)
        d_low = st.slider("Humidification threshold [g/kg]", 0.5, 8.0, 3.0, 0.5)
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        dehum = threshold_count_by_period(df, dehumidification_condition(df, d_high), aggregation, label="Dehumidification hours")
        humid = threshold_count_by_period(df, humidification_condition(df, d_low), aggregation, label="Humidification hours")
        combined = dehum.join(humid, how="outer").fillna(0)
        fig = stacked_monthly_bar(combined, "Humidification and dehumidification climate hours", "hours")
        render_plot(fig, hvac_interpretation(df))
    elif chart_group == "Outdoor-air enthalpy duration curve":
        fig = duration_chart(df, "moist_air_enthalpy_kj_kg", "Outdoor-air enthalpy duration curve", "kJ/kg dry air", ascending=False)
        render_plot(fig, hvac_interpretation(df))
    elif chart_group == "Heating and cooling degree-hours":
        monthly = aggregate_sum(df, "heating_degree_hours_kh", "Monthly")[["sum"]].rename(columns={"sum": "Heating degree-hours"})
        monthly["Cooling degree-hours"] = aggregate_sum(df, "cooling_degree_hours_kh", "Monthly")["sum"]
        fig = stacked_monthly_bar(monthly, "Monthly degree-hour climate severity", "K·h")
        render_plot(fig, degree_day_interpretation(df))
    elif chart_group == "Design-day candidates":
        daily = df.resample("D").agg(
            mean_t=("dry_bulb_temperature_c", "mean"),
            min_t=("dry_bulb_temperature_c", "min"),
            max_t=("dry_bulb_temperature_c", "max"),
            max_enthalpy=("moist_air_enthalpy_kj_kg", "max"),
            max_humidity_ratio=("humidity_ratio_g_kg", "max"),
            max_ghi=("global_horizontal_radiation_wh_m2", "max"),
        )
        mode = st.radio("Design-day ranking", ["Coldest days", "Hottest days", "Highest enthalpy days", "Most humid days"], horizontal=True)
        if mode == "Coldest days":
            table = daily.sort_values("min_t").head(15)
        elif mode == "Hottest days":
            table = daily.sort_values("max_t", ascending=False).head(15)
        elif mode == "Highest enthalpy days":
            table = daily.sort_values("max_enthalpy", ascending=False).head(15)
        else:
            table = daily.sort_values("max_humidity_ratio", ascending=False).head(15)
        st.dataframe(table, use_container_width=True)
        fig = profile_ribbon_chart(df, "dry_bulb_temperature_c", "Daily", "Daily dry-bulb temperature for design-day screening", "°C")
        render_plot(fig, hvac_interpretation(df))
    else:
        airflow_m3_h = st.number_input("Outdoor airflow [m³/h]", min_value=1.0, value=1000.0, step=100.0)
        heat_set_c = st.number_input("Heating supply target temperature [°C]", value=20.0, step=0.5)
        cool_set_c = st.number_input("Cooling supply target temperature [°C]", value=26.0, step=0.5)
        rho = df["moist_air_density_kg_m3"].fillna(1.2)
        m_dot = rho * airflow_m3_h / 3600.0
        cp = 1.006
        proxy = df.copy()
        proxy["ventilation_heating_kw"] = m_dot * cp * (heat_set_c - proxy["dry_bulb_temperature_c"]).clip(lower=0)
        proxy["ventilation_cooling_kw"] = m_dot * cp * (proxy["dry_bulb_temperature_c"] - cool_set_c).clip(lower=0)
        monthly = aggregate_sum(proxy, "ventilation_heating_kw", "Monthly")[["sum"]].rename(columns={"sum": "Heating proxy [kWh-like]"})
        monthly["Cooling proxy [kWh-like]"] = aggregate_sum(proxy, "ventilation_cooling_kw", "Monthly")["sum"]
        fig = stacked_monthly_bar(monthly, "Outdoor-air sensible ventilation load proxy", "kW·h proxy")
        render_plot(fig, hvac_interpretation(df))


def render_time_series_overlay(df: pd.DataFrame) -> None:
    """Render aligned variable-resolution series on one absolute time axis."""
    st.header("Time series and overlay")
    native_minutes = native_resolution_minutes(pd.DatetimeIndex(df.index))
    st.caption(
        f"Source resolution: {native_minutes} min. Choose an exact time window and overlay up to six series. "
        "Resolutions finer than the source are intentionally unavailable; no temporal interpolation is performed."
    )

    index = pd.DatetimeIndex(df.index).sort_values()
    if index.empty:
        st.info("No time-series records are available.")
        return

    default_start = pd.Timestamp(index.min())
    default_end = pd.Timestamp(index.max())
    date_min = default_start.date()
    date_max = default_end.date()
    step_seconds = max(60, int(native_minutes * 60))

    c1, c2, c3, c4 = st.columns(4)
    start_date = c1.date_input(
        "From date",
        value=default_start.date(),
        min_value=date_min,
        max_value=date_max,
        key="overlay_start_date",
    )
    start_time = c2.time_input(
        "From time",
        value=default_start.time(),
        step=step_seconds,
        key="overlay_start_time",
    )
    end_date = c3.date_input(
        "Through date",
        value=default_end.date(),
        min_value=date_min,
        max_value=date_max,
        key="overlay_end_date",
    )
    end_time = c4.time_input(
        "Through time",
        value=default_end.time(),
        step=step_seconds,
        key="overlay_end_time",
    )

    start = pd.Timestamp.combine(start_date, start_time)
    selected_end = pd.Timestamp.combine(end_date, end_time)
    if index.tz is not None:
        start = start.tz_localize(index.tz)
        selected_end = selected_end.tz_localize(index.tz)
    # "Through" denotes the selected source interval, so the internal viewport
    # ends at the following native interval boundary. This includes the selected
    # 23:00 EPW record without fabricating sub-hourly values.
    end = selected_end + pd.Timedelta(minutes=native_minutes)
    if selected_end < start:
        st.error("The end timestamp must not be earlier than the start timestamp.")
        return

    if start < pd.Timestamp(index.min()) or selected_end > pd.Timestamp(index.max()):
        st.error("The selected time range must stay inside the loaded source calendar.")
        return


    available_variables = [
        label
        for label, (column, _unit) in VARIABLES.items()
        if column in df.columns and pd.to_numeric(df[column], errors="coerce").notna().any()
    ]
    if not available_variables:
        st.info("No numeric climate variables are available for overlay.")
        return

    resolutions = available_resolution_labels(pd.DatetimeIndex(df.index))
    n_series = st.slider("Number of series", min_value=1, max_value=6, value=2, step=1)
    preferred = [
        "Dry-bulb temperature",
        "Global horizontal radiation",
        "Relative humidity",
        "Wind speed",
        "Dew-point temperature",
        "Station pressure",
    ]
    defaults = [item for item in preferred if item in available_variables]
    specs: list[OverlaySeries] = []

    st.markdown("#### Series")
    for i in range(n_series):
        col_variable, col_resolution = st.columns([3, 2])
        default_label = defaults[i] if i < len(defaults) else available_variables[min(i, len(available_variables) - 1)]
        variable_label = col_variable.selectbox(
            f"Series {i + 1} variable",
            available_variables,
            index=available_variables.index(default_label),
            key=f"overlay_variable_{i}",
        )
        default_resolution = "Native" if i == 0 else ("Daily" if "Daily" in resolutions else "Native")
        resolution = col_resolution.selectbox(
            f"Series {i + 1} resolution",
            resolutions,
            index=resolutions.index(default_resolution),
            key=f"overlay_resolution_{i}",
        )
        column, unit = VARIABLES[variable_label]
        specs.append(OverlaySeries(variable_label, column, unit, resolution))

    try:
        families = validate_unit_families(specs)
    except ValueError as exc:
        st.error(str(exc) + " Remove a physical quantity or choose variables from the same unit family.")
        return

    raw_view = df.loc[(df.index >= start) & (df.index < end)].copy()
    st.session_state["_active_filtered_export_df"] = raw_view
    if raw_view.empty:
        st.warning("The selected interval contains no source records.")
        return


    try:
        fig, tables = build_overlay_figure(df, specs, start, end, title="Climate time-series overlay")
    except (ValueError, KeyError) as exc:
        st.error(f"The requested overlay could not be constructed: {exc}")
        return

    st.caption(
        "All series share the same absolute X-axis. Aggregated series use calendar-aligned complete bins before the "
        "selected viewport is applied. Extensive interval quantities are summed, state/intensive quantities are averaged, "
        "and wind direction uses a circular mean."
    )
    if len(families) == 2:
        st.caption("Two physical unit families are shown on separate left and right Y-axes.")
    render_plot(
        fig,
        "The overlay preserves one common time axis for every series. Different temporal resolutions are displayed without "
        "upsampling or interpolation; complete aggregation bins retain their physical meaning even when only part of a bin "
        "falls inside the visible range.",
    )


def render_data_quality(epw, df: pd.DataFrame, issues: list[object]) -> None:
    """Render data-quality diagnostics and EPW metadata."""
    st.header("Data quality and EPW diagnostics")
    st.subheader("EPW location header")
    st.dataframe(pd.DataFrame(location_summary(epw.location).items(), columns=["Field", "Value"]), hide_index=True, use_container_width=True)

    st.subheader("Diagnostics")
    rows = [{"field": i.field, "issue": i.issue, "count": i.count, "severity": i.severity} for i in issues]
    if rows:
        issue_df = pd.DataFrame(rows)
        st.dataframe(issue_df, hide_index=True, use_container_width=True)
        fig = px.bar(issue_df, x="field", y="count", color="severity", title="Data-quality issue counts")
        fig.update_layout(template="plotly_white", xaxis_title="Field", yaxis_title="Count")
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True}, key=next_plot_key())
        render_interpretation(data_quality_interpretation(len(rows), int((issue_df["severity"] == "error").sum())))
    else:
        render_interpretation(data_quality_interpretation(0, 0))

    st.subheader("Missing values by field")
    missing = df.isna().sum().reset_index()
    missing.columns = ["field", "missing_count"]
    missing = missing[missing["missing_count"] > 0].sort_values("missing_count", ascending=False)
    st.dataframe(missing, hide_index=True, use_container_width=True)

    st.subheader("Header lines")
    for line in epw.header_lines:
        st.code(line)


def render_canonical_data_quality(dataset, df: pd.DataFrame) -> None:
    """Render diagnostics/provenance for a provider-neutral historical dataset."""
    st.header("Data quality and source metadata")
    location = dataset.location
    st.subheader("Station")
    st.dataframe(
        pd.DataFrame(
            {
                "Field": ["Station", "Station ID", "Region", "Country", "Latitude", "Longitude", "Elevation"],
                "Value": [
                    location.city, location.station_id, location.state, location.country,
                    location.latitude, location.longitude, location.elevation_m,
                ],
            }
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.subheader("Temporal/source contract")
    st.dataframe(
        pd.DataFrame(
            {
                "Field": ["Provider", "Dataset", "Calendar mode", "Native interval", "Timezone", "First timestamp", "Last timestamp", "Records"],
                "Value": [
                    dataset.provenance.provider, dataset.provenance.dataset, dataset.temporal.calendar_mode,
                    f"{dataset.temporal.native_interval_minutes} min", dataset.temporal.timezone_name,
                    str(dataset.start), str(dataset.end), len(df),
                ],
            }
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.subheader("Missing values by field")
    missing = df[list(dataset.available_canonical_variables)].isna().sum().reset_index()
    missing.columns = ["field", "missing_count"]
    missing = missing[missing["missing_count"] > 0].sort_values("missing_count", ascending=False)
    if missing.empty:
        st.success("No missing values occur in the loaded canonical measured variables.")
    else:
        st.dataframe(missing, hide_index=True, use_container_width=True)
    with st.expander("Provider provenance", expanded=False):
        st.write(dataset.provenance.source_name)
        st.code(dataset.provenance.source_reference)
        for note in dataset.provenance.notes:
            st.caption(note)


def render_historical_wind(df: pd.DataFrame) -> None:
    """Render only measured-wind analyses supported by the historical frame."""
    from epw_climate_analyzer.historical_capabilities import has_numeric_observations

    st.header("Measured wind analysis")
    has_speed = has_numeric_observations(df, "wind_speed_m_s")
    has_direction = has_numeric_observations(df, "wind_direction_deg")
    options: list[str] = []
    if has_speed:
        options.append("Wind speed explorer")
    if has_speed and has_direction:
        options.extend(["Wind rose", "Monthly wind rose", "Day-night wind rose"])
    if has_direction:
        options.append("Wind direction histogram")
    if not options:
        st.info("No measured wind observations are available in the selected interval.")
        return

    st.caption(
        "GeoSphere historical wind values are measured source-interval observations. Wind-rose radii and histogram "
        "frequencies are integrated in physical hours from the declared native cadence; missing timestamp gaps are not filled."
    )
    chart_group = st.selectbox("Analysis type", options, key="historical_wind_analysis")
    if chart_group == "Wind speed explorer":
        render_generic_variable_page(df, ["Wind speed"], "Wind speed", "Measured wind", None)
    elif chart_group == "Wind rose":
        fig = wind_rose_chart(df, "Measured wind rose")
        render_plot(fig, wind_interpretation(df))
    elif chart_group == "Monthly wind rose":
        observed = sorted({int(v) for v in pd.to_numeric(df["month_index"], errors="coerce").dropna().tolist() if 1 <= int(v) <= 12})
        month_names = [name for name, number in MONTHS.items() if number in observed]
        if not month_names:
            st.info("No valid month labels are available for the selected wind observations.")
            return
        month = st.selectbox("Month", month_names, key="historical_wind_month")
        data = df[df["month_index"] == MONTHS[month]]
        fig = wind_rose_chart(data, f"Measured wind rose: {month}")
        render_plot(fig, wind_interpretation(data))
    elif chart_group == "Day-night wind rose":
        period = st.radio("Period", ["Day", "Night"], horizontal=True, key="historical_wind_daynight")
        if period == "Day":
            data = df[df["hour_of_day"].between(7, 19)]
        else:
            data = df[(df["hour_of_day"] < 7) | (df["hour_of_day"] > 19)]
        fig = wind_rose_chart(data, f"Measured {period.lower()} wind rose")
        render_plot(fig, wind_interpretation(data))
    else:
        fig = histogram_chart(df, "wind_direction_deg", "Measured wind direction histogram", "deg", bins=36)
        render_plot(
            fig,
            "The histogram integrates the physical duration represented by each observed wind-direction record. "
            "Direction is circular; the histogram should be read by sectors rather than by arithmetic averaging."
        )


def render_historical_solar(df: pd.DataFrame) -> None:
    """Render measured horizontal solar analyses without fabricating DNI."""
    from epw_climate_analyzer.historical_capabilities import has_numeric_observations, horizontal_irradiance_frame

    st.header("Measured horizontal solar radiation")
    solar = horizontal_irradiance_frame(df)
    specs: list[tuple[str, str, str]] = []
    if has_numeric_observations(df, "global_horizontal_radiation_wh_m2"):
        specs.append(("Global horizontal irradiance", "global_horizontal_irradiance_w_m2", "global_horizontal_radiation_wh_m2"))
    if has_numeric_observations(df, "diffuse_horizontal_radiation_wh_m2"):
        specs.append(("Diffuse horizontal irradiance", "diffuse_horizontal_irradiance_w_m2", "diffuse_horizontal_radiation_wh_m2"))
    if not specs:
        st.info("No measured horizontal radiation observations are available in the selected interval.")
        return

    st.caption(
        "GeoSphere cglo/chim are measured 10-minute mean horizontal irradiances. The adapter stores canonical interval "
        "irradiation [Wh/m²]; this page converts it back to mean irradiance [W/m²] using the declared native interval. "
        "DNI and plane-of-array routes are intentionally unavailable in measured historical mode."
    )
    options = ["Horizontal irradiance explorer", "Monthly horizontal irradiation"]
    has_ghi = any(source == "global_horizontal_radiation_wh_m2" for _, _, source in specs)
    has_temperature = has_numeric_observations(df, "dry_bulb_temperature_c")
    if has_ghi and has_temperature:
        options.extend(["Cooling-risk solar hours", "Temperature vs GHI"])
    chart_group = st.selectbox("Analysis type", options, key="historical_solar_analysis")

    if chart_group == "Horizontal irradiance explorer":
        labels = [label for label, _, _ in specs]
        selected = st.selectbox("Variable", labels, key="historical_solar_variable")
        column = next(column for label, column, _ in specs if label == selected)
        chart_type = st.selectbox("Chart type", ["Profile", "Duration curve", "Month-hour heat map", "Histogram"], key="historical_solar_chart")
        if chart_type == "Profile":
            aggregation = st.selectbox("Aggregation", ["Hourly", "Daily", "Weekly", "Monthly", "Seasonal"], index=0, key="historical_solar_aggregation")
            fig = profile_ribbon_chart(solar, column, aggregation, f"{selected} — {aggregation.lower()}", "W/m²")
        elif chart_type == "Duration curve":
            fig = duration_chart(solar, column, f"{selected} duration curve", "W/m²", ascending=False)
        elif chart_type == "Month-hour heat map":
            fig = month_hour_heatmap(solar, column, f"{selected} month-hour heat map", "W/m²")
        else:
            bins = st.slider("Histogram bins", 10, 120, 40, key="historical_solar_bins")
            fig = histogram_chart(solar, column, f"{selected} histogram", "W/m²", bins=bins)
        render_plot(
            fig,
            "Values are measured mean horizontal irradiance over each source interval. Duration/frequency views use physical hours, not record counts."
        )
    elif chart_group == "Monthly horizontal irradiation":
        monthly = pd.DataFrame(index=range(1, 13))
        for label, _, source in specs:
            monthly[label] = pd.to_numeric(df[source], errors="coerce").clip(lower=0).groupby(df["month_index"]).sum(min_count=1) / 1000.0
        fig = stacked_monthly_bar(monthly, "Measured monthly horizontal irradiation", "kWh/m²")
        render_plot(
            fig,
            "Monthly irradiation sums the measured interval energy [Wh/m²]. Missing source records are excluded rather than interpolated."
        )
    elif chart_group == "Cooling-risk solar hours":
        t_threshold = st.slider("Temperature threshold [°C]", 15.0, 35.0, 24.0, 0.5, key="historical_solar_t_threshold")
        ghi_threshold = st.slider("Mean GHI threshold [W/m²]", 50.0, 1000.0, 300.0, 25.0, key="historical_solar_ghi_threshold")
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0, key="historical_solar_threshold_aggregation")
        condition = (solar["dry_bulb_temperature_c"] > t_threshold) & (solar["global_horizontal_irradiance_w_m2"] > ghi_threshold)
        counts = threshold_count_by_period(solar, condition, aggregation, label="hours")
        fig = threshold_bar_chart(counts, "Measured cooling-risk solar hours")
        render_plot(
            fig,
            "Hours combine measured outdoor temperature with measured mean global horizontal irradiance. Missing timestamp gaps do not contribute duration."
        )
    else:
        fig = scatter_chart(
            solar,
            "dry_bulb_temperature_c",
            "global_horizontal_irradiance_w_m2",
            "month_index",
            "Outdoor temperature vs measured global horizontal irradiance",
            "Dry-bulb temperature [°C]",
            "GHI [W/m²]",
        )
        render_plot(fig, "Each point combines coincident measured temperature and global horizontal irradiance at the source timestamp.")


def render_canonical_climate_analysis(dataset) -> None:
    """Run existing source-agnostic analyses on a real historical canonical dataset."""
    from epw_climate_analyzer.historical_capabilities import available_historical_pages

    historical_pages = available_historical_pages(dataset.data)
    if NAVIGATION_KEY not in st.session_state or st.session_state[NAVIGATION_KEY] not in historical_pages:
        preferred = "Temperature" if "Temperature" in historical_pages else "Time Series and Overlay"
        st.session_state[NAVIGATION_KEY] = preferred

    st.sidebar.markdown("### Explore")
    page = st.sidebar.radio(
        "Analysis section",
        historical_pages,
        format_func=navigation_label,
        key=NAVIGATION_KEY,
        label_visibility="collapsed",
    )
    if page == "Climate File Source":
        render_climate_file_source()
        return

    with st.sidebar.expander("Advanced calculation settings", expanded=False):
        pressure_mode = st.selectbox(
            "Psychrometric pressure mode",
            [
                "Measured station pressure with fallback median",
                "Normal pressure: 101325 Pa",
                "Altitude-derived standard atmosphere pressure",
                "Custom constant pressure",
            ],
            index=0,
            help=(
                "Default: use the measured GeoSphere station pressure for each 10-minute record. "
                "The median valid measured pressure is only a fallback for missing/invalid records."
            ),
        )
        custom_pressure = None
        if pressure_mode == "Custom constant pressure":
            custom_pressure = st.number_input(
                "Custom pressure [Pa]", min_value=30000.0, max_value=120000.0, value=101325.0, step=100.0
            )

    include_psychrometrics = page in {"Temperature", "Humidity and Psychrometrics", "Time Series and Overlay"}
    _ensure_analysis_dependencies(include_solar=False, include_comparison=False)
    source_pressure = dataset.data.get("atmospheric_station_pressure_pa")
    valid_pressure = pd.to_numeric(source_pressure, errors="coerce").dropna() if source_pressure is not None else pd.Series(dtype=float)
    measured_median = float(valid_pressure.median()) if not valid_pressure.empty else DEFAULT_PRESSURE_PA
    if pressure_mode == "Measured station pressure with fallback median":
        fallback_pressure = measured_median
        pressure_override = None
    elif pressure_mode == "Normal pressure: 101325 Pa":
        fallback_pressure = DEFAULT_PRESSURE_PA
        pressure_override = DEFAULT_PRESSURE_PA
    elif pressure_mode == "Altitude-derived standard atmosphere pressure":
        fallback_pressure = pressure_from_altitude_m(float(dataset.location.elevation_m or 0.0))
        pressure_override = fallback_pressure
    else:
        fallback_pressure = float(custom_pressure or DEFAULT_PRESSURE_PA)
        pressure_override = fallback_pressure

    from epw_climate_analyzer.historical import prepare_historical_analysis_frame
    try:
        full_df = prepare_historical_analysis_frame(
            dataset,
            include_psychrometrics=include_psychrometrics,
            fallback_pressure_pa=fallback_pressure,
            pressure_override_pa=pressure_override,
        )
    except Exception as exc:
        st.error(f"Historical climate data could not be prepared for this analysis: {exc}")
        return

    active_pressure = fallback_pressure if pressure_mode != "Measured station pressure with fallback median" else measured_median
    if page == "Time Series and Overlay":
        filtered_df = full_df
        st.session_state["_active_filtered_export_df"] = full_df
    else:
        filtered_df = sidebar_filters(full_df)
        if filtered_df.empty:
            st.warning("The current filters remove all data. Adjust the month or hour filter.")
            return

    st.sidebar.markdown("### Current climate")
    st.sidebar.write(f"**{dataset.location.city}, {dataset.location.country}**")
    st.sidebar.caption("GeoSphere Austria · measured 10-minute historical data")
    st.sidebar.write(f"Rows in current view: {len(filtered_df):,}")
    with st.sidebar.expander("Data provenance", expanded=False):
        st.caption(dataset.provenance.dataset)
        st.caption(f"Calendar: real historical UTC · native interval {dataset.temporal.native_interval_minutes} min")
        if pressure_mode == "Measured station pressure with fallback median":
            st.caption(f"Pressure: measured station values; fallback median {active_pressure:,.0f} Pa")
        else:
            st.caption(f"Calculation pressure: {active_pressure:,.0f} Pa")

    if page == "Temperature":
        st.caption("Measured-data threshold hours are integrated from the declared native interval; missing timestamp gaps are not counted as observed duration.")
        render_temperature(filtered_df)
    elif page == "Humidity and Psychrometrics":
        st.caption("Measured-data moisture-threshold hours are integrated from the declared native interval; missing timestamp gaps are not counted as observed duration.")
        render_humidity(filtered_df, pressure_pa=active_pressure)
    elif page == "Solar and Radiation":
        render_historical_solar(filtered_df)
    elif page == "Wind and Ventilation":
        render_historical_wind(filtered_df)
    elif page == "Time Series and Overlay":
        render_time_series_overlay(full_df)
    else:
        render_canonical_data_quality(dataset, full_df)


def main() -> None:
    """Run the Streamlit Climate Analyzer application."""
    st.sidebar.caption("Building Energy Tools")
    st.sidebar.title(APP_NAME)
    st.sidebar.caption(APP_RELEASE_LABEL)
    apply_queued_navigation(st.session_state)
    active_file = get_active_climate_file()
    active_canonical = get_active_canonical_climate()

    if active_file is None and active_canonical is None:
        st.sidebar.info("Choose a climate source to start the analysis.")
        render_climate_file_source()
        return
    if active_canonical is not None:
        render_canonical_climate_analysis(active_canonical)
        return

    if NAVIGATION_KEY not in st.session_state or st.session_state[NAVIGATION_KEY] not in NAVIGATION_PAGES:
        st.session_state[NAVIGATION_KEY] = "Overview"

    st.sidebar.markdown("### Explore")
    page = st.sidebar.radio(
        "Analysis section",
        NAVIGATION_PAGES,
        format_func=navigation_label,
        key=NAVIGATION_KEY,
        label_visibility="collapsed",
    )

    if page == "Climate File Source":
        render_climate_file_source()
        return

    with st.sidebar.expander("Advanced calculation settings", expanded=False):
        pressure_mode = st.selectbox(
            "Psychrometric pressure mode",
            [
                "Normal pressure: 101325 Pa",
                "EPW station pressure with fallback median",
                "Altitude-derived standard atmosphere pressure",
                "Custom constant pressure",
            ],
            index=1,
            help=(
                "Default: use the atmospheric station pressure stored in the EPW for each hourly record. "
                "The median valid EPW pressure is used only as a fallback when an EPW pressure value is missing or invalid."
            ),
        )
        custom_pressure = None
        if pressure_mode == "Custom constant pressure":
            custom_pressure = st.number_input(
                "Custom pressure [Pa]",
                min_value=30000.0,
                max_value=120000.0,
                value=101325.0,
                step=100.0,
            )

    include_psychrometrics, include_solar = page_derivation_flags(page)
    _ensure_analysis_dependencies(
        include_solar=include_solar,
        include_comparison=(page == "Compare Climates"),
    )
    payload = active_file.payload
    epw, full_df, issues = load_epw_from_bytes(
        active_file.name,
        payload,
        pressure_mode,
        custom_pressure,
        include_psychrometrics=include_psychrometrics,
        include_solar=include_solar,
    )

    if pressure_mode == "Normal pressure: 101325 Pa":
        active_pressure = DEFAULT_PRESSURE_PA
    elif pressure_mode == "Altitude-derived standard atmosphere pressure":
        active_pressure = pressure_from_altitude_m(epw.location.elevation_m)
    elif pressure_mode == "Custom constant pressure":
        active_pressure = float(custom_pressure or DEFAULT_PRESSURE_PA)
    else:
        valid_pressure = full_df["atmospheric_station_pressure_pa"].dropna()
        active_pressure = float(valid_pressure.median()) if not valid_pressure.empty else DEFAULT_PRESSURE_PA

    if page == "Time Series and Overlay":
        # This page owns an exact date/hour/minute viewport. Applying the global
        # month/hour sidebar filter as well would create two conflicting time
        # filters, so it starts from the complete loaded source calendar.
        filtered_df = full_df
        st.session_state["_active_filtered_export_df"] = full_df
    else:
        filtered_df = sidebar_filters(full_df)
        if filtered_df.empty:
            st.warning("The current filters remove all data. Adjust the month or hour filter.")
            return

    st.sidebar.markdown("### Current climate")
    st.sidebar.write(f"**{epw.location.city}, {epw.location.country}**")
    st.sidebar.caption(epw.name)
    st.sidebar.write(f"Rows in current view: {len(filtered_df):,}")
    with st.sidebar.expander("Data provenance", expanded=False):
        st.caption(active_file.source)
        if pressure_mode == "EPW station pressure with fallback median":
            st.caption(f"Pressure: hourly EPW station values; fallback median {active_pressure:,.0f} Pa")
        else:
            st.caption(f"Calculation pressure: {active_pressure:,.0f} Pa")

    if page == "Overview":
        render_overview(epw, filtered_df, full_df, issues)
    elif page == "Temperature":
        render_temperature(filtered_df)
    elif page == "Humidity and Psychrometrics":
        render_humidity(filtered_df, pressure_pa=active_pressure)
    elif page == "Solar and Radiation":
        render_solar(filtered_df)
    elif page == "Wind and Ventilation":
        render_wind(filtered_df)
    elif page == "Sky and Daylight":
        render_sky_daylight(filtered_df)
    elif page == "Precipitation and Snow":
        render_precipitation(filtered_df)
    elif page == "Time Series and Overlay":
        render_time_series_overlay(full_df)
    elif page == "Natural Ventilation":
        render_natural_ventilation(filtered_df, pressure_pa=active_pressure)
    elif page == "HVAC and Passive Design":
        render_hvac_passive(filtered_df)
    elif page == "Compare Climates":
        render_compare_climates(active_file, pressure_mode, custom_pressure, active_pressure)
    else:
        render_data_quality(epw, full_df, issues)


if __name__ == "__main__":
    main()
