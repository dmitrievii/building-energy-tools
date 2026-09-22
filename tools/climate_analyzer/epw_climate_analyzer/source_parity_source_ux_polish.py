"""Cross-cadence GeoSphere source UX polish."""
from __future__ import annotations
from contextlib import nullcontext
from typing import Any, Callable
import pandas as pd

_RESOURCE_CONTEXT = {
    "klima-v2-10min": "Official GeoSphere Austria availability context (translated summary): the 10-minute resource is the recent, high-resolution observation archive. Its published resource extent begins in May 1992. Actual coverage still depends on station and parameter; numeric availability is verified from returned observations rather than inferred from station validity metadata. Matching provider quality flags are loaded where available.",
    "klima-v2-1h": "Official GeoSphere Austria availability context (translated summary): the hourly dataset begins with Vienna sunshine-duration observations from 1880. Hourly air temperature, humidity and precipitation are documented for a small number of stations from 1941; measured parameters and station coverage increase continuously from about 1950. Depending on the parameter, an hourly value can be an instantaneous observation, previous-hour mean, previous-hour extreme or previous-hour sum. Quality status is provided through matching *_flag fields.",
    "klima-v2-1m": "Official GeoSphere Austria availability context (translated summary): the monthly resource has the longest published extent (from December 1767) and contains native monthly statistics such as means, extrema, totals and event counts. Station and parameter coverage varies strongly through the historical record; availability is therefore verified from returned observations and is not inferred from the station metadata validity interval.",
}

_CANONICAL_LABELS = {
    "dry_bulb_temperature_c": "Air temperature", "dry_bulb_temperature_min_c": "Minimum air temperature",
    "dry_bulb_temperature_max_c": "Maximum air temperature", "dew_point_temperature_c": "Dew-point temperature",
    "relative_humidity_pct": "Relative humidity", "atmospheric_station_pressure_pa": "Station pressure",
    "global_horizontal_radiation_wh_m2": "Global horizontal radiation", "direct_normal_radiation_wh_m2": "Direct normal radiation",
    "diffuse_horizontal_radiation_wh_m2": "Diffuse horizontal radiation", "wind_speed_m_s": "Wind speed",
    "wind_direction_deg": "Wind direction", "wind_gust_speed_m_s": "Wind gust speed", "wind_gust_direction_deg": "Wind gust direction",
    "liquid_precipitation_depth_mm": "Precipitation", "precipitation_duration_min": "Precipitation duration",
    "snow_depth_cm": "Snow depth", "sunshine_duration_s": "Sunshine duration",
    "ground_temperature_0_10m_c": "Ground temperature 0.10 m", "ground_temperature_0_20m_c": "Ground temperature 0.20 m",
    "ground_temperature_0_50m_c": "Ground temperature 0.50 m", "ground_temperature_1_00m_c": "Ground temperature 1.00 m",
    "ground_temperature_2_00m_c": "Ground temperature 2.00 m",
}

_MONTHLY_PARAMETER_SET_OPTIONS = (
    "Core variables",
    "Core + additional statistics",
    "All provider parameters",
)
_MONTHLY_CONTEXT_LABEL = "About this GeoSphere monthly dataset"


def _english_variable_name(row: pd.Series) -> str:
    canonical = str(row.get("Canonical field", "")).strip()
    if canonical in _CANONICAL_LABELS:
        return _CANONICAL_LABELS[canonical]
    if canonical:
        return canonical.replace("_", " ").strip().capitalize()
    return str(row.get("Measured variable", ""))


def _wrap_marker_labels(payload: Any) -> Any:
    if not isinstance(payload, list):
        return payload
    wrapped = []
    for item in payload:
        if not isinstance(item, list) or len(item) < 4:
            wrapped.append(item); continue
        row = list(item)
        parts = [part.strip() for part in str(row[3]).split(" · ") if part.strip()]
        if len(parts) > 1:
            row[3] = "<br>".join(parts if len(parts) <= 3 else (parts[0], " · ".join(parts[1:3]), " · ".join(parts[3:])))
        wrapped.append(row)
    return wrapped


def install_source_ux_polish(proxy: Any, parity: Any) -> None:
    if bool(getattr(proxy, "_GEOSPHERE_SOURCE_UX_POLISH_V1", False)):
        return
    st = parity.st
    if hasattr(proxy, "station_marker_payload"):
        previous_payload = proxy.station_marker_payload
        proxy.station_marker_payload = lambda data, *args, **kwargs: _wrap_marker_labels(previous_payload(data, *args, **kwargs))

    previous_selector = parity._render_geosphere_resource_selector
    def selector(legacy: Any, original: Callable) -> Any:
        real_editor, real_info, real_radio, real_expander = st.data_editor, st.info, st.radio, st.expander

        def editor(data: Any, *args: Any, **kwargs: Any):
            if isinstance(data, pd.DataFrame) and {"Measured variable", "Provider"}.issubset(data.columns):
                display = data.copy()
                display["Measured variable"] = display.apply(_english_variable_name, axis=1)
                return real_editor(display, *args, **kwargs)
            return real_editor(data, *args, **kwargs)

        def info(body: Any, *args: Any, **kwargs: Any):
            if str(body).startswith("Official GeoSphere Austria availability context"):
                return None
            return real_info(body, *args, **kwargs)

        def radio(label: Any, options: Any, *args: Any, **kwargs: Any):
            # The final monthly guidance layer historically intercepted a legacy
            # "Parameter catalogue" radio without checking cadence, then called
            # its captured real_radio as "Parameter set" even on 1 h / 10 min.
            # Suppress only that synthetic monthly control outside klima-v2-1m;
            # the inner wrapper already forces the legacy catalogue to its full
            # vocabulary, so no user-visible non-monthly control is lost here.
            values = list(options) if not isinstance(options, str) else [options]
            if (
                str(label) == "Parameter set"
                and str(st.session_state.get("geosphere_resource_id", "")) != "klima-v2-1m"
                and values == list(_MONTHLY_PARAMETER_SET_OPTIONS)
            ):
                return "Core variables"
            return real_radio(label, options, *args, **kwargs)

        def expander(label: Any, *args: Any, **kwargs: Any):
            # Older monthly wrappers may still invoke their explanatory expander
            # while a 1m -> 1h/10min transition is being recomposed. Suppress the
            # monthly-only shell whenever the committed resource is non-monthly.
            # On klima-v2-1m the final guidance layer renders the single intended
            # context block through this same outer boundary.
            if (
                str(label) == _MONTHLY_CONTEXT_LABEL
                and str(st.session_state.get("geosphere_resource_id", "")) != "klima-v2-1m"
            ):
                return nullcontext()
            return real_expander(label, *args, **kwargs)

        st.data_editor, st.info, st.radio, st.expander = editor, info, radio, expander
        try:
            result = previous_selector(legacy, original)
            # Resolve context after the composed selector has committed the
            # private dataset widget into geosphere_resource_id. Rendering it
            # before that hand-off could show stale monthly text on a 1m -> 1h
            # transition even though the selected resource was already hourly.
            resource_id = str(st.session_state.get("geosphere_resource_id", "klima-v2-10min"))
            context = _RESOURCE_CONTEXT.get(resource_id)
            if context:
                real_info(context)
            return result
        finally:
            st.data_editor, st.info, st.radio, st.expander = real_editor, real_info, real_radio, real_expander

    parity._render_geosphere_resource_selector = selector
    proxy._GEOSPHERE_SOURCE_UX_POLISH_V1 = True
