from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "epw_climate_analyzer"
TESTS = ROOT / "tests"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected anchor missing in {path}: {old[:160]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Expected one regex patch in {path}, got {count}: {pattern[:160]!r}")
    path.write_text(updated, encoding="utf-8")


# ---------------------------------------------------------------------------
# B1. Ground temperature belongs to Temperature, not top-level navigation.
# ---------------------------------------------------------------------------
ui = PKG / "ui_contract.py"
replace_once(ui, '    "Ground Temperature",\n', '')
replace_once(ui, '    "Ground Temperature": "Climate — Ground temperature",\n', '')

caps = PKG / "historical_capabilities.py"
replace_once(
    caps,
    '''    if has_temperature:\n        pages.append("Temperature")\n    if has_mean_temperature or has_ground:\n        pages.append("Ground Temperature")\n''',
    '''    if has_temperature or has_ground:\n        pages.append("Temperature")\n''',
)

app = ROOT / "app.py"
replace_once(
    app,
    'def render_temperature(df: pd.DataFrame, *, interval_count_metrics: bool = True) -> None:\n',
    'def render_temperature(\n    df: pd.DataFrame,\n    *,\n    interval_count_metrics: bool = True,\n    ground_source_label: str | None = None,\n    ground_native_df: pd.DataFrame | None = None,\n) -> None:\n',
)
replace_once(
    app,
    '''    st.header("Temperature and extremes")\n    chart_options = ["Temperature variable explorer", "Threshold hours", "Degree days", "Extreme days"]\n    if not interval_count_metrics:\n        chart_options.remove("Threshold hours")\n    chart_group = st.selectbox("Analysis type", chart_options)\n\n    if chart_group == "Degree days":\n''',
    '''    st.header("Temperature and extremes")\n    measured_ground_source = ground_native_df if ground_native_df is not None else df\n    has_air_temperature = (\n        "dry_bulb_temperature_c" in df.columns\n        and pd.to_numeric(df["dry_bulb_temperature_c"], errors="coerce").notna().any()\n    )\n    has_ground_measurement = any(\n        column in measured_ground_source.columns\n        and pd.to_numeric(measured_ground_source[column], errors="coerce").notna().any()\n        for column in ("ground_temperature_0_10m_c", "ground_temperature_0_20m_c", "ground_temperature_0_50m_c")\n    )\n\n    chart_options: list[str] = []\n    if has_air_temperature:\n        chart_options.append("Temperature variable explorer")\n    if has_air_temperature or has_ground_measurement:\n        chart_options.append("Ground temperature")\n    if has_air_temperature and interval_count_metrics:\n        chart_options.append("Threshold conditions")\n    if has_air_temperature:\n        chart_options.extend(["Degree days", "Extreme days"])\n    if not chart_options:\n        st.info("No air- or ground-temperature observations are available for the current Data filter.")\n        return\n    chart_group = st.selectbox("Analysis type", chart_options)\n\n    if chart_group == "Ground temperature":\n        render_ground_temperature_page(\n            df,\n            source_label=ground_source_label or "Calculated from outdoor dry-bulb temperature",\n            native_df=ground_native_df,\n        )\n        return\n\n    if chart_group == "Degree days":\n''',
)
replace_once(
    app,
    'if chart_group in {"Temperature variable explorer", "Threshold hours"}:',
    'if chart_group in {"Temperature variable explorer", "Threshold conditions"}:',
)
replace_once(app, 'elif chart_group == "Threshold hours":', 'elif chart_group == "Threshold conditions":')

# Historical route: Temperature gets measured shallow-ground source under the same page.
replace_once(
    app,
    '''    elif page == "Temperature":\n        st.caption("Threshold hours are evaluated on the canonical hourly analysis series. Physically incomplete source hours are absent and contribute no duration.")\n        render_temperature(filtered_df)\n    elif page == "Ground Temperature":\n        native_ground_df = apply_active_global_filter(prepare_historical_native_diagnostic_frame(dataset))\n        render_ground_temperature_page(\n            filtered_df,\n            source_label="GeoSphere measured",\n            native_df=native_ground_df,\n        )\n''',
    '''    elif page == "Temperature":\n        st.caption("Threshold conditions are evaluated on the canonical hourly analysis series. Physically incomplete source hours are absent and contribute no duration.")\n        native_ground_df = apply_active_global_filter(prepare_historical_native_diagnostic_frame(dataset))\n        render_temperature(\n            filtered_df,\n            ground_source_label="GeoSphere measured",\n            ground_native_df=native_ground_df,\n        )\n''',
)
# EPW route: same Temperature page; ground profile remains calculated/provenance-labelled.
replace_once(
    app,
    '''    elif page == "Temperature":\n        render_temperature(filtered_df)\n    elif page == "Ground Temperature":\n        render_ground_temperature_page(filtered_df, source_label="EPW calculated")\n''',
    '''    elif page == "Temperature":\n        render_temperature(filtered_df, ground_source_label="EPW calculated")\n''',
)

# ---------------------------------------------------------------------------
# B2. Generalize wind rose to arbitrary canonical speed/direction pairs.
# ---------------------------------------------------------------------------
charts = PKG / "charts.py"
regex_once(
    charts,
    r'def wind_rose_chart\(df: pd\.DataFrame, title: str = "Wind rose"\) -> go\.Figure:.*?\n\n\ndef _representative_sun_day',
    '''def wind_rose_chart(\n    df: pd.DataFrame,\n    title: str = "Wind rose",\n    *,\n    speed_column: str = "wind_speed_m_s",\n    direction_column: str = "wind_direction_deg",\n) -> go.Figure:\n    """Create a source-neutral wind rose from a paired speed/direction quantity."""\n    required = [direction_column, speed_column]\n    if any(column not in df.columns for column in required):\n        return go.Figure().update_layout(title="No paired wind data available")\n    data = df[required].dropna().copy()\n    if data.empty:\n        return go.Figure().update_layout(title="No paired wind data available")\n    direction_bin = (np.round(data[direction_column] / 22.5) * 22.5) % 360\n    data["direction_sector_deg"] = direction_bin\n    data["speed_bin"] = pd.cut(\n        data[speed_column],\n        bins=[0, 1, 2, 4, 6, 8, 12, np.inf],\n        labels=WIND_SPEED_LABELS,\n        include_lowest=True,\n    )\n    rose = data.groupby(["direction_sector_deg", "speed_bin"], observed=False).size().reset_index(name="hours")\n    rose["hours"] = rose["hours"].astype(float) * native_interval_hours(df)\n    fig = px.bar_polar(\n        rose,\n        r="hours",\n        theta="direction_sector_deg",\n        color="speed_bin",\n        title=title,\n        labels={"hours": "Hours", "direction_sector_deg": "Wind direction [deg]", "speed_bin": "Speed [m/s]"},\n        category_orders={"speed_bin": WIND_SPEED_LABELS},\n        color_discrete_map=WIND_SPEED_COLOR_MAP,\n    )\n    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))\n    return fig\n\n\ndef _representative_sun_day''',
)

# ---------------------------------------------------------------------------
# B3. One wind renderer for EPW and GeoSphere; capabilities only affect choices.
# ---------------------------------------------------------------------------
regex_once(
    app,
    r'def render_wind\(df: pd\.DataFrame\) -> None:.*?\n\n\ndef render_precipitation',
    '''def render_wind(df: pd.DataFrame) -> None:\n    """Render one capability-gated wind UI for every canonical climate source."""\n    st.header("Wind and natural-ventilation wind context")\n    st.caption(WIND_DIRECTION_FROM_NOTE)\n\n    def numeric(column: str) -> bool:\n        return column in df.columns and pd.to_numeric(df[column], errors="coerce").notna().any()\n\n    variable_labels = [\n        label\n        for label, column in (\n            ("Wind speed", "wind_speed_m_s"),\n            ("Wind direction", "wind_direction_deg"),\n            ("Wind gust speed", "wind_gust_speed_m_s"),\n            ("Wind gust direction", "wind_gust_direction_deg"),\n        )\n        if numeric(column)\n    ]\n    paired_datasets: list[tuple[str, str, str]] = []\n    if numeric("wind_speed_m_s") and numeric("wind_direction_deg"):\n        paired_datasets.append(("Mean wind", "wind_speed_m_s", "wind_direction_deg"))\n    if numeric("wind_gust_speed_m_s") and numeric("wind_gust_direction_deg"):\n        paired_datasets.append(("Maximum gust", "wind_gust_speed_m_s", "wind_gust_direction_deg"))\n    direction_datasets: list[tuple[str, str]] = []\n    if numeric("wind_direction_deg"):\n        direction_datasets.append(("Mean wind", "wind_direction_deg"))\n    if numeric("wind_gust_direction_deg"):\n        direction_datasets.append(("Maximum gust", "wind_gust_direction_deg"))\n\n    has_nv_inputs = all(\n        numeric(column)\n        for column in (\n            "wind_speed_m_s", "wind_direction_deg", "dry_bulb_temperature_c",\n            "relative_humidity_pct", "humidity_ratio_g_kg",\n        )\n    )\n    options: list[str] = []\n    if variable_labels:\n        options.append("Wind variable explorer")\n    if paired_datasets:\n        options.extend(["Wind rose", "Monthly wind rose", "Day-night wind rose"])\n    if has_nv_inputs:\n        options.append("Wind during natural-ventilation hours")\n    if direction_datasets:\n        options.append("Direction histogram")\n    if not options:\n        st.info("No usable wind observations are available in the selected interval.")\n        return\n\n    chart_group = st.selectbox("Analysis type", options, key="wind_analysis_type")\n    if chart_group == "Wind variable explorer":\n        default = "Wind speed" if "Wind speed" in variable_labels else variable_labels[0]\n        render_generic_variable_page(df, variable_labels, default, "Wind", None)\n        return\n\n    if chart_group == "Wind during natural-ventilation hours":\n        mask = natural_ventilation_condition(df)\n        data = df[mask]\n        if data.empty:\n            st.info("No records satisfy the active natural-ventilation suitability condition.")\n            return\n        fig = wind_rose_chart(data, "Mean wind during natural-ventilation-suitable hours")\n        render_plot(fig, natural_ventilation_interpretation(df, mask))\n        return\n\n    if chart_group == "Direction histogram":\n        labels = [item[0] for item in direction_datasets]\n        selected = st.selectbox("Wind dataset", labels, key="wind_direction_dataset") if len(labels) > 1 else labels[0]\n        direction_column = next(column for label, column in direction_datasets if label == selected)\n        fig = histogram_chart(df, direction_column, f"{selected} direction histogram", "deg", bins=36)\n        if selected == "Maximum gust":\n            text = (\n                "Gust direction remains paired with the governing maximum gust observation; it is not independently averaged. "\n                "The histogram integrates the physical duration represented by each canonical record."\n            )\n        else:\n            text = wind_interpretation(df)\n        render_plot(fig, text)\n        return\n\n    dataset_labels = [item[0] for item in paired_datasets]\n    selected_dataset = (\n        st.selectbox("Wind dataset", dataset_labels, key="wind_paired_dataset")\n        if len(dataset_labels) > 1 else dataset_labels[0]\n    )\n    _, speed_column, direction_column = next(item for item in paired_datasets if item[0] == selected_dataset)\n\n    if selected_dataset == "Maximum gust":\n        interpretation = (\n            "Maximum-gust visualizations use the canonical maximum gust speed together with its paired governing gust direction. "\n            "The direction is never independently circular-averaged away from the gust that produced it."\n        )\n    else:\n        interpretation = wind_interpretation(df)\n\n    if chart_group == "Wind rose":\n        fig = wind_rose_chart(\n            df, f"{selected_dataset} wind rose",\n            speed_column=speed_column, direction_column=direction_column,\n        )\n    elif chart_group == "Monthly wind rose":\n        observed = sorted({int(v) for v in pd.to_numeric(df["month_index"], errors="coerce").dropna().tolist() if 1 <= int(v) <= 12})\n        month_names = [name for name, number in MONTHS.items() if number in observed]\n        if not month_names:\n            st.info("No valid month labels are available for the selected wind observations.")\n            return\n        month = st.selectbox("Month", month_names, key="wind_month")\n        data = df[df["month_index"] == MONTHS[month]]\n        fig = wind_rose_chart(\n            data, f"{selected_dataset} wind rose: {month}",\n            speed_column=speed_column, direction_column=direction_column,\n        )\n    else:\n        period = st.radio("Period", ["Day", "Night"], horizontal=True, key="wind_daynight_period")\n        if period == "Day":\n            data = df[df["hour_of_day"].between(7, 19)]\n        else:\n            data = df[(df["hour_of_day"] < 7) | (df["hour_of_day"] > 19)]\n        fig = wind_rose_chart(\n            data, f"{selected_dataset} · {period.lower()} wind rose",\n            speed_column=speed_column, direction_column=direction_column,\n        )\n    render_plot(fig, interpretation)\n\n\ndef render_precipitation''',
)

# Replace historical duplicated wind renderer with a compatibility wrapper only.
regex_once(
    app,
    r'def render_historical_wind\(df: pd\.DataFrame\) -> None:.*?\n\n\ndef render_ground_temperature_page',
    '''def render_historical_wind(df: pd.DataFrame) -> None:\n    """Backward-compatible entry point; canonical wind UI is source-neutral."""\n    render_wind(df)\n\n\ndef render_ground_temperature_page''',
)
replace_once(app, '        render_historical_wind(filtered_df)\n', '        render_wind(filtered_df)\n')

# ---------------------------------------------------------------------------
# B4. Contract/regression tests.
# ---------------------------------------------------------------------------
public_test = TESTS / "test_public_ux_contract.py"
replace_once(public_test, '        self.assertEqual(len(NAVIGATION_PAGES), 14)\n', '        self.assertEqual(len(NAVIGATION_PAGES), 13)\n')
replace_once(public_test, '        self.assertIn("Ground Temperature", NAVIGATION_PAGES)\n', '        self.assertNotIn("Ground Temperature", NAVIGATION_PAGES)\n        self.assertIn("Temperature", NAVIGATION_PAGES)\n')

ground_test = TESTS / "test_daylight_ground_0_7_3.py"
replace_once(
    ground_test,
    '        self.assertIn("Ground Temperature", pages)\n',
    '        self.assertIn("Temperature", pages)\n        self.assertNotIn("Ground Temperature", pages)\n',
)

wind_test = TESTS / "test_historical_wind_solar_capabilities.py"
replace_once(
    wind_test,
    '''        self.assertIn("def render_historical_wind", source)\n''',
    '''        self.assertIn("def render_historical_wind", source)\n        self.assertIn("canonical wind UI is source-neutral", source)\n        self.assertIn('("Wind gust speed", "wind_gust_speed_m_s")', source)\n        self.assertIn('("Wind gust direction", "wind_gust_direction_deg")', source)\n        self.assertIn('st.selectbox("Wind dataset"', source)\n''',
)

(TESTS / "test_source_neutral_ui_0_7_4.py").write_text('''from __future__ import annotations\n\nfrom pathlib import Path\nimport unittest\n\nimport pandas as pd\n\nfrom epw_climate_analyzer.charts import wind_rose_chart\nfrom epw_climate_analyzer.historical_capabilities import available_historical_pages\nfrom epw_climate_analyzer.ui_contract import NAVIGATION_PAGES\n\nROOT = Path(__file__).resolve().parents[1]\nAPP = ROOT / "app.py"\n\n\nclass SourceNeutralUi074Tests(unittest.TestCase):\n    def test_ground_temperature_is_nested_under_temperature_navigation(self) -> None:\n        self.assertIn("Temperature", NAVIGATION_PAGES)\n        self.assertNotIn("Ground Temperature", NAVIGATION_PAGES)\n        idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")\n        ground_only = pd.DataFrame({"ground_temperature_0_10m_c": [4.0, 4.1]}, index=idx)\n        pages = available_historical_pages(ground_only)\n        self.assertIn("Temperature", pages)\n        self.assertNotIn("Ground Temperature", pages)\n        source = APP.read_text(encoding="utf-8")\n        self.assertIn('chart_options.append("Ground temperature")', source)\n\n    def test_wind_rose_accepts_gust_pair_without_mean_wind_columns(self) -> None:\n        idx = pd.date_range("2026-07-01", periods=4, freq="h", tz="UTC")\n        df = pd.DataFrame({\n            "wind_gust_speed_m_s": [4.0, 6.0, 8.0, 10.0],\n            "wind_gust_direction_deg": [0.0, 90.0, 180.0, 270.0],\n        }, index=idx)\n        df.attrs["canonical_native_interval_minutes"] = 60\n        fig = wind_rose_chart(\n            df, "Gust rose",\n            speed_column="wind_gust_speed_m_s",\n            direction_column="wind_gust_direction_deg",\n        )\n        represented = sum(sum(float(v) for v in trace.r) for trace in fig.data if getattr(trace, "r", None) is not None)\n        self.assertAlmostEqual(represented, 4.0)\n\n    def test_common_wind_renderer_contains_mean_and_gust_variables(self) -> None:\n        source = APP.read_text(encoding="utf-8")\n        start = source.index("def render_wind")\n        end = source.index("def render_precipitation", start)\n        body = source[start:end]\n        for label in ("Wind speed", "Wind direction", "Wind gust speed", "Wind gust direction"):\n            self.assertIn(label, body)\n        self.assertIn("Maximum gust", body)\n        self.assertIn("Wind dataset", body)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")

# Mark B as implemented in the handoff.
handoff = ROOT / "CLIMATE_CORE_0_7_4.md"
text = handoff.read_text(encoding="utf-8")
text = text.replace('## B — Source-neutral UI consolidation\n\nPlanned next on this same Draft PR:', '## B — Source-neutral UI consolidation\n\nImplemented in the current branch:')
text = text.replace('- Move Ground Temperature into **Temperature and extremes** while preserving its dedicated `T(z,t)` views rather than pretending it is an ordinary scalar variable.\n- Remove source-specific visualization divergence for canonical variables.\n- Consolidate mean wind and maximum gust around one wind-analysis architecture, including the existing direction/circular analyses and wind roses.\n', '- Ground Temperature is nested inside **Temperature and extremes** while retaining dedicated `T(z,t)` views.\n- The standalone Ground Temperature navigation page is removed.\n- EPW and GeoSphere use the same capability-gated wind renderer.\n- Mean wind and maximum gust share the variable explorer, direction distribution and wind-rose architecture; gust direction remains paired with the governing gust.\n')
handoff.write_text(text, encoding="utf-8")

print("v0.7.4-B source-neutral UI patch applied")
