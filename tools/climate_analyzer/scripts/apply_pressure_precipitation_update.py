from __future__ import annotations

from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "climate_analyzer"
APP = TOOL / "app.py"
UI = TOOL / "epw_climate_analyzer" / "ui_contract.py"
PRECIP = TOOL / "epw_climate_analyzer" / "precipitation.py"
TEST = TOOL / "tests" / "test_pressure_precipitation_contract.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


ui = UI.read_text(encoding="utf-8")
ui = replace_once(
    ui,
    '    "Explore EPW weather data for temperature, moisture, solar radiation, wind, "\n    "passive-design potential and early HVAC decision support."',
    '    "Explore EPW weather data for temperature, moisture, solar radiation, wind, precipitation, "\n    "passive-design potential and early HVAC decision support."',
    "intro precipitation",
)
ui = replace_once(
    ui,
    '    "Sky and Daylight",\n    "Natural Ventilation",',
    '    "Sky and Daylight",\n    "Precipitation and Snow",\n    "Natural Ventilation",',
    "navigation page",
)
ui = replace_once(
    ui,
    '    "Sky and Daylight": "Climate — Sky & daylight",\n    "Natural Ventilation": "Design — Natural ventilation",',
    '    "Sky and Daylight": "Climate — Sky & daylight",\n    "Precipitation and Snow": "Climate — Precipitation & snow",\n    "Natural Ventilation": "Design — Natural ventilation",',
    "navigation label",
)
UI.write_text(ui, encoding="utf-8")

precipitation_source = r'''"""Precipitation and snow helpers for EPW climate analysis.

Liquid precipitation depth is an extensive quantity and is summed over valid EPW
records. Snow depth is a state variable: it is never summed. Missing EPW sentinel
values are already converted to NA by the parser and remain excluded here.
"""

from __future__ import annotations

import math
import pandas as pd

LIQUID_PRECIPITATION_COLUMN = "liquid_precipitation_depth_mm"
SNOW_DEPTH_COLUMN = "snow_depth_cm"
SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]
RESAMPLE_RULES = {
    "Daily": "D",
    "Weekly": "W",
    "Monthly": "ME",
}


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(index=df.index, dtype=float, name=column)
    return pd.to_numeric(df[column], errors="coerce").rename(column)


def _finite_or_none(value) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def aggregate_liquid_precipitation(df: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    """Sum valid EPW liquid-precipitation depth records by period."""
    values = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    if aggregation == "Seasonal":
        frame = pd.DataFrame({"season": df.get("season"), "value": values}, index=df.index)
        totals = (
            frame.groupby("season", observed=False)["value"]
            .sum(min_count=1)
            .reindex(SEASON_ORDER)
        )
    else:
        rule = RESAMPLE_RULES.get(aggregation)
        if rule is None:
            raise ValueError(f"Unsupported precipitation aggregation: {aggregation}")
        totals = values.resample(rule).sum(min_count=1)
    return totals.dropna().rename("precipitation_mm").to_frame()


def occurrence_hours(
    df: pd.DataFrame,
    column: str,
    threshold: float,
    aggregation: str,
    *,
    inclusive: bool = True,
) -> pd.DataFrame:
    """Count valid EPW records meeting a precipitation or snow threshold."""
    values = _numeric_series(df, column)
    valid = values.notna()
    indicator = pd.Series(pd.NA, index=df.index, dtype="Float64", name="hours")
    condition = values >= float(threshold) if inclusive else values > float(threshold)
    indicator.loc[valid] = condition.loc[valid].astype(float)

    if aggregation == "Seasonal":
        frame = pd.DataFrame({"season": df.get("season"), "hours": indicator}, index=df.index)
        counts = (
            frame.groupby("season", observed=False)["hours"]
            .sum(min_count=1)
            .reindex(SEASON_ORDER)
        )
    else:
        rule = RESAMPLE_RULES.get(aggregation)
        if rule is None:
            raise ValueError(f"Unsupported occurrence aggregation: {aggregation}")
        counts = indicator.resample(rule).sum(min_count=1)
    return counts.dropna().rename("hours").to_frame()


def precipitation_summary(df: pd.DataFrame, wet_threshold_mm: float = 0.1) -> dict[str, object]:
    """Return compact precipitation/snow diagnostics for the current filtered view."""
    liquid = _numeric_series(df, LIQUID_PRECIPITATION_COLUMN)
    snow = _numeric_series(df, SNOW_DEPTH_COLUMN)
    liquid_available = bool(liquid.notna().any())
    snow_available = bool(snow.notna().any())

    return {
        "liquid_data_available": liquid_available,
        "snow_data_available": snow_available,
        "liquid_total_mm": _finite_or_none(liquid.sum(min_count=1)) if liquid_available else None,
        "wet_hours": int((liquid >= wet_threshold_mm).sum()) if liquid_available else None,
        "max_record_precipitation_mm": _finite_or_none(liquid.max()) if liquid_available else None,
        "max_snow_depth_cm": _finite_or_none(snow.max()) if snow_available else None,
        "snow_cover_hours": int((snow > 0.0).sum()) if snow_available else None,
    }
'''
PRECIP.write_text(precipitation_source, encoding="utf-8")

app = APP.read_text(encoding="utf-8")
app = replace_once(
    app,
    '    global DEFAULT_PRESSURE_PA, add_psychrometric_properties, pressure_from_altitude_m\n',
    '    global DEFAULT_PRESSURE_PA, add_psychrometric_properties, pressure_from_altitude_m\n    global aggregate_liquid_precipitation, occurrence_hours, precipitation_summary\n',
    "precipitation globals",
)
app = replace_once(
    app,
    '        from epw_climate_analyzer.statistics import (\n            calculated_statistics_tables,\n            climate_statistics_interpretation,\n            extreme_day_summary,\n            monthly_climate_summary,\n            seasonal_climate_summary,\n        )\n        _ANALYSIS_DEPENDENCIES_LOADED = True',
    '        from epw_climate_analyzer.statistics import (\n            calculated_statistics_tables,\n            climate_statistics_interpretation,\n            extreme_day_summary,\n            monthly_climate_summary,\n            seasonal_climate_summary,\n        )\n        from epw_climate_analyzer.precipitation import (\n            aggregate_liquid_precipitation,\n            occurrence_hours,\n            precipitation_summary,\n        )\n        _ANALYSIS_DEPENDENCIES_LOADED = True',
    "precipitation lazy import",
)
app = replace_once(
    app,
    '        extensive = column.endswith("_mm")',
    '        extensive = column == "liquid_precipitation_depth_mm"',
    "explicit extensive variable",
)
app = replace_once(
    app,
    '            - Wind roses, sun-path plots and façade-radiation charts\n            - Natural-ventilation, night-flushing, shading, economizer and latent-load indicators',
    '            - Wind roses, sun-path plots and façade-radiation charts\n            - Precipitation totals, wet-hour occurrence, snow depth and snow-cover occurrence\n            - Natural-ventilation, night-flushing, shading, economizer and latent-load indicators',
    "overview precipitation family",
)

render_precipitation = r'''

def render_precipitation(df: pd.DataFrame) -> None:
    """Render liquid-precipitation and snow-cover analysis from EPW fields."""
    st.header("Precipitation and snow")
    summary = precipitation_summary(df)
    liquid_available = bool(summary["liquid_data_available"])
    snow_available = bool(summary["snow_data_available"])

    metric_cols = st.columns(5)
    metric_cols[0].metric(
        "Liquid precipitation",
        "N/A" if summary["liquid_total_mm"] is None else f"{summary['liquid_total_mm']:.1f} mm",
        help="Sum of valid EPW liquid-precipitation depth records in the current sidebar-filtered view.",
    )
    metric_cols[1].metric(
        "Wet hours ≥ 0.1 mm",
        "N/A" if summary["wet_hours"] is None else f"{summary['wet_hours']:,}",
    )
    metric_cols[2].metric(
        "Max precipitation record",
        "N/A" if summary["max_record_precipitation_mm"] is None else f"{summary['max_record_precipitation_mm']:.1f} mm",
    )
    metric_cols[3].metric(
        "Max snow depth",
        "N/A" if summary["max_snow_depth_cm"] is None else f"{summary['max_snow_depth_cm']:.1f} cm",
    )
    metric_cols[4].metric(
        "Snow-cover hours",
        "N/A" if summary["snow_cover_hours"] is None else f"{summary['snow_cover_hours']:,}",
    )

    st.caption(
        "Precipitation and snow availability depends on the source EPW. Missing EPW sentinel values are excluded. "
        "Liquid precipitation is accumulated; snow depth is treated as a state variable and is never summed."
    )

    options: list[str] = []
    if liquid_available:
        options.extend(["Precipitation totals", "Wet-hour occurrence", "Liquid precipitation explorer"])
    if snow_available:
        options.extend(["Snow depth explorer", "Snow-cover occurrence"])
    if not options:
        st.info("This EPW file does not contain usable liquid-precipitation or snow-depth data.")
        return

    chart_group = st.selectbox("Analysis type", options)

    if chart_group == "Precipitation totals":
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        totals = aggregate_liquid_precipitation(df, aggregation)
        plot_data = totals.reset_index()
        x_column = plot_data.columns[0]
        fig = px.bar(
            plot_data,
            x=x_column,
            y="precipitation_mm",
            title=f"Liquid precipitation totals — {aggregation.lower()}",
            labels={x_column: "Period", "precipitation_mm": "Precipitation [mm]"},
        )
        fig.update_traces(marker_color=metric_color("liquid_precipitation_depth_mm"))
        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Precipitation [mm]")
        render_plot(
            fig,
            "Period totals sum valid EPW liquid-precipitation depth records. Missing EPW values are excluded rather than treated as zero.",
        )
    elif chart_group == "Wet-hour occurrence":
        threshold = st.number_input("Wet-hour threshold [mm]", min_value=0.0, value=0.1, step=0.1)
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        counts = occurrence_hours(
            df,
            "liquid_precipitation_depth_mm",
            float(threshold),
            aggregation,
            inclusive=True,
        )
        plot_data = counts.reset_index()
        x_column = plot_data.columns[0]
        fig = px.bar(
            plot_data,
            x=x_column,
            y="hours",
            title=f"Wet-hour occurrence ≥ {threshold:g} mm",
            labels={x_column: "Period", "hours": "Wet hours"},
        )
        fig.update_traces(marker_color=metric_color("liquid_precipitation_depth_mm"))
        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Wet hours")
        render_plot(fig, "Counts only EPW records with valid precipitation data that meet the selected depth threshold.")
    elif chart_group == "Liquid precipitation explorer":
        render_generic_variable_page(
            df,
            ["Liquid precipitation depth"],
            "Liquid precipitation depth",
            "Precipitation",
            None,
        )
    elif chart_group == "Snow depth explorer":
        render_generic_variable_page(df, ["Snow depth"], "Snow depth", "Snow cover", None)
    else:
        aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Seasonal"], index=0)
        counts = occurrence_hours(df, "snow_depth_cm", 0.0, aggregation, inclusive=False)
        plot_data = counts.reset_index()
        x_column = plot_data.columns[0]
        fig = px.bar(
            plot_data,
            x=x_column,
            y="hours",
            title="Snow-cover occurrence",
            labels={x_column: "Period", "hours": "Hours with snow depth > 0 cm"},
        )
        fig.update_traces(marker_color=metric_color("snow_depth_cm"))
        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Snow-cover hours")
        render_plot(fig, "Snow depth is a state variable; this chart counts valid EPW records with snow depth greater than zero.")
'''
app = replace_once(
    app,
    '\ndef render_sky_daylight(df: pd.DataFrame) -> None:\n',
    render_precipitation + '\n\ndef render_sky_daylight(df: pd.DataFrame) -> None:\n',
    "precipitation renderer insertion",
)

old_pressure = '''        pressure_mode = st.selectbox(
            "Psychrometric pressure mode",
            [
                "Normal pressure: 101325 Pa",
                "EPW station pressure with fallback median",
                "Altitude-derived standard atmosphere pressure",
                "Custom constant pressure",
            ],
            index=0,
        )'''
new_pressure = '''        pressure_mode = st.selectbox(
            "Psychrometric pressure mode",
            [
                "Normal pressure: 101325 Pa",
                "EPW station pressure with fallback median",
                "Altitude-derived standard atmosphere pressure",
                "Custom constant pressure",
            ],
            index=1,
            help=(
                "Default: use the atmospheric station pressure stored in the EPW for each hourly record. "
                "The median valid EPW pressure is used only as a fallback when an EPW pressure value is missing or invalid."
            ),
        )'''
app = replace_once(app, old_pressure, new_pressure, "EPW pressure default")
app = replace_once(
    app,
    '    with st.sidebar.expander("Data provenance", expanded=False):\n        st.caption(active_file.source)\n        st.caption(f"Calculation pressure: {active_pressure:,.0f} Pa")',
    '    with st.sidebar.expander("Data provenance", expanded=False):\n        st.caption(active_file.source)\n        if pressure_mode == "EPW station pressure with fallback median":\n            st.caption(f"Pressure: hourly EPW station values; fallback median {active_pressure:,.0f} Pa")\n        else:\n            st.caption(f"Calculation pressure: {active_pressure:,.0f} Pa")',
    "pressure provenance caption",
)
app = replace_once(
    app,
    '    elif page == "Sky and Daylight":\n        render_sky_daylight(filtered_df)\n    elif page == "Natural Ventilation":',
    '    elif page == "Sky and Daylight":\n        render_sky_daylight(filtered_df)\n    elif page == "Precipitation and Snow":\n        render_precipitation(filtered_df)\n    elif page == "Natural Ventilation":',
    "precipitation route",
)
APP.write_text(app, encoding="utf-8")

test_source = r'''from __future__ import annotations

import ast
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from epw_climate_analyzer.precipitation import (
    aggregate_liquid_precipitation,
    occurrence_hours,
    precipitation_summary,
)
from epw_climate_analyzer.ui_contract import NAVIGATION_LABELS, NAVIGATION_PAGES

TOOL_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = TOOL_ROOT / "app.py"


class PressureAndPrecipitationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = APP_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_epw_station_pressure_is_the_default_ui_mode(self) -> None:
        matches = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "selectbox":
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value != "Psychrometric pressure mode":
                continue
            matches.append(node)
        self.assertEqual(len(matches), 1)
        keywords = {kw.arg: kw.value for kw in matches[0].keywords if kw.arg}
        self.assertEqual(ast.literal_eval(keywords["index"]), 1)
        self.assertIn("atmospheric station pressure stored in the EPW", self.source)
        self.assertIn("hourly EPW station values; fallback median", self.source)

    def test_precipitation_has_a_first_class_navigation_page(self) -> None:
        self.assertIn("Precipitation and Snow", NAVIGATION_PAGES)
        self.assertEqual(NAVIGATION_LABELS["Precipitation and Snow"], "Climate — Precipitation & snow")
        self.assertIn('elif page == "Precipitation and Snow":', self.source)
        self.assertIn("render_precipitation(filtered_df)", self.source)

    def test_liquid_precipitation_is_explicitly_extensive_but_snow_is_not(self) -> None:
        self.assertIn('extensive = column == "liquid_precipitation_depth_mm"', self.source)
        self.assertNotIn('extensive = column.endswith("_mm")', self.source)
        self.assertIn('["Snow depth"]', self.source)

    def _fixture(self) -> pd.DataFrame:
        index = pd.to_datetime(
            [
                "2026-01-31 22:00",
                "2026-01-31 23:00",
                "2026-02-01 00:00",
                "2026-02-01 01:00",
                "2026-02-01 02:00",
            ]
        )
        return pd.DataFrame(
            {
                "liquid_precipitation_depth_mm": [1.0, 2.0, np.nan, 4.0, 0.0],
                "snow_depth_cm": [0.0, 1.0, np.nan, 3.0, 0.0],
                "season": ["Winter"] * 5,
            },
            index=index,
        )

    def test_precipitation_totals_sum_valid_records_and_preserve_missingness(self) -> None:
        totals = aggregate_liquid_precipitation(self._fixture(), "Monthly")
        self.assertAlmostEqual(float(totals.iloc[0, 0]), 3.0)
        self.assertAlmostEqual(float(totals.iloc[1, 0]), 4.0)

        missing = self._fixture().copy()
        missing["liquid_precipitation_depth_mm"] = np.nan
        self.assertTrue(aggregate_liquid_precipitation(missing, "Monthly").empty)

    def test_occurrence_counts_do_not_treat_missing_as_events(self) -> None:
        df = self._fixture()
        wet = occurrence_hours(df, "liquid_precipitation_depth_mm", 0.1, "Monthly")
        self.assertEqual(float(wet.iloc[0, 0]), 2.0)
        self.assertEqual(float(wet.iloc[1, 0]), 1.0)
        snow = occurrence_hours(df, "snow_depth_cm", 0.0, "Monthly", inclusive=False)
        self.assertEqual(float(snow.iloc[0, 0]), 1.0)
        self.assertEqual(float(snow.iloc[1, 0]), 1.0)

    def test_summary_keeps_liquid_accumulation_and_snow_state_semantics_separate(self) -> None:
        summary = precipitation_summary(self._fixture())
        self.assertTrue(summary["liquid_data_available"])
        self.assertTrue(summary["snow_data_available"])
        self.assertAlmostEqual(float(summary["liquid_total_mm"]), 7.0)
        self.assertEqual(summary["wet_hours"], 3)
        self.assertAlmostEqual(float(summary["max_record_precipitation_mm"]), 4.0)
        self.assertAlmostEqual(float(summary["max_snow_depth_cm"]), 3.0)
        self.assertEqual(summary["snow_cover_hours"], 2)


if __name__ == "__main__":
    unittest.main()
'''
TEST.write_text(test_source, encoding="utf-8")

print("CLIMATE-0.10.7 pressure + precipitation update applied")
