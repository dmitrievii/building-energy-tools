"""One-shot deterministic patch for Climate Analyzer 0.6.4 interannual heatmaps."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_regex_once(path: Path, pattern: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex match, found {count}")
    path.write_text(updated, encoding="utf-8")


def patch_aggregations() -> None:
    path = ROOT / "epw_climate_analyzer" / "aggregations.py"
    replace_once(
        path,
        "import pandas as pd\n\nfrom .temporal_filtering import (",
        "import numpy as np\nimport pandas as pd\n\nfrom .climate_model import aggregation_semantics_for\nfrom .temporal_filtering import (",
        "aggregation imports",
    )

    new_block = r'''HEATMAP_COMPARE_HOUR = "Hour of day"
HEATMAP_COMPARE_YEAR = "Year"
HEATMAP_COMPARISON_DIMENSIONS = (HEATMAP_COMPARE_HOUR, HEATMAP_COMPARE_YEAR)
HEATMAP_INTENSIVE_STATISTICS = ("Mean", "Minimum", "Maximum", "Median", "P05", "P95")
HEATMAP_EXTENSIVE_STATISTICS = ("Total",) + HEATMAP_INTENSIVE_STATISTICS
HEATMAP_CIRCULAR_STATISTICS = ("Circular mean",)


def heatmap_statistic_options(column: str) -> tuple[str, ...]:
    """Return quantity-aware statistics that are meaningful for a heat-map cell."""
    semantics = aggregation_semantics_for(column)
    if semantics == "sum":
        return HEATMAP_EXTENSIVE_STATISTICS
    if semantics == "circular mean":
        return HEATMAP_CIRCULAR_STATISTICS
    return HEATMAP_INTENSIVE_STATISTICS


def heatmap_default_statistic(column: str) -> str:
    """Return the physically preferred default statistic for a canonical variable."""
    semantics = aggregation_semantics_for(column)
    if semantics == "sum":
        return "Total"
    if semantics == "circular mean":
        return "Circular mean"
    return "Mean"


def _normalise_heatmap_statistic(column: str, statistic: str) -> str:
    requested = str(statistic).strip()
    semantics = aggregation_semantics_for(column)
    if semantics == "circular mean" and requested == "Mean":
        requested = "Circular mean"
    options = heatmap_statistic_options(column)
    if requested not in options:
        raise ValueError(f"Unsupported heat-map statistic '{requested}' for {column}; choose one of {options}.")
    return requested


def _circular_mean_degrees(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if numeric.empty:
        return float("nan")
    radians = np.deg2rad(np.mod(numeric.to_numpy(), 360.0))
    sin_mean = float(np.sin(radians).mean())
    cos_mean = float(np.cos(radians).mean())
    if abs(sin_mean) < 1e-12 and abs(cos_mean) < 1e-12:
        return float("nan")
    return float(np.mod(np.rad2deg(np.arctan2(sin_mean, cos_mean)), 360.0))


def _heatmap_reduce(grouped, statistic: str) -> pd.Series:
    if statistic == "Mean":
        return grouped.mean()
    if statistic == "Minimum":
        return grouped.min()
    if statistic == "Maximum":
        return grouped.max()
    if statistic == "Median":
        return grouped.median()
    if statistic == "P05":
        return grouped.quantile(0.05)
    if statistic == "P95":
        return grouped.quantile(0.95)
    if statistic == "Total":
        return grouped.sum(min_count=1)
    if statistic == "Circular mean":
        return grouped.apply(_circular_mean_degrees)
    raise ValueError(f"Unsupported heat-map statistic: {statistic}")


def _heatmap_period_key(index: pd.DatetimeIndex, row_group: str, *, include_year: bool) -> pd.Index:
    group = str(row_group).strip().lower()
    if group == "day":
        values = index.strftime("%Y-%m-%d" if include_year else "%m-%d")
        return pd.Index(values, name="Day")
    if group == "week":
        iso = index.isocalendar()
        if include_year:
            values = [f"{int(year):04d}-W{int(week):02d}" for year, week in zip(iso.year, iso.week, strict=False)]
        else:
            values = [f"W{int(week):02d}" for week in iso.week]
        return pd.Index(values, name="Week")
    if group == "month":
        if include_year:
            return pd.Index(index.strftime("%Y-%m"), name="Month")
        return pd.Index(index.month.astype(int), name="Month")
    raise ValueError("row_group must be 'day', 'week' or 'month'")


def temporal_heatmap_matrix(
    df: pd.DataFrame,
    column: str,
    row_group: str = "day",
    compare_across: str = HEATMAP_COMPARE_HOUR,
    statistic: str = "Mean",
) -> pd.DataFrame:
    """Create a generic heat-map matrix from period, comparison dimension and statistic.

    ``Hour of day`` preserves the existing heat-map semantics. In chronological
    multi-year mode the period key keeps the year; in calendar-profile mode the
    year is intentionally folded away. ``Year`` is an explicit interannual view
    and therefore always preserves real calendar years regardless of the global
    calendar-profile setting.

    For extensive quantities in calendar-profile mode, ``Total`` is first
    calculated independently for every year/cell and then averaged across years,
    preventing a multi-year dataset from being reported as an inflated typical
    period total.
    """
    if column not in df.columns:
        raise KeyError(f"Heat-map column is missing: {column}")
    if compare_across not in HEATMAP_COMPARISON_DIMENSIONS:
        raise ValueError(f"Unsupported heat-map comparison dimension: {compare_across}")

    statistic = _normalise_heatmap_statistic(column, statistic)
    index = pd.DatetimeIndex(df.index)
    values = pd.to_numeric(df[column], errors="coerce")
    temp = pd.DataFrame({"_value": values.to_numpy()}, index=index)

    if compare_across == HEATMAP_COMPARE_YEAR:
        temp["_y"] = index.year.astype(int)
        temp["_x"] = _heatmap_period_key(index, row_group, include_year=False).to_numpy()
    else:
        preserve_year = time_basis(df) == CHRONOLOGICAL and is_multiyear(df)
        temp["_y"] = (
            pd.to_numeric(df["hour_of_day"], errors="coerce").to_numpy()
            if "hour_of_day" in df.columns
            else index.hour.astype(int)
        )
        temp["_x"] = _heatmap_period_key(index, row_group, include_year=preserve_year).to_numpy()

    temp = temp.dropna(subset=["_value", "_y"])
    if temp.empty:
        return pd.DataFrame()

    if (
        statistic == "Total"
        and compare_across == HEATMAP_COMPARE_HOUR
        and time_basis(df) == CALENDAR_PROFILE
        and is_multiyear(df)
    ):
        temp["_year"] = temp.index.year.astype(int)
        per_year = temp.groupby(["_year", "_y", "_x"], observed=False, sort=True)["_value"].sum(min_count=1)
        reduced = per_year.groupby(["_y", "_x"], observed=False, sort=True).mean()
    else:
        grouped = temp.groupby(["_y", "_x"], observed=False, sort=True)["_value"]
        reduced = _heatmap_reduce(grouped, statistic)

    matrix = reduced.unstack("_x").sort_index()
    if str(row_group).strip().lower() == "month" and all(isinstance(value, (int, np.integer)) for value in matrix.columns):
        matrix = matrix.reindex(columns=list(range(1, 13)))
    return matrix


def calendar_matrix(df: pd.DataFrame, column: str, row_group: str = "day") -> pd.DataFrame:
    """Backward-compatible period-by-hour matrix using a mean cell statistic."""
    return temporal_heatmap_matrix(
        df,
        column,
        row_group=row_group,
        compare_across=HEATMAP_COMPARE_HOUR,
        statistic="Mean",
    )


def monthly_hour_matrix(df: pd.DataFrame, column: str, aggfunc: str = "mean") -> pd.DataFrame:
    """Backward-compatible month-by-hour matrix without folding chronological years."""
    statistic = {
        "mean": "Mean",
        "min": "Minimum",
        "max": "Maximum",
        "median": "Median",
        "sum": "Total",
    }.get(str(aggfunc).strip().lower())
    if statistic is None:
        raise ValueError(f"Unsupported monthly-hour aggregation: {aggfunc}")
    return temporal_heatmap_matrix(
        df,
        column,
        row_group="month",
        compare_across=HEATMAP_COMPARE_HOUR,
        statistic=statistic,
    )
'''
    replace_regex_once(
        path,
        r'def calendar_matrix\(.*?\n\ndef duration_curve',
        new_block + '\n\ndef duration_curve',
        "generic temporal heatmap matrix",
    )


def patch_charts() -> None:
    path = ROOT / "epw_climate_analyzer" / "charts.py"
    replace_once(
        path,
        "from .aggregations import aggregate_summary, aggregate_sum, calendar_matrix, duration_curve, monthly_box_data, monthly_hour_matrix, native_interval_hours",
        "from .aggregations import (\n    HEATMAP_COMPARE_HOUR,\n    aggregate_summary,\n    aggregate_sum,\n    duration_curve,\n    monthly_box_data,\n    native_interval_hours,\n    temporal_heatmap_matrix,\n)",
        "chart heatmap imports",
    )

    new_block = r'''def temporal_heatmap_chart(
    df: pd.DataFrame,
    column: str,
    row_group: str,
    compare_across: str,
    statistic: str,
    title: str,
    unit: str,
    temperature_thresholds: tuple[float, float] | None = None,
) -> go.Figure:
    """Create a period × comparison-dimension heatmap with an explicit cell statistic."""
    matrix = temporal_heatmap_matrix(
        df,
        column,
        row_group=row_group,
        compare_across=compare_across,
        statistic=statistic,
    )
    if matrix.empty:
        raise ValueError("No numeric observations remain for the selected heat-map configuration.")

    period_label = str(row_group).strip().capitalize()
    colorscale = _heatmap_colorscale(column, matrix.values, temperature_thresholds)
    zmin, zmax = _axis_limits_for_column(column, matrix.values, pad_fraction=0.0)
    fig = px.imshow(
        matrix,
        aspect="auto",
        color_continuous_scale=colorscale,
        zmin=zmin,
        zmax=zmax,
        labels=dict(x=period_label, y=compare_across, color=unit),
        title=title,
    )
    if str(row_group).strip().lower() == "month" and all(isinstance(value, (int, np.integer)) for value in matrix.columns):
        fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=MONTH_LABELS)
    if compare_across == HEATMAP_COMPARE_HOUR:
        fig.update_yaxes(range=[23, 0], autorangeoptions=dict(minallowed=0, maxallowed=23))
    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))
    return fig


def heatmap_chart(
    df: pd.DataFrame,
    column: str,
    row_group: str,
    title: str,
    unit: str,
    temperature_thresholds: tuple[float, float] | None = None,
) -> go.Figure:
    """Create the legacy period-by-hour heatmap using mean cell values."""
    return temporal_heatmap_chart(
        df,
        column,
        row_group=row_group,
        compare_across=HEATMAP_COMPARE_HOUR,
        statistic="Mean",
        title=title,
        unit=unit,
        temperature_thresholds=temperature_thresholds,
    )


def month_hour_heatmap(
    df: pd.DataFrame,
    column: str,
    title: str,
    unit: str,
    aggfunc: str = "mean",
    temperature_thresholds: tuple[float, float] | None = None,
) -> go.Figure:
    """Create the legacy month-by-hour heatmap through the generic heatmap engine."""
    statistic = {
        "mean": "Mean",
        "min": "Minimum",
        "max": "Maximum",
        "median": "Median",
        "sum": "Total",
    }.get(str(aggfunc).strip().lower())
    if statistic is None:
        raise ValueError(f"Unsupported month-hour aggregation: {aggfunc}")
    return temporal_heatmap_chart(
        df,
        column,
        row_group="month",
        compare_across=HEATMAP_COMPARE_HOUR,
        statistic=statistic,
        title=title,
        unit=unit,
        temperature_thresholds=temperature_thresholds,
    )
'''
    replace_regex_once(
        path,
        r'def heatmap_chart\(.*?\n\ndef duration_chart',
        new_block + '\n\ndef duration_chart',
        "generic temporal heatmap chart",
    )


def patch_temporal_filtering() -> None:
    path = ROOT / "epw_climate_analyzer" / "temporal_filtering.py"
    replace_once(
        path,
        '''        if aggregation == "Daily":\n            if multiyear:\n                return list(idx.strftime("%d %b %Y"))\n            return [int(stamp.dayofyear) for stamp in idx]\n        if aggregation == "Seasonal":\n''',
        '''        if aggregation == "Daily":\n            if multiyear:\n                return list(idx.strftime("%d %b %Y"))\n            return [int(stamp.dayofyear) for stamp in idx]\n        if aggregation == "Annual":\n            return [str(int(stamp.year)) for stamp in idx]\n        if aggregation == "Seasonal":\n''',
        "annual display labels",
    )


def patch_app() -> None:
    path = ROOT / "app.py"
    replace_once(
        path,
        "global aggregate_sum, duration_curve, filter_by_months_and_hours, native_interval_hours, threshold_count_by_period",
        "global aggregate_sum, duration_curve, filter_by_months_and_hours, heatmap_default_statistic, heatmap_statistic_options, native_interval_hours, threshold_count_by_period",
        "analysis dependency globals aggregations",
    )
    replace_once(
        path,
        "global duration_chart, heatmap_chart, histogram_chart, GIVONI_MILNE_ZONES",
        "global duration_chart, heatmap_chart, histogram_chart, temporal_heatmap_chart, GIVONI_MILNE_ZONES",
        "analysis dependency globals charts",
    )
    replace_once(
        path,
        '''            aggregate_sum,\n            duration_curve,\n            filter_by_months_and_hours,\n            native_interval_hours,\n            threshold_count_by_period,\n''',
        '''            aggregate_sum,\n            duration_curve,\n            filter_by_months_and_hours,\n            heatmap_default_statistic,\n            heatmap_statistic_options,\n            native_interval_hours,\n            threshold_count_by_period,\n''',
        "analysis dependency import aggregations",
    )
    replace_once(
        path,
        '''            heatmap_chart,\n            histogram_chart,\n            GIVONI_MILNE_ZONES,\n''',
        '''            heatmap_chart,\n            histogram_chart,\n            temporal_heatmap_chart,\n            GIVONI_MILNE_ZONES,\n''',
        "analysis dependency import charts",
    )

    old_heatmap = r'''    if chart_type == "Heat map":
        heatmap_period = st.selectbox("Heat-map aggregation", ["Day", "Week", "Month"], index=0)
        if column == "dry_bulb_temperature_c":
            st.caption("Temperature heatmap colours use the current heating and cooling thresholds: blue = cold, green = neutral band, red = hot.")
        if heatmap_period == "Month":
            fig = month_hour_heatmap(
                df,
                column,
                f"{title_prefix}: {variable_label} month-hour heat map",
                unit,
                temperature_thresholds=temperature_thresholds if column == "dry_bulb_temperature_c" else None,
            )
        else:
            fig = heatmap_chart(
                df,
                column,
                heatmap_period.lower(),
                f"{title_prefix}: {variable_label} {heatmap_period.lower()}-hour heat map",
                unit,
                temperature_thresholds=temperature_thresholds if column == "dry_bulb_temperature_c" else None,
            )
'''
    new_heatmap = r'''    if chart_type == "Heat map":
        heatmap_period = st.selectbox("Heat-map aggregation", ["Day", "Week", "Month"], index=0)
        compare_across = st.selectbox("Compare across", ["Hour of day", "Year"], index=0)
        statistic_options = list(heatmap_statistic_options(column))
        default_statistic = heatmap_default_statistic(column)
        statistic = st.selectbox(
            "Statistic",
            statistic_options,
            index=statistic_options.index(default_statistic),
            help=(
                "The statistic defines the value represented by each heat-map cell. Extensive canonical variables "
                "such as irradiation and precipitation default to period Total; state/intensive variables default to Mean."
            ),
        )
        if compare_across == "Year":
            st.caption(
                "Year comparison preserves real calendar years from the current Data filter even when the global Time basis is Calendar profile."
            )
        if column == "dry_bulb_temperature_c":
            st.caption("Temperature heatmap colours use the current heating and cooling thresholds: blue = cold, green = neutral band, red = hot.")
        fig = temporal_heatmap_chart(
            df,
            column,
            heatmap_period.lower(),
            compare_across,
            statistic,
            f"{title_prefix}: {variable_label} {heatmap_period.lower()} × {compare_across.lower()} heat map · {statistic}",
            unit,
            temperature_thresholds=temperature_thresholds if column == "dry_bulb_temperature_c" else None,
        )
'''
    replace_once(path, old_heatmap, new_heatmap, "generic variable heatmap UI")

    replace_once(
        path,
        'aggregation = st.selectbox("Aggregation", ["Monthly", "Weekly", "Daily", "Hourly", "Seasonal"], index=0)',
        'aggregation = st.selectbox("Aggregation", ["Monthly", "Annual", "Weekly", "Daily", "Hourly", "Seasonal"], index=0)',
        "annual generic aggregation",
    )

    old_nv = r'''    if chart_group == "Heat map":
        row_group = st.radio("Heat-map aggregation", ["day", "week", "month"], horizontal=True)
        fig = heatmap_chart(df_nv, "natural_ventilation_suitable", row_group, "Natural ventilation eligibility", "0/1")
        render_plot(fig, natural_ventilation_interpretation(df, mask))
'''
    new_nv = r'''    if chart_group == "Heat map":
        row_group = st.radio("Heat-map aggregation", ["Day", "Week", "Month"], horizontal=True)
        compare_across = st.radio("Compare across", ["Hour of day", "Year"], horizontal=True)
        statistic_options = list(heatmap_statistic_options("natural_ventilation_suitable"))
        statistic = st.selectbox("Statistic", statistic_options, index=0, key="nv_heatmap_statistic")
        if compare_across == "Year":
            st.caption("Year comparison preserves real calendar years from the current Data filter.")
        fig = temporal_heatmap_chart(
            df_nv,
            "natural_ventilation_suitable",
            row_group.lower(),
            compare_across,
            statistic,
            f"Natural ventilation eligibility · {row_group.lower()} × {compare_across.lower()} · {statistic}",
            "0/1",
        )
        render_plot(fig, natural_ventilation_interpretation(df, mask))
'''
    replace_once(path, old_nv, new_nv, "natural ventilation heatmap UI")


def create_tests() -> None:
    path = ROOT / "tests" / "test_interannual_heatmaps_0_6_4.py"
    if path.exists():
        return
    path.write_text(r'''from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.aggregations import (
    HEATMAP_COMPARE_HOUR,
    HEATMAP_COMPARE_YEAR,
    aggregate_summary,
    heatmap_default_statistic,
    heatmap_statistic_options,
    temporal_heatmap_matrix,
)
from epw_climate_analyzer.temporal_filtering import CALENDAR_PROFILE, CHRONOLOGICAL, display_period_labels, with_time_basis


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def frame() -> pd.DataFrame:
    idx = pd.to_datetime(
        [
            "2024-01-01T00:00:00Z", "2024-01-01T12:00:00Z",
            "2024-02-01T00:00:00Z", "2024-02-01T12:00:00Z",
            "2024-02-29T12:00:00Z",
            "2025-01-01T00:00:00Z", "2025-01-01T12:00:00Z",
            "2025-02-01T00:00:00Z", "2025-02-01T12:00:00Z",
        ]
    )
    df = pd.DataFrame(
        {
            "dry_bulb_temperature_c": [0.0, 10.0, 20.0, 30.0, 40.0, 2.0, 12.0, 22.0, 32.0],
            "global_horizontal_radiation_wh_m2": [1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 20.0, 30.0, 40.0],
            "wind_direction_deg": [350.0, 10.0, 90.0, 90.0, 180.0, 350.0, 10.0, 90.0, 90.0],
        },
        index=idx,
    )
    df["hour_of_day"] = df.index.hour
    df["month_index"] = df.index.month
    df["day_of_year"] = df.index.dayofyear
    df["week_of_year"] = df.index.isocalendar().week.astype(int).to_numpy()
    return with_time_basis(df, CHRONOLOGICAL)


class InterannualHeatmap064Tests(unittest.TestCase):
    def test_month_by_year_mean_and_maximum_preserve_real_years(self) -> None:
        df = frame()
        mean = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_YEAR, "Mean")
        maximum = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_YEAR, "Maximum")
        self.assertEqual(mean.index.tolist(), [2024, 2025])
        self.assertEqual(mean.columns.tolist(), list(range(1, 13)))
        self.assertAlmostEqual(float(mean.loc[2024, 1]), 5.0)
        self.assertAlmostEqual(float(mean.loc[2025, 1]), 7.0)
        self.assertAlmostEqual(float(maximum.loc[2024, 2]), 40.0)
        self.assertAlmostEqual(float(maximum.loc[2025, 2]), 32.0)

    def test_year_compare_overrides_calendar_profile_folding(self) -> None:
        df = with_time_basis(frame(), CALENDAR_PROFILE)
        matrix = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_YEAR, "Mean")
        self.assertEqual(matrix.index.tolist(), [2024, 2025])
        self.assertAlmostEqual(float(matrix.loc[2024, 1]), 5.0)
        self.assertAlmostEqual(float(matrix.loc[2025, 1]), 7.0)

    def test_one_year_year_compare_is_a_single_stripe(self) -> None:
        df = frame().loc["2024"].copy()
        df = with_time_basis(df, CHRONOLOGICAL)
        matrix = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "month", HEATMAP_COMPARE_YEAR, "Mean")
        self.assertEqual(matrix.index.tolist(), [2024])
        self.assertEqual(matrix.shape[0], 1)

    def test_day_by_year_uses_calendar_date_and_keeps_leap_day_gap(self) -> None:
        df = frame()
        matrix = temporal_heatmap_matrix(df, "dry_bulb_temperature_c", "day", HEATMAP_COMPARE_YEAR, "Mean")
        self.assertIn("02-29", matrix.columns)
        self.assertAlmostEqual(float(matrix.loc[2024, "02-29"]), 40.0)
        self.assertTrue(np.isnan(matrix.loc[2025, "02-29"]))

    def test_calendar_profile_hour_total_averages_per_year_totals(self) -> None:
        df = with_time_basis(frame(), CALENDAR_PROFILE)
        matrix = temporal_heatmap_matrix(df, "global_horizontal_radiation_wh_m2", "month", HEATMAP_COMPARE_HOUR, "Total")
        # Jan 00:00 totals are 1 (2024) and 10 (2025), so the typical-year cell is 5.5, not 11.
        self.assertAlmostEqual(float(matrix.loc[0, 1]), 5.5)
        self.assertAlmostEqual(float(matrix.loc[12, 1]), 11.0)

    def test_quantity_aware_statistic_options_and_defaults(self) -> None:
        self.assertEqual(heatmap_default_statistic("dry_bulb_temperature_c"), "Mean")
        self.assertIn("Maximum", heatmap_statistic_options("dry_bulb_temperature_c"))
        self.assertEqual(heatmap_default_statistic("global_horizontal_radiation_wh_m2"), "Total")
        self.assertEqual(heatmap_statistic_options("global_horizontal_radiation_wh_m2")[0], "Total")
        self.assertEqual(heatmap_default_statistic("wind_direction_deg"), "Circular mean")
        self.assertEqual(heatmap_statistic_options("wind_direction_deg"), ("Circular mean",))

    def test_circular_mean_wraps_through_north(self) -> None:
        df = frame().loc[[pd.Timestamp("2024-01-01T00:00:00Z"), pd.Timestamp("2024-01-01T12:00:00Z")]].copy()
        df = with_time_basis(df, CHRONOLOGICAL)
        matrix = temporal_heatmap_matrix(df, "wind_direction_deg", "month", HEATMAP_COMPARE_YEAR, "Circular mean")
        value = float(matrix.loc[2024, 1])
        self.assertTrue(value < 1.0 or value > 359.0)

    def test_annual_aggregation_is_first_class_and_labels_years(self) -> None:
        df = frame()
        annual = aggregate_summary(df, "dry_bulb_temperature_c", "Annual")
        labels = display_period_labels(annual.index, "Annual", CHRONOLOGICAL)
        self.assertEqual(labels, ["2024", "2025"])
        self.assertAlmostEqual(float(annual.iloc[0]["min"]), 0.0)
        self.assertAlmostEqual(float(annual.iloc[0]["max"]), 40.0)


class InterannualHeatmap064UiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_generic_heatmap_exposes_orthogonal_controls(self) -> None:
        self.assertIn('st.selectbox("Heat-map aggregation", ["Day", "Week", "Month"]', self.source)
        self.assertIn('st.selectbox("Compare across", ["Hour of day", "Year"]', self.source)
        self.assertIn('"Statistic",\n            statistic_options', self.source)
        self.assertIn("temporal_heatmap_chart(", self.source)

    def test_annual_is_exposed_in_generic_profile_aggregation(self) -> None:
        self.assertIn('["Monthly", "Annual", "Weekly", "Daily", "Hourly", "Seasonal"]', self.source)

    def test_natural_ventilation_heatmap_uses_same_dimensions(self) -> None:
        self.assertIn('st.radio("Compare across", ["Hour of day", "Year"]', self.source)
        self.assertIn('key="nv_heatmap_statistic"', self.source)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")


def main() -> None:
    patch_aggregations()
    patch_charts()
    patch_temporal_filtering()
    patch_app()
    create_tests()


if __name__ == "__main__":
    main()
