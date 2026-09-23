from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} block, found {count}")
    return text.replace(old, new, 1)


cleanup_path = Path("tools/climate_analyzer/epw_climate_analyzer/source_parity_monthly_cleanup.py")
cleanup = cleanup_path.read_text(encoding="utf-8")

cleanup = replace_once(
    cleanup,
    'MONTHLY_OVERLAY_RESOLUTIONS = ("Monthly", "Annual")\n',
    'MONTHLY_OVERLAY_RESOLUTIONS = ("Native", "Monthly", "Seasonal", "Annual")\n',
    "monthly overlay resolution capability",
)

helper_anchor = '''def monthly_semantics_from_column(column: str) -> str | None:\n    value = str(column)\n    if not value.startswith("monthly__"):\n        return None\n    parts = value.split("__", 3)\n    if len(parts) < 4:\n        return None\n    semantics = parts[1].replace("_", " ")\n    return semantics if semantics in {"mean", "sum", "min", "max", "circular mean"} else None\n\n\n'''
helper_replacement = helper_anchor + '''def monthly_overlay_resolution_options(column: str) -> tuple[str, ...]:\n    """Return scientifically valid overlay resolutions for a native-monthly field.\n\n    Native always preserves the provider-published monthly observation/statistic.\n    Coarser aggregation is exposed only when the quantity semantics are known.\n    """\n    known_semantics = (\n        monthly_semantics_from_column(column) is not None\n        or column in monthly_ui._MONTHLY_CANONICAL_ALIASES.values()\n    )\n    return MONTHLY_OVERLAY_RESOLUTIONS if known_semantics else ("Native",)\n\n\n'''
cleanup = replace_once(cleanup, helper_anchor, helper_replacement, "monthly overlay capability helper insertion")

cleanup = replace_once(
    cleanup,
    '''        resolution_options = list(MONTHLY_OVERLAY_RESOLUTIONS)\n        if monthly_semantics_from_column(column) is None and column not in monthly_ui._MONTHLY_CANONICAL_ALIASES.values():\n            # Unknown provider statistics can still be plotted monthly. Do not\n            # invent an annual meaning until their provider contract is known.\n            resolution_options = ["Monthly"]\n''',
    '''        resolution_options = list(monthly_overlay_resolution_options(column))\n''',
    "monthly overlay resolution selection",
)

cleanup = replace_once(
    cleanup,
    '''            help=(\n                "Monthly preserves the published value. Annual applies the canonical quantity semantics "\n                f"({semantics}) to the twelve published months when available."\n            ),\n''',
    '''            help=(\n                "Native preserves each provider-published monthly value. Monthly keeps calendar-month bins without "\n                "reconstructing finer data. Seasonal and Annual aggregate only published monthly records using the "\n                f"canonical quantity semantics ({semantics}) when that semantics is known."\n            ),\n''',
    "monthly overlay help text",
)

# Monthly data change capabilities/metadata, not the chart engine.  Keep the
# canonical monthly page forwarding into the shared time-series renderer and do
# not wrap that renderer back into a source-specific monthly overlay.
cleanup = replace_once(
    cleanup,
    '''    _install_semantic_engines()\n    _install_unified_overlay(proxy)\n    _install_parameter_catalogue(parity)\n''',
    '''    _install_semantic_engines()\n    _install_parameter_catalogue(parity)\n''',
    "duplicate monthly overlay interception",
)

cleanup_path.write_text(cleanup, encoding="utf-8")


# The shared renderer historically assumed every source had a meaningful fixed
# intraday cadence. Native monthly data are calendar-native published statistics:
# 28-31 day months are not a fixed minute interval and their 00:00 timestamp is
# only an anchor. Give them a month-only viewport and keep exact time controls for
# 10-minute/hourly sources.
app_path = Path("tools/climate_analyzer/app.py")
app = app_path.read_text(encoding="utf-8")
old_window = '''    native_minutes = native_resolution_minutes(pd.DatetimeIndex(df.index))\n    st.caption(\n        f"Source resolution: {native_minutes} min. Choose an exact time window and overlay up to six series. "\n        "Resolutions finer than the source are intentionally unavailable; no temporal interpolation is performed."\n    )\n\n    index = pd.DatetimeIndex(df.index).sort_values()\n    if index.empty:\n        st.info("No time-series records are available.")\n        return\n\n    default_start = pd.Timestamp(index.min())\n    default_end = pd.Timestamp(index.max())\n    date_min = default_start.date()\n    date_max = default_end.date()\n    step_seconds = max(60, int(native_minutes * 60))\n\n    c1, c2, c3, c4 = st.columns(4)\n    start_date = c1.date_input(\n        "From date",\n        value=default_start.date(),\n        min_value=date_min,\n        max_value=date_max,\n        key="overlay_start_date",\n    )\n    start_time = c2.time_input(\n        "From time",\n        value=default_start.time(),\n        step=step_seconds,\n        key="overlay_start_time",\n    )\n    end_date = c3.date_input(\n        "Through date",\n        value=default_end.date(),\n        min_value=date_min,\n        max_value=date_max,\n        key="overlay_end_date",\n    )\n    end_time = c4.time_input(\n        "Through time",\n        value=default_end.time(),\n        step=step_seconds,\n        key="overlay_end_time",\n    )\n\n    start = pd.Timestamp.combine(start_date, start_time)\n    selected_end = pd.Timestamp.combine(end_date, end_time)\n    if index.tz is not None:\n        start = start.tz_localize(index.tz)\n        selected_end = selected_end.tz_localize(index.tz)\n    # "Through" denotes the selected source interval, so the internal viewport\n    # ends at the following native interval boundary. This includes the selected\n    # 23:00 EPW record without fabricating sub-hourly values.\n    end = selected_end + pd.Timedelta(minutes=native_minutes)\n    if selected_end < start:\n        st.error("The end timestamp must not be earlier than the start timestamp.")\n        return\n\n    if start < pd.Timestamp(index.min()) or selected_end > pd.Timestamp(index.max()):\n        st.error("The selected time range must stay inside the loaded source calendar.")\n        return\n\n\n'''
new_window = '''    native_minutes = native_resolution_minutes(pd.DatetimeIndex(df.index))\n    native_calendar = str(df.attrs.get("canonical_native_resolution", "")).strip().lower()\n    if native_calendar == "monthly":\n        st.caption(\n            "Source resolution: calendar month. Choose whole published months and overlay up to six series. "\n            "No sub-monthly timestamps are reconstructed or interpolated."\n        )\n    else:\n        st.caption(\n            f"Source resolution: {native_minutes} min. Choose an exact time window and overlay up to six series. "\n            "Resolutions finer than the source are intentionally unavailable; no temporal interpolation is performed."\n        )\n\n    index = pd.DatetimeIndex(df.index).sort_values()\n    if index.empty:\n        st.info("No time-series records are available.")\n        return\n\n    default_start = pd.Timestamp(index.min())\n    default_end = pd.Timestamp(index.max())\n\n    if native_calendar == "monthly":\n        month_options = list(dict.fromkeys(pd.Timestamp(value) for value in index))\n        c1, c2 = st.columns(2)\n        start = pd.Timestamp(c1.selectbox(\n            "From month",\n            month_options,\n            index=0,\n            format_func=lambda value: pd.Timestamp(value).strftime("%Y-%m"),\n            key="overlay_start_month",\n        ))\n        selected_end = pd.Timestamp(c2.selectbox(\n            "Through month",\n            month_options,\n            index=len(month_options) - 1,\n            format_func=lambda value: pd.Timestamp(value).strftime("%Y-%m"),\n            key="overlay_end_month",\n        ))\n        end = selected_end + pd.offsets.MonthBegin(1)\n    else:\n        date_min = default_start.date()\n        date_max = default_end.date()\n        step_seconds = max(60, int(native_minutes * 60))\n\n        c1, c2, c3, c4 = st.columns(4)\n        start_date = c1.date_input(\n            "From date",\n            value=default_start.date(),\n            min_value=date_min,\n            max_value=date_max,\n            key="overlay_start_date",\n        )\n        start_time = c2.time_input(\n            "From time",\n            value=default_start.time(),\n            step=step_seconds,\n            key="overlay_start_time",\n        )\n        end_date = c3.date_input(\n            "Through date",\n            value=default_end.date(),\n            min_value=date_min,\n            max_value=date_max,\n            key="overlay_end_date",\n        )\n        end_time = c4.time_input(\n            "Through time",\n            value=default_end.time(),\n            step=step_seconds,\n            key="overlay_end_time",\n        )\n\n        start = pd.Timestamp.combine(start_date, start_time)\n        selected_end = pd.Timestamp.combine(end_date, end_time)\n        if index.tz is not None:\n            start = start.tz_localize(index.tz)\n            selected_end = selected_end.tz_localize(index.tz)\n        # "Through" denotes the selected source interval, so the internal viewport\n        # ends at the following native interval boundary. This includes the selected\n        # 23:00 EPW record without fabricating sub-hourly values.\n        end = selected_end + pd.Timedelta(minutes=native_minutes)\n\n    if selected_end < start:\n        st.error("The end timestamp must not be earlier than the start timestamp.")\n        return\n\n    if start < pd.Timestamp(index.min()) or selected_end > pd.Timestamp(index.max()):\n        st.error("The selected time range must stay inside the loaded source calendar.")\n        return\n\n\n'''
app = replace_once(app, old_window, new_window, "calendar-native monthly overlay window")
app_path.write_text(app, encoding="utf-8")


test_path = Path("tools/climate_analyzer/tests/test_geosphere_monthly_cleanup_0_7_5_4.py")
test = test_path.read_text(encoding="utf-8")

test = replace_once(
    test,
    '''from epw_climate_analyzer.source_parity_monthly_cleanup import (\n    MONTHLY_GENERIC_AGGREGATIONS,\n    _forward_monthly_overlay,\n    describe_monthly_parameter,\n    monthly_semantics_from_column,\n    semantic_analysis_column,\n)\n''',
    '''from epw_climate_analyzer.source_parity_monthly_cleanup import (\n    MONTHLY_GENERIC_AGGREGATIONS,\n    MONTHLY_OVERLAY_RESOLUTIONS,\n    _forward_monthly_overlay,\n    describe_monthly_parameter,\n    install_monthly_cleanup,\n    monthly_overlay_resolution_options,\n    monthly_semantics_from_column,\n    semantic_analysis_column,\n)\n''',
    "monthly cleanup imports",
)

test = replace_once(
    test,
    '''    def test_monthly_and_annual_are_the_only_generic_periods(self) -> None:\n        self.assertEqual(MONTHLY_GENERIC_AGGREGATIONS, ("Monthly", "Annual"))\n\n''',
    '''    def test_monthly_and_annual_are_the_only_generic_periods(self) -> None:\n        self.assertEqual(MONTHLY_GENERIC_AGGREGATIONS, ("Monthly", "Annual"))\n\n    def test_native_monthly_overlay_exposes_identity_and_only_valid_coarser_periods(self) -> None:\n        self.assertEqual(\n            MONTHLY_OVERLAY_RESOLUTIONS,\n            ("Native", "Monthly", "Seasonal", "Annual"),\n        )\n        self.assertEqual(\n            monthly_overlay_resolution_options("dry_bulb_temperature_c"),\n            ("Native", "Monthly", "Seasonal", "Annual"),\n        )\n        self.assertEqual(\n            monthly_overlay_resolution_options("monthly__mean__temperature__tl_mittel"),\n            ("Native", "Monthly", "Seasonal", "Annual"),\n        )\n        self.assertEqual(\n            monthly_overlay_resolution_options("provider_defined_unknown_statistic"),\n            ("Native",),\n        )\n\n    def test_monthly_cleanup_does_not_rewrap_shared_overlay_renderer(self) -> None:\n        source = inspect.getsource(install_monthly_cleanup)\n        self.assertNotIn("_install_unified_overlay(proxy)", source)\n        self.assertIn("monthly_ui._render_monthly_overlay = _forward_monthly_overlay", source)\n\n''',
    "native monthly capability and routing regression",
)

test_path.write_text(test, encoding="utf-8")
