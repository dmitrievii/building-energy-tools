from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "tools/climate_analyzer/app.py"
PRECIP = ROOT / "tools/climate_analyzer/epw_climate_analyzer/precipitation.py"
CAPS = ROOT / "tools/climate_analyzer/epw_climate_analyzer/historical_capabilities.py"
PRESSURE_TEST = ROOT / "tools/climate_analyzer/tests/test_pressure_precipitation_contract.py"
NEW_TEST = ROOT / "tools/climate_analyzer/tests/test_geosphere_0_6_2_precip_map_variables.py"


PRECIP.write_text('''"""Precipitation and snow helpers for canonical climate analysis.

Liquid precipitation depth is an interval-extensive measurement quantity and is
summed over valid source records.  Snow depth is a state variable and is never
summed.  Event-record occurrence and physical duration are intentionally kept
separate: precipitation occurrence counts source records, while snow-cover
hours integrate the declared native source cadence.
"""

from __future__ import annotations

import math
import pandas as pd

from .aggregations import native_interval_hours

LIQUID_PRECIPITATION_COLUMN = "liquid_precipitation_depth_mm"
SNOW_DEPTH_COLUMN = "snow_depth_cm"
SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]
RESAMPLE_RULES = {
    "Daily": "D",
    "Weekly": "W",
    "Monthly": "ME",
}


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(index=df.index, dtype=float, name=column)
    return pd.to_numeric(df[column], errors="coerce").rename(column)


def _finite_or_none(value) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _aggregate_occurrence(indicator: pd.Series, df: pd.DataFrame, aggregation: str, label: str) -> pd.DataFrame:
    if aggregation == "Seasonal":
        frame = pd.DataFrame({"season": df.get("season"), label: indicator}, index=df.index)
        result = (
            frame.groupby("season", observed=False)[label]
            .sum(min_count=1)
            .reindex(SEASON_ORDER)
        )
    else:
        rule = RESAMPLE_RULES.get(aggregation)
        if rule is None:
            raise ValueError(f"Unsupported occurrence aggregation: {aggregation}")
        result = indicator.resample(rule).sum(min_count=1)
    return result.dropna().rename(label).to_frame()


def aggregate_liquid_precipitation(df: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    """Sum valid liquid-precipitation depth records by period."""
    values = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    if aggregation == "Seasonal":
        frame = pd.DataFrame({"season": df.get("season"), "value": values}, index=df.index)
        totals = (
            frame.groupby("season", observed=False)["value"]
            .sum(min_count=1)
            .reindex(SEASON_ORDER)
        )
    else:
        rule = RESAMPLE_RULES.get(aggregation)
        if rule is None:
            raise ValueError(f"Unsupported precipitation aggregation: {aggregation}")
        totals = values.resample(rule).sum(min_count=1)
    return totals.dropna().rename("precipitation_mm").to_frame()


def occurrence_records(
    df: pd.DataFrame,
    column: str,
    threshold: float,
    aggregation: str,
    *,
    inclusive: bool = True,
) -> pd.DataFrame:
    """Count valid source records meeting a threshold.

    This is deliberately a record-occurrence metric.  It must not be presented
    as rainfall duration because a precipitation-depth record describes an
    interval amount and does not identify how long rain occurred inside it.
    """
    values = _numeric_series(df, column)
    valid = values.notna()
    indicator = pd.Series(pd.NA, index=df.index, dtype="Float64", name="records")
    condition = values >= float(threshold) if inclusive else values > float(threshold)
    indicator.loc[valid] = condition.loc[valid].astype(float)
    return _aggregate_occurrence(indicator, df, aggregation, "records")


def occurrence_hours(
    df: pd.DataFrame,
    column: str,
    threshold: float,
    aggregation: str,
    *,
    inclusive: bool = True,
) -> pd.DataFrame:
    """Integrate physical hours for a thresholded state variable.

    Each valid source record contributes exactly the declared native interval.
    Missing timestamp gaps therefore contribute no duration.  This preserves
    hourly EPW numerics while correctly mapping a 10-minute GeoSphere record to
    one sixth of an hour.
    """
    values = _numeric_series(df, column)
    valid = values.notna()
    interval_h = float(native_interval_hours(df))
    indicator = pd.Series(pd.NA, index=df.index, dtype="Float64", name="hours")
    condition = values >= float(threshold) if inclusive else values > float(threshold)
    indicator.loc[valid] = condition.loc[valid].astype(float) * interval_h
    return _aggregate_occurrence(indicator, df, aggregation, "hours")


def precipitation_summary(df: pd.DataFrame, wet_threshold_mm: float = 0.1) -> dict[str, object]:
    """Return compact precipitation/snow diagnostics for the current filtered view."""
    liquid = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    snow = _numeric_series(df, SNOW_DEPTH_COLUMN)
    liquid_available = bool(liquid.notna().any())
    snow_available = bool(snow.notna().any())
    interval_h = float(native_interval_hours(df))

    return {
        "liquid_data_available": liquid_available,
        "snow_data_available": snow_available,
        "liquid_total_mm": _finite_or_none(liquid.sum(min_count=1)) if liquid_available else None,
        "precipitation_records": int((liquid >= wet_threshold_mm).sum()) if liquid_available else None,
        "max_record_precipitation_mm": _finite_or_none(liquid.max()) if liquid_available else None,
        "max_snow_depth_cm": _finite_or_none(snow.max()) if snow_available else None,
        "snow_cover_hours": _finite_or_none((snow > 0.0).sum() * interval_h) if snow_available else None,
    }
''', encoding='utf-8')


app = APP.read_text(encoding="utf-8")
app = app.replace(
    "    global aggregate_liquid_precipitation, occurrence_hours\n",
    "    global aggregate_liquid_precipitation, occurrence_hours, occurrence_records\n",
    1,
)
app = app.replace(
    "            aggregate_liquid_precipitation,\n            occurrence_hours,\n",
    "            aggregate_liquid_precipitation,\n            occurrence_hours,\n            occurrence_records,\n",
    1,
)

start = app.index("def render_geosphere_source() -> None:\n")
end = app.index("\ndef render_climate_file_source() -> None:\n", start)
new_geosphere = '''def render_geosphere_source() -> None:
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

    col_filter1, col_filter2 = st.columns([2, 1])
    search = col_filter1.text_input("Search GeoSphere station", value="", key="geosphere_station_search")
    states = sorted(value for value in catalog["state"].dropna().astype(str).unique().tolist() if value.strip())
    selected_states = col_filter2.multiselect("Federal states / regions", states, default=[], key="geosphere_station_states")
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
    st.caption(f"Visible GeoSphere stations after filters: {len(filtered):,} of {len(catalog):,}")
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

    selected_id = str(st.session_state.get("geosphere_selected_station_id", option_ids[0]))
    if selected_id not in option_ids:
        selected_id = option_ids[0]
        st.session_state["geosphere_selected_station_id"] = selected_id

    # GeoSphere uses the same persistent clustered Leaflet engine as Find climate.
    # Only the 530-provider-station table differs; pan/zoom remain browser-owned
    # and the map returns only an explicit station click to Streamlit.
    _ensure_map_dependencies()
    map_groups = filtered[["station_id", "name", "state", "latitude", "longitude", "elevation_m"]].copy()
    map_groups["station_group_id"] = map_groups["station_id"].astype(str)
    map_groups["country"] = "Austria"
    map_groups["region"] = map_groups["state"].fillna("").astype(str)
    map_groups["dataset"] = "GeoSphere klima-v2-10min"
    map_groups["climate_count"] = 1
    map_groups = map_groups.reset_index(drop=True)

    if "geosphere_map_view_epoch" not in st.session_state:
        st.session_state["geosphere_map_view_epoch"] = 0
    default_center = [float(map_groups["latitude"].mean()), float(map_groups["longitude"].mean())]
    initial_zoom = 7 if len(map_groups) > 25 else 9

    left, right = st.columns([2, 1])
    with left:
        map_reset_col, map_note_col = st.columns([1, 3])
        with map_reset_col:
            if st.button("Reset map", key="geosphere_reset_map"):
                st.session_state["geosphere_map_view_epoch"] = int(st.session_state.get("geosphere_map_view_epoch", 0)) + 1
                st.rerun()
        with map_note_col:
            st.caption("Clustered GeoSphere station map · click a station bubble to select it.")
        with st.expander("Advanced map settings", expanded=False):
            detail_zoom_threshold = st.slider(
                "Show individual stations from zoom level",
                min_value=6,
                max_value=12,
                value=int(st.session_state.get("geosphere_detail_zoom_threshold", 9)),
                key="geosphere_detail_zoom_threshold_slider",
                help=(
                    "The clustered overview remains visible at lower zoom levels. At this zoom level or closer, "
                    "the same Leaflet map reveals clickable individual station bubbles."
                ),
            )
            st.session_state["geosphere_detail_zoom_threshold"] = detail_zoom_threshold

        marker_payload = station_marker_payload(map_groups)
        base_map, marker_group = station_catalog_persistent_map_layers(
            map_groups,
            marker_payload=marker_payload,
            center=[47.5, 14.2],
            zoom=7,
            detail_zoom_threshold=int(st.session_state.get("geosphere_detail_zoom_threshold", 9)),
        )
        map_state = st_folium(
            base_map,
            feature_group_to_add=marker_group,
            height=560,
            use_container_width=True,
            returned_objects=["last_object_clicked_tooltip"],
            center=tuple(default_center),
            zoom=initial_zoom,
            key=f"geosphere_selectable_cluster_map_{int(st.session_state.get('geosphere_map_view_epoch', 0))}",
        )

    clicked_station = None
    if isinstance(map_state, dict):
        clicked_station = station_group_from_tooltip(map_groups, map_state.get("last_object_clicked_tooltip"))
    if clicked_station is not None:
        clicked_id = str(clicked_station["station_group_id"])
        if clicked_id in option_ids:
            selected_id = clicked_id
            st.session_state["geosphere_selected_station_id"] = selected_id

    station = station_by_id[selected_id]
    with right:
        st.markdown("#### Selected station")
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
        st.markdown("#### Manual station selection")
        manual_id = st.selectbox(
            "Search-result stations",
            option_ids,
            index=option_ids.index(selected_id),
            format_func=station_label,
            key="geosphere_manual_station_choice",
        )
        if st.button("Use station from list", key="geosphere_use_station_from_list"):
            st.session_state["geosphere_selected_station_id"] = manual_id
            st.rerun()

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

    st.markdown("#### Measured variables to load")
    st.caption(
        "Select the measured GeoSphere fields required for this load. The checkbox is the single source of selection state; "
        "analysis pages are still enabled only when the returned interval contains actual numeric observations."
    )
    variable_rows = pd.DataFrame(
        [
            {
                "Selected": True,
                "Measured variable": spec.description or spec.canonical_name,
                "Provider": name,
                "Canonical field": spec.canonical_name,
            }
            for name, spec in supported.items()
        ]
    )
    edited_variables = st.data_editor(
        variable_rows,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        disabled=["Measured variable", "Provider", "Canonical field"],
        column_config={
            "Selected": st.column_config.CheckboxColumn("Load", width="small"),
            "Measured variable": st.column_config.TextColumn("Measured variable", width="medium"),
            "Provider": st.column_config.TextColumn("Provider parameter", width="small"),
            "Canonical field": st.column_config.TextColumn("Canonical field", width="large"),
        },
        key="geosphere_variable_editor",
    )
    provider_parameters = tuple(
        edited_variables.loc[edited_variables["Selected"].fillna(False).astype(bool), "Provider"].astype(str).tolist()
    )
    st.caption("Source: GeoSphere Austria `klima-v2-10min` · CC BY 4.0 · DOI 10.60669/8fya-7x87")
    if not provider_parameters:
        st.warning("Select at least one measured GeoSphere variable to load.")
        return

    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(hours=23, minutes=50)
    canonical_variables = tuple(supported[name].canonical_name for name in provider_parameters)
    estimated = estimate_geosphere_datapoints(start_ts, end_ts, len(provider_parameters), 1)
    batches = plan_geosphere_queries(station.station_id, start_ts, end_ts, provider_parameters)
    st.caption(
        f"Requested interval: {selected_days} day(s), 10-minute source data, {len(provider_parameters)} selected measured variables. "
        f"Estimated provider datapoints: {estimated:,}; bounded API batches: {len(batches)}. "
        "There is no fixed one-year UI limit; long intervals are split into bounded provider requests."
    )
    if estimated > 2_000_000:
        st.warning(
            "This is a large historical request. It is valid and will be split into bounded API batches, but loading and "
            "browser analysis can take substantially longer. Selecting only the variables you need reduces transfer and memory use."
        )
    if "tl" not in provider_parameters:
        st.info(
            "Air temperature is not selected. Temperature and temperature-dependent psychrometric analyses will remain "
            "unavailable unless a later load contains measured temperature observations."
        )

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
'''
app = app[:start] + new_geosphere + app[end:]

start = app.index("def render_precipitation(df: pd.DataFrame) -> None:\n")
end = app.index("\ndef render_sky_daylight(df: pd.DataFrame) -> None:\n", start)
new_precip_ui = '''def render_precipitation(df: pd.DataFrame) -> None:
    """Render liquid-precipitation and snow-cover analysis from available source fields."""
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
        options.extend(["Snow depth explorer", "Snow-cover duration"])
    if not options:
        st.info("The loaded climate interval does not contain usable liquid-precipitation or snow-depth observations.")
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
            "Period totals sum valid interval precipitation-depth records. Missing source values and missing timestamp gaps are excluded rather than treated as zero.",
        )
    elif chart_group == "Precipitation-record occurrence":
        threshold = st.number_input("Precipitation-record threshold [mm]", min_value=0.0, value=0.1, step=0.1)
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        counts = occurrence_records(
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
            y="records",
            title=f"Precipitation-record occurrence ≥ {threshold:g} mm",
            labels={x_column: "Period", "records": "Source records meeting threshold"},
        )
        fig.update_traces(marker_color=metric_color("liquid_precipitation_depth_mm"))
        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Source records meeting threshold")
        render_plot(
            fig,
            "Counts source precipitation-depth records meeting the selected threshold. This is deliberately a record-occurrence metric, not exact rainfall duration: an interval precipitation amount does not reveal how long rain occurred inside that source interval.",
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
            title="Snow-cover duration",
            labels={x_column: "Period", "hours": "Observed hours with snow depth > 0 cm"},
        )
        fig.update_traces(marker_color=metric_color("snow_depth_cm"))
        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Observed snow-cover hours")
        render_plot(
            fig,
            "Snow depth is a state variable. Each valid record with snow depth greater than zero contributes exactly one native source interval: 1 h for hourly EPW and 1/6 h for 10-minute GeoSphere data. Missing timestamp gaps contribute no duration.",
        )
'''
app = app[:start] + new_precip_ui + app[end:]

old_dispatch = '''    elif page == "Wind and Ventilation":
        render_historical_wind(filtered_df)
    elif page == "Time Series and Overlay":
        render_time_series_overlay(full_df)
'''
new_dispatch = '''    elif page == "Wind and Ventilation":
        render_historical_wind(filtered_df)
    elif page == "Precipitation and Snow":
        st.caption(
            "Liquid precipitation is an interval-depth measurement; threshold occurrence therefore counts source records, not rainfall duration. "
            "Snow-cover duration integrates the declared native cadence, and missing timestamp gaps contribute no observed time."
        )
        render_precipitation(filtered_df)
    elif page == "Time Series and Overlay":
        render_time_series_overlay(full_df)
'''
if old_dispatch not in app:
    raise RuntimeError("historical dispatch block not found")
app = app.replace(old_dispatch, new_dispatch, 1)
APP.write_text(app, encoding="utf-8")


caps = CAPS.read_text(encoding="utf-8")
old_caps = '''    has_solar = has_numeric_observations(df, "global_horizontal_radiation_wh_m2") or has_numeric_observations(
        df, "diffuse_horizontal_radiation_wh_m2"
    )

    if has_temperature:
'''
new_caps = '''    has_solar = has_numeric_observations(df, "global_horizontal_radiation_wh_m2") or has_numeric_observations(
        df, "diffuse_horizontal_radiation_wh_m2"
    )
    has_precipitation_or_snow = has_numeric_observations(df, "liquid_precipitation_depth_mm") or has_numeric_observations(
        df, "snow_depth_cm"
    )

    if has_temperature:
'''
if old_caps not in caps:
    raise RuntimeError("historical capability declaration block not found")
caps = caps.replace(old_caps, new_caps, 1)
old_caps2 = '''    if has_wind:
        pages.append("Wind and Ventilation")
    pages.extend(["Time Series and Overlay", "Data Quality"])
'''
new_caps2 = '''    if has_wind:
        pages.append("Wind and Ventilation")
    if has_precipitation_or_snow:
        pages.append("Precipitation and Snow")
    pages.extend(["Time Series and Overlay", "Data Quality"])
'''
if old_caps2 not in caps:
    raise RuntimeError("historical capability page block not found")
caps = caps.replace(old_caps2, new_caps2, 1)
CAPS.write_text(caps, encoding="utf-8")


pressure_test = PRESSURE_TEST.read_text(encoding="utf-8")
pressure_test = pressure_test.replace(
    '''from epw_climate_analyzer.precipitation import (\n    aggregate_liquid_precipitation,\n    occurrence_hours,\n)''',
    '''from epw_climate_analyzer.precipitation import (\n    aggregate_liquid_precipitation,\n    occurrence_hours,\n    occurrence_records,\n)''',
    1,
)
pressure_test = pressure_test.replace(
    'wet = occurrence_hours(df, "liquid_precipitation_depth_mm", 0.1, "Monthly")',
    'wet = occurrence_records(df, "liquid_precipitation_depth_mm", 0.1, "Monthly")',
    1,
)
PRESSURE_TEST.write_text(pressure_test, encoding="utf-8")


NEW_TEST.write_text('''from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.historical_capabilities import available_historical_pages
from epw_climate_analyzer.precipitation import occurrence_hours, occurrence_records, precipitation_summary

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class GeoSphere062PrecipitationSnowTests(unittest.TestCase):
    @staticmethod
    def frame(freq: str, periods: int = 6) -> pd.DataFrame:
        idx = pd.date_range("2026-01-01T00:00:00Z", periods=periods, freq=freq)
        frame = pd.DataFrame(
            {
                "liquid_precipitation_depth_mm": [0.2] * periods,
                "snow_depth_cm": [2.0] * periods,
                "season": ["Winter"] * periods,
            },
            index=idx,
        )
        return frame

    def test_snow_cover_duration_is_cadence_aware(self) -> None:
        ten = self.frame("10min")
        ten.attrs["canonical_native_interval_minutes"] = 10
        hourly = self.frame("1h")
        hourly.attrs["canonical_native_interval_minutes"] = 60
        self.assertAlmostEqual(float(occurrence_hours(ten, "snow_depth_cm", 0.0, "Daily", inclusive=False).iloc[0, 0]), 1.0)
        self.assertAlmostEqual(float(occurrence_hours(hourly, "snow_depth_cm", 0.0, "Daily", inclusive=False).iloc[0, 0]), 6.0)
        self.assertAlmostEqual(float(precipitation_summary(ten)["snow_cover_hours"]), 1.0)
        self.assertAlmostEqual(float(precipitation_summary(hourly)["snow_cover_hours"]), 6.0)

    def test_precipitation_occurrence_remains_record_count_not_duration(self) -> None:
        ten = self.frame("10min")
        ten.attrs["canonical_native_interval_minutes"] = 10
        counts = occurrence_records(ten, "liquid_precipitation_depth_mm", 0.1, "Daily")
        self.assertEqual(float(counts.iloc[0, 0]), 6.0)
        self.assertEqual(counts.columns.tolist(), ["records"])

    def test_missing_timestamp_gap_adds_no_snow_duration(self) -> None:
        idx = pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:10:00Z",
            "2026-01-01T01:00:00Z",
        ])
        frame = pd.DataFrame({"snow_depth_cm": [1.0, 1.0, 1.0], "season": ["Winter"] * 3}, index=idx)
        frame.attrs["canonical_native_interval_minutes"] = 10
        hours = occurrence_hours(frame, "snow_depth_cm", 0.0, "Daily", inclusive=False)
        self.assertAlmostEqual(float(hours.iloc[0, 0]), 0.5)

    def test_historical_precipitation_page_is_observation_gated(self) -> None:
        rr = pd.DataFrame({"liquid_precipitation_depth_mm": [0.0, 0.2]}, index=pd.date_range("2026-01-01", periods=2, freq="10min", tz="UTC"))
        sh = pd.DataFrame({"snow_depth_cm": [0.0, 1.0]}, index=rr.index)
        empty = pd.DataFrame({"liquid_precipitation_depth_mm": [pd.NA, pd.NA]}, index=rr.index)
        self.assertIn("Precipitation and Snow", available_historical_pages(rr))
        self.assertIn("Precipitation and Snow", available_historical_pages(sh))
        self.assertNotIn("Precipitation and Snow", available_historical_pages(empty))


class GeoSphere062UiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_variable_selection_is_one_editable_checkbox_table(self) -> None:
        self.assertIn('st.markdown("#### Measured variables to load")', self.source)
        self.assertIn("edited_variables = st.data_editor(", self.source)
        self.assertIn('st.column_config.CheckboxColumn("Load"', self.source)
        self.assertNotIn('st.multiselect(\n            "Measured variables to load"', self.source)
        self.assertNotIn('with st.expander("Measured variables and provenance"', self.source)

    def test_geosphere_map_reuses_find_climate_persistent_map_engine(self) -> None:
        self.assertIn("GeoSphere uses the same persistent clustered Leaflet engine as Find climate", self.source)
        self.assertIn("station_catalog_persistent_map_layers(\n            map_groups", self.source)
        self.assertIn('returned_objects=["last_object_clicked_tooltip"]', self.source)
        self.assertIn('key=f"geosphere_selectable_cluster_map_', self.source)
        self.assertIn('tiles="OpenStreetMap"', self.source)

    def test_precipitation_ui_keeps_records_and_hours_semantically_separate(self) -> None:
        self.assertIn("counts = occurrence_records(", self.source)
        self.assertIn('y="records"', self.source)
        self.assertIn("counts = occurrence_hours(df, \"snow_depth_cm\"", self.source)
        self.assertIn("10-minute GeoSphere data", self.source)
        self.assertIn('elif page == "Precipitation and Snow":', self.source)


if __name__ == "__main__":
    unittest.main()
''', encoding='utf-8')

print("CLIMATE_GEOSPHERE_0_6_2_PATCH_APPLIED")
