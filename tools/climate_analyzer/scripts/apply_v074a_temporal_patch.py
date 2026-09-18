from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "epw_climate_analyzer"
TESTS = ROOT / "tests"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected patch anchor not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Expected one regex patch in {path}, got {count}: {pattern[:120]!r}")
    path.write_text(updated, encoding="utf-8")


# ---------------------------------------------------------------------------
# A1. Heat-map temporal contract: Chronological means absolute periods.
# ---------------------------------------------------------------------------
agg = PKG / "aggregations.py"
replace_once(
    agg,
    "def temporal_heatmap_matrix(\n",
    '''def _chronological_heatmap_period_key(index: pd.DatetimeIndex, row_group: str) -> pd.Index:\n    """Return absolute, sortable period labels for chronological heat maps."""\n    idx = pd.DatetimeIndex(index)\n    group = str(row_group).strip().lower()\n    if group == "day":\n        return pd.Index(idx.strftime("%Y-%m-%d"), name="Date")\n    if group == "week":\n        iso = idx.isocalendar()\n        return pd.Index(\n            [f"{int(year):04d}-W{int(week):02d}" for year, week in zip(iso.year, iso.week, strict=False)],\n            name="Week",\n        )\n    if group == "month":\n        return pd.Index(idx.strftime("%Y-%m"), name="Month")\n    raise ValueError("row_group must be 'day', 'week' or 'month'")\n\n\ndef temporal_heatmap_matrix(\n''',
)
replace_once(
    agg,
    '''    group = str(row_group).strip().lower()\n\n    if compare_across == HEATMAP_COMPARE_YEAR:\n        if group == "week":\n            iso = index.isocalendar()\n            temp["_y"] = iso.year.astype(int).to_numpy()\n            temp["_x"] = iso.week.astype(int).to_numpy()\n        else:\n            temp["_y"] = index.year.astype(int)\n            temp["_x"] = _heatmap_period_key(index, row_group).to_numpy()\n    else:\n        temp["_y"] = (\n            pd.to_numeric(df["hour_of_day"], errors="coerce").to_numpy()\n            if "hour_of_day" in df.columns\n            else index.hour.astype(int)\n        )\n        temp["_x"] = _heatmap_period_key(index, row_group).to_numpy()\n''',
    '''    group = str(row_group).strip().lower()\n    basis = time_basis(df)\n\n    if compare_across == HEATMAP_COMPARE_YEAR:\n        # Interannual comparison intentionally aligns equivalent calendar\n        # positions, independent of the global basis. The UI exposes this view\n        # in Calendar-profile mode, where that alignment is semantically clear.\n        if group == "week":\n            iso = index.isocalendar()\n            temp["_y"] = iso.year.astype(int).to_numpy()\n            temp["_x"] = iso.week.astype(int).to_numpy()\n        else:\n            temp["_y"] = index.year.astype(int)\n            temp["_x"] = _heatmap_period_key(index, row_group).to_numpy()\n    else:\n        temp["_y"] = (\n            pd.to_numeric(df["hour_of_day"], errors="coerce").to_numpy()\n            if "hour_of_day" in df.columns\n            else index.hour.astype(int)\n        )\n        temp["_x"] = (\n            _chronological_heatmap_period_key(index, row_group).to_numpy()\n            if basis == CHRONOLOGICAL\n            else _heatmap_period_key(index, row_group).to_numpy()\n        )\n''',
)
replace_once(
    agg,
    '''    if statistic == "Total" and compare_across == HEATMAP_COMPARE_HOUR and is_multiyear(df):\n''',
    '''    if (\n        statistic == "Total"\n        and compare_across == HEATMAP_COMPARE_HOUR\n        and basis == CALENDAR_PROFILE\n        and is_multiyear(df)\n    ):\n''',
)
replace_once(
    agg,
    '''    elif group in {"day", "week"} and len(matrix.columns):\n        numeric_columns = [int(value) for value in matrix.columns]\n        matrix = matrix.reindex(columns=list(range(min(numeric_columns), max(numeric_columns) + 1)))\n''',
    '''    elif (\n        group in {"day", "week"}\n        and len(matrix.columns)\n        and all(isinstance(value, (int, np.integer)) for value in matrix.columns)\n    ):\n        numeric_columns = [int(value) for value in matrix.columns]\n        matrix = matrix.reindex(columns=list(range(min(numeric_columns), max(numeric_columns) + 1)))\n''',
)

# ---------------------------------------------------------------------------
# A2. Robust heat-map colors + plain-language percentile chart labels.
# ---------------------------------------------------------------------------
charts = PKG / "charts.py"
regex_once(
    charts,
    r'def _heatmap_colorscale\(column: str, values=None, temperature_thresholds: tuple\[float, float\] \| None = None\):.*?\n\ndef apply_common_layout',
    '''def _heatmap_colorscale(column: str, values=None, temperature_thresholds: tuple[float, float] | None = None):\n    """Return a valid semantic colorscale for the selected climate variable."""\n    if column == "dry_bulb_temperature_c" and temperature_thresholds is not None:\n        heat_t, cool_t = map(float, temperature_thresholds)\n        vmin, vmax = _finite_min_max(values)\n        if vmin is None or vmax is None or abs(vmax - vmin) < 1e-9:\n            return TEMPERATURE_COMFORT_COLORSCALE\n        if heat_t > cool_t:\n            heat_t, cool_t = cool_t, heat_t\n        blue, green, red = "#1d4ed8", "#22c55e", "#dc2626"\n        if vmax <= heat_t:\n            return [[0.0, blue], [1.0, blue]]\n        if vmin >= cool_t:\n            return [[0.0, red], [1.0, red]]\n        if vmin >= heat_t and vmax <= cool_t:\n            return [[0.0, green], [1.0, green]]\n\n        span = vmax - vmin\n        stops: list[list[float | str]] = []\n        start_color = blue if vmin < heat_t else (green if vmin < cool_t else red)\n        stops.append([0.0, start_color])\n        if vmin < heat_t < vmax:\n            p = float(np.clip((heat_t - vmin) / span, 0.0, 1.0))\n            stops.extend([[p, blue], [p, green]])\n        if vmin < cool_t < vmax:\n            p = float(np.clip((cool_t - vmin) / span, 0.0, 1.0))\n            stops.extend([[p, green], [p, red]])\n        end_color = red if vmax > cool_t else (green if vmax > heat_t else blue)\n        stops.append([1.0, end_color])\n        return stops\n    if column in {"natural_ventilation_suitable", "night_flushing_suitable"} or "suitable" in column:\n        return BINARY_SUITABILITY_COLORSCALE\n    if "sky_cover" in column:\n        return [[0.0, "rgba(255,255,255,0.0)"], [0.25, "#dbeafe"], [1.0, "#0f172a"]]\n    if "radiation" in column or "irradiance" in column or "illuminance" in column:\n        return SOLAR_COLORSCALE\n    return "Viridis"\n\n\ndef apply_common_layout''',
)
replace_once(charts, 'name="P95"', 'name="Upper 5% boundary (P95)"')
replace_once(charts, 'hovertemplate="P95: %{y:.2f} "', 'hovertemplate="Upper 5% boundary (P95): %{y:.2f} "')
replace_once(charts, 'name="P05"', 'name="Lower 5% boundary (P05)"')
replace_once(charts, 'hovertemplate="P05: %{y:.2f} "', 'hovertemplate="Lower 5% boundary (P05): %{y:.2f} "')
replace_once(
    charts,
    '''    if str(row_group).strip().lower() == "month" and all(isinstance(value, (int, np.integer)) for value in matrix.columns):\n        fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)\n    if compare_across == HEATMAP_COMPARE_HOUR:\n''',
    '''    if str(row_group).strip().lower() == "month" and all(isinstance(value, (int, np.integer)) for value in matrix.columns):\n        fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)\n    if compare_across == "Year":\n        years = [int(value) for value in matrix.index]\n        fig.update_yaxes(tickmode="array", tickvals=years, ticktext=[str(year) for year in years])\n    if compare_across == HEATMAP_COMPARE_HOUR:\n''',
)

# ---------------------------------------------------------------------------
# A3. UI semantics: percentile wording, chronological controls, degree labels.
# ---------------------------------------------------------------------------
app = ROOT / "app.py"
replace_once(
    app,
    'global CHRONOLOGICAL, CALENDAR_PROFILE, display_period_labels, time_basis',
    'global CHRONOLOGICAL, CALENDAR_PROFILE, display_period_labels, is_multiyear, time_basis',
)
replace_once(
    app,
    '''            CALENDAR_PROFILE,\n            CHRONOLOGICAL,\n            display_period_labels,\n            time_basis,\n''',
    '''            CALENDAR_PROFILE,\n            CHRONOLOGICAL,\n            display_period_labels,\n            is_multiyear,\n            time_basis,\n''',
)
replace_once(app, '"Percentile band P05-P50-P95",', '"Middle 90% range with median",')
replace_once(
    app,
    '''        compare_across = st.selectbox("Compare across", ["Hour of day", "Year"], index=0)\n        statistic_options = list(heatmap_statistic_options(column))\n''',
    '''        compare_options = ["Hour of day"] if time_basis(df) == CHRONOLOGICAL else ["Hour of day", "Year"]\n        compare_across = st.selectbox("Compare across", compare_options, index=0)\n        if time_basis(df) == CHRONOLOGICAL and is_multiyear(df):\n            st.caption("Chronological heat maps keep every real day, week or month in sequence across years. Switch Time basis to Calendar profile to align equivalent calendar periods and compare years directly.")\n        statistic_options = list(heatmap_statistic_options(column))\n''',
)
replace_once(
    app,
    '''        statistic = st.selectbox(\n            "Statistic",\n            statistic_options,\n            index=statistic_options.index(default_statistic),\n            help=(\n                "The statistic defines the value represented by each heat-map cell. Extensive canonical variables "\n                "such as irradiation and precipitation default to period Total; state/intensive variables default to Mean."\n            ),\n        )\n''',
    '''        statistic_labels = {\n            "P05": "Lower 5% boundary (P05)",\n            "P95": "Upper 5% boundary (P95)",\n        }\n        statistic = st.selectbox(\n            "Statistic",\n            statistic_options,\n            index=statistic_options.index(default_statistic),\n            format_func=lambda value: statistic_labels.get(value, value),\n            help=(\n                "The statistic defines the value represented by each heat-map cell. Lower 5% boundary means only about 5% of contributing values are lower; "\n                "Upper 5% boundary means only about 5% are higher. The interval between them contains the middle 90% of observations. "\n                "Extensive canonical variables such as irradiation and precipitation default to period Total; state/intensive variables default to Mean."\n            ),\n        )\n''',
)
replace_once(
    app,
    'elif chart_type == "Percentile band P05-P50-P95":',
    'elif chart_type == "Middle 90% range with median":',
)
replace_once(
    app,
    'fig = percentile_band_chart(df, column, aggregation or "Monthly", f"{title_prefix}: {variable_label} percentiles", unit)',
    'fig = percentile_band_chart(df, column, aggregation or "Monthly", f"{title_prefix}: {variable_label} · middle 90% range with median", unit)',
)
replace_once(
    app,
    '''        cooling_limit = cool_col2.slider(\n            "Cooling limit [°C]",\n            10.0,\n            35.0,\n            18.3,\n            0.1,\n''',
    '''        cooling_limit = cool_col2.slider(\n            "Cooling limit [°C]",\n            10.0,\n            35.0,\n            20.0,\n            0.1,\n''',
)
regex_once(
    app,
    r'''        plot_data = table\.reset_index\(\)\n        plot_data = plot_data\.rename\(columns=\{plot_data\.columns\[0\]: "Period"\}\)\n        if aggregation == "Monthly":.*?        elif aggregation == "Annual":\n            plot_data\["Period"\] = pd\.to_datetime\(plot_data\["Period"\]\)\.dt\.strftime\("%Y"\)\n''',
    '''        plot_data = table.reset_index()\n        plot_data = plot_data.rename(columns={plot_data.columns[0]: "Period"})\n        plot_data["Period"] = display_period_labels(table.index, aggregation, time_basis(df))\n''',
)
replace_once(
    app,
    'mode = st.radio("Condition", ["Below heating threshold", "Above cooling threshold", "Frost hours", "Tropical nights proxy"])',
    'mode = st.radio("Condition", ["Below heating threshold", "Above cooling threshold", "Frost hours (Tdry < 0 °C)", "Nighttime hours > 20 °C (20:00–06:59)"])',
)
replace_once(app, 'elif mode == "Frost hours":', 'elif mode == "Frost hours (Tdry < 0 °C)":')

# ---------------------------------------------------------------------------
# A4. Automatic interpretation: explain middle 90%, preserve year dynamics.
# ---------------------------------------------------------------------------
interp = PKG / "interpretations.py"
replace_once(
    interp,
    'from .aggregations import native_interval_hours\n',
    'from .aggregations import native_interval_hours\nfrom .temporal_filtering import CHRONOLOGICAL, time_basis\n',
)
replace_once(
    interp,
    '''def variable_interpretation(\n''',
    '''def _interannual_mean_sentence(df: pd.DataFrame, column: str, label: str, unit: str) -> str:\n    """Summarize real-year mean evolution for chronological multi-year data."""\n    if not isinstance(df.index, pd.DatetimeIndex) or time_basis(df) != CHRONOLOGICAL:\n        return ""\n    numeric = pd.to_numeric(df.get(column), errors="coerce")\n    if numeric is None:\n        return ""\n    annual = numeric.groupby(pd.DatetimeIndex(df.index).year).mean().dropna()\n    if len(annual) < 2:\n        return ""\n    first_year, last_year = int(annual.index[0]), int(annual.index[-1])\n    low_year, high_year = int(annual.idxmin()), int(annual.idxmax())\n    return (\n        f" Across real years, annual mean {label} changes from {_fmt(annual.iloc[0])} {unit} in {first_year} "\n        f"to {_fmt(annual.iloc[-1])} {unit} in {last_year}; the lowest annual mean is {_fmt(annual.min())} {unit} "\n        f"({low_year}) and the highest is {_fmt(annual.max())} {unit} ({high_year})."\n    )\n\n\ndef variable_interpretation(\n''',
)
replace_once(
    interp,
    'f"The 5th to 95th percentile interval is {_fmt(p05)}...{_fmt(p95)} {unit}."\n    )',
    'f"The middle 90% of observations lies between {_fmt(p05)} and {_fmt(p95)} {unit}; only about 5% are lower and about 5% are higher."\n        + _interannual_mean_sentence(df, column, label, unit)\n    )',
)
replace_once(
    interp,
    '''        f"The file contains approximately {tropical_nights:,} tropical nights with night minimum above 20 °C."\n    )\n''',
    '''        f"The file contains approximately {tropical_nights:,} tropical nights with night minimum above 20 °C."\n        + _interannual_mean_sentence(df, "dry_bulb_temperature_c", "outdoor temperature", "°C")\n    )\n''',
)

# ---------------------------------------------------------------------------
# A5. Update old tests whose assertions deliberately encoded the old contract.
# ---------------------------------------------------------------------------
interannual = TESTS / "test_interannual_heatmaps_0_6_4.py"
text = interannual.read_text(encoding="utf-8")
text = re.sub(
    r'''    def test_hour_compare_uses_calendar_axes_even_in_chronological_multiyear_mode\(self\) -> None:.*?\n    def test_calendar_profile_hour_total_averages_per_year_totals''',
    '''    def test_hour_compare_preserves_absolute_periods_in_chronological_multiyear_mode(self) -> None:\n        df = frame()\n        day = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "day", HEATMAP_COMPARE_HOUR, "Mean")\n        week = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "week", HEATMAP_COMPARE_HOUR, "Mean")\n        month = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_HOUR, "Mean")\n\n        self.assertIn("2024-01-01", day.columns)\n        self.assertIn("2025-01-01", day.columns)\n        self.assertIn("2024-W01", week.columns)\n        self.assertIn("2025-W01", week.columns)\n        self.assertIn("2024-01", month.columns)\n        self.assertIn("2025-01", month.columns)\n\n    def test_calendar_profile_hour_total_averages_per_year_totals''',
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r'''    def test_chronological_multiyear_hour_total_is_not_inflated_by_year_count\(self\) -> None:.*?\n    def test_quantity_aware_statistic_options_and_defaults''',
    '''    def test_chronological_multiyear_hour_total_keeps_real_year_months_separate(self) -> None:\n        df = frame()\n        matrix = temporal_heatmap_matrix(df, "global_horizontal_radiation_wh_m2", "month", HEATMAP_COMPARE_HOUR, "Total")\n        self.assertAlmostEqual(float(matrix.loc[0, "2024-01"]), 1.0)\n        self.assertAlmostEqual(float(matrix.loc[0, "2025-01"]), 10.0)\n        self.assertAlmostEqual(float(matrix.loc[12, "2024-01"]), 2.0)\n        self.assertAlmostEqual(float(matrix.loc[12, "2025-01"]), 20.0)\n\n    def test_quantity_aware_statistic_options_and_defaults''',
    text,
    count=1,
    flags=re.S,
)
interannual.write_text(text, encoding="utf-8")

(TESTS / "test_heatmap_axis_rendering_0_6_5.py").write_text('''from __future__ import annotations\n\nimport unittest\n\nimport numpy as np\nimport pandas as pd\n\nfrom epw_climate_analyzer.aggregations import HEATMAP_COMPARE_HOUR, HEATMAP_COMPARE_YEAR\nfrom epw_climate_analyzer.charts import temporal_heatmap_chart\nfrom epw_climate_analyzer.temporal_filtering import CALENDAR_PROFILE, CHRONOLOGICAL, with_time_basis\n\n\nclass HeatmapAxisRendering065Tests(unittest.TestCase):\n    @staticmethod\n    def _frame(basis: str = CHRONOLOGICAL) -> pd.DataFrame:\n        index = pd.to_datetime([\n            "2010-01-01T00:00:00Z", "2010-01-01T12:00:00Z",\n            "2010-03-01T00:00:00Z", "2010-03-01T12:00:00Z",\n            "2018-01-01T00:00:00Z", "2018-01-01T12:00:00Z",\n            "2018-03-01T00:00:00Z", "2018-03-01T12:00:00Z",\n        ])\n        frame = pd.DataFrame({"dry_bulb_temperature_c": [0.0, 5.0, 10.0, 15.0, 2.0, 7.0, 12.0, 17.0]}, index=index)\n        frame["hour_of_day"] = frame.index.hour\n        frame.attrs["canonical_native_interval_minutes"] = 60\n        return with_time_basis(frame, basis)\n\n    def test_chronological_hour_heatmaps_use_absolute_period_labels(self) -> None:\n        frame = self._frame(CHRONOLOGICAL)\n        expected = {"day": "2010-01-01", "week": "2009-W53", "month": "2010-01"}\n        for period, first_label in expected.items():\n            with self.subTest(period=period):\n                fig = temporal_heatmap_chart(frame, "dry_bulb_temperature_c", period, HEATMAP_COMPARE_HOUR, "Mean", "test", "°C")\n                x = list(fig.data[0].x)\n                self.assertIn(first_label, x)\n                self.assertTrue(any(str(value).startswith("2018") for value in x))\n                self.assertEqual([int(value) for value in fig.data[0].y], [0, 12])\n\n    def test_calendar_profile_hour_heatmaps_keep_numeric_calendar_axes(self) -> None:\n        frame = self._frame(CALENDAR_PROFILE)\n        bounds = {"day": (1, 366), "week": (1, 53), "month": (1, 12)}\n        for period, (lo, hi) in bounds.items():\n            fig = temporal_heatmap_chart(frame, "dry_bulb_temperature_c", period, HEATMAP_COMPARE_HOUR, "Mean", "test", "°C")\n            x = list(fig.data[0].x)\n            self.assertTrue(all(isinstance(value, (int, np.integer)) for value in x))\n            self.assertGreaterEqual(min(int(value) for value in x), lo)\n            self.assertLessEqual(max(int(value) for value in x), hi)\n\n    def test_year_comparison_uses_integer_tick_labels_only(self) -> None:\n        frame = self._frame(CALENDAR_PROFILE)\n        fig = temporal_heatmap_chart(frame, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_YEAR, "Mean", "test", "°C")\n        self.assertEqual(list(fig.layout.yaxis.tickvals), [2010, 2018])\n        self.assertEqual(list(fig.layout.yaxis.ticktext), ["2010", "2018"])\n\n    def test_complete_day_hour_heatmap_keeps_all_24_hour_rows(self) -> None:\n        index = pd.date_range("2018-07-01T00:00:00Z", periods=24, freq="h")\n        frame = pd.DataFrame({"dry_bulb_temperature_c": np.linspace(12.0, 28.0, 24)}, index=index)\n        frame["hour_of_day"] = frame.index.hour\n        frame.attrs["canonical_native_interval_minutes"] = 60\n        frame = with_time_basis(frame, CHRONOLOGICAL)\n        fig = temporal_heatmap_chart(frame, "dry_bulb_temperature_c", "day", HEATMAP_COMPARE_HOUR, "Mean", "test", "°C")\n        self.assertEqual([int(value) for value in fig.data[0].y], list(range(24)))\n        self.assertEqual(np.asarray(fig.data[0].z).shape[0], 24)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")

degree_test = TESTS / "test_degree_metrics_controls.py"
replace_once(degree_test, '        self.assertIn("18.3", text)\n', '        self.assertNotIn("18.3", text)\n        self.assertGreaterEqual(text.count("20.0"), 2)\n')

# New focused regression file for the user-reported failures.
(TESTS / "test_temporal_ux_0_7_4.py").write_text('''from __future__ import annotations\n\nfrom pathlib import Path\nimport unittest\n\nimport pandas as pd\n\nfrom epw_climate_analyzer.charts import temporal_heatmap_chart\nfrom epw_climate_analyzer.interpretations import variable_interpretation\nfrom epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis\n\nROOT = Path(__file__).resolve().parents[1]\nAPP = ROOT / "app.py"\n\n\nclass TemporalUx074Tests(unittest.TestCase):\n    def test_temperature_minimum_heatmap_cannot_generate_invalid_colorscale(self) -> None:\n        idx = pd.date_range("2025-01-01", periods=48, freq="h")\n        df = pd.DataFrame({"dry_bulb_temperature_c": [-15.0] * 24 + [-10.0] * 24}, index=idx)\n        df["hour_of_day"] = df.index.hour\n        df = with_time_basis(df, CHRONOLOGICAL)\n        fig = temporal_heatmap_chart(df, "dry_bulb_temperature_c", "day", "Hour of day", "Minimum", "Minimum", "°C", temperature_thresholds=(18.0, 26.0))\n        scale = fig.layout.coloraxis.colorscale\n        self.assertTrue(scale)\n        self.assertTrue(all(0.0 <= float(stop[0]) <= 1.0 for stop in scale))\n\n    def test_interpretation_explains_middle_90_without_requiring_percentile_knowledge(self) -> None:\n        idx = pd.to_datetime(["2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01"])\n        df = pd.DataFrame({"dry_bulb_temperature_c": [0.0, 20.0, 2.0, 24.0]}, index=idx)\n        df = with_time_basis(df, CHRONOLOGICAL)\n        text = variable_interpretation(df, "dry_bulb_temperature_c", "temperature", "°C")\n        self.assertIn("middle 90%", text)\n        self.assertIn("only about 5% are lower", text)\n        self.assertIn("2024", text)\n        self.assertIn("2025", text)\n        self.assertIn("annual mean", text)\n\n    def test_ui_uses_plain_language_percentile_labels_and_20c_cooling_limit(self) -> None:\n        source = APP.read_text(encoding="utf-8")\n        self.assertIn("Middle 90% range with median", source)\n        self.assertIn("Lower 5% boundary (P05)", source)\n        self.assertIn("Upper 5% boundary (P95)", source)\n        self.assertIn("Nighttime hours > 20 °C (20:00–06:59)", source)\n        self.assertIn('"Cooling limit [°C]",\\n            10.0,\\n            35.0,\\n            20.0', source)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")

print("v0.7.4-A temporal semantics patch applied")
