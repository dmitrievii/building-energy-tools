from __future__ import annotations

from pathlib import Path


APP = Path("tools/climate_analyzer/app.py")
WORKFLOW = Path(".github/workflows/web-0.9-lazy-import-remediation.yml")
PATCHER = Path("deployment/apply_web09_lazy_import_patch.py")


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = APP.read_text(encoding="utf-8")

    eager_start = "\nimport folium\n"
    ui_start = "\nfrom epw_climate_analyzer.ui_contract import ("
    if text.count(eager_start) != 1 or text.count(ui_start) != 1:
        raise SystemExit("Eager import boundaries are not unique")
    start = text.index(eager_start)
    end = text.index(ui_start)
    if end <= start:
        raise SystemExit("Unexpected import block ordering")
    text = text[:start] + "\nimport streamlit as st\n" + text[end:]

    helper_marker = ")\n\n\nVARIABLES = {"
    helpers = r''')


_MAP_DEPENDENCIES_LOADED = False
_ANALYSIS_DEPENDENCIES_LOADED = False
_SOLAR_DEPENDENCIES_LOADED = False
_COMPARISON_DEPENDENCIES_LOADED = False


def _ensure_map_dependencies() -> None:
    """Load map/catalog dependencies only after the user selects Find climate."""
    global _MAP_DEPENDENCIES_LOADED
    global pd, folium, FastMarkerCluster, MarkerCluster, st_folium
    global download_station_epw, filter_station_catalog
    global catalog_runtime_summary, load_production_station_catalog, station_provenance_text

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
        station_provenance_text,
    )
    _MAP_DEPENDENCIES_LOADED = True


def _ensure_analysis_dependencies(*, include_solar: bool, include_comparison: bool) -> None:
    """Load scientific/plotting dependencies only after an EPW analysis is requested."""
    global _ANALYSIS_DEPENDENCIES_LOADED, _SOLAR_DEPENDENCIES_LOADED, _COMPARISON_DEPENDENCIES_LOADED
    global pd, px
    global aggregate_sum, duration_curve, filter_by_months_and_hours, threshold_count_by_period
    global duration_chart, heatmap_chart, histogram_chart, GIVONI_MILNE_ZONES
    global matrix_heatmap, month_hour_heatmap, givoni_milne_zone_table, monthly_box_chart
    global multi_line_monthly, orientation_bar_chart, percentile_band_chart, profile_ribbon_chart
    global psychrometric_chart, scatter_chart, stacked_monthly_bar, sun_path_chart
    global sun_position_diagram, threshold_bar_chart, wind_rose_chart
    global add_degree_metrics, comfort_condition, dehumidification_condition, economizer_condition
    global humidification_condition, natural_ventilation_condition, night_flushing_condition
    global passive_strategy_monthly, passive_strategy_table, rejection_reasons_for_nv, shading_condition
    global location_summary, parse_epw, quality_issues
    global data_quality_interpretation, degree_day_interpretation, hvac_interpretation
    global natural_ventilation_interpretation, psychrometric_interpretation, sky_interpretation
    global solar_interpretation, temperature_interpretation, variable_interpretation, wind_interpretation
    global DEFAULT_PRESSURE_PA, add_psychrometric_properties, pressure_from_altitude_m
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

    if not _ANALYSIS_DEPENDENCIES_LOADED:
        import pandas as pd
        import plotly.express as px
        from epw_climate_analyzer.aggregations import (
            aggregate_sum,
            duration_curve,
            filter_by_months_and_hours,
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


VARIABLES = {'''
    text = replace_exact(text, helper_marker, helpers, "lazy helper insertion")

    old_active = '''def set_active_climate_file(name: str, payload: bytes, source: str) -> None:
    """Store the selected EPW payload and open the summary view."""
    st.session_state["active_climate_file"] = ClimateFilePayload(name=name, payload=payload, source=source)
    queue_navigation(st.session_state, "Overview")


def get_active_climate_file() -> ClimateFilePayload | None:
    """Return the currently selected EPW payload from Streamlit session state."""
    value = st.session_state.get("active_climate_file")
    return value if isinstance(value, ClimateFilePayload) else None
'''
    new_active = '''def set_active_climate_file(name: str, payload: bytes, source: str) -> None:
    """Store the selected EPW payload and open the summary view."""
    from epw_climate_analyzer.climate_sources import ClimateFilePayload

    st.session_state["active_climate_file"] = ClimateFilePayload(name=name, payload=payload, source=source)
    queue_navigation(st.session_state, "Overview")


def get_active_climate_file() -> ClimateFilePayload | None:
    """Return the currently selected EPW payload from Streamlit session state."""
    value = st.session_state.get("active_climate_file")
    if value is None:
        return None
    from epw_climate_analyzer.climate_sources import ClimateFilePayload

    return value if isinstance(value, ClimateFilePayload) else None
'''
    text = replace_exact(text, old_active, new_active, "active climate helper")

    text = replace_exact(
        text,
        '''        return

    st.subheader("Find a climate from Climate.OneBuilding")
''',
        '''        return

    _ensure_map_dependencies()
    st.subheader("Find a climate from Climate.OneBuilding")
''',
        "Find climate lazy gate",
    )

    text = replace_exact(
        text,
        '''    include_psychrometrics, include_solar = page_derivation_flags(page)
    payload = active_file.payload
''',
        '''    include_psychrometrics, include_solar = page_derivation_flags(page)
    _ensure_analysis_dependencies(
        include_solar=include_solar,
        include_comparison=(page == "Compare Climates"),
    )
    payload = active_file.payload
''',
        "analysis lazy gate",
    )

    prefix = text.split("_MAP_DEPENDENCIES_LOADED = False", 1)[0]
    forbidden = (
        "\nimport folium\n",
        "\nimport pandas as pd\n",
        "\nimport plotly.express as px\n",
        "\nfrom streamlit_folium import st_folium\n",
        "\nfrom epw_climate_analyzer.charts import (",
        "\nfrom epw_climate_analyzer.comparison import (",
        "\nfrom epw_climate_analyzer.solar import (",
        "\nfrom epw_climate_analyzer.climate_sources import (",
    )
    for token in forbidden:
        if token in prefix:
            raise SystemExit(f"Eager dependency remains before lazy layer: {token!r}")

    APP.write_text(text, encoding="utf-8")
    print("WEB-0.9 lazy import patch applied")


if __name__ == "__main__":
    main()
