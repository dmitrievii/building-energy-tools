"""Canonical-page UI binding for GeoSphere ``klima-v2-1m``.

The monthly resource changes temporal capabilities, not the product information
architecture. It therefore uses the same top-level analysis pages and shared
chart engines as EPW and higher-resolution GeoSphere resources. Controls that
would imply sub-monthly information are removed or capability-gated.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

import pandas as pd

from . import geosphere
from .geosphere_monthly import (
    MONTHLY_DOI,
    MONTHLY_RESOURCE_ID,
    monthly_coverage_table,
)


MONTHLY_ALLOWED_GENERIC_CHART_TYPES = (
    "Profile with min-mean-max ribbon",
    "Middle 90% range with median",
    "Heat map",
    "Histogram",
    "Monthly boxplot",
    "Monthly violin plot",
)
MONTHLY_ALLOWED_AGGREGATIONS = ("Monthly", "Annual")
MONTHLY_HEATMAP_PERIODS = ("Month",)
MONTHLY_COMPARE_DIMENSIONS = ("Year",)
MONTHLY_HUMIDITY_ANALYSIS_OPTIONS = (
    "Humidity variable explorer",
    "Psychrometric chart",
)

# Provider monthly statistics that have a direct, physically compatible
# canonical interpretation at the source interval (= one calendar month).
# The provider-native columns remain in the frame as well.
_MONTHLY_CANONICAL_ALIASES: dict[str, str] = {
    "tl_mittel": "dry_bulb_temperature_c",
    "tlmin": "dry_bulb_temperature_min_c",
    "tlmax": "dry_bulb_temperature_max_c",
    "rf_mittel": "relative_humidity_pct",
    "tp_mittel": "dew_point_temperature_c",
    "p": "atmospheric_station_pressure_pa",
    "rr": "liquid_precipitation_depth_mm",
    "so_h": "sunshine_duration_s",
    "tb10_mittel": "ground_temperature_0_10m_c",
    "tb20_mittel": "ground_temperature_0_20m_c",
    "tb50_mittel": "ground_temperature_0_50m_c",
    "tb100_mittel": "ground_temperature_1_00m_c",
    "tb200_mittel": "ground_temperature_2_00m_c",
}


def _normalise_unit(value: object) -> str:
    return str(value or "").strip().lower().replace("℃", "°c").replace(" ", "")


def _alias_scale(provider: str, unit: str) -> float | None:
    normalized = _normalise_unit(unit)
    if provider == "p":
        if normalized in {"hpa", "mbar"}:
            return 100.0
        if normalized == "pa":
            return 1.0
        return None
    if provider == "so_h":
        if normalized in {"h", "hr", "hour", "hours"}:
            return 3600.0
        if normalized in {"s", "sec"}:
            return 1.0
        return None
    return 1.0


def monthly_analysis_frame(dataset: Any) -> pd.DataFrame:
    """Return provider-native monthly data plus safe canonical aliases."""
    source = dataset.data
    frame = source.copy()
    frame.attrs.update(source.attrs)
    metadata = source.attrs.get("geosphere_parameter_metadata", {})
    aliases: dict[str, str] = {}
    if isinstance(metadata, Mapping):
        for provider, canonical in _MONTHLY_CANONICAL_ALIASES.items():
            if provider not in frame.columns:
                continue
            info = metadata.get(provider, {})
            unit = str(info.get("unit") or "") if isinstance(info, Mapping) else ""
            scale = _alias_scale(provider, unit)
            if scale is None:
                continue
            frame[canonical] = pd.to_numeric(frame[provider], errors="coerce") * float(scale)
            aliases[provider] = canonical
    frame.attrs["geosphere_monthly_canonical_aliases"] = aliases
    frame.attrs["canonical_frame_role"] = "native-monthly"
    frame.attrs["canonical_native_resolution"] = "monthly"
    frame.attrs["canonical_analysis_resolution"] = "monthly"
    return frame


def _classify_monthly_parameter(provider: str, long_name: str) -> str | None:
    """Classify one provider parameter into the existing canonical page taxonomy."""
    name = str(provider).strip().lower()
    text = f"{name} {str(long_name).strip().lower()}"

    if (
        name.startswith(("tl", "tb", "ts", "gras", "bet"))
        or name.startswith("temp")
        or name in {"frost", "eis", "sommer", "tropen", "stfrost", "gradt"}
        or "temperatur" in text
        or "frost" in text
    ):
        return "Temperature"
    if (
        name.startswith(("rf", "dampf", "absf", "feucht", "schwuel", "eschwuel", "enth", "aequi", "efftemp"))
        or "feuchte" in text
        or "humidity" in text
        or "dampf" in text
        or "taupunkt" in text
    ):
        return "Humidity and Psychrometrics"
    if name.startswith(("cglo", "global")) or "strahlung" in text or "radiation" in text:
        return "Solar and Radiation"
    if (
        name.startswith(("so", "sonn", "sicht", "nebel", "heit", "trueb", "schoenw"))
        or "sonnen" in text
        or "sunshine" in text
        or "sicht" in text
        or "nebel" in text
        or "cloud" in text
    ):
        return "Sky and Daylight"
    if (
        name.startswith(("bewm", "dd", "w6", "w8", "v60", "v70", "v80", "v100"))
        or "wind" in text
    ):
        return "Wind and Ventilation"
    if (
        name.startswith(("rr", "sch", "sh", "hagel", "graupel", "reif", "raureif"))
        or "niederschlag" in text
        or "precip" in text
        or "schnee" in text
        or "snow" in text
        or "hagel" in text
    ):
        return "Precipitation and Snow"
    return None


def _standard_label_for_column(legacy: Any, column: str) -> str | None:
    for label, value in legacy.VARIABLES.items():
        if isinstance(value, tuple) and len(value) >= 2 and str(value[0]) == str(column):
            return str(label)
    return None


def monthly_variable_registry(legacy: Any, dataset: Any, frame: pd.DataFrame) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Register monthly fields in the shared variable vocabulary and page taxonomy."""
    source = dataset.data
    metadata = source.attrs.get("geosphere_parameter_metadata", {})
    physical = tuple(source.attrs.get("geosphere_selected_physical_parameters", ()))
    aliases = frame.attrs.get("geosphere_monthly_canonical_aliases", {})
    groups: dict[str, list[str]] = defaultdict(list)
    label_to_provider: dict[str, str] = {}
    used_labels: set[str] = set()

    for provider in physical:
        if provider not in frame.columns:
            continue
        info = metadata.get(provider, {}) if isinstance(metadata, Mapping) else {}
        long_name = str(info.get("long_name") or provider) if isinstance(info, Mapping) else str(provider)
        provider_unit = str(info.get("unit") or "") if isinstance(info, Mapping) else ""
        canonical = aliases.get(provider) if isinstance(aliases, Mapping) else None

        label: str
        column: str
        unit: str
        standard = _standard_label_for_column(legacy, str(canonical)) if canonical else None
        if standard:
            label = standard
            column, unit = legacy.VARIABLES[standard]
        else:
            label = long_name
            if label in used_labels or label in legacy.VARIABLES:
                label = f"{long_name} — {provider}"
            column = str(provider)
            unit = provider_unit
            legacy.VARIABLES[label] = (column, unit)

        if label not in used_labels:
            used_labels.add(label)
            label_to_provider[label] = str(provider)
            groups["Time Series and Overlay"].append(label)
            page = _classify_monthly_parameter(str(provider), long_name)
            if page:
                groups[page].append(label)

    return dict(groups), label_to_provider


def monthly_page_names(groups: Mapping[str, list[str]]) -> tuple[str, ...]:
    pages: list[str] = ["Climate File Source", "Overview"]
    for page in (
        "Temperature",
        "Humidity and Psychrometrics",
        "Solar and Radiation",
        "Sky and Daylight",
        "Wind and Ventilation",
        "Precipitation and Snow",
    ):
        if groups.get(page):
            pages.append(page)
    if groups.get("Time Series and Overlay"):
        pages.append("Time Series and Overlay")
    pages.append("Data Quality")
    return tuple(pages)


def _monthly_sidebar_filters(legacy: Any, df: pd.DataFrame) -> pd.DataFrame:
    st = legacy.st
    st.sidebar.markdown("### Data filter")
    if df.empty:
        st.session_state["_active_filtered_export_df"] = df
        return df

    source_start = pd.Timestamp(df.index.min())
    source_end = pd.Timestamp(df.index.max())
    years = legacy.available_years(df)
    st.sidebar.caption(f"Available: {source_start.strftime('%b %Y')} → {source_end.strftime('%b %Y')}")
    st.sidebar.caption("Native temporal resolution: monthly. Hour/day filters are not applicable.")

    range_mode = st.sidebar.selectbox(
        "Range",
        ["All available", "Year", "Custom"],
        index=0,
        key="global_data_range_mode",
    )
    ranged = df
    selected_year: int | None = None
    start_value = None
    end_value = None
    if range_mode == "Year":
        selected_year = int(
            st.sidebar.selectbox(
                "Year",
                years,
                index=max(len(years) - 1, 0),
                key="global_data_range_year",
            )
        )
        ranged = legacy.filter_year(df, selected_year)
    elif range_mode == "Custom":
        cols = st.sidebar.columns(2)
        start_date = cols[0].date_input(
            "From date",
            value=source_start.date(),
            min_value=source_start.date(),
            max_value=source_end.date(),
            key="global_data_range_start_date",
        )
        end_date = cols[1].date_input(
            "To date",
            value=source_end.date(),
            min_value=source_start.date(),
            max_value=source_end.date(),
            key="global_data_range_end_date",
        )
        start_value = pd.Timestamp(start_date)
        end_value = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        if start_value > end_value:
            st.sidebar.error("From must not be later than start date.")
            ranged = df.iloc[0:0].copy()
        else:
            ranged = legacy.filter_datetime_range(df, start=start_value, end=end_value)

    ranged_years = legacy.available_years(ranged) if not ranged.empty else []
    if len(ranged_years) > 1:
        basis = st.sidebar.selectbox(
            "Time basis",
            [legacy.CHRONOLOGICAL, legacy.CALENDAR_PROFILE],
            index=0,
            key="global_time_basis",
            help=(
                "Chronological keeps every published month in sequence. Calendar profile aligns the same calendar month "
                "across source years for multi-year monthly statistics."
            ),
        )
    else:
        basis = legacy.CHRONOLOGICAL
    ranged = legacy.with_time_basis(ranged, basis)

    selected_names = st.sidebar.multiselect(
        "Months",
        list(legacy.MONTHS.keys()),
        default=list(legacy.MONTHS.keys()),
        key="global_months_monthly_source",
    )
    months = [legacy.MONTHS[name] for name in selected_names]
    index = pd.DatetimeIndex(ranged.index)
    filtered = ranged.loc[index.month.isin(months)].copy()
    filtered.attrs.update(ranged.attrs)
    filtered = legacy.with_time_basis(filtered, basis)
    st.session_state["_active_global_filter_spec"] = {
        "range_mode": range_mode,
        "year": selected_year,
        "start": start_value,
        "end": end_value,
        "basis": basis,
        "months": tuple(months),
        "hours": None,
        "native_resolution": "monthly",
    }
    st.session_state["_active_filtered_export_df"] = filtered
    return filtered


def _monthly_interpretation(_df: pd.DataFrame, _column: str, label: str, unit: str) -> str:
    suffix = f" [{unit}]" if unit else ""
    return (
        f"{label.capitalize()}{suffix} is shown at the native GeoSphere monthly resolution. "
        "No hourly or daily values are reconstructed, interpolated or inferred."
    )


def _render_monthly_generic(legacy: Any, df: pd.DataFrame, labels: list[str], title: str) -> None:
    if not labels:
        legacy.st.info("No variables for this analysis are available in the active monthly dataset.")
        return
    st = legacy.st
    real_selectbox = st.selectbox

    def selectbox(label: str, options: Any, *args: Any, **kwargs: Any):
        values = list(options)
        replacement = None
        if label == "Chart type":
            replacement = [value for value in values if value in MONTHLY_ALLOWED_GENERIC_CHART_TYPES]
        elif label == "Aggregation":
            replacement = list(MONTHLY_ALLOWED_AGGREGATIONS)
        elif label == "Heat-map aggregation":
            replacement = ["Month"]
            kwargs["disabled"] = True
        elif label == "Compare across":
            replacement = ["Year"]
            kwargs["disabled"] = True
        if replacement is not None:
            values = replacement
            kwargs["index"] = 0
        return real_selectbox(label, values, *args, **kwargs)

    st.selectbox = selectbox
    try:
        legacy.render_generic_variable_page(
            df,
            labels,
            labels[0],
            title,
            _monthly_interpretation,
        )
    finally:
        st.selectbox = real_selectbox


def _monthly_psychrometric_ready(df: pd.DataFrame) -> bool:
    """Return whether at least one representative monthly moist-air state exists."""
    required = ("dry_bulb_temperature_c", "relative_humidity_pct")
    if any(column not in df.columns for column in required):
        return False
    pair = pd.DataFrame(
        {
            column: pd.to_numeric(df[column], errors="coerce")
            for column in required
        },
        index=df.index,
    )
    return bool(pair.notna().all(axis=1).any())


def _monthly_reference_pressure(legacy: Any, df: pd.DataFrame) -> float:
    """Return a representative pressure for chart background curves."""
    if "atmospheric_station_pressure_pa" in df.columns:
        values = pd.to_numeric(df["atmospheric_station_pressure_pa"], errors="coerce")
        values = values.loc[values.between(30_000.0, 120_000.0)]
        if not values.empty:
            return float(values.median())
    return float(getattr(legacy, "DEFAULT_PRESSURE_PA", 101325.0))


def _render_monthly_humidity(legacy: Any, filtered: pd.DataFrame, labels: list[str], title: str) -> None:
    """Render monthly humidity with a physically valid representative-state chart."""
    st = legacy.st
    psychrometric_ready = _monthly_psychrometric_ready(filtered)
    options = list(MONTHLY_HUMIDITY_ANALYSIS_OPTIONS if psychrometric_ready else MONTHLY_HUMIDITY_ANALYSIS_OPTIONS[:1])
    analysis = st.selectbox(
        "Analysis type",
        options,
        index=0,
        key="monthly_humidity_analysis_v1",
        help=(
            "The psychrometric chart uses one representative state per published month. "
            "No hourly distribution, duration, or threshold count is reconstructed."
        ),
    )
    st.caption(
        "Native monthly source: sub-monthly analyses are unavailable. Only graph operations that remain physically meaningful for published monthly statistics are enabled."
    )

    if analysis != "Psychrometric chart":
        _render_monthly_generic(legacy, filtered, labels, title)
        return

    pressure_pa = _monthly_reference_pressure(legacy, filtered)
    psychrometric = legacy.add_psychrometric_properties(filtered, fallback_pressure_pa=pressure_pa)
    valid = psychrometric[["dry_bulb_temperature_c", "humidity_ratio_g_kg"]].dropna()
    if valid.empty:
        st.info("No complete monthly temperature / relative-humidity state is available for the psychrometric chart.")
        return

    chart_type = st.radio(
        "Psychrometric axes",
        ["T-d", "i-d"],
        horizontal=True,
        key="monthly_psychrometric_axes_v1",
    )
    st.caption(
        "Each point is one published monthly-mean temperature / relative-humidity state. Derived dew point, humidity ratio, enthalpy and wet-bulb temperature describe that representative monthly state; they are not arithmetic means of unobserved hourly psychrometric quantities."
    )
    fig = legacy.psychrometric_chart(
        psychrometric,
        chart_type=chart_type,
        pressure_pa=pressure_pa,
        show_rh_curves=True,
        show_comfort_zone=False,
        data_mode="Monthly points",
        metric_layers=["Relative humidity"],
        color_mode="Month",
    )
    legacy.render_plot(
        fig,
        "Representative monthly psychrometric states from published monthly mean temperature and relative humidity; no sub-monthly distribution is inferred.",
    )


def _render_monthly_overview(legacy: Any, dataset: Any, filtered: pd.DataFrame) -> None:
    st = legacy.st
    st.header("Climate overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("First month", pd.Timestamp(filtered.index.min()).strftime("%Y-%m"))
    c2.metric("Last month", pd.Timestamp(filtered.index.max()).strftime("%Y-%m"))
    c3.metric("Monthly records", f"{len(filtered):,}")
    physical = tuple(dataset.data.attrs.get("geosphere_selected_physical_parameters", ()))
    c4.metric("Loaded variables", len(physical))
    st.subheader("Actual per-variable coverage")
    st.dataframe(monthly_coverage_table(dataset.data), hide_index=True, use_container_width=True)
    st.caption(
        "Coverage is evaluated independently for each provider variable. A valid early sunshine series is retained even when another variable starts later."
    )


def _render_monthly_quality(legacy: Any, dataset: Any) -> None:
    st = legacy.st
    data = dataset.data
    st.header("Data quality")
    st.subheader("Per-variable coverage")
    st.dataframe(monthly_coverage_table(data), hide_index=True, use_container_width=True)

    metadata = data.attrs.get("geosphere_parameter_metadata", {})
    physical = tuple(data.attrs.get("geosphere_selected_physical_parameters", ()))
    rows = []
    for provider in physical:
        info = metadata.get(provider, {}) if isinstance(metadata, Mapping) else {}
        rows.append(
            {
                "Provider": provider,
                "Variable": info.get("long_name") or provider,
                "Unit": info.get("unit") or "",
                "Description": info.get("description") or "",
            }
        )
    st.subheader("Loaded parameter metadata")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    flag_columns = [column for column in data.columns if str(column).startswith(geosphere.QUALITY_FLAG_COLUMN_PREFIX)]
    if not flag_columns:
        st.info("No quality flags were loaded. Flag transfer is opt-in at source selection.")
        return
    codebooks = data.attrs.get(geosphere.QUALITY_CODEBOOK_ATTR, {})
    quality_rows: list[dict[str, object]] = []
    for column in flag_columns:
        provider = str(column).removeprefix(geosphere.QUALITY_FLAG_COLUMN_PREFIX)
        counts = pd.to_numeric(data[column], errors="coerce").value_counts(dropna=False)
        codebook = codebooks.get(provider, {}) if isinstance(codebooks, Mapping) else {}
        for code, count in counts.items():
            if pd.isna(code):
                state = "missing"
            else:
                code_int = int(code)
                state = str(codebook.get(code_int, code_int)) if isinstance(codebook, Mapping) else str(code_int)
            quality_rows.append({"Provider": provider, "Quality state": state, "Months": int(count)})
    st.subheader("Loaded quality flags")
    st.dataframe(pd.DataFrame(quality_rows), hide_index=True, use_container_width=True)


def render_monthly_canonical_analysis(legacy: Any, dataset: Any) -> None:
    """Render ``klima-v2-1m`` through the shared canonical page architecture."""
    st = legacy.st
    legacy._ensure_analysis_dependencies(include_solar=False, include_comparison=False)
    full = monthly_analysis_frame(dataset)
    groups, _label_to_provider = monthly_variable_registry(legacy, dataset, full)
    pages = monthly_page_names(groups)

    if legacy.NAVIGATION_KEY not in st.session_state or st.session_state[legacy.NAVIGATION_KEY] not in pages:
        st.session_state[legacy.NAVIGATION_KEY] = "Overview"
    st.sidebar.markdown("### Explore")
    page = st.sidebar.radio(
        "Analysis section",
        pages,
        format_func=legacy.navigation_label,
        key=legacy.NAVIGATION_KEY,
        label_visibility="collapsed",
    )
    if page == "Climate File Source":
        legacy.render_climate_file_source()
        return

    filtered = full if page == "Data Quality" else _monthly_sidebar_filters(legacy, full)
    if filtered.empty:
        st.warning("The current Data filter removes all monthly records.")
        return

    st.sidebar.markdown("### Current climate")
    st.sidebar.write(f"**{dataset.location.city}, {dataset.location.country}**")
    st.sidebar.caption("GeoSphere Austria · native monthly climatological statistics")
    st.sidebar.write(f"Monthly rows in current view: {len(filtered):,}")
    with st.sidebar.expander("Data provenance", expanded=False):
        st.caption(dataset.provenance.dataset)
        st.caption(f"Dataset DOI: {MONTHLY_DOI}")
        st.caption("Native resolution: monthly")
        st.caption("No hourly or daily reconstruction is applied.")

    if page == "Overview":
        _render_monthly_overview(legacy, dataset, filtered)
        return
    if page == "Data Quality":
        _render_monthly_quality(legacy, dataset)
        return
    if page == "Time Series and Overlay":
        # There is intentionally no monthly Plotly renderer here. The source
        # capability layer forwards into the same canonical overlay renderer as
        # every other source; its only job is to gate resolutions/semantics.
        legacy.render_time_series_overlay(filtered)
        return

    titles = {
        "Temperature": "Temperature and extremes",
        "Humidity and Psychrometrics": "Humidity and psychrometrics",
        "Solar and Radiation": "Solar and radiation",
        "Sky and Daylight": "Sky and daylight",
        "Wind and Ventilation": "Wind and ventilation",
        "Precipitation and Snow": "Precipitation and snow",
    }

    if page == "Humidity and Psychrometrics":
        st.header(titles[page])
        _render_monthly_humidity(legacy, filtered, groups.get(page, []), titles[page])
        return

    st.header(titles.get(page, page))
    analysis_label = {
        "Temperature": "Temperature variable explorer",
        "Solar and Radiation": "Solar/radiation variable explorer",
        "Sky and Daylight": "Sky/daylight variable explorer",
        "Wind and Ventilation": "Wind variable explorer",
        "Precipitation and Snow": "Precipitation/snow variable explorer",
    }.get(page, "Variable explorer")
    st.selectbox("Analysis type", [analysis_label], index=0, disabled=True, key=f"monthly_locked_analysis_{page}")
    st.caption(
        "Native monthly source: sub-monthly analyses are unavailable. Only graph operations that remain physically meaningful for published monthly statistics are enabled."
    )
    _render_monthly_generic(legacy, filtered, groups.get(page, []), titles.get(page, page))


def install_monthly_canonical_ui(proxy: Any, parity: Any) -> None:
    """Bind the native-monthly source to canonical analysis pages."""
    if bool(getattr(proxy, "_GEOSPHERE_MONTHLY_CANONICAL_UI_INSTALLED", False)):
        return
    previous = proxy.render_canonical_climate_analysis

    def render(dataset: Any) -> None:
        resource_id = str(getattr(dataset, "data", pd.DataFrame()).attrs.get("geosphere_resource_id", ""))
        if resource_id == MONTHLY_RESOURCE_ID:
            render_monthly_canonical_analysis(proxy, dataset)
            return
        previous(dataset)

    proxy.render_canonical_climate_analysis = render
    proxy._GEOSPHERE_MONTHLY_CANONICAL_UI_INSTALLED = True
