"""Follow-up UX contracts for GeoSphere selection and interannual overlays.

This module deliberately patches the mature Streamlit shell at runtime instead of
forking source-specific pages.  Two user-facing contracts are implemented here:

* measured-variable checkbox edits are staged inside a Streamlit form, so checking
  or unchecking rows does not rerun the whole GeoSphere station/map page and does
  not issue provider requests; the existing load action is committed by the form
  submit button in the same rerun;
* ``Interannual overlay`` is a third global temporal basis.  It aligns equivalent
  calendar positions across real source years while preserving every year as an
  independent series.  No cross-year averaging is performed for min/mean/max or
  percentile profiles.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from . import aggregations, charts, source_parity_monthly_canonical, temporal_filtering


INTERANNUAL_OVERLAY = "Interannual overlay"
_GEOSPHERE_FORM_INSTALLED = "_GEOSPHERE_VARIABLE_FORM_INSTALLED_V1"
_FORM_REQUEST_KEY = "_geosphere_variable_form_load_requested_v1"
_FORM_KEY_PREFIX = "geosphere_variable_load_form_v1"
_HIGHLIGHT_KEY = "_interannual_overlay_highlight_year"


def _selected_count(data: Any) -> int:
    if not isinstance(data, pd.DataFrame) or "Selected" not in data.columns:
        return 0
    return int(data["Selected"].fillna(False).astype(bool).sum())


def _scope(st: Any) -> tuple[str, str]:
    return (
        str(st.session_state.get("geosphere_resource_id", "klima-v2-10min")),
        str(st.session_state.get("geosphere_selected_station_id", "")),
    )


def install_geosphere_variable_form(parity: Any) -> None:
    """Stage variable-editor changes locally and submit them as one load action.

    The mature source renderer currently returns early while zero variables are
    selected and renders the provider-load button only afterwards.  The wrapper
    therefore owns the visible submit button inside the form and converts that
    submit event into the old button's boolean result later in the same script
    run.  This keeps all downstream loading/progress/error handling unchanged.
    """
    if bool(getattr(parity, _GEOSPHERE_FORM_INSTALLED, False)):
        return
    setattr(parity, _GEOSPHERE_FORM_INSTALLED, True)

    previous = parity._render_geosphere_resource_selector
    st = parity.st

    def selector(legacy: Any, original: Callable) -> Any:
        real_editor = st.data_editor
        real_button = st.button
        real_warning = st.warning
        form_rendered = {"value": False}

        def editor(data: Any, *args: Any, **kwargs: Any):
            qualifies = (
                isinstance(data, pd.DataFrame)
                and {"Provider", "Selected", "Measured variable"}.issubset(data.columns)
                and str(kwargs.get("key", "")).startswith("geosphere_variable_editor")
            )
            if not qualifies:
                return real_editor(data, *args, **kwargs)

            # Never let a failed/short-circuited previous script run leave a
            # latent request that could fire on an unrelated later rerun.
            st.session_state.pop(_FORM_REQUEST_KEY, None)
            resource_id, station_id = _scope(st)
            form_signature = sha1(f"{resource_id}\0{station_id}".encode("utf-8")).hexdigest()[:12]
            form_key = f"{_FORM_KEY_PREFIX}::{form_signature}"
            form_rendered["value"] = True

            with st.form(form_key, clear_on_submit=False):
                edited = real_editor(data, *args, **kwargs)
                st.caption(
                    "Variable choices are staged locally. Checking or unchecking rows does not reload this page and does not request GeoSphere data."
                )
                submitted = st.form_submit_button(
                    "Load measured GeoSphere interval",
                    type="primary",
                    help="Submit the current variable selection and start the provider request.",
                )
                if submitted:
                    if _selected_count(edited) <= 0:
                        real_warning("Select at least one measured GeoSphere variable to load.")
                    else:
                        st.session_state[_FORM_REQUEST_KEY] = (resource_id, station_id)
            return edited

        def button(label: Any, *args: Any, **kwargs: Any):
            if str(label) != "Load measured GeoSphere interval":
                return real_button(label, *args, **kwargs)
            request = st.session_state.pop(_FORM_REQUEST_KEY, None)
            return request == _scope(st)

        def warning(body: Any, *args: Any, **kwargs: Any):
            # The form itself validates an empty submit.  Suppress the mature
            # renderer's always-visible empty-selection warning so it does not
            # become stale while the user edits checkboxes client-side.
            if (
                form_rendered["value"]
                and str(body).strip() == "Select at least one measured GeoSphere variable to load."
            ):
                return None
            return real_warning(body, *args, **kwargs)

        st.data_editor = editor
        st.button = button
        st.warning = warning
        try:
            return previous(legacy, original)
        finally:
            st.data_editor = real_editor
            st.button = real_button
            st.warning = real_warning

    parity._render_geosphere_resource_selector = selector


def _enable_time_basis_contract() -> None:
    temporal_filtering.INTERANNUAL_OVERLAY = INTERANNUAL_OVERLAY
    bases = tuple(getattr(temporal_filtering, "VALID_TIME_BASES", ()))
    if INTERANNUAL_OVERLAY not in bases:
        temporal_filtering.VALID_TIME_BASES = bases + (INTERANNUAL_OVERLAY,)


def _append_overlay_option(options: Iterable[object]) -> list[object]:
    values = list(options)
    if INTERANNUAL_OVERLAY not in values:
        values.append(INTERANNUAL_OVERLAY)
    return values


def _time_basis_help() -> str:
    return (
        "Chronological keeps real timestamps in sequence. Calendar profile groups equivalent calendar positions across years into climatological buckets. "
        "Interannual overlay aligns equivalent calendar positions on one axis but preserves every real source year as an independent series; values from different years are never averaged together."
    )


def _with_hex_alpha(color: str, alpha: float) -> str:
    value = str(color).strip()
    if value.startswith("#") and len(value) == 7:
        return f"rgba({int(value[1:3], 16)},{int(value[3:5], 16)},{int(value[5:7], 16)},{float(alpha):.4f})"
    return value


def _year_subset(df: pd.DataFrame, year: int) -> pd.DataFrame:
    attrs = dict(df.attrs)
    index = pd.DatetimeIndex(df.index)
    out = df.loc[index.year == int(year)].copy()
    out.attrs.update(attrs)
    out.attrs[temporal_filtering.TIME_BASIS_ATTR] = temporal_filtering.CHRONOLOGICAL
    return out


def _summary_slot(index: pd.Index, aggregation: str) -> list[object]:
    values = list(index)
    if aggregation == "Seasonal" and not isinstance(index, pd.DatetimeIndex):
        return [str(value) for value in values]
    if aggregation == "Annual" and not isinstance(index, pd.DatetimeIndex):
        return ["Annual"] * len(values)

    idx = pd.DatetimeIndex(index)
    if aggregation == "Hourly":
        return [(int(v.month), int(v.day), int(v.hour), int(v.minute)) for v in idx]
    if aggregation == "Daily":
        return [(int(v.month), int(v.day)) for v in idx]
    if aggregation == "Weekly":
        iso = idx.isocalendar()
        return [int(value) for value in iso.week]
    if aggregation == "Monthly":
        return [int(v.month) for v in idx]
    if aggregation == "Seasonal":
        return [temporal_filtering.season_name(int(v.month)) for v in idx]
    if aggregation == "Annual":
        return ["Annual"] * len(idx)
    raise ValueError(f"Unsupported aggregation: {aggregation}")


def _slot_sort_key(slot: object, aggregation: str) -> tuple:
    if aggregation in {"Hourly", "Daily"}:
        return tuple(slot) if isinstance(slot, tuple) else (slot,)
    if aggregation in {"Weekly", "Monthly"}:
        return (int(slot),)
    if aggregation == "Seasonal":
        order = {name: pos for pos, name in enumerate(temporal_filtering.SEASON_ORDER)}
        return (order.get(str(slot), 99),)
    return (0,)


def _x_for_slots(slots: list[object], aggregation: str) -> list[object]:
    if aggregation == "Hourly":
        return [pd.Timestamp(2000, int(slot[0]), int(slot[1]), int(slot[2]), int(slot[3])) for slot in slots]
    if aggregation == "Daily":
        return [pd.Timestamp(2000, int(slot[0]), int(slot[1])) for slot in slots]
    if aggregation == "Weekly":
        return [int(slot) for slot in slots]
    if aggregation == "Monthly":
        return [charts.MONTH_LABELS[int(slot) - 1] for slot in slots]
    if aggregation == "Seasonal":
        return [str(slot) for slot in slots]
    return ["Annual" for _ in slots]


def _actual_period_labels(index: pd.Index, aggregation: str) -> list[str]:
    if not isinstance(index, pd.DatetimeIndex):
        return [str(value) for value in index]
    idx = pd.DatetimeIndex(index)
    if aggregation == "Hourly":
        return list(idx.strftime("%Y-%m-%d %H:%M"))
    if aggregation == "Daily":
        return list(idx.strftime("%Y-%m-%d"))
    if aggregation == "Weekly":
        iso = idx.isocalendar()
        return [f"{int(year):04d}-W{int(week):02d}" for year, week in zip(iso.year, iso.week, strict=False)]
    if aggregation == "Monthly":
        return list(idx.strftime("%b %Y"))
    if aggregation == "Seasonal":
        return [f"{temporal_filtering.season_name(int(value.month))} {int(value.year)}" for value in idx]
    return [str(int(value.year)) for value in idx]


def _collapse_duplicate_slots(summary: pd.DataFrame, aggregation: str, extensive: bool) -> pd.DataFrame:
    out = summary.copy()
    out["_slot"] = _summary_slot(summary.index, aggregation)
    out["_actual_period"] = _actual_period_labels(summary.index, aggregation)
    numeric_columns = [column for column in out.columns if column not in {"_slot", "_actual_period"}]
    if not out["_slot"].duplicated().any():
        return out.set_index("_slot", drop=True)

    rows: list[dict[str, object]] = []
    for slot, group in out.groupby("_slot", sort=False, observed=False):
        row: dict[str, object] = {"_slot": slot, "_actual_period": " / ".join(dict.fromkeys(group["_actual_period"].astype(str)))}
        for column in numeric_columns:
            values = pd.to_numeric(group[column], errors="coerce")
            if column == "min":
                row[column] = values.min()
            elif column == "max":
                row[column] = values.max()
            elif column == "p05":
                row[column] = values.quantile(0.05)
            elif column == "p95":
                row[column] = values.quantile(0.95)
            elif column == "sum" and extensive:
                row[column] = values.sum(min_count=1)
            else:
                row[column] = values.mean()
        rows.append(row)
    return pd.DataFrame(rows).set_index("_slot", drop=True)


def interannual_year_summaries(
    df: pd.DataFrame,
    column: str,
    aggregation: str,
    *,
    extensive: bool = False,
) -> tuple[list[object], dict[int, pd.DataFrame]]:
    """Return year-isolated summaries reindexed to one shared calendar slot axis."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Interannual overlay requires a DatetimeIndex.")
    years = temporal_filtering.available_years(df)
    summaries: dict[int, pd.DataFrame] = {}
    slot_union: set[object] = set()
    for year in years:
        yearly = _year_subset(df, year)
        if yearly.empty:
            continue
        summary = (
            aggregations.aggregate_sum(yearly, column, aggregation)
            if extensive
            else aggregations.aggregate_summary(yearly, column, aggregation)
        )
        collapsed = _collapse_duplicate_slots(summary, aggregation, extensive)
        summaries[int(year)] = collapsed
        slot_union.update(collapsed.index.tolist())

    slots = sorted(slot_union, key=lambda value: _slot_sort_key(value, aggregation))
    for year, summary in list(summaries.items()):
        summaries[year] = summary.reindex(slots)
    return slots, summaries


def _series_customdata(year: int, summary: pd.DataFrame, slots: list[object], aggregation: str) -> np.ndarray:
    fallback = _x_for_slots(slots, aggregation)
    labels: list[str] = []
    actual = summary.get("_actual_period")
    for index, value in enumerate(fallback):
        label = None
        if actual is not None:
            raw = actual.iloc[index]
            if pd.notna(raw):
                label = str(raw)
        labels.append(label or str(value))
    return np.asarray([[int(year), label] for label in labels], dtype=object)


def _overlay_axis(fig: go.Figure, aggregation: str) -> None:
    if aggregation == "Monthly":
        fig.update_xaxes(categoryorder="array", categoryarray=charts.MONTH_LABELS)
    elif aggregation == "Seasonal":
        fig.update_xaxes(categoryorder="array", categoryarray=list(temporal_filtering.SEASON_ORDER))
    elif aggregation == "Daily":
        fig.update_xaxes(tickformat="%d %b")
    elif aggregation == "Hourly":
        fig.update_xaxes(tickformat="%d %b<br>%H:%M")


def _year_palette(years: list[int]) -> dict[int, str]:
    palette = list(px.colors.qualitative.Alphabet) or list(px.colors.qualitative.Plotly)
    return {year: palette[index % len(palette)] for index, year in enumerate(years)}


def _interannual_profile_chart(
    df: pd.DataFrame,
    column: str,
    aggregation: str,
    title: str,
    unit: str,
    *,
    extensive: bool,
    highlight_year: int | None,
) -> go.Figure:
    slots, summaries = interannual_year_summaries(df, column, aggregation, extensive=extensive)
    years = sorted(summaries)
    if not years:
        return charts.profile_ribbon_chart(_year_subset(df, temporal_filtering.available_years(df)[0]), column, aggregation, title, unit, extensive=extensive)
    highlight = int(highlight_year) if highlight_year in years else years[-1]
    colors = _year_palette(years)
    x = _x_for_slots(slots, aggregation)
    central = "sum" if extensive and aggregation != "Hourly" else "mean"
    fig = go.Figure()

    for year in years:
        summary = summaries[year]
        color = colors[year]
        focused = year == highlight
        mode = "lines+markers" if len(slots) <= 60 else "lines"
        customdata = _series_customdata(year, summary, slots, aggregation)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=summary["max"],
                mode=mode,
                name=f"{year} · maximum",
                legendgroup=str(year),
                showlegend=False,
                line=dict(color=color, width=1.1 if focused else 0.7),
                opacity=0.65 if focused else 0.16,
                connectgaps=False,
                customdata=customdata,
                hovertemplate="Year %{customdata[0]}<br>%{customdata[1]}<br>Maximum: %{y:.2f} " + unit + "<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=summary["min"],
                mode=mode,
                name=f"{year} · minimum",
                legendgroup=str(year),
                showlegend=False,
                line=dict(color=color, width=1.1 if focused else 0.7),
                opacity=0.65 if focused else 0.16,
                fill="tonexty",
                fillcolor=_with_hex_alpha(color, 0.12 if focused else 0.018),
                connectgaps=False,
                customdata=customdata,
                hovertemplate="Year %{customdata[0]}<br>%{customdata[1]}<br>Minimum: %{y:.2f} " + unit + "<extra></extra>",
            )
        )
        label = "Mean" if central == "mean" else "Sum"
        fig.add_trace(
            go.Scatter(
                x=x,
                y=summary[central],
                mode=mode,
                name=str(year),
                legendgroup=str(year),
                showlegend=True,
                line=dict(color=color, width=2.8 if focused else 1.15),
                opacity=1.0 if focused else 0.34,
                connectgaps=False,
                customdata=customdata,
                hovertemplate=f"Year %{{customdata[0]}}<br>%{{customdata[1]}}<br>{label}: %{{y:.2f}} {unit}<extra></extra>",
            )
        )

    charts.apply_common_layout(fig, f"{title} · interannual overlay", "Calendar position", unit)
    fig.update_layout(legend_title_text="Year", legend=dict(groupclick="togglegroup"))
    _overlay_axis(fig, aggregation)
    all_values = pd.concat(
        [summary[column_name] for summary in summaries.values() for column_name in ("min", central, "max")],
        ignore_index=True,
    )
    return charts._apply_axis_constraints(fig, column=column, y_values=all_values)


def _interannual_percentile_chart(
    df: pd.DataFrame,
    column: str,
    aggregation: str,
    title: str,
    unit: str,
    *,
    highlight_year: int | None,
) -> go.Figure:
    slots, summaries = interannual_year_summaries(df, column, aggregation, extensive=False)
    years = sorted(summaries)
    if not years:
        return charts.percentile_band_chart(df, column, aggregation, title, unit)
    highlight = int(highlight_year) if highlight_year in years else years[-1]
    colors = _year_palette(years)
    x = _x_for_slots(slots, aggregation)
    fig = go.Figure()

    for year in years:
        summary = summaries[year]
        color = colors[year]
        focused = year == highlight
        mode = "lines+markers" if len(slots) <= 60 else "lines"
        customdata = _series_customdata(year, summary, slots, aggregation)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=summary["p95"],
                mode=mode,
                name=f"{year} · P95",
                legendgroup=str(year),
                showlegend=False,
                line=dict(color=color, width=1.1 if focused else 0.7),
                opacity=0.65 if focused else 0.16,
                connectgaps=False,
                customdata=customdata,
                hovertemplate="Year %{customdata[0]}<br>%{customdata[1]}<br>P95: %{y:.2f} " + unit + "<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=summary["p05"],
                mode=mode,
                name=f"{year} · P05",
                legendgroup=str(year),
                showlegend=False,
                line=dict(color=color, width=1.1 if focused else 0.7),
                opacity=0.65 if focused else 0.16,
                fill="tonexty",
                fillcolor=_with_hex_alpha(color, 0.12 if focused else 0.018),
                connectgaps=False,
                customdata=customdata,
                hovertemplate="Year %{customdata[0]}<br>%{customdata[1]}<br>P05: %{y:.2f} " + unit + "<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=summary["median"],
                mode=mode,
                name=str(year),
                legendgroup=str(year),
                showlegend=True,
                line=dict(color=color, width=2.8 if focused else 1.15),
                opacity=1.0 if focused else 0.34,
                connectgaps=False,
                customdata=customdata,
                hovertemplate="Year %{customdata[0]}<br>%{customdata[1]}<br>Median: %{y:.2f} " + unit + "<extra></extra>",
            )
        )

    charts.apply_common_layout(fig, f"{title} · interannual overlay", "Calendar position", unit)
    fig.update_layout(legend_title_text="Year", legend=dict(groupclick="togglegroup"))
    _overlay_axis(fig, aggregation)
    all_values = pd.concat(
        [summary[column_name] for summary in summaries.values() for column_name in ("p05", "median", "p95")],
        ignore_index=True,
    )
    return charts._apply_axis_constraints(fig, column=column, y_values=all_values)


def _patch_charts(st: Any) -> None:
    if bool(getattr(charts, "_INTERANNUAL_OVERLAY_PATCHED", False)):
        return
    charts._INTERANNUAL_OVERLAY_PATCHED = True
    original_profile = charts.profile_ribbon_chart
    original_percentile = charts.percentile_band_chart

    def profile_ribbon_chart(
        df: pd.DataFrame,
        column: str,
        aggregation: str,
        title: str,
        unit: str,
        extensive: bool = False,
    ) -> go.Figure:
        if temporal_filtering.time_basis(df) != INTERANNUAL_OVERLAY or not temporal_filtering.is_multiyear(df):
            return original_profile(df, column, aggregation, title, unit, extensive=extensive)
        highlight = st.session_state.get(_HIGHLIGHT_KEY)
        try:
            highlight = int(highlight) if highlight is not None else None
        except (TypeError, ValueError):
            highlight = None
        return _interannual_profile_chart(
            df,
            column,
            aggregation,
            title,
            unit,
            extensive=extensive,
            highlight_year=highlight,
        )

    def percentile_band_chart(
        df: pd.DataFrame,
        column: str,
        aggregation: str,
        title: str,
        unit: str,
    ) -> go.Figure:
        if temporal_filtering.time_basis(df) != INTERANNUAL_OVERLAY or not temporal_filtering.is_multiyear(df):
            return original_percentile(df, column, aggregation, title, unit)
        highlight = st.session_state.get(_HIGHLIGHT_KEY)
        try:
            highlight = int(highlight) if highlight is not None else None
        except (TypeError, ValueError):
            highlight = None
        return _interannual_percentile_chart(
            df,
            column,
            aggregation,
            title,
            unit,
            highlight_year=highlight,
        )

    charts.profile_ribbon_chart = profile_ribbon_chart
    charts.percentile_band_chart = percentile_band_chart

    # Box/violin plots do not have an interannual line-overlay representation.
    # Treat this basis like chronological there so real source years are not
    # silently collapsed into one Jan...Dec distribution.
    original_monthly_box = aggregations.monthly_box_data

    def monthly_box_data(df: pd.DataFrame, column: str) -> pd.DataFrame:
        if temporal_filtering.time_basis(df) != INTERANNUAL_OVERLAY:
            return original_monthly_box(df, column)
        chronological = df.copy()
        chronological.attrs.update(dict(df.attrs))
        chronological.attrs[temporal_filtering.TIME_BASIS_ATTR] = temporal_filtering.CHRONOLOGICAL
        return original_monthly_box(chronological, column)

    aggregations.monthly_box_data = monthly_box_data
    charts.monthly_box_data = monthly_box_data


def _wrap_time_basis_renderer(st: Any, renderer: Callable) -> Callable:
    def wrapped(*args: Any, **kwargs: Any):
        real_selectbox = st.sidebar.selectbox

        def selectbox(label: str, options: Iterable[object], *s_args: Any, **s_kwargs: Any):
            values = list(options)
            if str(label) == "Time basis":
                values = _append_overlay_option(values)
                s_kwargs["help"] = _time_basis_help()
            value = real_selectbox(label, values, *s_args, **s_kwargs)
            if str(label) == "Time basis" and value == INTERANNUAL_OVERLAY:
                st.sidebar.caption(
                    "Years share one calendar x-axis but remain independent series. Aggregation is performed inside each year before plotting; no cross-year mean is introduced."
                )
            return value

        st.sidebar.selectbox = selectbox
        try:
            return renderer(*args, **kwargs)
        finally:
            st.sidebar.selectbox = real_selectbox

    return wrapped


def _patch_generic_renderer(legacy: Any, st: Any) -> None:
    if hasattr(legacy, "_source_parity_original_generic_interannual"):
        return
    original = legacy.render_generic_variable_page
    legacy._source_parity_original_generic_interannual = original

    def render_generic(*args: Any, **kwargs: Any):
        df = args[0] if args else kwargs.get("df")
        title_prefix = str(args[3] if len(args) > 3 else kwargs.get("title_prefix", "variable"))
        real_selectbox = st.selectbox

        def selectbox(label: str, options: Iterable[object], *s_args: Any, **s_kwargs: Any):
            values = list(options)
            if (
                str(label) == "Compare across"
                and isinstance(df, pd.DataFrame)
                and temporal_filtering.time_basis(df) == INTERANNUAL_OVERLAY
            ):
                values = ["Year"] + [value for value in values if str(value) != "Year"]
                s_kwargs["index"] = 0
            value = real_selectbox(label, values, *s_args, **s_kwargs)
            if (
                str(label) == "Aggregation"
                and isinstance(df, pd.DataFrame)
                and temporal_filtering.time_basis(df) == INTERANNUAL_OVERLAY
                and temporal_filtering.is_multiyear(df)
            ):
                years = temporal_filtering.available_years(df)
                key = "interannual_highlight_year_" + sha1(title_prefix.encode("utf-8")).hexdigest()[:10]
                current = st.session_state.get(_HIGHLIGHT_KEY, years[-1])
                default_year = int(current) if current in years else years[-1]
                highlight = real_selectbox(
                    "Highlight year",
                    years,
                    index=years.index(default_year),
                    key=key,
                    help="The highlighted year is drawn at full opacity. All other years remain visible and can be toggled from the legend.",
                )
                st.session_state[_HIGHLIGHT_KEY] = int(highlight)
                st.caption(
                    "Interannual overlay: each year is aggregated independently, then aligned to the same calendar position. Missing periods remain gaps."
                )
            return value

        st.selectbox = selectbox
        try:
            return original(*args, **kwargs)
        finally:
            st.selectbox = real_selectbox

    legacy.render_generic_variable_page = render_generic


def install_interannual_overlay(legacy: Any) -> None:
    """Install the third temporal basis and year-isolated profile rendering."""
    _enable_time_basis_contract()
    st = legacy.st
    _patch_charts(st)

    if not hasattr(legacy, "_source_parity_original_sidebar_filters_interannual"):
        original_sidebar = legacy.sidebar_filters
        legacy._source_parity_original_sidebar_filters_interannual = original_sidebar
        legacy.sidebar_filters = _wrap_time_basis_renderer(st, original_sidebar)

    _patch_generic_renderer(legacy, st)

    monthly = source_parity_monthly_canonical
    if not bool(getattr(monthly, "_INTERANNUAL_MONTHLY_FILTER_PATCHED", False)):
        monthly._INTERANNUAL_MONTHLY_FILTER_PATCHED = True
        monthly._monthly_sidebar_filters = _wrap_time_basis_renderer(st, monthly._monthly_sidebar_filters)
