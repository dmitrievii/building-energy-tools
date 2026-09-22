"""Cross-cadence GeoSphere source UX polish.

Keeps provider metadata/provider codes internal while presenting one consistent
English source-selection surface for 10-minute, hourly and monthly resources.
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd


_RESOURCE_CONTEXT = {
    "klima-v2-10min": (
        "Official GeoSphere Austria availability context (translated summary): the 10-minute resource is the recent, "
        "high-resolution observation archive. Its published resource extent begins in May 1992. Actual coverage still "
        "depends on station and parameter; numeric availability is verified from returned observations rather than inferred "
        "from station validity metadata. Matching provider quality flags are loaded where available."
    ),
    "klima-v2-1h": (
        "Official GeoSphere Austria availability context (translated summary): the hourly dataset begins with Vienna "
        "sunshine-duration observations from 1880. Hourly air temperature, humidity and precipitation are documented for a "
        "small number of stations from 1941; measured parameters and station coverage increase continuously from about 1950. "
        "Depending on the parameter, an hourly value can be an instantaneous observation, previous-hour mean, previous-hour "
        "extreme or previous-hour sum. Quality status is provided through matching *_flag fields."
    ),
    "klima-v2-1m": (
        "Official GeoSphere Austria availability context (translated summary): the monthly resource has the longest published "
        "extent (from December 1767) and contains native monthly statistics such as means, extrema, totals and event counts. "
        "Station and parameter coverage varies strongly through the historical record; availability is therefore verified from "
        "returned observations and is not inferred from the station metadata validity interval."
    ),
}

_CANONICAL_LABELS = {
    "dry_bulb_temperature_c": "Air temperature",
    "dry_bulb_temperature_min_c": "Minimum air temperature",
    "dry_bulb_temperature_max_c": "Maximum air temperature",
    "dew_point_temperature_c": "Dew-point temperature",
    "relative_humidity_pct": "Relative humidity",
    "atmospheric_station_pressure_pa": "Station pressure",
    "global_horizontal_radiation_wh_m2": "Global horizontal radiation",
    "direct_normal_radiation_wh_m2": "Direct normal radiation",
    "diffuse_horizontal_radiation_wh_m2": "Diffuse horizontal radiation",
    "wind_speed_m_s": "Wind speed",
    "wind_direction_deg": "Wind direction",
    "wind_gust_speed_m_s": "Wind gust speed",
    "wind_gust_direction_deg": "Wind gust direction",
    "liquid_precipitation_depth_mm": "Precipitation",
    "precipitation_duration_min": "Precipitation duration",
    "snow_depth_cm": "Snow depth",
    "sunshine_duration_s": "Sunshine duration",
    "ground_temperature_0_10m_c": "Ground temperature 0.10 m",
    "ground_temperature_0_20m_c": "Ground temperature 0.20 m",
    "ground_temperature_0_50m_c": "Ground temperature 0.50 m",
    "ground_temperature_1_00m_c": "Ground temperature 1.00 m",
    "ground_temperature_2_00m_c": "Ground temperature 2.00 m",
}


def _english_variable_name(row: pd.Series) -> str:
    canonical = str(row.get("Canonical field", "")).strip()
    if canonical in _CANONICAL_LABELS:
        return _CANONICAL_LABELS[canonical]
    # Monthly canonical/provider field identifiers are deliberately stable and
    # English-readable after replacing separators; provider German long names
    # remain available in the metadata expander for provenance.
    if canonical:
        return canonical.replace("_", " ").strip().capitalize()
    provider = str(row.get("Provider", "")).strip()
    return provider or str(row.get("Measured variable", ""))


def _wrap_marker_labels(payload: Any) -> Any:
    if not isinstance(payload, list):
        return payload
    wrapped: list[Any] = []
    for item in payload:
        if not isinstance(item, list) or len(item) < 4:
            wrapped.append(item)
            continue
        row = list(item)
        label = str(row[3])
        parts = [part.strip() for part in label.split(" · ") if part.strip()]
        if len(parts) > 1:
            # 2–3 compact lines: station; ID/elevation; validity/remaining data.
            if len(parts) <= 3:
                label = "<br>".join(parts)
            else:
                label = "<br>".join((parts[0], " · ".join(parts[1:3]), " · ".join(parts[3:])))
        row[3] = label
        wrapped.append(row)
    return wrapped


def install_source_ux_polish(proxy: Any, parity: Any) -> None:
    if bool(getattr(proxy, "_GEOSPHERE_SOURCE_UX_POLISH_V1", False)):
        return
    st = parity.st

    # Keep map marker payload compact, but make the hover card readable instead
    # of one viewport-wide line.
    if hasattr(proxy, "station_marker_payload"):
        previous_payload = proxy.station_marker_payload

        def marker_payload(data: Any, *args: Any, **kwargs: Any):
            return _wrap_marker_labels(previous_payload(data, *args, **kwargs))

        proxy.station_marker_payload = marker_payload

    previous_selector = parity._render_geosphere_resource_selector

    def selector(legacy: Any, original: Callable) -> Any:
        real_editor = st.data_editor
        real_dataframe = st.dataframe
        real_info = st.info
        real_folium = getattr(proxy, "st_folium", None)
        context_rendered = {"value": False}

        def editor(data: Any, *args: Any, **kwargs: Any):
            if isinstance(data, pd.DataFrame) and {"Measured variable", "Provider"}.issubset(data.columns):
                display = data.copy()
                display["Measured variable"] = display.apply(_english_variable_name, axis=1)
                return real_editor(display, *args, **kwargs)
            return real_editor(data, *args, **kwargs)

        def dataframe(data: Any = None, *args: Any, **kwargs: Any):
            # The expanded metadata table is also user-facing: normalize its
            # variable names to English while retaining provider codes verbatim.
            if isinstance(data, pd.DataFrame) and {"Variable", "Provider", "Availability"}.issubset(data.columns):
                display = data.copy()
                reverse = {str(row.get("Provider", "")): _english_variable_name(row) for _, row in data.iterrows()}
                display["Variable"] = [reverse.get(str(provider), str(value)) for provider, value in zip(display["Provider"], display["Variable"], strict=False)]
                data = display
            return real_dataframe(data, *args, **kwargs)

        def info(body: Any, *args: Any, **kwargs: Any):
            text = str(body)
            if text.startswith("Official GeoSphere Austria availability context"):
                # Monthly used to render this inside the narrow right station
                # column. The unified context is rendered directly below map.
                return None
            return real_info(body, *args, **kwargs)

        def folium(*args: Any, **kwargs: Any):
            result = real_folium(*args, **kwargs)
            if not context_rendered["value"]:
                resource_id = str(st.session_state.get("geosphere_resource_id", "klima-v2-10min"))
                text = _RESOURCE_CONTEXT.get(resource_id)
                if text:
                    real_info(text)
                    context_rendered["value"] = True
            return result

        st.data_editor = editor
        st.dataframe = dataframe
        st.info = info
        if callable(real_folium):
            proxy.st_folium = folium
        try:
            return previous_selector(legacy, original)
        finally:
            st.data_editor = real_editor
            st.dataframe = real_dataframe
            st.info = real_info
            if callable(real_folium):
                proxy.st_folium = real_folium

    parity._render_geosphere_resource_selector = selector
    proxy._GEOSPHERE_SOURCE_UX_POLISH_V1 = True
