"""One-shot source patch for Climate Analyzer 0.6.3 temporal filtering.

This script is intentionally deterministic and fail-fast: every replacement is
anchored to the v0.6.2 production source. It is executed once on the dedicated
feature branch and removed before merge.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: Path, old: str, new: str, label: str, expected: int) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        # Idempotent second execution after all replacements have landed.
        if new in text:
            return
        raise RuntimeError(f"{label}: source anchor not found")
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{label}: expected {expected} anchors, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def patch_app() -> None:
    path = ROOT / "app.py"

    replace_once(
        path,
        "    global native_resolution_minutes, validate_unit_families\n",
        "    global native_resolution_minutes, validate_unit_families\n"
        "    global available_years, filter_datetime_range, filter_year, with_time_basis\n"
        "    global CHRONOLOGICAL, CALENDAR_PROFILE, display_period_labels, time_basis\n",
        "app temporal globals",
    )

    replace_once(
        path,
        "            validate_unit_families,\n"
        "        )\n"
        "        _ANALYSIS_DEPENDENCIES_LOADED = True\n",
        "            validate_unit_families,\n"
        "        )\n"
        "        from epw_climate_analyzer.temporal_filtering import (\n"
        "            CALENDAR_PROFILE,\n"
        "            CHRONOLOGICAL,\n"
        "            available_years,\n"
        "            display_period_labels,\n"
        "            filter_datetime_range,\n"
        "            filter_year,\n"
        "            time_basis,\n"
        "            with_time_basis,\n"
        "        )\n"
        "        _ANALYSIS_DEPENDENCIES_LOADED = True\n",
        "app temporal imports",
    )

    old_filter = '''def sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Create global month and hour filters in the sidebar."""
    st.sidebar.markdown("### Data filter")
    selected_month_names = st.sidebar.multiselect("Months", list(MONTHS.keys()), default=list(MONTHS.keys()))
    selected_hours = st.sidebar.slider("Hour range", min_value=0, max_value=23, value=(0, 23))
    months = [MONTHS[m] for m in selected_month_names]
    hours = list(range(selected_hours[0], selected_hours[1] + 1))
    filtered = filter_by_months_and_hours(df, months=months, hours=hours)
    # Export uses exactly the dataframe after the active global filters. Keeping
    # it in transient Streamlit session state avoids duplicating filter logic in
    # every chart renderer.
    st.session_state["_active_filtered_export_df"] = filtered
    return filtered
'''
    new_filter = '''def sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the source-neutral global time, month and hour filters.

    The absolute range is the primary filter for EPW, GeoSphere and future
    sources. Chronological is the default temporal basis, so multi-year data keep
    every real month/day/hour distinct. Calendar profile is an explicit opt-in
    that aligns equivalent calendar positions across the selected years.
    """
    st.sidebar.markdown("### Data filter")
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        st.session_state["_active_filtered_export_df"] = df
        return df

    source_start = pd.Timestamp(df.index.min())
    source_end = pd.Timestamp(df.index.max())
    years = available_years(df)
    st.sidebar.caption(
        f"Available: {source_start.strftime('%d %b %Y %H:%M')} → {source_end.strftime('%d %b %Y %H:%M')}"
    )

    range_mode = st.sidebar.selectbox(
        "Range",
        ["All available", "Year", "Custom"],
        index=0,
        key="global_data_range_mode",
    )
    ranged = df
    if range_mode == "Year":
        selected_year = st.sidebar.selectbox(
            "Year",
            years,
            index=max(len(years) - 1, 0),
            key="global_data_range_year",
        )
        ranged = filter_year(df, int(selected_year))
    elif range_mode == "Custom":
        date_cols = st.sidebar.columns(2)
        start_date = date_cols[0].date_input(
            "From date",
            value=source_start.date(),
            min_value=source_start.date(),
            max_value=source_end.date(),
            key="global_data_range_start_date",
        )
        end_date = date_cols[1].date_input(
            "To date",
            value=source_end.date(),
            min_value=source_start.date(),
            max_value=source_end.date(),
            key="global_data_range_end_date",
        )
        time_cols = st.sidebar.columns(2)
        start_time = time_cols[0].time_input(
            "From time",
            value=source_start.time().replace(tzinfo=None),
            key="global_data_range_start_time",
        )
        end_time = time_cols[1].time_input(
            "To time",
            value=source_end.time().replace(tzinfo=None),
            key="global_data_range_end_time",
        )
        start_value = pd.Timestamp.combine(start_date, start_time)
        end_value = pd.Timestamp.combine(end_date, end_time)
        if start_value > end_value:
            st.sidebar.error("From must not be later than To.")
            ranged = df.iloc[0:0].copy()
        else:
            ranged = filter_datetime_range(df, start=start_value, end=end_value)

    ranged_years = available_years(ranged) if not ranged.empty else []
    if len(ranged_years) > 1:
        basis = st.sidebar.selectbox(
            "Time basis",
            [CHRONOLOGICAL, CALENDAR_PROFILE],
            index=0,
            key="global_time_basis",
            help=(
                "Chronological keeps every real period in order. Calendar profile aligns equivalent "
                "calendar positions across the selected years for multi-year min/mean/max or typical-period analysis."
            ),
        )
    else:
        basis = CHRONOLOGICAL
    ranged = with_time_basis(ranged, basis)

    # Existing recurring month/hour controls are retained: they now refine the
    # absolute range instead of acting as the only global time filter.
    selected_month_names = st.sidebar.multiselect("Months", list(MONTHS.keys()), default=list(MONTHS.keys()))
    selected_hours = st.sidebar.slider("Hour range", min_value=0, max_value=23, value=(0, 23))
    months = [MONTHS[m] for m in selected_month_names]
    hours = list(range(selected_hours[0], selected_hours[1] + 1))
    filtered = filter_by_months_and_hours(ranged, months=months, hours=hours)
    filtered = with_time_basis(filtered, basis)

    # Export uses exactly the dataframe after the active global filters. Keeping
    # it in transient Streamlit session state avoids duplicating filter logic in
    # every chart renderer.
    st.session_state["_active_filtered_export_df"] = filtered
    return filtered
'''
    replace_once(path, old_filter, new_filter, "app global data filter")

    old_hist = '''    active_pressure = fallback_pressure if pressure_mode != "Measured station pressure with fallback median" else measured_median
    if page in {"Time Series and Overlay", "Overview", "Data Quality"}:
        filtered_df = full_df
        st.session_state["_active_filtered_export_df"] = full_df
    else:
        filtered_df = sidebar_filters(full_df)
        if filtered_df.empty:
            st.warning("The current filters remove all data. Adjust the month or hour filter.")
            return
'''
    new_hist = '''    active_pressure = fallback_pressure if pressure_mode != "Measured station pressure with fallback median" else measured_median
    filtered_df = sidebar_filters(full_df)
    if filtered_df.empty:
        st.warning("The current filters remove all data. Adjust the date, month or hour filter.")
        return
'''
    replace_once(path, old_hist, new_hist, "historical global filtering")

    replace_once(
        path,
        '''    if page == "Overview":
        render_historical_overview(dataset, full_df)
''',
        '''    if page == "Overview":
        render_historical_overview(dataset, filtered_df)
''',
        "historical overview filtered frame",
    )
    replace_once(
        path,
        '''    elif page == "Time Series and Overlay":
        render_time_series_overlay(full_df)
    else:
        render_canonical_data_quality(dataset, full_df)
''',
        '''    elif page == "Time Series and Overlay":
        render_time_series_overlay(filtered_df)
    else:
        render_canonical_data_quality(dataset, filtered_df)
''',
        "historical overlay and quality filtered frame",
    )

    old_epw = '''    if page == "Time Series and Overlay":
        # This page owns an exact date/hour/minute viewport. Applying the global
        # month/hour sidebar filter as well would create two conflicting time
        # filters, so it starts from the complete loaded source calendar.
        filtered_df = full_df
        st.session_state["_active_filtered_export_df"] = full_df
    else:
        filtered_df = sidebar_filters(full_df)
        if filtered_df.empty:
            st.warning("The current filters remove all data. Adjust the month or hour filter.")
            return
'''
    new_epw = '''    filtered_df = sidebar_filters(full_df)
    if filtered_df.empty:
        st.warning("The current filters remove all data. Adjust the date, month or hour filter.")
        return
'''
    replace_once(path, old_epw, new_epw, "EPW global filtering")

    replace_once(
        path,
        '''    elif page == "Time Series and Overlay":
        render_time_series_overlay(full_df)
''',
        '''    elif page == "Time Series and Overlay":
        render_time_series_overlay(filtered_df)
''',
        "EPW overlay filtered frame",
    )


def patch_aggregations() -> None:
    path = ROOT / "epw_climate_analyzer" / "aggregations.py"
    replace_once(
        path,
        '''    "Monthly": "ME",
    "Seasonal": None,
}''',
        '''    "Monthly": "ME",
    "Annual": "YE",
    "Seasonal": None,
}''',
        "annual aggregation rule",
    )


def patch_charts() -> None:
    path = ROOT / "epw_climate_analyzer" / "charts.py"
    replace_once(
        path,
        '''from .aggregations import aggregate_summary, aggregate_sum, calendar_matrix, duration_curve, monthly_box_data, monthly_hour_matrix, native_interval_hours
from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves
''',
        '''from .aggregations import aggregate_summary, aggregate_sum, calendar_matrix, duration_curve, monthly_box_data, monthly_hour_matrix, native_interval_hours
from .temporal_filtering import CALENDAR_PROFILE, CHRONOLOGICAL, display_period_labels, is_multiyear, time_basis
from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves
''',
        "charts temporal imports",
    )

    old_period = '''def _period_x(summary: pd.DataFrame, aggregation: str) -> list:
    """Return human-readable x values for an aggregated summary table."""
    idx = summary.index
    if aggregation == "Monthly":
        if isinstance(idx, pd.DatetimeIndex):
            return [MONTH_LABELS[i - 1] for i in idx.month]
        return [MONTH_LABELS[int(i) - 1] if str(i).isdigit() and 1 <= int(i) <= 12 else str(i) for i in idx]
    if aggregation == "Weekly":
        if isinstance(idx, pd.DatetimeIndex):
            return [f"W{int(i.isocalendar().week):02d}" for i in idx]
        return [f"W{int(i):02d}" if str(i).isdigit() else str(i) for i in idx]
    if aggregation == "Daily":
        if isinstance(idx, pd.DatetimeIndex):
            return [int(i.dayofyear) for i in idx]
        return list(idx)
    return list(idx)
'''
    new_period = '''def _period_x(summary: pd.DataFrame, aggregation: str) -> list:
    """Return source-neutral period labels without collapsing chronological years."""
    return display_period_labels(summary.index, aggregation, time_basis(summary))


def _year_neutral_monthly(summary: pd.DataFrame, aggregation: str) -> bool:
    """Return whether a monthly result should use the legacy Jan...Dec axis order."""
    if aggregation != "Monthly":
        return False
    idx = summary.index
    return not (
        isinstance(idx, pd.DatetimeIndex)
        and time_basis(summary) == CHRONOLOGICAL
        and is_multiyear(idx)
    )
'''
    replace_once(path, old_period, new_period, "chart period labels")

    replace_once(
        path,
        '''    if aggregation == "Hourly":
        x = summary.index
''',
        '''    if aggregation == "Hourly" and time_basis(summary) == CHRONOLOGICAL:
        x = summary.index
''',
        "hourly chronological profile path",
    )

    replace_all(
        path,
        '''    if aggregation == "Monthly":
        fig.update_xaxes(categoryorder="array", categoryarray=MONTH_LABELS)
''',
        '''    if _year_neutral_monthly(summary, aggregation):
        fig.update_xaxes(categoryorder="array", categoryarray=MONTH_LABELS)
''',
        "monthly profile category ordering",
        expected=2,
    )

    old_month_heatmap = '''def month_hour_heatmap(
    df: pd.DataFrame,
    column: str,
    title: str,
    unit: str,
    aggfunc: str = "mean",
    temperature_thresholds: tuple[float, float] | None = None,
) -> go.Figure:
    """Create a month-by-hour heatmap with month on x-axis and hour on y-axis."""
    matrix = monthly_hour_matrix(df, column, aggfunc=aggfunc)
    z = matrix.T
    colorscale = _heatmap_colorscale(column, z.values, temperature_thresholds)
    zmin, zmax = _axis_limits_for_column(column, z.values, pad_fraction=0.0)
    fig = px.imshow(
        z,
        aspect="auto",
        color_continuous_scale=colorscale,
        zmin=zmin,
        zmax=zmax,
        labels=dict(x="Month", y="Hour of day", color=unit),
        title=title,
    )
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)
    fig.update_yaxes(range=[23, 0], autorangeoptions=dict(minallowed=0, maxallowed=23))
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    return fig
'''
    new_month_heatmap = '''def month_hour_heatmap(
    df: pd.DataFrame,
    column: str,
    title: str,
    unit: str,
    aggfunc: str = "mean",
    temperature_thresholds: tuple[float, float] | None = None,
) -> go.Figure:
    """Create a month/period-by-hour heatmap without folding chronological years."""
    matrix = monthly_hour_matrix(df, column, aggfunc=aggfunc)
    z = matrix.T
    year_neutral = not (time_basis(df) == CHRONOLOGICAL and is_multiyear(df))
    x_label = "Month" if year_neutral else "Period"
    colorscale = _heatmap_colorscale(column, z.values, temperature_thresholds)
    zmin, zmax = _axis_limits_for_column(column, z.values, pad_fraction=0.0)
    fig = px.imshow(
        z,
        aspect="auto",
        color_continuous_scale=colorscale,
        zmin=zmin,
        zmax=zmax,
        labels=dict(x=x_label, y="Hour of day", color=unit),
        title=title,
    )
    if year_neutral:
        fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)
    fig.update_yaxes(range=[23, 0], autorangeoptions=dict(minallowed=0, maxallowed=23))
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    return fig
'''
    replace_once(path, old_month_heatmap, new_month_heatmap, "month-hour heatmap")

    old_box = '''def monthly_box_chart(df: pd.DataFrame, column: str, title: str, unit: str, violin: bool = False) -> go.Figure:
    """Create monthly boxplot or violin plot."""
    data = monthly_box_data(df, column)
    data["month_name"] = pd.Categorical(data["month_name"], MONTH_LABELS, ordered=True)
    base_color = metric_color(column)
    if violin:
        fig = px.violin(data, x="month_name", y=column, box=True, points=False, title=title)
        fig.update_traces(marker_color=base_color, line_color=base_color, fillcolor=rgba(base_color, 0.24))
    else:
        fig = px.box(data, x="month_name", y=column, title=title)
        fig.update_traces(marker_color=base_color, line_color=base_color)
    fig = apply_common_layout(fig, title, "Month", unit)
    fig.update_xaxes(categoryorder="array", categoryarray=MONTH_LABELS)
    return _apply_axis_constraints(fig, column=column, y_values=data[column])
'''
    new_box = '''def monthly_box_chart(df: pd.DataFrame, column: str, title: str, unit: str, violin: bool = False) -> go.Figure:
    """Create monthly boxplot/violin while preserving chronological year-months."""
    data = monthly_box_data(df, column)
    chronological_multiyear = time_basis(df) == CHRONOLOGICAL and is_multiyear(df)
    if chronological_multiyear:
        x_column = "period_name"
        x_label = "Period"
    else:
        data["month_name"] = pd.Categorical(data["month_name"], MONTH_LABELS, ordered=True)
        x_column = "month_name"
        x_label = "Month"
    base_color = metric_color(column)
    if violin:
        fig = px.violin(data, x=x_column, y=column, box=True, points=False, title=title)
        fig.update_traces(marker_color=base_color, line_color=base_color, fillcolor=rgba(base_color, 0.24))
    else:
        fig = px.box(data, x=x_column, y=column, title=title)
        fig.update_traces(marker_color=base_color, line_color=base_color)
    fig = apply_common_layout(fig, title, x_label, unit)
    if not chronological_multiyear:
        fig.update_xaxes(categoryorder="array", categoryarray=MONTH_LABELS)
    return _apply_axis_constraints(fig, column=column, y_values=data[column])
'''
    replace_once(path, old_box, new_box, "monthly box/violin")

    old_threshold = '''def threshold_bar_chart(counts: pd.DataFrame, title: str, unit: str = "hours") -> go.Figure:
    """Create a bar chart for threshold-hour counts with readable period labels."""
    column = counts.columns[0]
    data = counts.copy()
    # Preserve correct period order while avoiding unreadable month-end datetime
    # labels such as "Mar 2026" for a typical-year monthly chart.
    if isinstance(data.index, pd.DatetimeIndex):
        if len(data) <= 12 and data.index.to_series().dt.is_month_end.all():
            data = data.copy()
            data["Period"] = [MONTH_LABELS[int(i.month) - 1] for i in data.index]
            categoryarray = MONTH_LABELS
        elif len(data) <= 60:
            data = data.copy()
            data["Period"] = [f"W{int(i.isocalendar().week):02d}" for i in data.index]
            categoryarray = None
        else:
            data = data.copy()
            data["Period"] = [int(i.dayofyear) for i in data.index]
            categoryarray = None
    else:
        data = data.reset_index().rename(columns={data.index.name or "index": "Period"})
        categoryarray = MONTH_LABELS if set(data["Period"].astype(str)).issubset(set(MONTH_LABELS)) else None
    if "Period" not in data.columns:
        data = data.reset_index().rename(columns={data.index.name or "index": "Period"})
    fig = px.bar(data, x="Period", y=column, title=title, color_discrete_sequence=[semantic_color_from_text(title)])
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title="Period", yaxis_title=unit, margin=dict(l=40, r=20, t=70, b=45))
    if categoryarray is not None:
        fig.update_xaxes(categoryorder="array", categoryarray=categoryarray)
    fig.update_yaxes(range=[0, max(float(data[column].max()) * 1.05, 1.0)], autorangeoptions=dict(minallowed=0))
    return fig
'''
    new_threshold = '''def threshold_bar_chart(counts: pd.DataFrame, title: str, unit: str = "hours") -> go.Figure:
    """Create a threshold bar chart using the aggregation's explicit time semantics."""
    column = counts.columns[0]
    aggregation = str(counts.attrs.get("aggregation", ""))
    basis = time_basis(counts)
    data = counts.copy()
    if aggregation:
        labels = display_period_labels(data.index, aggregation, basis)
    else:
        labels = [str(value) for value in data.index]
    data = data.reset_index(drop=False)
    data["Period"] = labels
    categoryarray = None
    if aggregation == "Monthly" and not (
        isinstance(counts.index, pd.DatetimeIndex)
        and basis == CHRONOLOGICAL
        and is_multiyear(counts.index)
    ):
        categoryarray = MONTH_LABELS
    fig = px.bar(data, x="Period", y=column, title=title, color_discrete_sequence=[semantic_color_from_text(title)])
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title="Period", yaxis_title=unit, margin=dict(l=40, r=20, t=70, b=45))
    if categoryarray is not None:
        fig.update_xaxes(categoryorder="array", categoryarray=categoryarray)
    fig.update_yaxes(range=[0, max(float(data[column].max()) * 1.05, 1.0)], autorangeoptions=dict(minallowed=0))
    return fig
'''
    replace_once(path, old_threshold, new_threshold, "threshold bar labels")

    old_stacked = '''def stacked_monthly_bar(df: pd.DataFrame, title: str, y_label: str = "Hours") -> go.Figure:
    """Create semantic monthly bars; solar components are grouped, never stacked."""
    series_names = [str(column) for column in df.columns]
    data = df.reset_index().melt(id_vars=df.index.name or "index", var_name="series", value_name="value")
    x_column = df.index.name or "index"
    color_map: dict[str, str] = {}
    for index, name in enumerate(series_names):
        inferred = semantic_color_from_text(name)
        color_map[name] = inferred if inferred != DEFAULT_METRIC_COLOR else CLIMATE_COLORS[index % len(CLIMATE_COLORS)]
    solar_tokens = ("global horizontal", "direct normal", "diffuse horizontal", "ghi", "dni", "dhi")
    solar_series = [name for name in series_names if any(token in name.lower() for token in solar_tokens)]
    is_solar_components = len(solar_series) >= 2 and any(token in title.lower() for token in ("solar", "radiation", "irradiation"))
    barmode = "group" if is_solar_components else "stack"
    fig = px.bar(data, x=x_column, y="value", color="series", title=title, barmode=barmode, category_orders={"series": series_names}, color_discrete_map=color_map)
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title="Month", yaxis_title=y_label, barmode=barmode, margin=dict(l=40, r=20, t=70, b=45))
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)
    return fig


def multi_line_monthly(df: pd.DataFrame, title: str, y_label: str) -> go.Figure:
    """Create multi-line monthly charts with semantic series colours."""
    fig = go.Figure()
    for index, column in enumerate(df.columns):
        name = str(column)
        inferred = semantic_color_from_text(name)
        color = inferred if inferred != DEFAULT_METRIC_COLOR else CLIMATE_COLORS[index % len(CLIMATE_COLORS)]
        fig.add_trace(go.Scatter(x=df.index, y=df[column], mode="lines+markers", name=name, line=dict(color=color)))
    fig = apply_common_layout(fig, title, "Month", y_label)
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)
    return fig
'''
    new_stacked = '''def _monthly_axis_values(df: pd.DataFrame) -> tuple[list, str, bool]:
    """Return adaptive monthly x values, axis label and Jan-Dec ordering flag."""
    if isinstance(df.index, pd.DatetimeIndex):
        chronological_multiyear = time_basis(df) == CHRONOLOGICAL and is_multiyear(df.index)
        return display_period_labels(df.index, "Monthly", time_basis(df)), ("Period" if chronological_multiyear else "Month"), not chronological_multiyear
    values = list(df.index)
    numeric_months = all(str(value).isdigit() and 1 <= int(value) <= 12 for value in values)
    if numeric_months:
        return [MONTH_LABELS[int(value) - 1] for value in values], "Month", True
    return [str(value) for value in values], "Period", False


def stacked_monthly_bar(df: pd.DataFrame, title: str, y_label: str = "Hours") -> go.Figure:
    """Create semantic monthly bars without folding chronological year-months."""
    series_names = [str(column) for column in df.columns]
    x_values, x_label, year_neutral = _monthly_axis_values(df)
    wide = df.copy()
    wide["__period__"] = x_values
    data = wide.reset_index(drop=True).melt(id_vars="__period__", var_name="series", value_name="value")
    color_map: dict[str, str] = {}
    for index, name in enumerate(series_names):
        inferred = semantic_color_from_text(name)
        color_map[name] = inferred if inferred != DEFAULT_METRIC_COLOR else CLIMATE_COLORS[index % len(CLIMATE_COLORS)]
    solar_tokens = ("global horizontal", "direct normal", "diffuse horizontal", "ghi", "dni", "dhi")
    solar_series = [name for name in series_names if any(token in name.lower() for token in solar_tokens)]
    is_solar_components = len(solar_series) >= 2 and any(token in title.lower() for token in ("solar", "radiation", "irradiation"))
    barmode = "group" if is_solar_components else "stack"
    fig = px.bar(data, x="__period__", y="value", color="series", title=title, barmode=barmode, category_orders={"series": series_names}, color_discrete_map=color_map)
    fig.update_layout(template=PLOT_TEMPLATE, xaxis_title=x_label, yaxis_title=y_label, barmode=barmode, margin=dict(l=40, r=20, t=70, b=45))
    if year_neutral:
        fig.update_xaxes(categoryorder="array", categoryarray=MONTH_LABELS)
    return fig


def multi_line_monthly(df: pd.DataFrame, title: str, y_label: str) -> go.Figure:
    """Create multi-line monthly charts without collapsing distinct years."""
    x_values, x_label, year_neutral = _monthly_axis_values(df)
    fig = go.Figure()
    for index, column in enumerate(df.columns):
        name = str(column)
        inferred = semantic_color_from_text(name)
        color = inferred if inferred != DEFAULT_METRIC_COLOR else CLIMATE_COLORS[index % len(CLIMATE_COLORS)]
        fig.add_trace(go.Scatter(x=x_values, y=df[column], mode="lines+markers", name=name, line=dict(color=color)))
    fig = apply_common_layout(fig, title, x_label, y_label)
    if year_neutral:
        fig.update_xaxes(categoryorder="array", categoryarray=MONTH_LABELS)
    return fig
'''
    replace_once(path, old_stacked, new_stacked, "adaptive stacked/multiline monthly charts")


def patch_decisions() -> None:
    path = ROOT / "epw_climate_analyzer" / "decisions.py"
    replace_once(
        path,
        "import pandas as pd\n",
        "import pandas as pd\n\nfrom .aggregations import threshold_count_by_period\n",
        "decision aggregation import",
    )
    old = '''def passive_strategy_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Return monthly hours for selected passive and HVAC strategy indicators."""
    masks = {
        "Comfort": comfort_condition(df),
        "Natural ventilation": natural_ventilation_condition(df),
        "Night flushing": night_flushing_condition(df),
        "Shading": shading_condition(df),
        "Economizer": economizer_condition(df),
        "Dehumidification": dehumidification_condition(df),
        "Humidification": humidification_condition(df),
        "Heating": df["dry_bulb_temperature_c"] < 18.0,
        "Cooling": df["dry_bulb_temperature_c"] > 26.0,
    }
    out = pd.DataFrame(index=range(1, 13))
    for label, mask in masks.items():
        temp = pd.Series(mask.fillna(False).astype(int).values, index=df.index)
        out[label] = temp.groupby(df["month_index"]).sum()
    out.index.name = "month"
    return out.fillna(0)
'''
    new = '''def passive_strategy_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Return monthly strategy hours using the active global temporal basis."""
    masks = {
        "Comfort": comfort_condition(df),
        "Natural ventilation": natural_ventilation_condition(df),
        "Night flushing": night_flushing_condition(df),
        "Shading": shading_condition(df),
        "Economizer": economizer_condition(df),
        "Dehumidification": dehumidification_condition(df),
        "Humidification": humidification_condition(df),
        "Heating": df["dry_bulb_temperature_c"] < 18.0,
        "Cooling": df["dry_bulb_temperature_c"] > 26.0,
    }
    frames = [
        threshold_count_by_period(df, mask, "Monthly", label=label)
        for label, mask in masks.items()
    ]
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=1).fillna(0.0)
    out.attrs.update(dict(frames[0].attrs))
    return out
'''
    replace_once(path, old, new, "passive strategy monthly semantics")


def patch_degree_metrics() -> None:
    path = ROOT / "epw_climate_analyzer" / "degree_metrics.py"
    replace_once(
        path,
        "import pandas as pd\n\n\nDegreeMetric",
        "import pandas as pd\n\nfrom .aggregations import period_total_series\n\n\nDegreeMetric",
        "degree metric aggregation import",
    )
    old_aggregate = '''def _aggregate_table(table: pd.DataFrame, aggregation: DegreeAggregation) -> pd.DataFrame:
    if aggregation == "Daily":
        return table.resample("D").sum(min_count=1).dropna(how="all")
    if aggregation == "Seasonal":
        season = pd.Categorical(
            [_season_from_month(int(ts.month)) for ts in table.index],
            categories=SEASON_ORDER,
            ordered=True,
        )
        grouped = table.groupby(season, observed=False).sum(min_count=1)
        grouped.index.name = "Season"
        return grouped.reindex(SEASON_ORDER).dropna(how="all")
    rule = RESAMPLE_RULES.get(aggregation)
    if rule is None:
        raise ValueError(f"Unsupported degree-metric aggregation: {aggregation}")
    return table.resample(rule).sum(min_count=1).dropna(how="all")
'''
    new_aggregate = '''def _aggregate_table(table: pd.DataFrame, aggregation: DegreeAggregation) -> pd.DataFrame:
    """Aggregate extensive degree metrics using the active global time basis."""
    columns: list[pd.Series] = []
    for column in table.columns:
        aggregated = period_total_series(table[column], table, aggregation).rename(column)
        columns.append(aggregated)
    if not columns:
        return table.iloc[0:0].copy()
    result = pd.concat(columns, axis=1).dropna(how="all")
    result.attrs.update(dict(table.attrs))
    result.attrs["aggregation"] = aggregation
    return result
'''
    replace_once(path, old_aggregate, new_aggregate, "degree metric temporal aggregation")

    replace_once(
        path,
        '''        source = pd.DataFrame(index=df.index.copy())
        source["Heating degree-hours (HGT)"] = heating * interval_hours
        source["Cooling degree-hours (KGT)"] = cooling * interval_hours
''',
        '''        source = pd.DataFrame(index=df.index.copy())
        source.attrs.update(dict(df.attrs))
        source["Heating degree-hours (HGT)"] = heating * interval_hours
        source["Cooling degree-hours (KGT)"] = cooling * interval_hours
''',
        "degree-hour attrs",
    )
    replace_once(
        path,
        '''        daily = pd.DataFrame(index=daily_temperature.index)
        daily["Heating degree-days (HGT)"] = heating
        daily["Cooling degree-days (KGT)"] = cooling
        if aggregation == "Daily":
            result = daily.dropna(how="all")
        else:
            result = _aggregate_table(daily, aggregation)
''',
        '''        daily = pd.DataFrame(index=daily_temperature.index)
        daily.attrs.update(dict(df.attrs))
        daily["Heating degree-days (HGT)"] = heating
        daily["Cooling degree-days (KGT)"] = cooling
        result = _aggregate_table(daily, aggregation)
''',
        "degree-day global semantics",
    )


def main() -> None:
    patch_app()
    patch_aggregations()
    patch_charts()
    patch_decisions()
    patch_degree_metrics()


if __name__ == "__main__":
    main()
