from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} marker not found")
    return text.replace(old, new, 1)


ground = Path("tools/climate_analyzer/epw_climate_analyzer/ground_temperature.py")
text = ground.read_text(encoding="utf-8")
text = replace_once(
    text,
    """    idx = pd.DatetimeIndex(values.index[valid])
    y = values.loc[valid].to_numpy(dtype=float)
    # Use annual phase within each represented calendar year so multi-year
""",
    """    idx = pd.DatetimeIndex(values.index[valid])
    represented_day_of_year = set(int(day) for day in idx.dayofyear)
    if len(represented_day_of_year) < 300:
        raise ValueError(
            "Calculated annual ground profile requires at least 300 represented calendar days; "
            "use a near-full-year Data filter or measured ground temperatures instead."
        )
    y = values.loc[valid].to_numpy(dtype=float)
    # Use annual phase within each represented calendar year so multi-year
""",
    "ground harmonic coverage",
)
ground.write_text(text, encoding="utf-8")

app = Path("tools/climate_analyzer/app.py")
text = app.read_text(encoding="utf-8")
text = replace_once(
    text,
    "def render_ground_temperature_page(df: pd.DataFrame, *, source_label: str) -> None:\n",
    "def render_ground_temperature_page(df: pd.DataFrame, *, source_label: str, native_df: pd.DataFrame | None = None) -> None:\n",
    "ground render signature",
)
text = replace_once(
    text,
    "    measured = measured_monthly_ground(df)\n",
    "    measured_source = native_df if native_df is not None else df\n    measured = measured_monthly_ground(measured_source)\n",
    "measured source",
)
text = replace_once(
    text,
    """    elif page == "Ground Temperature":
        render_ground_temperature_page(filtered_df, source_label="GeoSphere measured")
""",
    """    elif page == "Ground Temperature":
        native_ground_df = apply_active_global_filter(prepare_historical_native_diagnostic_frame(dataset))
        render_ground_temperature_page(
            filtered_df,
            source_label="GeoSphere measured",
            native_df=native_ground_df,
        )
""",
    "historical ground dispatch",
)
text = replace_once(
    text,
    """    elif chart_group == "Measured sunshine duration":
        render_generic_variable_page(df, ["Sunshine duration"], "Sunshine duration", "Measured sunshine duration", None)
    elif chart_group == "Relative sunshine duration":
        summary = monthly_daylight_sunshine_summary(df, float(latitude))
        data = summary.dropna(subset=["relative_sunshine_pct"])
        fig = px.bar(data, x="month", y="relative_sunshine_pct", title="Measured sunshine as share of astronomical daylight")
        fig.update_layout(template="plotly_white", xaxis_title="Month", yaxis_title="Relative sunshine duration [%]")
        render_plot(fig, "Measured sunshine duration divided by the astronomical daylight duration represented by the same calendar days.")
""",
    """    elif chart_group == "Measured sunshine duration":
        sunshine = pd.to_numeric(df["sunshine_duration_s"], errors="coerce") / 3600.0
        aggregation = st.selectbox("Aggregation", ["Daily", "Monthly", "Annual"], index=1, key="sunshine_duration_aggregation")
        rule = {"Daily": "D", "Monthly": "MS", "Annual": "YS"}[aggregation]
        totals = sunshine.resample(rule).sum(min_count=1).dropna().to_frame("sunshine_h")
        if totals.empty:
            st.info("No measured sunshine-duration values are available in the active Data filter.")
            return
        plot_data = totals.reset_index()
        period_column = plot_data.columns[0]
        fig = px.bar(plot_data, x=period_column, y="sunshine_h", title=f"Measured sunshine duration — {aggregation.lower()}")
        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Measured sunshine duration [h]")
        render_plot(fig, "GeoSphere sunshine duration is a measured interval-duration quantity summed in hours. Missing observations are excluded, never replaced by zero.")
    elif chart_group == "Relative sunshine duration":
        summary = monthly_daylight_sunshine_summary(df, float(latitude))
        if "relative_sunshine_pct" not in summary.columns:
            st.info("Relative sunshine duration requires complete measured sunshine coverage for at least one full calendar day in the active Data filter.")
            return
        data = summary.dropna(subset=["relative_sunshine_pct"])
        if data.empty:
            st.info("Relative sunshine duration requires complete measured sunshine coverage for at least one full calendar day in the active Data filter.")
            return
        fig = px.bar(data, x="month", y="relative_sunshine_pct", title="Measured sunshine as share of astronomical daylight")
        fig.update_layout(template="plotly_white", xaxis_title="Month", yaxis_title="Relative sunshine duration [%]")
        render_plot(fig, "Measured sunshine duration divided by astronomical daylight only for fully observed calendar days; incomplete days are excluded rather than treated as zero sunshine.")
""",
    "sunshine branches",
)
app.write_text(text, encoding="utf-8")
