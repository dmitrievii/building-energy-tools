from __future__ import annotations

from pathlib import Path

ROOT = Path("tools/climate_analyzer")
AGG = ROOT / "epw_climate_analyzer" / "aggregations.py"
APP = ROOT / "app.py"
PUBLIC_TEST = ROOT / "tests" / "test_geosphere_public_integration.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_aggregations() -> None:
    text = AGG.read_text(encoding="utf-8")
    old = '''def threshold_count_by_period(
    df: pd.DataFrame,
    condition: pd.Series,
    aggregation: str,
    label: str = "hours",
) -> pd.DataFrame:
    """Count hours satisfying a Boolean condition by a selected aggregation."""
    indicator = condition.fillna(False).astype(int).rename(label)
    temp = df.copy()
    temp[label] = indicator.values

    if aggregation == "Hourly":
        return temp[[label]]
    if aggregation == "Seasonal":
        return temp.groupby("season", observed=False)[label].sum().reindex(SEASON_ORDER).dropna().to_frame()

    rule = RESAMPLE_RULES.get(aggregation)
    if rule is None:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    return temp[label].resample(rule).sum().to_frame()
'''
    new = '''def native_interval_hours(df: pd.DataFrame) -> float:
    """Return one source record's declared physical duration in hours.

    Canonical datasets carry ``canonical_native_interval_minutes`` as source
    metadata.  Historical gaps must not be interpreted as longer observations,
    so a present record always contributes only the declared native interval.
    Legacy frames without that attribute fall back to the median positive
    timestamp spacing, then to one hour when no cadence can be inferred.
    """
    declared = df.attrs.get("canonical_native_interval_minutes")
    try:
        minutes = float(declared)
    except (TypeError, ValueError):
        minutes = float("nan")

    if not pd.notna(minutes) or minutes <= 0.0:
        if isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 1:
            index = pd.DatetimeIndex(df.index).sort_values().unique()
            deltas = pd.Series(index[1:] - index[:-1]).dt.total_seconds().div(60.0)
            positive = deltas[deltas > 0.0]
            minutes = float(positive.median()) if not positive.empty else 60.0
        else:
            minutes = 60.0

    return minutes / 60.0


def threshold_count_by_period(
    df: pd.DataFrame,
    condition: pd.Series,
    aggregation: str,
    label: str = "hours",
) -> pd.DataFrame:
    """Integrate condition duration in physical hours by aggregation period."""
    hours_per_record = native_interval_hours(df)
    aligned = condition.reindex(df.index).fillna(False).astype(float)
    temp = df.copy()
    temp[label] = aligned * hours_per_record

    if aggregation == "Hourly":
        return temp[label].resample("h").sum(min_count=1).to_frame()
    if aggregation == "Seasonal":
        return (
            temp.groupby("season", observed=False)[label]
            .sum(min_count=1)
            .reindex(SEASON_ORDER)
            .dropna()
            .to_frame()
        )

    rule = RESAMPLE_RULES.get(aggregation)
    if rule is None:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    return temp[label].resample(rule).sum(min_count=1).to_frame()
'''
    AGG.write_text(replace_once(text, old, new, label="aggregations threshold helper"), encoding="utf-8")


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    old = '''    if page == "Temperature":
        st.info("Measured-data mode: count-based 'threshold hours' is hidden until all occurrence routes are cadence-aware. HGT/KGT degree-hours already use the native 10-minute interval.")
        render_temperature(filtered_df, interval_count_metrics=False)
    elif page == "Humidity and Psychrometrics":
        st.info("Measured-data mode: count-based moisture-threshold hours are hidden until occurrence metrics are cadence-aware.")
        render_humidity(filtered_df, pressure_pa=active_pressure, interval_count_metrics=False)
'''
    new = '''    if page == "Temperature":
        st.caption("Measured-data threshold hours are integrated from the declared native interval; missing timestamp gaps are not counted as observed duration.")
        render_temperature(filtered_df)
    elif page == "Humidity and Psychrometrics":
        st.caption("Measured-data moisture-threshold hours are integrated from the declared native interval; missing timestamp gaps are not counted as observed duration.")
        render_humidity(filtered_df, pressure_pa=active_pressure)
'''
    APP.write_text(replace_once(text, old, new, label="historical threshold UI"), encoding="utf-8")


def patch_public_test() -> None:
    text = PUBLIC_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        self.assertIn('render_temperature(filtered_df, interval_count_metrics=False)', self.source)
        self.assertIn('render_humidity(filtered_df, pressure_pa=active_pressure, interval_count_metrics=False)', self.source)
''',
        '''        self.assertIn('render_temperature(filtered_df)', self.source)
        self.assertIn('render_humidity(filtered_df, pressure_pa=active_pressure)', self.source)
''',
        label="historical renderer contract",
    )
    text = replace_once(
        text,
        '''    def test_record_count_hour_routes_are_hidden_for_ten_minute_measured_data(self) -> None:
        self.assertIn('chart_options.remove("Threshold hours")', self.source)
        self.assertIn('chart_options.remove("Moisture thresholds")', self.source)
        self.assertIn('HGT/KGT degree-hours already use the native 10-minute interval', self.source)
''',
        '''    def test_historical_threshold_routes_are_reenabled_with_duration_semantics(self) -> None:
        self.assertIn('Measured-data threshold hours are integrated from the declared native interval', self.source)
        self.assertIn('Measured-data moisture-threshold hours are integrated from the declared native interval', self.source)
        self.assertNotIn('render_temperature(filtered_df, interval_count_metrics=False)', self.source)
        self.assertNotIn('render_humidity(filtered_df, pressure_pa=active_pressure, interval_count_metrics=False)', self.source)
''',
        label="historical hour-route contract",
    )
    PUBLIC_TEST.write_text(text, encoding="utf-8")


def main() -> None:
    patch_aggregations()
    patch_app()
    patch_public_test()
    print("CLIMATE-GEOSPHERE-0.4 cadence-duration patch applied")


if __name__ == "__main__":
    main()
