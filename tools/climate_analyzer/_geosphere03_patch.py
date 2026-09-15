from pathlib import Path

root = Path(__file__).resolve().parents[2]
app_path = root / "tools/climate_analyzer/app.py"
ui_path = root / "tools/climate_analyzer/epw_climate_analyzer/ui_contract.py"
historical_path = root / "tools/climate_analyzer/epw_climate_analyzer/historical.py"
test_path = root / "tools/climate_analyzer/tests/test_geosphere_public_integration.py"
doc_path = root / "tools/climate_analyzer/CLIMATE_GEOSPHERE_0_3.md"

# ---------------------------------------------------------------------------
# Provider-neutral historical analysis preparation.
# ---------------------------------------------------------------------------
historical_path.write_text('''"""Provider-neutral preparation helpers for real historical climate datasets.

Historical observations keep their real timezone-aware timestamps. This module
adds only the calendar helper columns required by existing analysis views and,
when requested, derives psychrometric quantities from canonical primary
observations. It does not convert observations to an EPW typical-year calendar.
"""

from __future__ import annotations

import pandas as pd

from .climate_model import CanonicalClimateDataset
from .psychrometrics import DEFAULT_PRESSURE_PA, add_psychrometric_properties


def add_historical_calendar_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add analysis calendar columns without changing real historical timestamps."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Historical climate data require a pandas DatetimeIndex.")
    attrs = dict(df.attrs)
    data = df.copy()
    index = pd.DatetimeIndex(data.index)
    data["year"] = index.year
    data["date"] = index.date
    data["month_index"] = index.month
    data["month_name"] = index.month_name().str.slice(stop=3)
    data["day_of_year"] = index.dayofyear
    data["week_of_year"] = index.isocalendar().week.astype(int)
    data["hour_of_day"] = index.hour
    data["season"] = data["month_index"].map(
        {
            12: "Winter", 1: "Winter", 2: "Winter",
            3: "Spring", 4: "Spring", 5: "Spring",
            6: "Summer", 7: "Summer", 8: "Summer",
            9: "Autumn", 10: "Autumn", 11: "Autumn",
        }
    )
    data.attrs.update(attrs)
    return data


def prepare_historical_analysis_frame(
    dataset: CanonicalClimateDataset,
    *,
    include_psychrometrics: bool = False,
    fallback_pressure_pa: float = DEFAULT_PRESSURE_PA,
) -> pd.DataFrame:
    """Prepare a canonical historical dataset for source-agnostic analysis views."""
    data = add_historical_calendar_columns(dataset.data)
    if include_psychrometrics:
        required = {"dry_bulb_temperature_c", "relative_humidity_pct"}
        missing = sorted(required - set(data.columns))
        if missing:
            raise ValueError(
                "Psychrometric analysis requires canonical variables: " + ", ".join(missing)
            )
        if "atmospheric_station_pressure_pa" not in data.columns:
            data["atmospheric_station_pressure_pa"] = float(fallback_pressure_pa)
        data = add_psychrometric_properties(data, fallback_pressure_pa=float(fallback_pressure_pa))
        data.attrs.setdefault("canonical_native_interval_minutes", dataset.temporal.native_interval_minutes)
        data.attrs.setdefault("canonical_calendar_mode", dataset.temporal.calendar_mode)
        data.attrs.setdefault("canonical_timezone_name", dataset.temporal.timezone_name)
    return data
''', encoding="utf-8")

# ---------------------------------------------------------------------------
# UI contract copy: product is no longer EPW-only at the source boundary.
# ---------------------------------------------------------------------------
ui = ui_path.read_text(encoding="utf-8")
old_intro = '''APP_INTRO = (\n    "Explore EPW weather data for temperature, moisture, solar radiation, wind, precipitation, "\n    "passive-design potential and early HVAC decision support."\n)'''
new_intro = '''APP_INTRO = (\n    "Explore EPW weather files and measured station data for temperature, moisture, solar radiation, wind, precipitation, "\n    "passive-design potential and early HVAC decision support."\n)'''
if old_intro not in ui:
    raise SystemExit("APP_INTRO anchor not found")
ui_path.write_text(ui.replace(old_intro, new_intro, 1), encoding="utf-8")

# ---------------------------------------------------------------------------
# Streamlit application integration.
# ---------------------------------------------------------------------------
app = app_path.read_text(encoding="utf-8")

app = app.replace(
'''_MAP_DEPENDENCIES_LOADED = False\n_ANALYSIS_DEPENDENCIES_LOADED = False\n_SOLAR_DEPENDENCIES_LOADED = False\n_COMPARISON_DEPENDENCIES_LOADED = False\n''',
'''_MAP_DEPENDENCIES_LOADED = False\n_GEOSPHERE_DEPENDENCIES_LOADED = False\n_ANALYSIS_DEPENDENCIES_LOADED = False\n_SOLAR_DEPENDENCIES_LOADED = False\n_COMPARISON_DEPENDENCIES_LOADED = False\n''',
1,
)

map_end = '''    _MAP_DEPENDENCIES_LOADED = True\n\n\ndef _ensure_analysis_dependencies'''
geosphere_loader = '''    _MAP_DEPENDENCIES_LOADED = True\n\n\ndef _ensure_geosphere_dependencies() -> None:\n    """Load GeoSphere adapter dependencies only when that source is selected."""\n    global _GEOSPHERE_DEPENDENCIES_LOADED\n    global pd\n    global fetch_geosphere_metadata, geosphere_station_catalog, parse_geosphere_stations\n    global supported_geosphere_parameter_mapping, fetch_geosphere_station_dataset\n    global plan_geosphere_queries, estimate_geosphere_datapoints\n\n    if _GEOSPHERE_DEPENDENCIES_LOADED:\n        return\n\n    import pandas as pd\n    from epw_climate_analyzer.geosphere import (\n        estimate_request_datapoints as estimate_geosphere_datapoints,\n        fetch_metadata as fetch_geosphere_metadata,\n        fetch_station_dataset as fetch_geosphere_station_dataset,\n        parse_stations as parse_geosphere_stations,\n        plan_data_queries as plan_geosphere_queries,\n        station_catalog as geosphere_station_catalog,\n        supported_parameter_mapping as supported_geosphere_parameter_mapping,\n    )\n    _GEOSPHERE_DEPENDENCIES_LOADED = True\n\n\ndef _ensure_analysis_dependencies'''
if map_end not in app:
    raise SystemExit("map dependency end anchor not found")
app = app.replace(map_end, geosphere_loader, 1)

old_active_block = '''def set_active_climate_file(name: str, payload: bytes, source: str) -> None:\n    """Store the selected EPW payload and open the summary view."""\n    from epw_climate_analyzer.climate_sources import ClimateFilePayload\n\n    st.session_state["active_climate_file"] = ClimateFilePayload(name=name, payload=payload, source=source)\n    queue_navigation(st.session_state, "Overview")\n\n\ndef get_active_climate_file() -> ClimateFilePayload | None:\n    """Return the currently selected EPW payload from Streamlit session state."""\n    value = st.session_state.get("active_climate_file")\n    if value is None:\n        return None\n    from epw_climate_analyzer.climate_sources import ClimateFilePayload\n\n    return value if isinstance(value, ClimateFilePayload) else None\n\n\ndef clear_active_climate_file() -> None:\n    """Remove the currently selected climate file and reset navigation."""\n    st.session_state.pop("active_climate_file", None)\n    queue_navigation_reset(st.session_state)\n'''
new_active_block = '''def set_active_climate_file(name: str, payload: bytes, source: str) -> None:\n    """Store the selected EPW payload and open the summary view."""\n    from epw_climate_analyzer.climate_sources import ClimateFilePayload\n\n    st.session_state["active_climate_file"] = ClimateFilePayload(name=name, payload=payload, source=source)\n    st.session_state.pop("active_canonical_climate", None)\n    queue_navigation(st.session_state, "Overview")\n\n\ndef set_active_canonical_climate(dataset: object) -> None:\n    """Store a provider-neutral canonical historical dataset for analysis."""\n    from epw_climate_analyzer.climate_model import CanonicalClimateDataset\n\n    if not isinstance(dataset, CanonicalClimateDataset):\n        raise TypeError("Expected CanonicalClimateDataset for historical climate activation.")\n    st.session_state["active_canonical_climate"] = dataset\n    st.session_state.pop("active_climate_file", None)\n    queue_navigation(st.session_state, "Temperature")\n\n\ndef get_active_climate_file() -> ClimateFilePayload | None:\n    """Return the currently selected EPW payload from Streamlit session state."""\n    value = st.session_state.get("active_climate_file")\n    if value is None:\n        return None\n    from epw_climate_analyzer.climate_sources import ClimateFilePayload\n\n    return value if isinstance(value, ClimateFilePayload) else None\n\n\ndef get_active_canonical_climate():\n    """Return the active provider-neutral historical dataset, if any."""\n    value = st.session_state.get("active_canonical_climate")\n    if value is None:\n        return None\n    from epw_climate_analyzer.climate_model import CanonicalClimateDataset\n\n    return value if isinstance(value, CanonicalClimateDataset) else None\n\n\ndef clear_active_climate_file() -> None:\n    """Remove every active climate source and reset navigation."""\n    st.session_state.pop("active_climate_file", None)\n    st.session_state.pop("active_canonical_climate", None)\n    queue_navigation_reset(st.session_state)\n'''
if old_active_block not in app:
    raise SystemExit("active source block not found")
app = app.replace(old_active_block, new_active_block, 1)

# Cache provider metadata separately from the global EPW catalog cache.
cache_anchor = '''@st.cache_data(show_spinner=False)\ndef _cached_station_catalog_by_identity'''
cache_insert = '''@st.cache_data(show_spinner=False, ttl=3600)\ndef cached_geosphere_metadata() -> dict:\n    """Cache current GeoSphere metadata for one hour within a user session/runtime."""\n    from epw_climate_analyzer.geosphere import fetch_metadata\n\n    return fetch_metadata()\n\n\n@st.cache_data(show_spinner=False)\ndef _cached_station_catalog_by_identity'''
if cache_anchor not in app:
    raise SystemExit("catalog cache anchor not found")
app = app.replace(cache_anchor, cache_insert, 1)

# Insert a dedicated source selector that returns a canonical dataset, not EPW bytes.
source_anchor = '''def render_climate_file_source() -> None:\n'''
geosphere_source = '''def render_geosphere_source() -> None:\n    """Render GeoSphere Austria historical station selection and bounded loading."""\n    _ensure_geosphere_dependencies()\n    st.subheader("GeoSphere Austria — measured historical station data")\n    st.caption(\n        "Quality-checked `klima-v2-10min` observations are loaded directly from the official GeoSphere Austria Dataset API. "\n        "Timestamps remain real UTC historical timestamps; the data are not converted to an EPW typical year."\n    )\n    try:\n        metadata = cached_geosphere_metadata()\n        supported = supported_geosphere_parameter_mapping(metadata)\n        stations = parse_geosphere_stations(metadata)\n        catalog = geosphere_station_catalog(metadata)\n    except Exception as exc:\n        st.error(f"GeoSphere metadata could not be loaded or validated: {exc}")\n        return\n\n    search = st.text_input("Search GeoSphere station", value="", key="geosphere_station_search")\n    states = sorted(value for value in catalog["state"].dropna().astype(str).unique().tolist() if value.strip())\n    selected_states = st.multiselect("Federal states / regions", states, default=[], key="geosphere_station_states")\n    filtered = catalog.copy()\n    if search.strip():\n        needle = search.strip().lower()\n        mask = (\n            filtered["name"].astype(str).str.lower().str.contains(needle, regex=False)\n            | filtered["station_id"].astype(str).str.lower().str.contains(needle, regex=False)\n            | filtered["state"].astype(str).str.lower().str.contains(needle, regex=False)\n        )\n        filtered = filtered[mask]\n    if selected_states:\n        filtered = filtered[filtered["state"].isin(selected_states)]\n    if filtered.empty:\n        st.warning("No GeoSphere stations match the current filter.")\n        return\n\n    station_by_id = {station.station_id: station for station in stations}\n    option_ids = [str(value) for value in filtered["station_id"].tolist() if str(value) in station_by_id]\n    if not option_ids:\n        st.error("GeoSphere metadata contain no selectable stations after normalization.")\n        return\n\n    def station_label(station_id: str) -> str:\n        station = station_by_id[station_id]\n        state = f" — {station.state}" if station.state else ""\n        return f"{station.name}{state} — ID {station.station_id}"\n\n    selected_id = st.selectbox(\n        "Station",\n        option_ids,\n        format_func=station_label,\n        key="geosphere_station_id",\n    )\n    station = station_by_id[selected_id]\n    st.dataframe(\n        pd.DataFrame(\n            {\n                "Field": ["Station", "ID", "Region", "Latitude", "Longitude", "Elevation", "Provider validity"],\n                "Value": [\n                    station.name, station.station_id, station.state,\n                    f"{station.latitude:.5f}", f"{station.longitude:.5f}",\n                    f"{station.elevation_m:.0f} m" if station.elevation_m is not None else "",\n                    f"{station.valid_from or 'unknown'} … {station.valid_to or 'unknown'}",\n                ],\n            }\n        ),\n        hide_index=True,\n        use_container_width=True,\n    )\n\n    today = pd.Timestamp.now(tz="UTC").date()\n    parsed_from = pd.to_datetime(station.valid_from, errors="coerce")\n    parsed_to = pd.to_datetime(station.valid_to, errors="coerce")\n    min_date = parsed_from.date() if pd.notna(parsed_from) else pd.Timestamp("1900-01-01").date()\n    provider_max = parsed_to.date() if pd.notna(parsed_to) else today\n    max_date = min(provider_max, today)\n    if max_date < min_date:\n        st.error("The station validity interval does not overlap the available historical date range.")\n        return\n    default_end = max_date\n    default_start = max(min_date, (pd.Timestamp(default_end) - pd.Timedelta(days=30)).date())\n    c1, c2 = st.columns(2)\n    start_date = c1.date_input(\n        "From date (UTC)", value=default_start, min_value=min_date, max_value=max_date, key="geosphere_start_date"\n    )\n    end_date = c2.date_input(\n        "Through date (UTC)", value=default_end, min_value=min_date, max_value=max_date, key="geosphere_end_date"\n    )\n    if end_date < start_date:\n        st.error("GeoSphere end date must not be earlier than start date.")\n        return\n    selected_days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days + 1\n    if selected_days > 366:\n        st.error("The public beta currently allows at most 366 days per GeoSphere load. Choose a shorter interval.")\n        return\n\n    start_ts = pd.Timestamp(start_date, tz="UTC")\n    end_ts = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(hours=23, minutes=50)\n    provider_parameters = tuple(supported.keys())\n    if "tl" not in provider_parameters:\n        st.error("Current GeoSphere metadata do not expose the required air-temperature parameter `tl`.")\n        return\n    canonical_variables = tuple(spec.canonical_name for spec in supported.values())\n    estimated = estimate_geosphere_datapoints(start_ts, end_ts, len(provider_parameters), 1)\n    batches = plan_geosphere_queries(station.station_id, start_ts, end_ts, provider_parameters)\n    st.caption(\n        f"Requested interval: {selected_days} day(s), 10-minute source data, {len(provider_parameters)} supported measured variables. "\n        f"Estimated provider datapoints: {estimated:,}; bounded API batches: {len(batches)}."\n    )\n    with st.expander("Measured variables and provenance", expanded=False):\n        variable_rows = [\n            {"Provider": name, "Canonical field": spec.canonical_name, "Description": spec.description}\n            for name, spec in supported.items()\n        ]\n        st.dataframe(pd.DataFrame(variable_rows), hide_index=True, use_container_width=True)\n        st.caption("Source: GeoSphere Austria `klima-v2-10min` · CC BY 4.0 · DOI 10.60669/8fya-7x87")\n\n    if st.button("Load measured GeoSphere interval", type="primary", key="load_geosphere_interval"):\n        try:\n            with st.spinner(f"Loading {len(batches)} bounded GeoSphere request batch(es)..."):\n                dataset = fetch_geosphere_station_dataset(\n                    station=station,\n                    start=start_ts,\n                    end=end_ts,\n                    metadata=metadata,\n                    canonical_variables=canonical_variables,\n                )\n            set_active_canonical_climate(dataset)\n            st.rerun()\n        except Exception as exc:\n            st.error(f"GeoSphere station-data load failed: {exc}")\n\n\ndef render_climate_file_source() -> None:\n'''
if source_anchor not in app:
    raise SystemExit("source render anchor not found")
app = app.replace(source_anchor, geosphere_source, 1)

# Source page copy and source-mode selector.
app = app.replace(
'''        "Start with an EPW weather file from your computer or select a climate from the reviewed "\n        "Climate.OneBuilding station catalog. No building model is required."\n    )\n\n    active = get_active_climate_file()\n    if active is not None:\n        st.success(f"Current climate: {active.name}")\n        with st.expander("Data source details", expanded=False):\n            st.caption(active.source)\n''',
'''        "Start with an EPW weather file, select a reviewed Climate.OneBuilding climate, or load measured "\n        "historical station observations from GeoSphere Austria. No building model is required."\n    )\n\n    active = get_active_climate_file()\n    active_historical = get_active_canonical_climate()\n    if active is not None or active_historical is not None:\n        active_name = active.name if active is not None else active_historical.display_name\n        st.success(f"Current climate: {active_name}")\n        with st.expander("Data source details", expanded=False):\n            if active is not None:\n                st.caption(active.source)\n            else:\n                st.caption(f"{active_historical.provenance.provider} | {active_historical.provenance.dataset}")\n                st.caption(active_historical.provenance.source_reference)\n''',
1,
)
app = app.replace(
'''        ["Upload EPW", "Find climate"],\n''',
'''        ["Upload EPW", "Find climate", "GeoSphere Austria"],\n''',
1,
)
app = app.replace(
'''        return\n\n    _ensure_map_dependencies()\n    st.subheader("Find a climate from Climate.OneBuilding")\n''',
'''        return\n\n    if source_mode == "GeoSphere Austria":\n        render_geosphere_source()\n        return\n\n    _ensure_map_dependencies()\n    st.subheader("Find a climate from Climate.OneBuilding")\n''',
1,
)

# Historical-safe versions hide record-count-as-hour analyses until those routes
# become explicitly cadence-aware.
app = app.replace(
'''def render_temperature(df: pd.DataFrame) -> None:\n    """Render temperature-analysis charts."""\n    st.header("Temperature and extremes")\n    chart_group = st.selectbox("Analysis type", ["Temperature variable explorer", "Threshold hours", "Degree days", "Extreme days"])\n''',
'''def render_temperature(df: pd.DataFrame, *, interval_count_metrics: bool = True) -> None:\n    """Render temperature-analysis charts."""\n    st.header("Temperature and extremes")\n    chart_options = ["Temperature variable explorer", "Threshold hours", "Degree days", "Extreme days"]\n    if not interval_count_metrics:\n        chart_options.remove("Threshold hours")\n    chart_group = st.selectbox("Analysis type", chart_options)\n''',
1,
)
app = app.replace(
'''def render_humidity(df: pd.DataFrame, pressure_pa: float) -> None:\n    """Render humidity and psychrometric charts."""\n    st.header("Humidity and psychrometrics")\n    chart_group = st.selectbox(\n        "Analysis type",\n        ["Humidity variable explorer", "Psychrometric chart", "Moisture thresholds", "Psychrometric scatter relationships"],\n    )\n''',
'''def render_humidity(df: pd.DataFrame, pressure_pa: float, *, interval_count_metrics: bool = True) -> None:\n    """Render humidity and psychrometric charts."""\n    st.header("Humidity and psychrometrics")\n    chart_options = ["Humidity variable explorer", "Psychrometric chart", "Moisture thresholds", "Psychrometric scatter relationships"]\n    if not interval_count_metrics:\n        chart_options.remove("Moisture thresholds")\n    chart_group = st.selectbox("Analysis type", chart_options)\n''',
1,
)

# Time-series controls must preserve timezone awareness for real UTC data.
old_time = '''    start = pd.Timestamp.combine(start_date, start_time)\n    selected_end = pd.Timestamp.combine(end_date, end_time)\n    # "Through" denotes the selected source interval, so the internal viewport\n'''
new_time = '''    start = pd.Timestamp.combine(start_date, start_time)\n    selected_end = pd.Timestamp.combine(end_date, end_time)\n    if index.tz is not None:\n        start = start.tz_localize(index.tz)\n        selected_end = selected_end.tz_localize(index.tz)\n    # "Through" denotes the selected source interval, so the internal viewport\n'''
if old_time not in app:
    raise SystemExit("time-series timezone anchor not found")
app = app.replace(old_time, new_time, 1)

# Source-neutral diagnostics and canonical run path.
main_anchor = '''def main() -> None:\n'''
canonical_runner = '''def render_canonical_data_quality(dataset, df: pd.DataFrame) -> None:\n    """Render diagnostics/provenance for a provider-neutral historical dataset."""\n    st.header("Data quality and source metadata")\n    location = dataset.location\n    st.subheader("Station")\n    st.dataframe(\n        pd.DataFrame(\n            {\n                "Field": ["Station", "Station ID", "Region", "Country", "Latitude", "Longitude", "Elevation"],\n                "Value": [\n                    location.city, location.station_id, location.state, location.country,\n                    location.latitude, location.longitude, location.elevation_m,\n                ],\n            }\n        ),\n        hide_index=True,\n        use_container_width=True,\n    )\n    st.subheader("Temporal/source contract")\n    st.dataframe(\n        pd.DataFrame(\n            {\n                "Field": ["Provider", "Dataset", "Calendar mode", "Native interval", "Timezone", "First timestamp", "Last timestamp", "Records"],\n                "Value": [\n                    dataset.provenance.provider, dataset.provenance.dataset, dataset.temporal.calendar_mode,\n                    f"{dataset.temporal.native_interval_minutes} min", dataset.temporal.timezone_name,\n                    str(dataset.start), str(dataset.end), len(df),\n                ],\n            }\n        ),\n        hide_index=True,\n        use_container_width=True,\n    )\n    st.subheader("Missing values by field")\n    missing = df[list(dataset.available_canonical_variables)].isna().sum().reset_index()\n    missing.columns = ["field", "missing_count"]\n    missing = missing[missing["missing_count"] > 0].sort_values("missing_count", ascending=False)\n    if missing.empty:\n        st.success("No missing values occur in the loaded canonical measured variables.")\n    else:\n        st.dataframe(missing, hide_index=True, use_container_width=True)\n    with st.expander("Provider provenance", expanded=False):\n        st.write(dataset.provenance.source_name)\n        st.code(dataset.provenance.source_reference)\n        for note in dataset.provenance.notes:\n            st.caption(note)\n\n\ndef render_canonical_climate_analysis(dataset) -> None:\n    """Run existing source-agnostic analyses on a real historical canonical dataset."""\n    historical_pages = (\n        "Climate File Source",\n        "Temperature",\n        "Humidity and Psychrometrics",\n        "Time Series and Overlay",\n        "Data Quality",\n    )\n    if NAVIGATION_KEY not in st.session_state or st.session_state[NAVIGATION_KEY] not in historical_pages:\n        st.session_state[NAVIGATION_KEY] = "Temperature"\n\n    st.sidebar.markdown("### Explore")\n    page = st.sidebar.radio(\n        "Analysis section",\n        historical_pages,\n        format_func=navigation_label,\n        key=NAVIGATION_KEY,\n        label_visibility="collapsed",\n    )\n    if page == "Climate File Source":\n        render_climate_file_source()\n        return\n\n    with st.sidebar.expander("Advanced calculation settings", expanded=False):\n        pressure_mode = st.selectbox(\n            "Psychrometric pressure mode",\n            [\n                "Measured station pressure with fallback median",\n                "Normal pressure: 101325 Pa",\n                "Altitude-derived standard atmosphere pressure",\n                "Custom constant pressure",\n            ],\n            index=0,\n            help=(\n                "Default: use the measured GeoSphere station pressure for each 10-minute record. "\n                "The median valid measured pressure is only a fallback for missing/invalid records."\n            ),\n        )\n        custom_pressure = None\n        if pressure_mode == "Custom constant pressure":\n            custom_pressure = st.number_input(\n                "Custom pressure [Pa]", min_value=30000.0, max_value=120000.0, value=101325.0, step=100.0\n            )\n\n    include_psychrometrics = page in {"Temperature", "Humidity and Psychrometrics", "Time Series and Overlay"}\n    _ensure_analysis_dependencies(include_solar=False, include_comparison=False)\n    source_pressure = dataset.data.get("atmospheric_station_pressure_pa")\n    valid_pressure = pd.to_numeric(source_pressure, errors="coerce").dropna() if source_pressure is not None else pd.Series(dtype=float)\n    measured_median = float(valid_pressure.median()) if not valid_pressure.empty else DEFAULT_PRESSURE_PA\n    if pressure_mode == "Normal pressure: 101325 Pa":\n        fallback_pressure = DEFAULT_PRESSURE_PA\n    elif pressure_mode == "Altitude-derived standard atmosphere pressure":\n        fallback_pressure = pressure_from_altitude_m(float(dataset.location.elevation_m or 0.0))\n    elif pressure_mode == "Custom constant pressure":\n        fallback_pressure = float(custom_pressure or DEFAULT_PRESSURE_PA)\n    else:\n        fallback_pressure = measured_median\n\n    from epw_climate_analyzer.historical import prepare_historical_analysis_frame\n    try:\n        full_df = prepare_historical_analysis_frame(\n            dataset,\n            include_psychrometrics=include_psychrometrics,\n            fallback_pressure_pa=fallback_pressure,\n        )\n    except Exception as exc:\n        st.error(f"Historical climate data could not be prepared for this analysis: {exc}")\n        return\n\n    active_pressure = fallback_pressure if pressure_mode != "Measured station pressure with fallback median" else measured_median\n    if page == "Time Series and Overlay":\n        filtered_df = full_df\n        st.session_state["_active_filtered_export_df"] = full_df\n    else:\n        filtered_df = sidebar_filters(full_df)\n        if filtered_df.empty:\n            st.warning("The current filters remove all data. Adjust the month or hour filter.")\n            return\n\n    st.sidebar.markdown("### Current climate")\n    st.sidebar.write(f"**{dataset.location.city}, {dataset.location.country}**")\n    st.sidebar.caption("GeoSphere Austria · measured 10-minute historical data")\n    st.sidebar.write(f"Rows in current view: {len(filtered_df):,}")\n    with st.sidebar.expander("Data provenance", expanded=False):\n        st.caption(dataset.provenance.dataset)\n        st.caption(f"Calendar: real historical UTC · native interval {dataset.temporal.native_interval_minutes} min")\n        if pressure_mode == "Measured station pressure with fallback median":\n            st.caption(f"Pressure: measured station values; fallback median {active_pressure:,.0f} Pa")\n        else:\n            st.caption(f"Calculation pressure fallback: {active_pressure:,.0f} Pa")\n\n    if page == "Temperature":\n        st.info("Measured-data mode: count-based 'threshold hours' is hidden until all occurrence routes are cadence-aware. HGT/KGT degree-hours already use the native 10-minute interval.")\n        render_temperature(filtered_df, interval_count_metrics=False)\n    elif page == "Humidity and Psychrometrics":\n        st.info("Measured-data mode: count-based moisture-threshold hours are hidden until occurrence metrics are cadence-aware.")\n        render_humidity(filtered_df, pressure_pa=active_pressure, interval_count_metrics=False)\n    elif page == "Time Series and Overlay":\n        render_time_series_overlay(full_df)\n    else:\n        render_canonical_data_quality(dataset, full_df)\n\n\ndef main() -> None:\n'''
if main_anchor not in app:
    raise SystemExit("main anchor not found")
app = app.replace(main_anchor, canonical_runner, 1)

# Main source dispatch: canonical historical data are first-class active sources.
old_main_start = '''    apply_queued_navigation(st.session_state)\n    active_file = get_active_climate_file()\n\n    if active_file is None:\n        st.sidebar.info("Choose a climate file to start the analysis.")\n        render_climate_file_source()\n        return\n'''
new_main_start = '''    apply_queued_navigation(st.session_state)\n    active_file = get_active_climate_file()\n    active_canonical = get_active_canonical_climate()\n\n    if active_file is None and active_canonical is None:\n        st.sidebar.info("Choose a climate source to start the analysis.")\n        render_climate_file_source()\n        return\n    if active_canonical is not None:\n        render_canonical_climate_analysis(active_canonical)\n        return\n'''
if old_main_start not in app:
    raise SystemExit("main active source anchor not found")
app = app.replace(old_main_start, new_main_start, 1)

app_path.write_text(app, encoding="utf-8")

# ---------------------------------------------------------------------------
# Regression/contract tests.
# ---------------------------------------------------------------------------
test_path.write_text('''from __future__ import annotations

import ast
from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
)
from epw_climate_analyzer.historical import add_historical_calendar_columns, prepare_historical_analysis_frame


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
UI = ROOT / "epw_climate_analyzer" / "ui_contract.py"


def sample_dataset() -> CanonicalClimateDataset:
    index = pd.date_range("2025-07-01T00:00:00Z", periods=12, freq="10min")
    data = pd.DataFrame(
        {
            "dry_bulb_temperature_c": [20.0 + i * 0.1 for i in range(12)],
            "relative_humidity_pct": [55.0] * 12,
            "atmospheric_station_pressure_pa": [96500.0] * 12,
            "global_horizontal_radiation_wh_m2": [0.0] * 12,
        },
        index=index,
    )
    data.attrs["canonical_native_interval_minutes"] = 10
    return CanonicalClimateDataset(
        climate_id="geosphere:test:11240",
        display_name="Graz test — GeoSphere 10 min",
        data=data,
        location=ClimateLocation(47.08, 15.45, 366.0, "Graz/Universitaet", "Steiermark", "Austria", "11240"),
        temporal=ClimateTemporalMetadata(10, "historical", "UTC", "unknown"),
        provenance=ClimateProvenance("GeoSphere Austria", "klima-v2-10min", "Dataset API JSON", "test source"),
    )


class HistoricalPreparationTests(unittest.TestCase):
    def test_real_utc_timestamps_and_native_cadence_are_preserved(self) -> None:
        dataset = sample_dataset()
        prepared = add_historical_calendar_columns(dataset.data)
        self.assertEqual(prepared.index[0], dataset.data.index[0])
        self.assertEqual(str(prepared.index.tz), "UTC")
        self.assertEqual(prepared.attrs["canonical_native_interval_minutes"], 10)
        self.assertEqual(prepared["hour_of_day"].iloc[0], 0)
        self.assertEqual(prepared["month_index"].iloc[0], 7)

    def test_psychrometric_derivation_uses_canonical_primary_observations(self) -> None:
        prepared = prepare_historical_analysis_frame(sample_dataset(), include_psychrometrics=True, fallback_pressure_pa=96500.0)
        self.assertIn("humidity_ratio_g_kg", prepared.columns)
        self.assertIn("wet_bulb_temperature_c", prepared.columns)
        self.assertTrue(prepared["humidity_ratio_g_kg"].notna().all())
        self.assertEqual(prepared.attrs["canonical_native_interval_minutes"], 10)


class GeoSpherePublicUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_source_selector_exposes_geosphere_and_bounded_year_range(self) -> None:
        self.assertIn('"GeoSphere Austria"', self.source)
        self.assertIn('def render_geosphere_source()', self.source)
        self.assertIn('selected_days > 366', self.source)
        self.assertIn('plan_geosphere_queries', self.source)
        self.assertIn('fetch_geosphere_station_dataset', self.source)

    def test_historical_dataset_uses_existing_analysis_renderers_not_duplicate_provider_pages(self) -> None:
        self.assertIn('render_temperature(filtered_df, interval_count_metrics=False)', self.source)
        self.assertIn('render_humidity(filtered_df, pressure_pa=active_pressure, interval_count_metrics=False)', self.source)
        self.assertIn('render_time_series_overlay(full_df)', self.source)
        self.assertNotIn('def render_geosphere_temperature', self.source)
        self.assertNotIn('def render_geosphere_humidity', self.source)

    def test_record_count_hour_routes_are_hidden_for_ten_minute_measured_data(self) -> None:
        self.assertIn('chart_options.remove("Threshold hours")', self.source)
        self.assertIn('chart_options.remove("Moisture thresholds")', self.source)
        self.assertIn('HGT/KGT degree-hours already use the native 10-minute interval', self.source)

    def test_time_series_localizes_ui_range_to_real_historical_timezone(self) -> None:
        self.assertIn('if index.tz is not None:', self.source)
        self.assertIn('start = start.tz_localize(index.tz)', self.source)
        self.assertIn('selected_end = selected_end.tz_localize(index.tz)', self.source)

    def test_public_intro_no_longer_claims_epw_only_input(self) -> None:
        ui = UI.read_text(encoding="utf-8")
        self.assertIn("EPW weather files and measured station data", ui)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

# ---------------------------------------------------------------------------
# Stage note.
# ---------------------------------------------------------------------------
doc_path.write_text('''# CLIMATE-GEOSPHERE-0.3 — public historical station selection

## Scope

This stage connects the qualified `klima-v2-10min` GeoSphere Austria adapter to Climate Analyzer without converting measured observations to EPW.

The Start page now offers **GeoSphere Austria** as a third climate source. The user can search quality-checked stations, select a UTC historical date range, see the expected request size/batch count, and load up to 366 days. Long ranges use the bounded batching introduced in CLIMATE-GEOSPHERE-0.2.

## Canonical analysis path

Loaded GeoSphere data remain a `CanonicalClimateDataset` with real historical UTC timestamps and a declared 10-minute native interval. Existing source-agnostic renderers are reused for:

- Temperature and extremes;
- Humidity and psychrometrics;
- Time series and overlay;
- source/provenance diagnostics.

A provider-specific duplicate temperature/humidity plotting stack is deliberately not introduced.

## Cadence safety gate

Several legacy EPW routes label a Boolean record count as "hours" because EPW is hourly. Those routes are not valid for 10-minute observations without explicit duration weighting. Therefore, measured-data mode currently hides:

- temperature threshold-hours;
- moisture threshold-hours;
- wind/ventilation occurrence views;
- precipitation occurrence views;
- natural-ventilation/HVAC occurrence summaries;
- multi-climate comparison.

HGT/KGT degree-hours remain enabled because `degree_metric_table()` weights each source interval by the canonical native interval; degree-days remain based on daily mean outdoor temperature.

## Public request boundary

The UI permits at most 366 days per load. Every provider request stays below the conservative 200,000-datapoint local batch limit, and exact request URLs remain in provenance. Historical gaps and missing values are retained; no temporal interpolation is performed.

## Next stage

CLIMATE-GEOSPHERE-0.4 should make occurrence/count routes explicitly duration-aware so wind, precipitation, natural ventilation and related HVAC views can be enabled safely for 10-minute measured data. Historical comparison should then consume canonical datasets rather than reintroducing EPW-only assumptions.
''', encoding="utf-8")

print("CLIMATE-GEOSPHERE-0.3 public historical integration patch applied")
