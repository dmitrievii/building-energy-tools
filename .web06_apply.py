from pathlib import Path

path = Path("tools/climate_analyzer/app.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    '''from epw_climate_analyzer.statistics import (
    calculated_statistics_tables,
    climate_statistics_interpretation,
    extreme_day_summary,
    monthly_climate_summary,
    seasonal_climate_summary,
)


VARIABLES = {''',
    '''from epw_climate_analyzer.statistics import (
    calculated_statistics_tables,
    climate_statistics_interpretation,
    extreme_day_summary,
    monthly_climate_summary,
    seasonal_climate_summary,
)
from epw_climate_analyzer.ui_contract import (
    APP_BROWSER_TITLE,
    APP_INTRO,
    APP_NAME,
    APP_TAGLINE,
    NAVIGATION_PAGES,
    navigation_label,
)


VARIABLES = {''',
    "UI contract import",
)

replace_once(
    'st.set_page_config(page_title="EPW Climate Analyzer", layout="wide", page_icon="🌦️")',
    'NAVIGATION_KEY = "climate_analyzer_navigation"\nst.set_page_config(page_title=APP_BROWSER_TITLE, layout="wide", page_icon="🌦️")',
    "page config",
)

replace_once(
    '''def set_active_climate_file(name: str, payload: bytes, source: str) -> None:
    """Store the selected EPW payload in Streamlit session state."""
    st.session_state["active_climate_file"] = ClimateFilePayload(name=name, payload=payload, source=source)''',
    '''def set_active_climate_file(name: str, payload: bytes, source: str) -> None:
    """Store the selected EPW payload and open the summary view."""
    st.session_state["active_climate_file"] = ClimateFilePayload(name=name, payload=payload, source=source)
    st.session_state[NAVIGATION_KEY] = "Overview"''',
    "active climate navigation",
)

replace_once(
    '''def clear_active_climate_file() -> None:
    """Remove the currently selected climate file from session state."""
    st.session_state.pop("active_climate_file", None)''',
    '''def clear_active_climate_file() -> None:
    """Remove the currently selected climate file and reset navigation."""
    st.session_state.pop("active_climate_file", None)
    st.session_state.pop(NAVIGATION_KEY, None)''',
    "clear climate navigation",
)

replace_once(
    '''def render_climate_file_source() -> None:
    """Render the first page for local EPW upload and Climate.OneBuilding selection."""
    st.header("Climate file source")
    st.write(
        "Select a local EPW file or choose an online weather station from the "
        "Climate.OneBuilding catalog. The selected EPW becomes the active climate "
        "file for all charts and analysis layers."
    )

    active = get_active_climate_file()
    if active is not None:
        st.success(f"Active climate file: {active.name}")
        st.caption(f"Source: {active.source}")
        if st.button("Clear active climate file"):
            clear_active_climate_file()
            st.rerun()

    local_tab, map_tab = st.tabs(["Local EPW upload", "Climate.OneBuilding station map"])

    with local_tab:
        st.subheader("Load a local EPW file")
        local_file = st.file_uploader("Upload local EPW file", type=["epw"], key="local_epw_upload")
        if local_file is not None:
            st.write(f"Selected file: `{local_file.name}`")
            if st.button("Use uploaded EPW file", type="primary"):
                set_active_climate_file(local_file.name, local_file.getvalue(), "Local upload | user-provided EPW | transient session")
                st.rerun()

    with map_tab:
        st.subheader("Select a Climate.OneBuilding weather station")
        st.caption(
            "The map uses clustered markers: at low zoom levels it displays station counts; "
            "after zooming in, individual stations appear as purple points."
        )''',
    '''def render_climate_file_source() -> None:
    """Render the product entry page for local or catalog climate selection."""
    st.title(APP_NAME)
    st.markdown(f"#### {APP_TAGLINE}")
    st.write(APP_INTRO)
    st.caption(
        "Start with an EPW weather file from your computer or select a climate from the reviewed "
        "Climate.OneBuilding station catalog. No building model is required."
    )

    active = get_active_climate_file()
    if active is not None:
        st.success(f"Current climate: {active.name}")
        with st.expander("Data source details", expanded=False):
            st.caption(active.source)
        if st.button("Choose a different climate"):
            clear_active_climate_file()
            st.rerun()

    st.divider()
    local_tab, map_tab = st.tabs(["Upload EPW", "Find climate"])

    with local_tab:
        st.subheader("Upload an EPW weather file")
        st.write("Use an EnergyPlus Weather (EPW) file that you already have. The file is processed for the current session.")
        local_file = st.file_uploader("Choose EPW file", type=["epw"], key="local_epw_upload")
        if local_file is not None:
            st.write(f"Selected file: `{local_file.name}`")
            if st.button("Analyze this EPW", type="primary"):
                set_active_climate_file(local_file.name, local_file.getvalue(), "Local upload | user-provided EPW | transient session")
                st.rerun()

    with map_tab:
        st.subheader("Find a climate from Climate.OneBuilding")
        st.caption(
            "Search or zoom to a station, choose one of its available climate datasets, then load the EPW for analysis."
        )''',
    "source landing page",
)

replace_once('with st.expander("Map performance settings", expanded=False):', 'with st.expander("Advanced map settings", expanded=False):', "map expander")
replace_once('"Detailed marker zoom threshold",', '"Show individual stations from zoom level",', "map zoom label")
replace_once('"Maximum station groups in selectable clustered map",', '"Maximum station groups rendered on map",', "map count label")

main_start = text.index('def main() -> None:\n')
main_end = text.index('\n\nif __name__ == "__main__":', main_start)
new_main = '''def main() -> None:
    """Run the Streamlit Climate Analyzer application."""
    st.sidebar.caption("Building Energy Tools")
    st.sidebar.title(APP_NAME)
    active_file = get_active_climate_file()

    if active_file is None:
        st.sidebar.info("Choose a climate file to start the analysis.")
        render_climate_file_source()
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
            index=0,
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
    elif page == "Natural Ventilation":
        render_natural_ventilation(filtered_df, pressure_pa=active_pressure)
    elif page == "HVAC and Passive Design":
        render_hvac_passive(filtered_df)
    elif page == "Compare Climates":
        render_compare_climates(active_file, pressure_mode, custom_pressure, active_pressure)
    else:
        render_data_quality(epw, full_df, issues)
'''
text = text[:main_start] + new_main + text[main_end:]

path.write_text(text, encoding="utf-8")
print("WEB-0.6 deterministic UX transform PASS")
