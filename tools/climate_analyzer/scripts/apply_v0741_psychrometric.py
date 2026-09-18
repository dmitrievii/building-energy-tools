from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
CHARTS = ROOT / "epw_climate_analyzer" / "charts.py"
COMPARISON = ROOT / "epw_climate_analyzer" / "comparison.py"
INTERPRETATIONS = ROOT / "epw_climate_analyzer" / "interpretations.py"
TEST = ROOT / "tests" / "test_psychrometric_redesign_0_7_4.py"
DOC = ROOT / "CLIMATE_CORE_0_7_4_1.md"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: Path, start: str, end: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{path}: start marker not found: {start!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{path}: end marker not found: {end!r}")
    path.write_text(text[:start_index] + replacement + text[end_index:], encoding="utf-8")


replace_once(
    CHARTS,
    "from .psychrometric_distribution import envelope_polygon_coordinates, psychrometric_occupancy_envelope\n",
    "from .psychrometric_distribution import add_climate_zone_traces, psychrometric_axis_ranges\n",
)

new_psychrometric_chart = r'''def psychrometric_chart(
    df: pd.DataFrame,
    chart_type: str = "T-d",
    pressure_pa: float = DEFAULT_PRESSURE_PA,
    show_rh_curves: bool = True,
    show_comfort_zone: bool = True,
    data_mode: str = "Climate zone",
    t_range: tuple[float, float] | None = None,
    d_range: tuple[float, float] | None = None,
    h_range: tuple[float, float] | None = None,
    metric_layers: list[str] | None = None,
    shown_bioclimatic_zones: list[str] | None = None,
    show_heat_index_overlay: bool = False,
    selected_months: list[int] | None = None,
    color_metric_column: str | None = None,
    color_metric_label: str = "Month",
    color_mode: str = "Month",
    zone_coverage: float = 0.90,
    zone_interior_style: str = "Density gradient",
    show_core_zone: bool = True,
    year_mode: str = "All years combined",
    selected_years: list[int] | None = None,
) -> go.Figure:
    """Create a source-neutral psychrometric chart with climate-zone-first UX.

    Climate zones are smooth duration-weighted 2-D iso-density regions in the
    displayed psychrometric coordinates. The old selected-cell 90% mosaic is no
    longer used. Points remain available as a diagnostic representation.
    """
    fig = go.Figure()
    chart_type = "i-d" if chart_type == "i-d" else "T-d"
    if data_mode in {"Hourly values", "Source interval values", "Monthly points", "All observations", "Points"}:
        representation = "Points"
    else:
        representation = "Climate zone"
    if selected_months is None:
        selected_months = list(range(1, 13))

    plot_df = df[df["month_index"].isin(selected_months)].copy() if "month_index" in df.columns else df.copy()
    plot_df.attrs.update(df.attrs)
    years_available: list[int] = []
    if isinstance(plot_df.index, pd.DatetimeIndex) and not plot_df.empty:
        years_available = sorted({int(value) for value in pd.DatetimeIndex(plot_df.index).year})
    if selected_years:
        chosen = {int(value) for value in selected_years}
        plot_df = plot_df[pd.DatetimeIndex(plot_df.index).year.isin(chosen)].copy()
        plot_df.attrs.update(df.attrs)

    if metric_layers is None:
        metric_layers = ["Relative humidity"] if show_rh_curves else []

    if chart_type == "i-d":
        x_label = "Moisture content d [g/kg dry air]"
        y_label = "Enthalpy i [kJ/kg dry air]"
        x_col = "humidity_ratio_g_kg"
        y_col = "moist_air_enthalpy_kj_kg"
        hover_base = "d: %{x:.2f} g/kg<br>i: %{y:.2f} kJ/kg"
    else:
        x_label = "Dry-bulb temperature [°C]"
        y_label = "Moisture content d [g/kg dry air]"
        x_col = "dry_bulb_temperature_c"
        y_col = "humidity_ratio_g_kg"
        hover_base = "T: %{x:.2f} °C<br>d: %{y:.2f} g/kg"

    auto_x, auto_y = psychrometric_axis_ranges([plot_df], chart_type)
    if chart_type == "T-d":
        axis_ranges = (tuple(t_range) if t_range is not None else auto_x, tuple(d_range) if d_range is not None else auto_y)
    else:
        axis_ranges = (tuple(d_range) if d_range is not None else auto_x, tuple(h_range) if h_range is not None else auto_y)

    # Reference construction lines are deliberately separate from climate-state
    # coordinates. Changing pressure_pa moves the psychrometric reference grid,
    # not the already calculated T-d / i-d climate observations.
    _add_psychrometric_metric_layers(
        fig,
        chart_type,
        pressure_pa,
        t_range,
        d_range,
        h_range,
        metric_layers,
    )

    compare_years = (
        year_mode == "Compare selected years"
        and isinstance(plot_df.index, pd.DatetimeIndex)
        and len({int(value) for value in pd.DatetimeIndex(plot_df.index).year}) > 1
    )

    if representation == "Climate zone":
        if compare_years:
            grouped: list[tuple[str, pd.DataFrame]] = []
            for year in sorted({int(value) for value in pd.DatetimeIndex(plot_df.index).year}):
                group = plot_df[pd.DatetimeIndex(plot_df.index).year == year].copy()
                group.attrs.update(plot_df.attrs)
                grouped.append((str(year), group))
        else:
            grouped = [("Climate zone", plot_df)]
        for index, (label, group) in enumerate(grouped):
            color = CLIMATE_COLORS[index % len(CLIMATE_COLORS)]
            add_climate_zone_traces(
                fig,
                group,
                chart_type=chart_type,
                label=label,
                color=color,
                coverage=float(zone_coverage),
                interior_style=zone_interior_style,
                axis_ranges=axis_ranges,
                show_core=bool(show_core_zone),
                core_coverage=0.50,
                legendgroup=f"psych-zone-{label}",
            )
    else:
        base_cols = _unique_existing_columns([x_col, y_col, "month_index", "month_name", "hour_of_day", color_metric_column], plot_df)
        data = plot_df[base_cols].dropna(subset=[x_col, y_col]).copy()
        if compare_years:
            for index, year in enumerate(sorted({int(value) for value in pd.DatetimeIndex(data.index).year})):
                subset = data[pd.DatetimeIndex(data.index).year == year]
                if subset.empty:
                    continue
                fig.add_trace(
                    go.Scattergl(
                        x=subset[x_col],
                        y=subset[y_col],
                        mode="markers",
                        name=str(year),
                        marker=dict(size=3.6, opacity=0.34, color=CLIMATE_COLORS[index % len(CLIMATE_COLORS)]),
                        hovertemplate=f"Year: {year}<br>" + hover_base + "<extra></extra>",
                    )
                )
        elif color_mode == "Month" or color_metric_column not in data.columns:
            for month in sorted(set(selected_months)):
                subset = data[data["month_index"] == month]
                if subset.empty:
                    continue
                fig.add_trace(
                    go.Scattergl(
                        x=subset[x_col],
                        y=subset[y_col],
                        mode="markers",
                        name=MONTH_LABELS[month - 1],
                        legendgroup="months",
                        legendrank=month,
                        marker=dict(size=3.5, opacity=0.42, color=MONTH_COLORS[month - 1]),
                        customdata=np.repeat(MONTH_LABELS[month - 1], len(subset)),
                        hovertemplate="Month: %{customdata}<br>" + hover_base + "<extra></extra>",
                    )
                )
        else:
            values = pd.Series(data[color_metric_column]).to_numpy(dtype=float)
            cmin, cmax = _finite_min_max(values)
            fig.add_trace(
                go.Scattergl(
                    x=data[x_col],
                    y=data[y_col],
                    mode="markers",
                    name=color_metric_label,
                    showlegend=False,
                    marker=dict(
                        size=3.8,
                        opacity=0.58,
                        color=values,
                        colorscale=_metric_colorscale(color_metric_column),
                        cmin=cmin,
                        cmax=cmax,
                        showscale=True,
                        colorbar=dict(title=color_metric_label, orientation="h", x=0.36, y=-0.20, len=0.44, thickness=12, xanchor="center", yanchor="top"),
                    ),
                    hovertemplate=hover_base + f"<br>{color_metric_label}: %{{marker.color:.2f}}<extra></extra>",
                )
            )

    if show_comfort_zone:
        _add_givoni_milne_overlay(fig, chart_type, pressure_pa, shown_bioclimatic_zones)
    if show_heat_index_overlay:
        _add_heat_index_overlay(fig, chart_type, pressure_pa, t_range, d_range, h_range)

    fig = apply_common_layout(fig, f"Psychrometric chart ({chart_type})", x_label, y_label)
    if compare_years:
        legend_title = "Year"
    elif representation == "Climate zone":
        legend_title = "Climate data"
    else:
        legend_title = "Month" if color_mode == "Month" else "Climate data"
    fig.update_layout(
        height=760,
        autosize=True,
        hovermode="closest",
        legend=dict(
            title=dict(text=legend_title, font=dict(size=13)),
            orientation="h",
            yanchor="top",
            y=-0.12,
            xanchor="center",
            x=0.36,
            itemsizing="constant",
            font=dict(size=12),
            groupclick="toggleitem",
            traceorder="normal",
        ),
        legend2=dict(
            title=dict(text="Zones", font=dict(size=13)),
            orientation="v",
            yanchor="top",
            y=1.0,
            xanchor="left",
            x=0.755,
            itemsizing="constant",
            font=dict(size=12),
            groupclick="togglegroup",
            traceorder="normal",
        ),
        margin=dict(l=64, r=24, t=74, b=155),
    )
    fig.update_xaxes(domain=[0.0, 0.72], range=list(axis_ranges[0]), autorange=False, constrain="domain")
    fig.update_yaxes(range=list(axis_ranges[1]), autorange=False)
    return fig

'''
replace_between(CHARTS, "def psychrometric_chart(\n", "def wind_rose_chart(\n", new_psychrometric_chart)

replace_once(
    COMPARISON,
    "from .psychrometric_distribution import envelope_polygon_coordinates, psychrometric_occupancy_envelope\n",
    "from .psychrometric_distribution import add_climate_zone_traces, psychrometric_axis_ranges\n",
)

new_comparison_chart = r'''def psychrometric_comparison_chart(
    climates: list[ClimateDataset],
    chart_type: str = "T-d",
    mode: str = "Overlay",
    pressure_pa: float = DEFAULT_PRESSURE_PA,
    data_display: str = "Climate zones",
    zone_coverage: float = 0.90,
    zone_interior_style: str = "Density gradient",
    show_core_zone: bool = True,
    reference_pressure_pa: float | None = None,
) -> go.Figure:
    """Create one shared psychrometric comparison diagram.

    Climate zones are the primary representation. Their geometry comes only
    from each climate's already calculated T-d / i-d states. ``reference_pressure_pa``
    controls the common RH construction grid only and cannot move a climate zone.
    """
    del mode
    if data_display in {"All observations", "Points"}:
        representation = "Points"
    elif data_display in {"Climate zones", "Middle 90% envelopes"}:
        representation = "Climate zones"
    else:
        raise ValueError(f"Unsupported psychrometric comparison display: {data_display}")
    chart_type = "i-d" if chart_type == "i-d" else "T-d"
    colors = climate_color_map([climate.display_name for climate in climates])
    fig = go.Figure()
    if chart_type == "i-d":
        x_col = "humidity_ratio_g_kg"
        y_col = "moist_air_enthalpy_kj_kg"
        x_label = "Moisture content d [g/kg dry air]"
        y_label = "Enthalpy i [kJ/kg dry air]"
    else:
        x_col = "dry_bulb_temperature_c"
        y_col = "humidity_ratio_g_kg"
        x_label = "Dry-bulb temperature [°C]"
        y_label = "Moisture content d [g/kg dry air]"

    shared_ranges = psychrometric_axis_ranges([climate.data for climate in climates], chart_type)
    grid_pressure = float(reference_pressure_pa if reference_pressure_pa is not None else pressure_pa)
    temperature_values = pd.concat(
        [pd.to_numeric(climate.data.get("dry_bulb_temperature_c"), errors="coerce") for climate in climates],
        ignore_index=True,
    ).dropna()
    if temperature_values.empty:
        t_min, t_max = -10.0, 40.0
    else:
        t_min = float(temperature_values.min()) - 2.0
        t_max = float(temperature_values.max()) + 2.0

    # One explicitly chosen reference grid keeps the psychrometric background
    # readable. It is a visual construction reference only; climate state points
    # and density zones retain the pressure used when each dataset was derived.
    for curve in psychrometric_rh_curves(chart_type, pressure_pa=grid_pressure, t_min_c=t_min, t_max_c=t_max):
        fig.add_trace(
            go.Scatter(
                x=curve["x"],
                y=curve["y"],
                mode="lines",
                line=dict(color="rgba(100,116,139,0.30)", width=0.75, dash="dash"),
                name=str(curve["label"]),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    for climate in climates:
        color = colors[climate.display_name]
        if representation == "Climate zones":
            add_climate_zone_traces(
                fig,
                climate.data,
                chart_type=chart_type,
                label=climate.display_name,
                color=color,
                coverage=float(zone_coverage),
                interior_style=zone_interior_style,
                axis_ranges=shared_ranges,
                show_core=bool(show_core_zone),
                core_coverage=0.50,
                legendgroup=f"climate-{climate.climate_id}",
            )
        else:
            data = climate.data[[x_col, y_col]].replace([np.inf, -np.inf], np.nan).dropna()
            fig.add_trace(
                go.Scattergl(
                    x=data[x_col],
                    y=data[y_col],
                    mode="markers",
                    name=climate.display_name,
                    marker=dict(size=3.5, opacity=0.22, color=color),
                    hovertemplate=f"{climate.display_name}<br>x: %{{x:.2f}}<br>y: %{{y:.2f}}<extra></extra>",
                )
            )

    title_mode = "climate zones" if representation == "Climate zones" else "observations"
    fig.update_layout(
        template=PLOT_TEMPLATE,
        title=f"Psychrometric climate comparison — {title_mode} ({chart_type})",
        xaxis_title=x_label,
        yaxis_title=y_label,
        hovermode="closest",
        height=760,
        legend_title_text="Climate",
        margin=dict(l=55, r=25, t=70, b=55),
    )
    fig.update_xaxes(range=list(shared_ranges[0]), autorange=False)
    fig.update_yaxes(range=list(shared_ranges[1]), autorange=False)
    return fig

'''
replace_between(COMPARISON, "def psychrometric_comparison_chart(\n", "def sun_path_comparison_chart(\n", new_comparison_chart)

# EPW pressure fallback must belong to the file being loaded, not to another
# active/reference climate. Missing station pressure falls back to that EPW's
# own elevation-derived standard atmosphere pressure.
replace_once(
    APP,
    """    else:\n        valid = data[\"atmospheric_station_pressure_pa\"].dropna()\n        fallback_pressure = float(valid.median()) if not valid.empty else DEFAULT_PRESSURE_PA\n\n    if include_psychrometrics:\n""",
    """    else:\n        valid = pd.to_numeric(data[\"atmospheric_station_pressure_pa\"], errors=\"coerce\").dropna()\n        fallback_pressure = (\n            float(valid.median())\n            if not valid.empty\n            else pressure_from_altitude_m(float(epw.location.elevation_m or 0.0))\n        )\n\n    if include_psychrometrics:\n""",
)

new_render_humidity = r'''def render_humidity(df: pd.DataFrame, pressure_pa: float, *, interval_count_metrics: bool = True) -> None:
    """Render humidity and psychrometric charts."""
    st.header("Humidity and psychrometrics")
    chart_options = ["Humidity variable explorer", "Psychrometric chart", "Moisture thresholds", "Psychrometric scatter relationships"]
    if not interval_count_metrics:
        chart_options.remove("Moisture thresholds")
    chart_group = st.selectbox("Analysis type", chart_options)
    if chart_group == "Humidity variable explorer":
        render_generic_variable_page(
            df,
            ["Relative humidity", "Humidity ratio", "Dew-point temperature", "Wet-bulb temperature", "Moist-air enthalpy", "Specific volume", "Moist-air density"],
            "Humidity ratio",
            "Humidity",
            None,
        )
    elif chart_group == "Psychrometric chart":
        chart_type = st.radio("Psychrometric axes", ["T-d", "i-d"], horizontal=True)
        representation = st.radio(
            "Representation",
            ["Climate zone", "Points"],
            horizontal=True,
            help="Climate zone is the recommended view. Points are retained for inspecting individual observations and outliers.",
        )

        zone_coverage = 0.90
        zone_interior_style = "Density gradient"
        show_core_zone = True
        if representation == "Climate zone":
            z1, z2, z3 = st.columns([1, 1.4, 1])
            coverage_pct = z1.slider("Zone coverage [%]", 50, 99, 90, 1, key="psych_zone_coverage")
            zone_coverage = float(coverage_pct) / 100.0
            zone_interior_style = z2.selectbox(
                "Zone interior",
                ["Density gradient", "Sparse points", "Solid fill", "Contour only"],
                index=0,
                key="psych_zone_interior",
            )
            show_core_zone = z3.checkbox("Show 50% core contour", value=True, key="psych_zone_core")
            st.caption(
                "The zone boundary is a smooth two-dimensional iso-density contour containing the selected share of represented climate duration. "
                "The density gradient shows where states occur most frequently inside that contour; no selected-cell mosaic is used."
            )

        col_a, col_b, col_c = st.columns(3)
        t_min = float(df["dry_bulb_temperature_c"].min())
        t_max = float(df["dry_bulb_temperature_c"].max())
        d_max_default = max(20.0, float(df["humidity_ratio_g_kg"].quantile(0.995)) * 1.1)
        h_min = float(df["moist_air_enthalpy_kj_kg"].quantile(0.005))
        h_max = float(df["moist_air_enthalpy_kj_kg"].quantile(0.995))
        t_limits = col_a.slider(
            "Dry-bulb temperature range [°C]",
            -40.0,
            60.0,
            (float(max(-40, int(t_min // 5 * 5))), float(min(60, int(t_max // 5 * 5 + 10)))),
            1.0,
        )
        d_limits = col_b.slider("Moisture content range [g/kg]", 0.0, 40.0, (0.0, float(min(40.0, d_max_default))), 0.5)
        h_limits = col_c.slider(
            "Enthalpy range [kJ/kg dry air]",
            -30.0,
            140.0,
            (float(max(-30, int(h_min // 10 * 10))), float(min(140, int(h_max // 10 * 10 + 20)))),
            1.0,
        )

        with st.expander("Chart metrics and overlays", expanded=True):
            metric_layers = st.multiselect(
                "Metric lines",
                PSYCHROMETRIC_METRIC_LINES,
                default=["Dry-bulb temperature", "Humidity ratio", "Relative humidity"],
                help="Turn psychrometric metric lines on or off. Lines are intentionally grey and low-emphasis.",
            )
            show_givoni = st.checkbox("Show Givoni-Milne bioclimatic overlay", value=True)
            selected_zones: list[str] | None = None
            show_heat_index = st.checkbox("Show heat-index overlay", value=False)

        with st.expander("Loaded data mapping", expanded=True):
            months = st.multiselect("Displayed months", list(MONTHS.keys()), default=list(MONTHS.keys()), key="psych_month_filter")
            selected_months = [MONTHS[m] for m in months]
            chronological_multiyear = time_basis(df) == CHRONOLOGICAL and is_multiyear(df)
            year_mode = "All years combined"
            selected_years: list[int] | None = None
            if chronological_multiyear:
                years = available_years(df)
                year_mode = st.selectbox(
                    "Year display",
                    ["All years combined", "Single year", "Compare selected years"],
                    index=0,
                    key="psych_year_mode",
                )
                if year_mode == "Single year":
                    selected_years = [int(st.selectbox("Year", years, index=len(years) - 1, key="psych_single_year"))]
                elif year_mode == "Compare selected years":
                    default_years = years if len(years) <= 5 else years[-5:]
                    selected_years = [int(value) for value in st.multiselect("Years", years, default=default_years, key="psych_compare_years")]
                    if not selected_years:
                        st.info("Select at least one real source year for the psychrometric comparison.")
                        return
                    st.caption("Each selected year is drawn independently on the same fixed psychrometric axes.")

            color_mode = "Month"
            color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]
            if representation == "Points" and year_mode != "Compare selected years":
                metric_options = [name for name in PSYCHROMETRIC_COLOR_METRICS if name != "Frequency"]
                color_mode = st.selectbox("Colour mapped metric", metric_options, index=metric_options.index("Month"))
                color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]
            elif representation == "Points" and year_mode == "Compare selected years":
                st.caption("Point colours identify real source years; metric colouring is disabled while years are being compared.")

        fig = psychrometric_chart(
            df,
            chart_type=chart_type,
            pressure_pa=pressure_pa,
            show_rh_curves="Relative humidity" in metric_layers,
            show_comfort_zone=show_givoni,
            data_mode=representation,
            t_range=t_limits,
            d_range=d_limits,
            h_range=h_limits,
            metric_layers=metric_layers,
            shown_bioclimatic_zones=selected_zones,
            show_heat_index_overlay=show_heat_index,
            selected_months=selected_months,
            color_metric_column=color_metric_column,
            color_metric_label=color_metric_label,
            color_mode=color_mode,
            zone_coverage=zone_coverage,
            zone_interior_style=zone_interior_style,
            show_core_zone=show_core_zone,
            year_mode=year_mode,
            selected_years=selected_years,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True}, key=next_plot_key("psychrometric"))
        report_df = df[df["month_index"].isin(selected_months)].copy()
        report_df.attrs.update(df.attrs)
        if selected_years and isinstance(report_df.index, pd.DatetimeIndex):
            report_df = report_df[pd.DatetimeIndex(report_df.index).year.isin(selected_years)].copy()
            report_df.attrs.update(df.attrs)
        render_interpretation(psychrometric_interpretation(report_df))
        if show_givoni:
            render_bioclimatic_report(report_df)
    elif chart_group == "Moisture thresholds":
        d_low = st.slider("Dry-air threshold [g/kg]", 0.0, 8.0, 3.0, 0.25)
        d_high = st.slider("Humid-air threshold [g/kg]", 5.0, 25.0, 10.0, 0.25)
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        mode = st.radio("Condition", ["Below dry-air threshold", "Above humid-air threshold", "Relative humidity above 80%"])
        if mode == "Below dry-air threshold":
            condition = df["humidity_ratio_g_kg"] < d_low
        elif mode == "Above humid-air threshold":
            condition = df["humidity_ratio_g_kg"] > d_high
        else:
            condition = df["relative_humidity_pct"] > 80.0
        counts = threshold_count_by_period(df, condition, aggregation, label="hours")
        fig = threshold_bar_chart(counts, f"Moisture threshold hours: {mode}")
        render_plot(fig, psychrometric_interpretation(df))
    else:
        x_label = st.selectbox("X variable", ["Dry-bulb temperature", "Dew-point temperature", "Humidity ratio", "Moist-air enthalpy"])
        y_label = st.selectbox("Y variable", ["Humidity ratio", "Relative humidity", "Moist-air enthalpy", "Wet-bulb temperature"])
        x, x_unit = VARIABLES[x_label]
        y, y_unit = VARIABLES[y_label]
        fig = scatter_chart(df, x, y, "month_index", f"{x_label} vs {y_label}", f"{x_label} [{x_unit}]", f"{y_label} [{y_unit}]")
        render_plot(fig, psychrometric_interpretation(df))


'''
replace_between(APP, "def render_humidity(\n", "def render_solar(\n", new_render_humidity)

new_render_compare_humidity = r'''def render_compare_humidity(climates: list[ClimateDataset], reference_name: str, display_mode: str) -> None:
    """Render humidity and psychrometric comparison charts."""
    st.subheader("Humidity and psychrometric comparison")
    chart = st.selectbox(
        "Humidity chart",
        [
            "Humidity ratio monthly profile",
            "Humidity ratio duration curve",
            "Outdoor-air enthalpy duration curve",
            "Psychrometric climate zones",
            "Moisture and latent-load ranking",
        ],
    )
    mode = choose_display_mode(chart, display_mode, len(climates))
    if chart == "Humidity ratio monthly profile":
        table = monthly_profile_table(climates, "humidity_ratio_g_kg", statistic="mean")
        if mode == "Difference to reference":
            fig = monthly_difference_chart(table, reference_name, "Monthly humidity ratio", "Humidity ratio [g/kg]")
        elif mode == "Small multiples":
            fig = small_multiple_monthly_chart(table, "Monthly humidity ratio", "Humidity ratio [g/kg]")
        else:
            fig = overlay_monthly_chart(table, "Monthly humidity ratio", "Humidity ratio [g/kg]")
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Humidity ratio duration curve":
        fig = duration_comparison_chart(climates, "humidity_ratio_g_kg", "Humidity ratio duration curves", "Humidity ratio [g/kg]", ascending=False)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Outdoor-air enthalpy duration curve":
        fig = duration_comparison_chart(climates, "moist_air_enthalpy_kj_kg", "Outdoor-air enthalpy duration curves", "Enthalpy [kJ/kg dry air]", ascending=False)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    elif chart == "Psychrometric climate zones":
        chart_type = st.radio("Psychrometric axes", ["T-d", "i-d"], horizontal=True, key="compare_psych_axes")
        representation = st.radio(
            "Representation",
            ["Climate zones", "Points"],
            horizontal=True,
            key="compare_psych_representation",
        )
        zone_coverage = 0.90
        zone_interior_style = "Density gradient"
        show_core_zone = True
        if representation == "Climate zones":
            c1, c2, c3 = st.columns([1, 1.4, 1])
            zone_coverage = float(c1.slider("Zone coverage [%]", 50, 99, 90, 1, key="compare_psych_coverage")) / 100.0
            zone_interior_style = c2.selectbox(
                "Zone interior",
                ["Density gradient", "Sparse points", "Solid fill", "Contour only"],
                index=0,
                key="compare_psych_interior",
            )
            show_core_zone = c3.checkbox("Show 50% core contour", value=True, key="compare_psych_core")

        reference = next((climate for climate in climates if climate.display_name == reference_name), climates[0])
        pressure_values = pd.to_numeric(reference.data.get("atmospheric_station_pressure_pa"), errors="coerce").dropna()
        if not pressure_values.empty:
            reference_climate_pressure = float(pressure_values.median())
        else:
            reference_climate_pressure = pressure_from_altitude_m(float(reference.epw.location.elevation_m or 0.0))
        grid_mode = st.selectbox(
            "Reference psychrometric grid pressure",
            ["Standard atmosphere — 101325 Pa", f"Reference climate — {reference_name}", "Custom pressure"],
            index=0,
            key="compare_psych_grid_pressure_mode",
            help="This pressure controls only the grey RH construction grid. Climate zones and points retain each dataset's actual calculated psychrometric state.",
        )
        if grid_mode == "Standard atmosphere — 101325 Pa":
            reference_grid_pressure = DEFAULT_PRESSURE_PA
        elif grid_mode.startswith("Reference climate"):
            reference_grid_pressure = reference_climate_pressure
        else:
            reference_grid_pressure = st.number_input(
                "Reference grid pressure [Pa]",
                min_value=30000.0,
                max_value=120000.0,
                value=float(round(reference_climate_pressure / 100.0) * 100.0),
                step=100.0,
                key="compare_psych_grid_pressure_custom",
            )
        st.caption(
            f"Shared axes are fixed across representations. Reference grid: {float(reference_grid_pressure):,.0f} Pa. "
            "The grid is only a visual psychrometric reference; every climate retains the pressure used to derive its own humidity ratio and enthalpy."
        )
        if representation == "Climate zones":
            st.caption(
                "Each colour is one climate zone. The solid outer line encloses the selected duration share, the optional dotted line marks the 50% core, and the default interior gradient shows relative occurrence density within that climate."
            )
        fig = psychrometric_comparison_chart(
            climates,
            chart_type=chart_type,
            mode=mode,
            data_display=representation,
            zone_coverage=zone_coverage,
            zone_interior_style=zone_interior_style,
            show_core_zone=show_core_zone,
            reference_pressure_pa=float(reference_grid_pressure),
        )
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))
    else:
        metric = st.selectbox("Moisture metric", ["Mean humidity ratio [g/kg]", "Humidity ratio P95 [g/kg]", "Hours d >10 g/kg [h]", "Hours d <3 g/kg [h]", "Enthalpy P95 [kJ/kg]", "Maximum wet-bulb [°C]", "Dehumidification hours [h]", "Humidification hours [h]"])
        fig = ranked_metric_chart(climate_summary_metrics(climates), metric)
        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))


'''
replace_between(APP, "def render_compare_humidity(\n", "def render_compare_solar(\n", new_render_compare_humidity)
replace_once(
    APP,
    "        render_compare_humidity(climates, reference_name, display_mode, pressure_pa=active_pressure)\n",
    "        render_compare_humidity(climates, reference_name, display_mode)\n",
)

new_psych_interpretation = r'''def psychrometric_interpretation(df: pd.DataFrame) -> str:
    """Interpret psychrometric conditions and preserve real-year change."""
    d = df["humidity_ratio_g_kg"].dropna()
    h = df["moist_air_enthalpy_kj_kg"].dropna()
    if d.empty or h.empty:
        return "No valid psychrometric data are available."
    dry = _duration_hours_from_count(df, int((d < 3).sum()))
    humid = _duration_hours_from_count(df, int((d > 10).sum()))
    high_enthalpy = _duration_hours_from_count(df, int((h > 55).sum()))
    text = (
        f"The humidity-ratio range is {_fmt(d.min())}...{_fmt(d.max())} g/kg. "
        f"There are {_fmt_hours(dry)} very dry hours below 3 g/kg and {_fmt_hours(humid)} humid hours above 10 g/kg. "
        f"{_fmt_hours(high_enthalpy)} hours exceed 55 kJ/kg moist-air enthalpy, which is relevant for economizer and cooling/dehumidification decisions."
    )
    if isinstance(df.index, pd.DatetimeIndex) and time_basis(df) == CHRONOLOGICAL:
        years = pd.DatetimeIndex(df.index).year
        unique_years = sorted({int(value) for value in years})
        if len(unique_years) >= 2:
            annual_rows = []
            interval_h = native_interval_hours(df)
            for year in unique_years:
                mask = years == year
                d_year = pd.to_numeric(df.loc[mask, "humidity_ratio_g_kg"], errors="coerce").dropna()
                h_year = pd.to_numeric(df.loc[mask, "moist_air_enthalpy_kj_kg"], errors="coerce").dropna()
                if d_year.empty or h_year.empty:
                    continue
                annual_rows.append(
                    {
                        "year": year,
                        "mean_d": float(d_year.mean()),
                        "p95_d": float(d_year.quantile(0.95)),
                        "high_enthalpy_h": float((h_year > 55.0).sum()) * interval_h,
                    }
                )
            if len(annual_rows) >= 2:
                first = annual_rows[0]
                last = annual_rows[-1]
                wettest = max(annual_rows, key=lambda row: row["p95_d"])
                text += (
                    f" Across real years, mean humidity ratio changes from {first['mean_d']:.1f} g/kg in {first['year']} "
                    f"to {last['mean_d']:.1f} g/kg in {last['year']}; the highest annual P95 is {wettest['p95_d']:.1f} g/kg "
                    f"in {wettest['year']}. High-enthalpy duration changes from {_fmt_hours(first['high_enthalpy_h'])} to "
                    f"{_fmt_hours(last['high_enthalpy_h'])} hours between the first and last represented years."
                )
    return text


'''
replace_between(INTERPRETATIONS, "def psychrometric_interpretation(\n", "def hvac_interpretation(\n", new_psych_interpretation)

TEST.write_text(r'''from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd
import psychrolib

from epw_climate_analyzer.charts import psychrometric_chart
from epw_climate_analyzer.comparison import ClimateDataset, psychrometric_comparison_chart
from epw_climate_analyzer.psychrometric_distribution import psychrometric_axis_ranges, psychrometric_density_field
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis

psychrolib.SetUnitSystem(psychrolib.SI)
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
DIST = ROOT / "epw_climate_analyzer" / "psychrometric_distribution.py"


def _psych_frame(year: int = 2026, *, offset_c: float = 0.0, pressure_pa: float = 101325.0) -> pd.DataFrame:
    rng = np.random.default_rng(year)
    n = 720
    t = np.concatenate([
        rng.normal(8.0 + offset_c, 3.0, n // 3),
        rng.normal(19.0 + offset_c, 3.2, n // 3),
        rng.normal(28.0 + offset_c, 2.8, n - 2 * (n // 3)),
    ])
    rh = np.clip(72.0 - 0.9 * t + rng.normal(0.0, 8.0, n), 20.0, 98.0)
    index = pd.date_range(f"{year}-01-01", periods=n, freq="h")
    w = np.array([psychrolib.GetHumRatioFromRelHum(float(tt), float(rr) / 100.0, pressure_pa) for tt, rr in zip(t, rh, strict=True)])
    d = w * 1000.0
    h = np.array([psychrolib.GetMoistAirEnthalpy(float(tt), float(ww)) / 1000.0 for tt, ww in zip(t, w, strict=True)])
    frame = pd.DataFrame(
        {
            "dry_bulb_temperature_c": t,
            "relative_humidity_pct": rh,
            "humidity_ratio_g_kg": d,
            "moist_air_enthalpy_kj_kg": h,
            "atmospheric_station_pressure_pa": pressure_pa,
            "month_index": index.month,
            "month_name": index.strftime("%b"),
            "hour_of_day": index.hour,
        },
        index=index,
    )
    return with_time_basis(frame, CHRONOLOGICAL)


class PsychrometricRedesign0741Tests(unittest.TestCase):
    def test_zone_is_smooth_joint_density_with_requested_coverage(self) -> None:
        frame = _psych_frame()
        field = psychrometric_density_field(frame, target_share=0.90)
        self.assertGreater(field.threshold_hours, 0.0)
        self.assertGreaterEqual(field.achieved_share, 0.90)
        self.assertLess(field.achieved_share, 0.94)
        self.assertEqual(field.mass_hours.shape, (140, 120))
        self.assertFalse(hasattr(field, "selected_tiles"))
        self.assertGreater(np.count_nonzero((field.mass_hours > 0) & (field.mass_hours < field.max_mass_hours)), 100)

    def test_climate_zone_uses_contours_not_selected_cell_polygons(self) -> None:
        fig = psychrometric_chart(
            _psych_frame(),
            chart_type="T-d",
            show_comfort_zone=False,
            metric_layers=[],
            data_mode="Climate zone",
            zone_coverage=0.90,
            zone_interior_style="Density gradient",
        )
        contour_traces = [trace for trace in fig.data if trace.type == "contour"]
        self.assertGreaterEqual(len(contour_traces), 2)
        self.assertFalse(any(getattr(trace, "fill", None) == "toself" for trace in fig.data))
        self.assertIsNotNone(fig.layout.xaxis.range)
        self.assertIsNotNone(fig.layout.yaxis.range)

    def test_multiyear_compare_selected_years_draws_independent_zones_on_fixed_axes(self) -> None:
        frame = pd.concat([_psych_frame(2024), _psych_frame(2025, offset_c=1.5)])
        frame = with_time_basis(frame, CHRONOLOGICAL)
        fig = psychrometric_chart(
            frame,
            chart_type="T-d",
            show_comfort_zone=False,
            metric_layers=[],
            data_mode="Climate zone",
            year_mode="Compare selected years",
            selected_years=[2024, 2025],
        )
        legend_names = {str(trace.name) for trace in fig.data if trace.type == "scatter" and trace.showlegend}
        self.assertIn("2024", legend_names)
        self.assertIn("2025", legend_names)
        self.assertFalse(bool(fig.layout.xaxis.autorange))
        self.assertFalse(bool(fig.layout.yaxis.autorange))

    def test_reference_grid_pressure_does_not_move_comparison_zone_density(self) -> None:
        climate_a = _psych_frame(2026, pressure_pa=101325.0)
        climate_b = _psych_frame(2026, offset_c=3.0, pressure_pa=85000.0)
        climates = [
            ClimateDataset("a", "Climate A", "test", None, climate_a, []),
            ClimateDataset("b", "Climate B", "test", None, climate_b, []),
        ]
        sea = psychrometric_comparison_chart(climates, data_display="Climate zones", reference_pressure_pa=101325.0)
        high = psychrometric_comparison_chart(climates, data_display="Climate zones", reference_pressure_pa=85000.0)
        sea_zone = [trace for trace in sea.data if trace.type == "contour" and "% zone" in str(trace.name)]
        high_zone = [trace for trace in high.data if trace.type == "contour" and "% zone" in str(trace.name)]
        self.assertEqual(len(sea_zone), 2)
        self.assertEqual(len(high_zone), 2)
        for left, right in zip(sea_zone, high_zone, strict=True):
            np.testing.assert_allclose(np.asarray(left.z, dtype=float), np.asarray(right.z, dtype=float), rtol=0.0, atol=0.0)
            np.testing.assert_allclose(np.asarray(left.x, dtype=float), np.asarray(right.x, dtype=float), rtol=0.0, atol=0.0)
            np.testing.assert_allclose(np.asarray(left.y, dtype=float), np.asarray(right.y, dtype=float), rtol=0.0, atol=0.0)
        self.assertEqual(tuple(sea.layout.xaxis.range), tuple(high.layout.xaxis.range))
        self.assertEqual(tuple(sea.layout.yaxis.range), tuple(high.layout.yaxis.range))

    def test_comparison_has_one_shared_axis_and_climate_zone_identity(self) -> None:
        climates = [
            ClimateDataset("a", "Climate A", "test", None, _psych_frame(2026), []),
            ClimateDataset("b", "Climate B", "test", None, _psych_frame(2026, offset_c=4.0), []),
        ]
        fig = psychrometric_comparison_chart(climates, data_display="Climate zones")
        legend_names = {str(trace.name) for trace in fig.data if trace.type == "scatter" and trace.showlegend}
        self.assertEqual(legend_names, {"Climate A", "Climate B"})
        self.assertEqual(fig.layout.legend.title.text, "Climate")
        self.assertFalse(any(str(key).startswith("xaxis2") or str(key).startswith("yaxis2") for key in fig.layout))
        self.assertFalse(bool(fig.layout.xaxis.autorange))
        self.assertFalse(bool(fig.layout.yaxis.autorange))

    def test_shared_axis_helper_spans_all_climates(self) -> None:
        a = _psych_frame(2026)
        b = _psych_frame(2026, offset_c=8.0)
        (x0, x1), (y0, y1) = psychrometric_axis_ranges([a, b], "T-d")
        self.assertLessEqual(x0, float(min(a["dry_bulb_temperature_c"].min(), b["dry_bulb_temperature_c"].min())))
        self.assertGreaterEqual(x1, float(max(a["dry_bulb_temperature_c"].max(), b["dry_bulb_temperature_c"].max())))
        self.assertLessEqual(y0, float(min(a["humidity_ratio_g_kg"].min(), b["humidity_ratio_g_kg"].min())))
        self.assertGreaterEqual(y1, float(max(a["humidity_ratio_g_kg"].max(), b["humidity_ratio_g_kg"].max())))

    def test_ui_contract_removes_cell_90_and_exposes_zone_controls(self) -> None:
        source = APP.read_text(encoding="utf-8")
        distribution_source = DIST.read_text(encoding="utf-8")
        self.assertIn('["Climate zone", "Points"]', source)
        self.assertIn('["Climate zones", "Points"]', source)
        self.assertIn('"Zone coverage [%]"', source)
        self.assertIn('"Zone interior"', source)
        self.assertIn('"Density gradient"', source)
        self.assertIn('"Year display"', source)
        self.assertIn('"Compare selected years"', source)
        self.assertIn('"Reference psychrometric grid pressure"', source)
        self.assertNotIn("highest-density 1 °C × 5 %RH occupancy cells", source)
        self.assertNotIn("PsychrometricOccupancyEnvelope", distribution_source)
        self.assertNotIn("selected_tiles", distribution_source)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

DOC.write_text(r'''# Climate Analyzer 0.7.4.1 — Psychrometric Integration Remediation

## Purpose

This patch closes the psychrometric integration defects discovered after the 0.7.4 production merge. The previous selected-cell "Middle 90%" visualization is removed as a user-facing/statistical model for climate comparison.

## Climate-zone contract

- **Climate zones are continuous 2-D iso-density regions**, calculated in the actual displayed psychrometric coordinates (`T–d` or `i–d`).
- Observations are duration-weighted on a regular grid, smoothed deterministically with a NumPy Gaussian kernel, and the contour threshold is chosen by cumulative smooth density.
- `90%` therefore means: the smooth joint-density region containing at least 90% of represented physical duration.
- It is **not** an independent P05/P95 rectangle and **not** a union of selected 1 °C × 5% RH squares.
- Zone coverage is user-selectable from 50–99%.
- Default interior: **Density gradient** in the climate colour. Alternatives: Sparse points, Solid fill, Contour only.
- Optional dotted 50% core contour is available inside the main zone.

## Pressure contract

Psychrometric state coordinates retain the pressure used when that climate was derived. The common comparison RH grid has its own explicit **reference grid pressure** and is visual-only. Changing reference-grid pressure must not move climate observations or climate-zone density contours.

If an EPW station-pressure series is unavailable, that EPW falls back to pressure derived from **its own elevation**, never to the active/reference climate's pressure.

## Multi-year contract

Chronological multi-year psychrometric analysis exposes:

- All years combined
- Single year
- Compare selected years

Year comparisons use real source years on one fixed axis domain. Climate-zone representation is the default because it preserves distribution shape and temporal comparison without rendering tens of thousands of overlapping points.

## Compare Climates contract

The psychrometric comparison is one large shared diagram. Default representation is **Climate zones**, not small multiples, point clouds or square mosaics. Each climate has one colour, one outer contour and an optional density gradient/core contour. Axis limits are calculated once from all selected climates and remain fixed when switching representation.
''', encoding="utf-8")

print("0.7.4.1 psychrometric integration patch applied")
