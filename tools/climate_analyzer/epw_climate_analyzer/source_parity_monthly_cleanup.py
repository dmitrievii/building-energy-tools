"""Canonical cleanup for GeoSphere ``klima-v2-1m``.

The monthly provider changes capabilities and metadata, not chart engines.  This
module is installed after the monthly resource/canonical-page bindings and:

* removes repeated provider-description blocks from analysis pages;
* provides a curated Recommended parameter catalogue while retaining every
  provider field in an explicit All parameters view;
* explains historical climate-observation Terms I/II/III in-place;
* enables Monthly and Annual grouping where it is meaningful without any
  sub-monthly reconstruction;
* routes monthly overlay rendering through the shared OverlaySeries /
  build_overlay_figure engine instead of a source-specific Plotly renderer;
* carries monthly statistic semantics into annual overlay aggregation; and
* applies the common semantic colour families to monthly variables.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping

import pandas as pd

from . import chart_theme, charts, source_parity_monthly_canonical as monthly_ui, timeseries
from .climate_model import aggregation_semantics_for
from .geosphere_monthly import (
    MONTHLY_DATASET_PAGE,
    MONTHLY_DOI,
    MONTHLY_OFFICIAL_CONTEXT_EN,
    MONTHLY_RESOURCE_ID,
    monthly_coverage_table,
)


MONTHLY_GENERIC_AGGREGATIONS = ("Monthly", "Annual")
MONTHLY_OVERLAY_RESOLUTIONS = ("Monthly", "Annual")

_TERM_SCHEDULE = (
    "Historical climate-observation schedule: until 1971 Terms I/II/III were "
    "07:00/14:00/21:00 MOZ; from 1971 to 2003 they were 07:00/14:00/19:00 MOZ; "
    "since 2003 they are 07:00/14:00/19:00 MEZ. A term therefore describes a "
    "historical observation time, not one fixed UTC timestamp over the full record."
)

_KNOWN_MONTHLY_FIELDS: dict[str, tuple[str, str, str, bool]] = {
    "tl_mittel": ("Air temperature — monthly mean", "Temperature", "mean", True),
    "tlmin": ("Air temperature — absolute monthly minimum", "Temperature", "min", True),
    "tlmax": ("Air temperature — absolute monthly maximum", "Temperature", "max", True),
    "rf_mittel": ("Relative humidity — monthly mean", "Humidity and Psychrometrics", "mean", True),
    "tp_mittel": ("Dew-point temperature — monthly mean", "Humidity and Psychrometrics", "mean", True),
    "p": ("Station pressure — monthly mean", "Humidity and Psychrometrics", "mean", True),
    "rr": ("Precipitation — monthly total", "Precipitation and Snow", "sum", True),
    "so_h": ("Sunshine duration — monthly total", "Sky and Daylight", "sum", True),
    "tb10_mittel": ("Ground temperature 0.10 m — monthly mean", "Temperature", "mean", True),
    "tb20_mittel": ("Ground temperature 0.20 m — monthly mean", "Temperature", "mean", True),
    "tb50_mittel": ("Ground temperature 0.50 m — monthly mean", "Temperature", "mean", True),
    "tb100_mittel": ("Ground temperature 1.00 m — monthly mean", "Temperature", "mean", True),
    "tb200_mittel": ("Ground temperature 2.00 m — monthly mean", "Temperature", "mean", True),
}

_BLOCK_FROM_RECOMMENDED = (
    "termin", "beobachtungstermin", "observation time", "sicht", "visibility",
    "nebel", "fog", "hagel", "hail", "gewitter", "thunder", "glatteis",
    "klasse", "class", "verteilung", "distribution", "erschein", "phenomen",
)


@dataclass(frozen=True)
class MonthlyParameterDescriptor:
    provider: str
    label: str
    category: str
    statistic: str
    annual_semantics: str | None
    recommended: bool
    note: str


def _text(*values: object) -> str:
    return " ".join(str(value or "").strip().lower() for value in values)


def _observation_term(value: str) -> int | None:
    match = re.search(r"(?:termin|beobachtungstermin|observation[ -]?time)\s*([iv]{1,3}|[123])\b", value, re.I)
    if not match:
        return None
    raw = match.group(1).lower()
    return {"i": 1, "ii": 2, "iii": 3, "1": 1, "2": 2, "3": 3}.get(raw)


def monthly_category(provider: str, long_name: str = "", description: str = "") -> str:
    name = str(provider).strip().lower()
    text = _text(provider, long_name, description)
    if (
        name.startswith(("tl", "tb", "ts", "gras", "bet", "temp"))
        or "temperatur" in text or "temperature" in text or "frost" in text
    ):
        return "Temperature"
    if (
        name.startswith(("rf", "dampf", "absf", "feucht", "schwuel", "eschwuel", "enth", "aequi", "efftemp", "tp"))
        or "feuchte" in text or "humidity" in text or "dampf" in text or "taupunkt" in text or "dew point" in text
        or name == "p" or "luftdruck" in text or "pressure" in text
    ):
        return "Humidity and Psychrometrics"
    if name.startswith(("cglo", "global")) or "strahlung" in text or "radiation" in text or "irradi" in text:
        return "Solar and Radiation"
    if (
        name.startswith(("so", "sonn", "sicht", "nebel", "heit", "trueb", "schoenw"))
        or "sonnen" in text or "sunshine" in text or "sicht" in text or "visibility" in text
        or "nebel" in text or "cloud" in text
    ):
        return "Sky and Daylight"
    if name.startswith(("bewm", "dd", "ff", "w6", "w8", "v60", "v70", "v80", "v100")) or "wind" in text:
        return "Wind and Ventilation"
    if (
        name.startswith(("rr", "sch", "sh", "hagel", "graupel", "reif", "raureif"))
        or "niederschlag" in text or "precip" in text or "schnee" in text or "snow" in text or "hagel" in text
    ):
        return "Precipitation and Snow"
    return "Other monthly parameters"


def _statistic_contract(provider: str, long_name: str, description: str, category: str) -> tuple[str, str | None, str]:
    known = _KNOWN_MONTHLY_FIELDS.get(str(provider))
    if known:
        semantics = known[2]
        label = {
            "mean": "Monthly mean",
            "min": "Absolute monthly minimum",
            "max": "Absolute monthly maximum",
            "sum": "Monthly total",
        }[semantics]
        return label, semantics, ""

    text = _text(provider, long_name, description)
    term = _observation_term(text)
    if term is not None:
        return f"Observation-time monthly mean · Term {('I', 'II', 'III')[term - 1]}", "mean", _TERM_SCHEDULE
    if ("absolute" in text or "absolut" in text) and ("minimum" in text or "minimal" in text):
        return "Absolute monthly minimum", "min", "Annual aggregation takes the minimum of the published monthly minima."
    if ("absolute" in text or "absolut" in text) and ("maximum" in text or "maximal" in text):
        return "Absolute monthly maximum", "max", "Annual aggregation takes the maximum of the published monthly maxima."
    if "minimum" in text or "minimalwert" in text or re.search(r"(?:^|_)min(?:$|_)", str(provider).lower()):
        return "Monthly minimum", "min", ""
    if "maximum" in text or "maximalwert" in text or re.search(r"(?:^|_)max(?:$|_)", str(provider).lower()):
        return "Monthly maximum", "max", ""
    if "summe" in text or "monatssumme" in text or "monthly total" in text or "monthly sum" in text:
        return "Monthly total", "sum", "Annual aggregation sums the published monthly totals."
    if any(token in text for token in ("anzahl", "tage", "days", "count", "häufigkeit", "frequency")):
        return "Monthly count", "sum", "Annual aggregation sums the published monthly counts."
    if category == "Wind and Ventilation" and ("richtung" in text or "direction" in text or str(provider).lower().startswith("dd")):
        return "Monthly circular mean", "circular mean", "Annual aggregation uses a circular mean for direction."
    if "mittel" in text or "monthly mean" in text or "average" in text or "mean" in text:
        return "Monthly mean", "mean", "Annual aggregation averages the published monthly values."
    return "Provider-defined monthly statistic", None, "See the original GeoSphere parameter description in All parameters before interpreting annual aggregation."


def describe_monthly_parameter(
    provider: str,
    long_name: str = "",
    description: str = "",
    unit: str = "",
) -> MonthlyParameterDescriptor:
    provider = str(provider).strip()
    category = monthly_category(provider, long_name, description)
    statistic, semantics, note = _statistic_contract(provider, long_name, description, category)
    known = _KNOWN_MONTHLY_FIELDS.get(provider)
    if known:
        label = known[0]
        recommended = bool(known[3])
    else:
        label = str(long_name).strip() or provider
        text = _text(provider, long_name, description)
        blocked = any(token in text for token in _BLOCK_FROM_RECOMMENDED)
        core_candidate = (
            category in {"Solar and Radiation", "Wind and Ventilation", "Precipitation and Snow"}
            and semantics in {"mean", "sum", "min", "max", "circular mean"}
        )
        # Keep the default catalogue deliberately short.  Additional provider
        # statistics remain one click away in All parameters.
        recommended = bool(core_candidate and not blocked and len(label) <= 90)
    if unit and unit not in label and label == provider:
        label = f"{label} [{unit}]"
    return MonthlyParameterDescriptor(provider, label, category, statistic, semantics, recommended, note)


def semantic_analysis_column(provider: str, descriptor: MonthlyParameterDescriptor) -> str:
    semantics = (descriptor.annual_semantics or "unknown").replace(" ", "_")
    category = re.sub(r"[^a-z0-9]+", "_", descriptor.category.lower()).strip("_") or "other"
    provider_slug = re.sub(r"[^a-zA-Z0-9_]+", "_", str(provider)).strip("_")
    return f"monthly__{semantics}__{category}__{provider_slug}"


def monthly_semantics_from_column(column: str) -> str | None:
    value = str(column)
    if not value.startswith("monthly__"):
        return None
    parts = value.split("__", 3)
    if len(parts) < 4:
        return None
    semantics = parts[1].replace("_", " ")
    return semantics if semantics in {"mean", "sum", "min", "max", "circular mean"} else None


def monthly_metric_color(column: str, fallback: Callable[[str | None], str]) -> str:
    text = str(column).lower()
    if "__temperature__" in text:
        return fallback("dry_bulb_temperature_c")
    if "__humidity_and_psychrometrics__" in text:
        return fallback("relative_humidity_pct")
    if "__solar_and_radiation__" in text or "__sky_and_daylight__" in text or "sunshine" in text:
        return chart_theme.SOLAR_COMPONENT_COLORS["GHI"]
    if "__wind_and_ventilation__" in text:
        return fallback("wind_speed_m_s")
    if "__precipitation_and_snow__" in text:
        return fallback("liquid_precipitation_depth_mm")
    return fallback(column)


def _metadata_descriptor(parity: Any, provider: str, fallback_name: str = "", unit: str = "") -> MonthlyParameterDescriptor:
    description = ""
    long_name = fallback_name
    try:
        bundle = parity._cached_geosphere_resource_bundle(MONTHLY_RESOURCE_ID)
        params = bundle[5] if isinstance(bundle, tuple) and len(bundle) > 5 else {}
        parameter = params.get(provider) if isinstance(params, Mapping) else None
        if parameter is not None:
            long_name = str(getattr(parameter, "long_name", "") or long_name)
            description = str(getattr(parameter, "description", "") or "")
            unit = str(getattr(parameter, "unit", "") or unit)
    except Exception:
        pass
    return describe_monthly_parameter(provider, long_name, description, unit)


def _install_semantic_engines() -> None:
    original_timeseries_semantics = timeseries.aggregation_semantics
    if not bool(getattr(timeseries, "_MONTHLY_SEMANTICS_PATCHED", False)):
        def aggregation_semantics(column: str) -> str:
            monthly = monthly_semantics_from_column(column)
            return monthly or original_timeseries_semantics(column)
        timeseries.aggregation_semantics = aggregation_semantics
        timeseries._MONTHLY_SEMANTICS_PATCHED = True

    if not bool(getattr(chart_theme, "_MONTHLY_COLORS_PATCHED", False)):
        original_theme_color = chart_theme.metric_color
        original_timeseries_color = timeseries.metric_color
        original_charts_color = charts.metric_color

        def theme_color(column: str | None) -> str:
            return monthly_metric_color(str(column or ""), original_theme_color)

        def timeseries_color(column: str | None) -> str:
            return monthly_metric_color(str(column or ""), original_timeseries_color)

        def charts_color(column: str | None) -> str:
            return monthly_metric_color(str(column or ""), original_charts_color)

        chart_theme.metric_color = theme_color
        timeseries.metric_color = timeseries_color
        charts.metric_color = charts_color
        chart_theme._MONTHLY_COLORS_PATCHED = True


def _improved_monthly_registry(legacy: Any, dataset: Any, frame: pd.DataFrame) -> tuple[dict[str, list[str]], dict[str, str]]:
    source = dataset.data
    metadata = source.attrs.get("geosphere_parameter_metadata", {})
    physical = tuple(source.attrs.get("geosphere_selected_physical_parameters", ()))
    aliases = frame.attrs.get("geosphere_monthly_canonical_aliases", {})
    groups: dict[str, list[str]] = defaultdict(list)
    label_to_provider: dict[str, str] = {}
    annual_semantics: dict[str, str] = {}
    descriptors: dict[str, MonthlyParameterDescriptor] = {}
    used_labels: set[str] = set()

    for provider in physical:
        if provider not in frame.columns:
            continue
        info = metadata.get(provider, {}) if isinstance(metadata, Mapping) else {}
        long_name = str(info.get("long_name") or provider) if isinstance(info, Mapping) else str(provider)
        provider_unit = str(info.get("unit") or "") if isinstance(info, Mapping) else ""
        description = str(info.get("description") or "") if isinstance(info, Mapping) else ""
        descriptor = describe_monthly_parameter(provider, long_name, description, provider_unit)
        descriptors[str(provider)] = descriptor
        canonical = aliases.get(provider) if isinstance(aliases, Mapping) else None
        standard = monthly_ui._standard_label_for_column(legacy, str(canonical)) if canonical else None

        if standard:
            label = standard
            column, unit = legacy.VARIABLES[standard]
        else:
            label = descriptor.label
            if label in used_labels or label in legacy.VARIABLES:
                label = f"{descriptor.label} — {provider}"
            column = semantic_analysis_column(str(provider), descriptor)
            frame[column] = pd.to_numeric(frame[provider], errors="coerce")
            unit = provider_unit
            legacy.VARIABLES[label] = (column, unit)
            if descriptor.annual_semantics:
                annual_semantics[column] = descriptor.annual_semantics

        if label in used_labels:
            continue
        used_labels.add(label)
        label_to_provider[label] = str(provider)
        groups["Time Series and Overlay"].append(label)
        if descriptor.category != "Other monthly parameters":
            groups[descriptor.category].append(label)

    frame.attrs["geosphere_monthly_parameter_descriptors"] = descriptors
    frame.attrs["geosphere_monthly_annual_semantics"] = annual_semantics
    frame.attrs["geosphere_monthly_label_to_provider"] = label_to_provider
    return dict(groups), label_to_provider


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
            replacement = [value for value in values if value in monthly_ui.MONTHLY_ALLOWED_GENERIC_CHART_TYPES]
        elif label == "Aggregation":
            replacement = list(MONTHLY_GENERIC_AGGREGATIONS)
            kwargs.pop("disabled", None)
        elif label == "Heat-map aggregation":
            replacement = ["Month"]
            kwargs["disabled"] = True
        elif label == "Compare across":
            replacement = ["Year"]
            kwargs["disabled"] = True
        if replacement is not None:
            values = replacement
            kwargs["index"] = min(int(kwargs.get("index", 0)), len(values) - 1)
        return real_selectbox(label, values, *args, **kwargs)

    st.selectbox = selectbox
    try:
        legacy.render_generic_variable_page(
            df,
            labels,
            labels[0],
            title,
            monthly_ui._monthly_interpretation,
            temperature_thresholds=(18.0, 26.0) if title.startswith("Temperature") else None,
        )
        st.caption(
            "Monthly keeps the published GeoSphere values. Annual groups those published monthly values by real year; "
            "the chart statistic remains explicit. No daily or hourly values are reconstructed."
        )
    finally:
        st.selectbox = real_selectbox


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
        "Coverage is evaluated independently for each provider variable. A valid early series is retained even when another selected variable starts later."
    )


def _render_calendar_monthly_overlay(legacy: Any, df: pd.DataFrame) -> None:
    """Monthly capability adapter around the shared canonical overlay engine."""
    st = legacy.st
    st.header("Time series and overlay")
    st.caption(
        "Source resolution: native calendar month. Overlay uses the same canonical OverlaySeries engine as EPW and hourly GeoSphere. "
        "Annual is derived from the published monthly values according to each variable's aggregation semantics; no sub-monthly interpolation is performed."
    )
    index = pd.DatetimeIndex(df.index).sort_values()
    if index.empty:
        st.info("No time-series records are available.")
        return

    first = pd.Timestamp(index.min()).to_period("M").to_timestamp()
    last = pd.Timestamp(index.max()).to_period("M").to_timestamp()
    c1, c2 = st.columns(2)
    start_date = c1.date_input("From month", value=first.date(), min_value=first.date(), max_value=last.date(), key="overlay_start_date")
    end_date = c2.date_input("Through month", value=last.date(), min_value=first.date(), max_value=last.date(), key="overlay_end_date")
    start = pd.Timestamp(start_date).to_period("M").to_timestamp()
    selected_end = pd.Timestamp(end_date).to_period("M").to_timestamp()
    if selected_end < start:
        st.error("The end month must not be earlier than the start month.")
        return
    if index.tz is not None:
        start = start.tz_localize(index.tz)
        selected_end = selected_end.tz_localize(index.tz)
    end = selected_end + pd.offsets.MonthBegin(1)

    available_variables = [
        label for label, (column, _unit) in legacy.VARIABLES.items()
        if column in df.columns and pd.to_numeric(df[column], errors="coerce").notna().any()
    ]
    if not available_variables:
        st.info("No numeric climate variables are available for overlay.")
        return

    n_series = st.slider("Number of series", min_value=1, max_value=min(6, len(available_variables)), value=min(2, len(available_variables)), step=1)
    preferred = ["Dry-bulb temperature", "Relative humidity", "Liquid precipitation depth", "Sunshine duration", "Station pressure"]
    defaults = [item for item in preferred if item in available_variables]
    specs: list[timeseries.OverlaySeries] = []
    st.markdown("#### Series")

    for i in range(n_series):
        col_variable, col_resolution = st.columns([3, 2])
        default_label = defaults[i] if i < len(defaults) else available_variables[min(i, len(available_variables) - 1)]
        variable_label = col_variable.selectbox(
            f"Series {i + 1} variable", available_variables,
            index=available_variables.index(default_label), key=f"overlay_variable_{i}",
        )
        column, unit = legacy.VARIABLES[variable_label]
        semantics = monthly_semantics_from_column(column) or aggregation_semantics_for(column)
        resolution_options = list(MONTHLY_OVERLAY_RESOLUTIONS)
        if monthly_semantics_from_column(column) is None and column not in monthly_ui._MONTHLY_CANONICAL_ALIASES.values():
            # Unknown provider statistics can still be plotted monthly. Do not
            # invent an annual meaning until their provider contract is known.
            resolution_options = ["Monthly"]
        resolution = col_resolution.selectbox(
            f"Series {i + 1} resolution", resolution_options, index=0, key=f"overlay_resolution_{i}",
            help=(
                "Monthly preserves the published value. Annual applies the canonical quantity semantics "
                f"({semantics}) to the twelve published months when available."
            ),
        )
        style_labels = ["Solid", "Dashed", "Dotted", "Dash-dot"]
        style_to_dash = {"Solid": "solid", "Dashed": "dash", "Dotted": "dot", "Dash-dot": "dashdot"}
        with st.expander(f"Series {i + 1} style", expanded=False):
            s1, s2, s3, s4 = st.columns([1.25, 1.0, 1.0, 1.0])
            line_style = s1.selectbox("Line style", style_labels, index=i % len(style_labels), key=f"overlay_line_style_{i}")
            line_width = s2.slider("Line width", 0.5, 6.0, 2.0, 0.5, key=f"overlay_line_width_{i}")
            line_color = s3.color_picker("Line color", value=monthly_metric_color(column, chart_theme.metric_color), key=f"overlay_line_color_{i}")
            line_opacity = s4.slider("Opacity", 0.2, 1.0, 1.0, 0.05, key=f"overlay_line_opacity_{i}")
        specs.append(timeseries.OverlaySeries(
            variable_label, column, unit, resolution, color=line_color,
            dash=style_to_dash[line_style], width=float(line_width), opacity=float(line_opacity),
        ))

    try:
        families = timeseries.validate_unit_families(specs)
    except ValueError as exc:
        st.error(str(exc) + " Remove a physical quantity or choose variables from the same unit family.")
        return
    raw_view = df.loc[(df.index >= start) & (df.index < end)].copy()
    st.session_state["_active_filtered_export_df"] = raw_view
    if raw_view.empty:
        st.warning("The selected interval contains no published monthly records.")
        return
    try:
        fig, _tables = timeseries.build_overlay_figure(df, specs, start, end, title="Climate time-series overlay")
    except (ValueError, KeyError) as exc:
        st.error(f"The requested overlay could not be constructed: {exc}")
        return
    if len(families) == 2:
        st.caption("Two physical unit families are shown on separate left and right Y-axes.")
    legacy.render_plot(
        fig,
        "The overlay preserves one common calendar time axis and uses the shared canonical aggregation engine. "
        "Monthly values remain provider-published observations/statistics; Annual never fabricates daily or hourly samples.",
    )


def _forward_monthly_overlay(legacy: Any, df: pd.DataFrame, _labels: list[str]) -> None:
    legacy.render_time_series_overlay(df)


def _install_unified_overlay(proxy: Any) -> None:
    original = proxy.render_time_series_overlay
    if bool(getattr(proxy, "_MONTHLY_CANONICAL_OVERLAY_PATCHED", False)):
        return

    def render(df: pd.DataFrame) -> None:
        if str(df.attrs.get("canonical_native_resolution", "")).lower() == "monthly":
            _render_calendar_monthly_overlay(proxy, df)
            return
        original(df)

    proxy.render_time_series_overlay = render
    proxy._MONTHLY_CANONICAL_OVERLAY_PATCHED = True


def _decorate_parameter_table(parity: Any, data: pd.DataFrame) -> pd.DataFrame:
    out = data.copy()
    descriptors: list[MonthlyParameterDescriptor] = []
    for row in out.itertuples(index=False):
        values = row._asdict()
        provider = str(values.get("Provider", ""))
        name = str(values.get("Measured_variable", values.get("Measured variable", "")) or provider)
        unit = str(values.get("Unit", "") or "")
        descriptors.append(_metadata_descriptor(parity, provider, name, unit))
    out["Category"] = [item.category for item in descriptors]
    out["Statistic"] = [item.statistic for item in descriptors]
    out["Notes"] = [item.note for item in descriptors]
    out["_recommended"] = [item.recommended for item in descriptors]
    out["Original GeoSphere name"] = out.get("Measured variable", pd.Series([""] * len(out))).astype(str)
    out["Measured variable"] = [item.label for item in descriptors]
    return out


def _install_parameter_catalogue(parity: Any) -> None:
    st = parity.st
    previous_selector = parity._render_geosphere_resource_selector

    def selector(legacy: Any, original: Callable) -> None:
        if str(st.session_state.get("geosphere_resource_id", "")) != MONTHLY_RESOURCE_ID:
            previous_selector(legacy, original)
            return

        real_data_editor = st.data_editor
        real_info = st.info
        context_shown = {"value": False}

        def info(body: Any, *args: Any, **kwargs: Any):
            # The earlier monthly binding emitted the same long paragraph both
            # on source selection and Overview. The cleanup owns one compact
            # source-page copy instead.
            if isinstance(body, str) and body.strip() == MONTHLY_OFFICIAL_CONTEXT_EN.strip():
                return None
            return real_info(body, *args, **kwargs)

        def data_editor(data: Any, *args: Any, **kwargs: Any):
            if not (
                isinstance(data, pd.DataFrame)
                and {"Provider", "Measured variable"}.issubset(data.columns)
            ):
                return real_data_editor(data, *args, **kwargs)

            if not context_shown["value"]:
                with st.expander("About this GeoSphere monthly dataset", expanded=False):
                    st.write(MONTHLY_OFFICIAL_CONTEXT_EN)
                    st.caption(f"Official source: GeoSphere Austria Station Data-v2 (1 m) · {MONTHLY_DOI} · {MONTHLY_DATASET_PAGE}")
                context_shown["value"] = True

            decorated = _decorate_parameter_table(parity, data)
            scope = st.radio(
                "Parameter catalogue",
                ["Recommended", "All parameters"],
                index=0,
                horizontal=True,
                key="geosphere_monthly_parameter_catalogue",
                help=(
                    "Recommended keeps the source selector compact and building-climate oriented. All parameters exposes the complete live GeoSphere monthly vocabulary; nothing is removed from provider support."
                ),
            )
            if scope == "Recommended":
                visible = decorated.loc[decorated["_recommended"].fillna(False).astype(bool)].copy()
                if visible.empty:
                    visible = decorated.copy()
                    st.warning("No curated parameters matched the current live metadata; showing the complete provider catalogue instead.")
            else:
                visible = decorated.copy()
            visible = visible.drop(columns=["_recommended"])

            column_config = dict(kwargs.get("column_config") or {})
            column_config["Measured variable"] = st.column_config.TextColumn("Variable", width="large")
            column_config["Category"] = st.column_config.TextColumn("Category", width="medium")
            column_config["Statistic"] = st.column_config.TextColumn("Statistic", width="medium")
            column_config["Notes"] = st.column_config.TextColumn("Interpretation", width="large")
            column_config["Original GeoSphere name"] = st.column_config.TextColumn("Original GeoSphere name", width="large")
            column_config["Canonical field"] = None
            if scope == "Recommended":
                column_config["Provider"] = None
                column_config["Original GeoSphere name"] = None
            kwargs["column_config"] = column_config
            disabled = list(kwargs.get("disabled") or [])
            for name in ("Category", "Statistic", "Notes", "Original GeoSphere name"):
                if name not in disabled:
                    disabled.append(name)
            kwargs["disabled"] = disabled
            return real_data_editor(visible, *args, **kwargs)

        st.data_editor = data_editor
        st.info = info
        try:
            previous_selector(legacy, original)
        finally:
            st.data_editor = real_data_editor
            st.info = real_info

    parity._render_geosphere_resource_selector = selector


def install_monthly_cleanup(proxy: Any, parity: Any) -> None:
    """Install the monthly canonical cleanup exactly once."""
    if bool(getattr(proxy, "_GEOSPHERE_MONTHLY_CLEANUP_INSTALLED", False)):
        return
    _install_semantic_engines()
    _install_unified_overlay(proxy)
    _install_parameter_catalogue(parity)

    # Existing canonical monthly renderer resolves these module globals at call
    # time, so replacing the capability adapters removes the old duplicate
    # provenance and source-specific Plotly overlay without creating a second
    # navigation surface.
    monthly_ui.monthly_variable_registry = _improved_monthly_registry
    monthly_ui._render_monthly_generic = _render_monthly_generic
    monthly_ui._render_monthly_overview = _render_monthly_overview
    monthly_ui._render_monthly_overlay = _forward_monthly_overlay
    monthly_ui.MONTHLY_ALLOWED_AGGREGATIONS = MONTHLY_GENERIC_AGGREGATIONS

    proxy._GEOSPHERE_MONTHLY_CLEANUP_INSTALLED = True
