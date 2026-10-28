"""Bounded Streamlit workspace for historical and representative future years.

The engine's water-phase states use their own analysis adapter and plots.
The existing EPW/GeoSphere routes keep their established scientific contracts.
"""
from __future__ import annotations

from .engine_application import (EngineProduct, pilot_historical_request,
    run_historical_product, run_future_pilot_product)
from .engine_analysis import prepare_engine_analysis_frame, monthly_engine_summary
from .engine_station_product import CATALOG, load_station_year_product
from .engine.contracts import HistoricalRequest
from .ui_contract import NAVIGATION_KEY, navigation_label

PRODUCT_KEY = "ige_engine_completed_product"
ERROR_KEY = "ige_engine_last_failure"
REQUEST_KEY = "ige_engine_completed_request"
ERROR_REQUEST_KEY = "ige_engine_failed_request"
STATION_SOURCE = "Saved CH 2025 — station-temperature reconstruction"
PAGES = ("Climate File Source", "Overview", "Temperature", "Humidity and Psychrometrics",
    "Solar and Radiation", "Wind and Ventilation", "Sky and Daylight", "Precipitation and Snow",
    "Time Series and Overlay", "Data Quality")
VARIABLES = {
    "Temperature [°C]": "dry_bulb_temperature_c",
    "Source dew point [°C]": "dew_point_temperature_c",
    "Relative humidity over water [%]": "relative_humidity_pct",
    "Humidity ratio [g/kg dry air]": "humidity_ratio_g_kg",
    "Vapour pressure [Pa]": "vapor_pressure_pa",
    "Pressure proxy [Pa]": "atmospheric_station_pressure_pa",
    "Global horizontal irradiation [Wh/m²]": "global_horizontal_radiation_wh_m2",
    "Direct normal irradiation [Wh/m²]": "direct_normal_radiation_wh_m2",
    "Diffuse horizontal irradiation [Wh/m²]": "diffuse_horizontal_radiation_wh_m2",
    "Downward longwave irradiation [Wh/m²]": "horizontal_infrared_radiation_intensity_wh_m2",
    "Wind speed [m/s]": "wind_speed_m_s", "Wind direction [°]": "wind_direction_deg",
    "Total cloud cover [tenths]": "total_sky_cover_tenths",
    "Liquid rain [mm]": "liquid_precipitation_depth_mm",
    "Total precipitation [mm]": "total_precipitation_depth_mm",
}


def _scope(st, product: EngineProduct) -> None:
    future = product.report["calendar_mode"] == "climatology"
    station = product.report.get("product_kind") == "SAVED_STATION_T_RECONSTRUCTION"
    st.caption("Research generator · independent station accuracy is not qualified · production readiness is not qualified")
    if future:
        st.info("CanESM5 / r1i1p1f1 / SSP245 · climate window 2040–2059 · reference 2002–2014. "
            "The dates show the 2023 hourly pattern, not a forecast for particular future days or a selected TMY.")
        st.warning("NASA relative-humidity change is diagnostic and is not enforced (pilot monthly discrepancy up to 3.74 percentage points). "
            "Pressure, event timing, cloud cover, wind direction and precipitation phase rely on the historical pattern.")
    elif station:
        st.info("Saved CH 2025 station-temperature reconstruction · fixed CET UTC+1. "
            "Temperature uses the frozen R1 station residual method; humidity follows the explicit A1.4 projection. "
            "Wind, cloud, precipitation and radiation retain the ERA5-derived / NASA POWER background sources.")
        d = product.report["diagnostics"]
        st.warning(f"Instantaneous temperature accuracy is not qualified: the hourly-mean inverse can amplify rapid changes "
            f"(maximum hourly step {d['temperature']['max_endpoint_hourly_step_K']:.2f} K in this saved year). "
            "Pressure remains a conditional model-surface plus 2m proxy; pressure at the actual station height is not qualified.")
        st.caption(f"Humidity projection: {d['humidity_projection_hours']} hours. "
            "The original EPW and adjustment ledgers are preserved. Loading and view filters make no new weather request.")
    else:
        st.info("Historical grid background from ERA5-derived data and NASA POWER longwave. "
            "Local station and terrain corrections are not applied. Pressure is a model-surface proxy, not collocated with two-metre temperature/humidity.")
    d = product.report["source_geometry"]
    if station:
        st.caption(f"Station T-sensor coordinates: {d['requested_point']}; background cell: {d['background_cell']}; "
            f"distance {d['requested_to_background_distance_km']:.2f} km. Nominal station elevation "
            f"{d['nominal_station_elevation_m']:g} m; background elevation {d['elevation_m_provider_response_proxy']:g} m is an unverified provider proxy. "
            "The vertical-datum/model-orography transfer is not qualified.")
    else:
        st.caption(f"Requested point: {d['requested_point']}; background cell: {d['background_cell']}; distance {d['requested_to_background_distance_km']:.2f} km. "
            f"Elevation {d['elevation_m_provider_response_proxy']:g} m is an unverified provider proxy.")


def _station_provenance(st, product: EngineProduct) -> None:
    with st.expander("Field sources and adjustment ledgers", expanded=False):
        st.dataframe(product.report["field_provenance"], hide_index=True, width="stretch")
        st.caption("The ZIP contains the original A1.4 station snapshot, donor admission, mean-inverse and humidity/pressure ledgers. "
            "Original provider bodies remain in the linked SHA-pinned source packets.")
        st.json(product.report["source_references"])


def _downloads(st, product: EngineProduct) -> None:
    st.caption("Downloads always contain the complete generated year. View filters do not change the EPW or source data.")
    left, right = st.columns(2)
    left.download_button("Download EPW", data=product.files["climate.epw"],
        file_name=product.download_stem + ".epw", mime="application/octet-stream", key="ige_download_epw")
    right.download_button("Download data and report ZIP", data=product.archive,
        file_name=product.download_stem + ".zip", mime="application/zip", key="ige_download_zip")
    st.download_button("Download hourly CSV (gzip)", data=product.files["hourly.csv.gz"],
        file_name=product.download_stem + ".csv.gz", mime="application/gzip", key="ige_download_csv")
    st.download_button("Download quality report", data=product.files["ui_report.json"],
        file_name=product.download_stem + "_quality.json", mime="application/json", key="ige_download_quality")


def render_engine_source(activate) -> None:
    """Public point request. Saved examples belong to the research harness."""
    import streamlit as st
    from .location_picker import render_point_picker

    st.subheader("Generate a climate year")
    st.write("Select a point to request a historical gridded background and check whether a complete EPW can be assembled.")
    st.info("Source: ERA5-derived grid data via Open-Meteo, with NASA POWER longwave radiation. This is not station interpolation or a measured station year. For observations, select GeoSphere Austria.")
    lat, lon, height, height_reference = render_point_picker(st)
    left, right = st.columns(2)
    year = left.number_input("Historical year", 2002, 2025, 2023, step=1, key="ige_year")
    offset = right.selectbox("Standard UTC offset [hours]", list(range(-12, 13)), index=13, key="ige_offset")
    label = st.text_input("Location label", "Selected point", max_chars=120, key="ige_point_label")
    st.caption("2002–2025 is the current source-request window, not a guarantee of a complete year at every point. The fixed standard UTC offset has no daylight-saving changes; only whole-hour offsets are supported. Missing required weather data block export.")
    height_ready = height is None or bool(height_reference)
    if not height_ready:
        st.warning("Enter the elevation source / vertical datum, or clear the optional elevation.")
    request = None
    try:
        if height_ready:
            request = HistoricalRequest(lat, lon, int(year), int(offset)*60, label=label,
                                        site_elevation_m=height, site_elevation_reference=height_reference)
    except ValueError as exc:
        st.warning(str(exc))
    st.caption("Build sends the selected coordinates and year to Open-Meteo and NASA POWER. Site elevation is retained locally in the request record.")
    if st.button("Check data and build EPW", type="primary", key="ige_build_background", disabled=request is None):
        st.session_state.pop(ERROR_KEY, None)
        st.session_state.pop(ERROR_REQUEST_KEY, None)
        try:
            with st.status("Checking sources and assembling the complete year", expanded=True) as status:
                def progress(message):
                    status.update(label=message)
                    st.write(message)
                completed = run_historical_product(request, use_saved_pilot=False, progress=progress)
                status.update(label="Complete year and downloads verified", state="complete", expanded=False)
            st.session_state[PRODUCT_KEY] = completed
            st.session_state[REQUEST_KEY] = request.to_dict()
        except Exception as exc:
            st.session_state[ERROR_KEY] = f"{type(exc).__name__}: {exc}"
            st.session_state[ERROR_REQUEST_KEY] = request.to_dict()
    error = st.session_state.get(ERROR_KEY)
    if error:
        failed_current = request is not None and st.session_state.get(ERROR_REQUEST_KEY) == request.to_dict()
        st.error(("This request" if failed_current else "Previous request") + " did not produce a downloadable year: " + error)
    product = st.session_state.get(PRODUCT_KEY)
    if isinstance(product, EngineProduct):
        current = request is not None and st.session_state.get(REQUEST_KEY) == request.to_dict()
        st.divider()
        st.subheader("Completed result" if current and not error else "Previous completed result")
        if not current:
            st.warning("The downloads below belong to the previous completed request. Build the current selection to obtain a new year.")
        st.write(product.dataset.display_name)
        st.success(f"{len(product.dataset.data):,} hourly records · complete year verified")
        _scope(st, product)
        requested_height = product.report.get("diagnostics", {}).get("site_height_m_requested")
        if requested_height is not None:
            st.caption(f"Requested site elevation: {requested_height:g} m. No weather or EPW-location height correction was applied.")
        _downloads(st, product)
        if st.button("Explore this generated climate", type="primary", key="ige_explore"):
            activate(product.dataset)
            st.rerun()
    with st.expander("Station interpolation and future climate", expanded=False):
        st.write("A future climate must start from your selected historical base. Transforming an uploaded EPW, a station year or an interpolated point is not available in this panel yet. These routes need compatible historical periods, source coverage and climate-model signals.")


def render_engine_research_examples(activate) -> None:
    """Explicit offline regression harness; the public app does not call it."""
    import streamlit as st

    st.subheader("Generate a climate year")
    st.write("Build a historical background year, load an admitted station-temperature research year, or generate the future-climate pilot; then explore and download the complete year.")
    mode = st.radio("Generation mode", ["Historical climate", "Future climate"], horizontal=True, key="ige_generation_mode")
    request = pilot_historical_request()
    saved = True
    station_year = False
    station_key = None
    if mode == "Historical climate":
        source = st.selectbox("Historical source", ["Saved Graz 2023 pilot", "Coordinates — request provider data", STATION_SOURCE], key="ige_historical_source")
        saved = source == "Saved Graz 2023 pilot"
        station_year = source == STATION_SOURCE
        if station_year:
            st.caption("Limited saved research mode: Basel / Binningen and Altdorf, 2025, fixed CET UTC+1. "
                "No coordinate interpolation or arbitrary-year generation is requested by this option.")
            with st.form("ige_station_year_request"):
                labels = {site["label"]: key for key, site in CATALOG.items()}
                choice = st.selectbox("Station", list(labels), key="ige_station_year_choice")
                station_key = labels[choice]
                st.caption("Loading checks the original saved year and keeps its EPW unchanged. Independent local accuracy and production readiness are not qualified.")
                submitted = st.form_submit_button("Load station year", type="primary")
        else:
            if saved:
                for key, value in {"ige_latitude": 47.0707, "ige_longitude": 15.4395,
                        "ige_year": 2023, "ige_offset": 1, "ige_location_label": "Graz"}.items():
                    st.session_state[key] = value
            st.caption("One complete year; UTC offset is fixed local standard time without summer-time changes. "
                "No automatic local height correction. Source completeness is checked before export.")
            with st.form("ige_historical_request"):
                left, right = st.columns(2)
                lat = left.number_input("Latitude [°]", -90.0, 90.0, 47.0707, format="%.4f", disabled=saved, key="ige_latitude")
                lon = right.number_input("Longitude [°]", -180.0, 180.0, 15.4395, format="%.4f", disabled=saved, key="ige_longitude")
                year = left.number_input("Historical year", 2002, 2025, 2023, step=1, disabled=saved, key="ige_year")
                offset = right.selectbox("Standard UTC offset [hours]", list(range(-12, 13)), index=13, disabled=saved, key="ige_offset")
                label = st.text_input("Location label", "Graz", max_chars=120, disabled=saved, key="ige_location_label")
                if saved:
                    st.caption("Saved pilot: Graz 47.0707° N, 15.4395° E; 2023; UTC+1. No provider request.")
                else:
                    st.caption("Run sends these coordinates and the year to Open-Meteo and NASA POWER. Availability is checked at run time; an incomplete year is blocked.")
                submitted = st.form_submit_button("Generate historical year", type="primary")
            if submitted and not saved:
                try:
                    request = HistoricalRequest(float(lat), float(lon), int(year), int(offset)*60, label=label)
                except ValueError as exc:
                    st.session_state[ERROR_KEY] = str(exc)
                    submitted = False
    else:
        st.caption("First admitted pilot. More locations, models and scenarios require source admission before they can be selected.")
        with st.form("ige_future_request"):
            st.selectbox("Future location and hourly pattern", ["Graz · 2023 hourly pattern · UTC+1"], key="ige_future_location")
            st.selectbox("Climate model / member", ["CanESM5 / r1i1p1f1"], key="ige_future_model")
            st.selectbox("SSP scenario", ["SSP245"], key="ige_future_scenario")
            st.selectbox("Future climate period", ["2040–2059"], key="ige_future_period")
            st.caption("Historical climate reference: 2002–2014 for both local sources and NASA NEX-GDDP-CMIP6. "
                "The 2023 pattern supplies event timing. All pilot source packets are retained; no provider request.")
            submitted = st.form_submit_button("Generate future year", type="primary")
    if submitted:
        st.session_state.pop(ERROR_KEY, None)
        try:
            with st.status("Preparing the complete climate year", expanded=True) as status:
                def progress(message):
                    status.update(label=message)
                    st.write(message)
                if station_year:
                    completed = load_station_year_product(station_key, progress=progress)
                elif mode == "Historical climate":
                    completed = run_historical_product(request, use_saved_pilot=saved, progress=progress)
                else:
                    completed = run_future_pilot_product(progress=progress)
                status.update(label="Complete year and downloads verified", state="complete", expanded=False)
            # Atomic publication: errors above cannot replace the last valid result.
            st.session_state[PRODUCT_KEY] = completed
        except Exception as exc:
            st.session_state[ERROR_KEY] = f"{type(exc).__name__}: {exc}"
    error = st.session_state.get(ERROR_KEY)
    if error:
        st.error("This request did not produce a downloadable year: " + error)
    product = st.session_state.get(PRODUCT_KEY)
    if isinstance(product, EngineProduct):
        st.divider()
        st.subheader("Previous completed result" if error else "Completed result")
        st.write(product.dataset.display_name)
        st.success(f"{len(product.dataset.data):,} hourly records · complete year verified")
        _scope(st, product)
        if product.report.get("product_kind") == "SAVED_STATION_T_RECONSTRUCTION":
            _station_provenance(st, product)
        _downloads(st, product)
        if st.button("Explore this generated climate", type="primary", key="ige_explore"):
            activate(product.dataset)
            st.rerun()


def render_engine_analysis(dataset, render_source) -> None:
    """Use the engine's own phase/clock contract throughout this workspace."""
    import streamlit as st
    import plotly.graph_objects as go

    if st.session_state.get(NAVIGATION_KEY) not in PAGES:
        st.session_state[NAVIGATION_KEY] = "Overview"
    page = st.sidebar.radio("Analysis section", PAGES, format_func=navigation_label, key=NAVIGATION_KEY, label_visibility="collapsed")
    if page == "Climate File Source":
        if "climate_source_mode" not in st.session_state:
            st.session_state["climate_source_mode"] = "Generate climate"
        render_source()
        return
    product = st.session_state.get(PRODUCT_KEY)
    if not isinstance(product, EngineProduct) or product.dataset is not dataset:
        st.error("The generated dataset has no matching complete output package. Return to the climate source and generate a year.")
        return
    st.title(dataset.display_name)
    _scope(st, product)
    station = product.report.get("product_kind") == "SAVED_STATION_T_RECONSTRUCTION"
    try:
        full = prepare_engine_analysis_frame(dataset)
    except ValueError as exc:
        st.error(f"The engine state cannot be analysed safely: {exc}")
        return
    st.sidebar.caption("IGE research generator · original hourly calendar · liquid-water humidity")
    with st.sidebar.expander("View filter", expanded=False):
        months = st.multiselect("Months", list(range(1, 13)), default=list(range(1, 13)), key="ige_filter_months")
    data = full[full.index.month.isin(months)]
    st.caption("Row timestamps mark the start of each one-hour interval. Temperature, humidity, pressure, wind and cloud states are sampled at its end; radiation and precipitation cover the interval.")
    if page == "Overview":
        st.subheader("Complete generated year")
        a, b, c = st.columns(3)
        a.metric("Hourly records", f"{len(full):,}")
        b.metric("Temperature sample mean", f"{full['dry_bulb_temperature_c'].mean():.2f} °C")
        c.metric("Annual GHI", f"{full['global_horizontal_radiation_wh_m2'].sum()/1000:.1f} kWh/m²")
        st.dataframe(monthly_engine_summary(full), width="stretch")
        _downloads(st, product)
        return
    if page == "Data Quality":
        st.subheader("Four separate qualification axes")
        st.dataframe({"Axis": list(product.report["quality"]), "Status": list(product.report["quality"].values())}, hide_index=True, width="stretch")
        with st.expander("Physical definitions, clock and source geometry", expanded=True):
            st.json({"clock": product.report["row_clock"], "calendar_mode": product.report["calendar_mode"],
                "analysis_adapter": product.report["analysis_adapter"], "source_geometry": product.report["source_geometry"],
                "diagnostics": product.report["diagnostics"]})
        if station:
            _station_provenance(st, product)
        _downloads(st, product)
        return
    if data.empty:
        st.warning("Select at least one month to view hourly data.")
        return
    groups = {
        "Temperature": ["Temperature [°C]", "Source dew point [°C]"],
        "Humidity and Psychrometrics": ["Relative humidity over water [%]", "Humidity ratio [g/kg dry air]", "Vapour pressure [Pa]", "Pressure proxy [Pa]"],
        "Solar and Radiation": [k for k in VARIABLES if "irradiation" in k],
        "Wind and Ventilation": ["Wind speed [m/s]", "Wind direction [°]"],
        "Sky and Daylight": ["Total cloud cover [tenths]"],
        "Precipitation and Snow": ["Liquid rain [mm]", "Total precipitation [mm]"],
        "Time Series and Overlay": list(VARIABLES),
    }
    if page == "Humidity and Psychrometrics":
        st.caption("Vapour content uses the declared liquid-water convention. Phase-aware time series are shown here; the legacy ice-based psychrometric chart is not applied to these states.")
        if station:
            view = st.radio("Humidity view", ["Hourly time series", "Water-phase psychrometric chart"], horizontal=True, key="ige_station_humidity_view")
            st.caption("Specific humidity q is water per moist-air mass; humidity ratio w is water per dry-air mass. The chart and time series preserve the saved q.")
            if view == "Water-phase psychrometric chart":
                from .engine_psychrometrics import station_psychrometric_figure
                reference = st.number_input("Guide-curve reference pressure [Pa]", min_value=31000., max_value=120000.,
                    value=float(round(full["atmospheric_station_pressure_pa"].median())), step=100., key="ige_station_guide_pressure")
                st.caption("Guide curves use this single constant pressure and Murphy–Koop liquid-water saturation, including below zero. "
                    "Points retain their original per-hour q and conditional pressure; they are not recomputed at the guide pressure. "
                    "Pressure variation can place points above a reference guide without implying pointwise supersaturation.")
                st.plotly_chart(station_psychrometric_figure(data, reference), width="stretch", key="ige_station_psychrometric_plot")
                return
    if page == "Wind and Ventilation":
        st.caption("Wind is a source/pattern state. Local ventilation suitability is not qualified.")
    if page == "Sky and Daylight":
        st.caption("Only total cloud cover is available. Daylight and opaque-cloud values are not inferred.")
    if page == "Precipitation and Snow":
        st.caption("Liquid rain and total precipitation are distinct. Snow depth is not available. Future precipitation phase and event timing are inherited.")
    variables = dict(VARIABLES)
    if station:
        label = "Specific humidity q [g/kg moist air]"
        variables[label] = "specific_humidity_g_kg_moist_air"
        groups["Humidity and Psychrometrics"].append(label)
        groups["Time Series and Overlay"].append(label)
    variable = st.selectbox("Hourly variable", groups[page], key="ige_plot_variable_" + page)
    column = variables[variable]
    if column not in data:
        st.info("This variable is not part of the generated source contract.")
        return
    fig = go.Figure(go.Scattergl(x=data.index, y=data[column], mode="lines", name=variable))
    fig.update_layout(title=variable, xaxis_title="Interval start — fixed local standard time", yaxis_title=variable, height=400)
    st.plotly_chart(fig, width="stretch", key="ige_hourly_plot")
    st.caption(f"{len(data):,} hourly rows in this view. The temperature sample mean is distinct from NASA daily tas midrange.")
    if page == "Time Series and Overlay":
        st.dataframe(data[[column]], width="stretch")
