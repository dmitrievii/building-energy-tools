from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
MODEL = ROOT / "epw_climate_analyzer" / "climate_model.py"
HOURLY = ROOT / "epw_climate_analyzer" / "canonical_hourly.py"
HISTORICAL = ROOT / "epw_climate_analyzer" / "historical.py"
CAPS = ROOT / "epw_climate_analyzer" / "historical_capabilities.py"
GEOSPHERE = ROOT / "epw_climate_analyzer" / "geosphere.py"
AUDIT_TEST = ROOT / "tests" / "test_source_parity_audit_0_7_2.py"
NEW_TEST = ROOT / "tests" / "test_priority_a_geosphere_0_7_3.py"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


def patch_model() -> None:
    source = MODEL.read_text(encoding="utf-8")
    source = replace_once(
        source,
        'AggregationSemantics = Literal["mean", "sum", "circular mean"]',
        'AggregationSemantics = Literal["mean", "sum", "max", "min", "circular mean", "paired max direction"]',
        "aggregation semantics",
    )
    source = replace_once(
        source,
        '''    "dry_bulb_temperature_c": CanonicalVariable(\n        "dry_bulb_temperature_c", "°C", "temperature", "mean", "Outdoor dry-bulb air temperature"\n    ),\n''',
        '''    "dry_bulb_temperature_c": CanonicalVariable(\n        "dry_bulb_temperature_c", "°C", "temperature", "mean", "Outdoor dry-bulb air temperature"\n    ),\n    "dry_bulb_temperature_min_c": CanonicalVariable(\n        "dry_bulb_temperature_min_c", "°C", "temperature", "min", "True source-interval minimum 2 m air temperature"\n    ),\n    "dry_bulb_temperature_max_c": CanonicalVariable(\n        "dry_bulb_temperature_max_c", "°C", "temperature", "max", "True source-interval maximum 2 m air temperature"\n    ),\n''',
        "temperature extrema variables",
    )
    source = replace_once(
        source,
        '''    "wind_direction_deg": CanonicalVariable(\n        "wind_direction_deg", "deg", "direction", "circular mean", "Wind direction clockwise from north"\n    ),\n''',
        '''    "wind_direction_deg": CanonicalVariable(\n        "wind_direction_deg", "deg", "direction", "circular mean", "Wind direction clockwise from north"\n    ),\n    "wind_gust_speed_m_s": CanonicalVariable(\n        "wind_gust_speed_m_s", "m/s", "wind speed", "max", "Maximum wind gust speed within the source interval"\n    ),\n    "wind_gust_direction_deg": CanonicalVariable(\n        "wind_gust_direction_deg", "deg", "direction", "paired max direction", "Direction paired with the maximum wind gust"\n    ),\n''',
        "gust variables",
    )
    source = replace_once(
        source,
        '''    "snow_depth_cm": CanonicalVariable(\n        "snow_depth_cm", "cm", "snow depth", "mean", "Snow depth state"\n    ),\n''',
        '''    "snow_depth_cm": CanonicalVariable(\n        "snow_depth_cm", "cm", "snow depth", "mean", "Snow depth state"\n    ),\n    "sunshine_duration_s": CanonicalVariable(\n        "sunshine_duration_s", "s", "duration", "sum", "Measured sunshine duration within the source interval"\n    ),\n''',
        "sunshine variable",
    )
    MODEL.write_text(source, encoding="utf-8")


def patch_hourly() -> None:
    source = HOURLY.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''def _hourly_reduce(values: pd.Series, semantics: str) -> pd.Series:\n    if semantics == "circular mean":\n        return _circular_hourly_mean(values)\n    grouped = values.resample("h", label="left", closed="left")\n    if semantics == "sum":\n        return grouped.sum(min_count=1)\n    return grouped.mean()\n''',
        '''def _paired_direction_at_hourly_max(direction: pd.Series, magnitude: pd.Series) -> pd.Series:\n    """Return the direction paired with the largest magnitude in each hour.\n\n    GeoSphere ``ddx`` is not an independently averaged direction: every source\n    value belongs to the source-interval gust maximum ``ffx``. For an hourly\n    analysis value we therefore select the direction from the row containing the\n    largest gust. Ties are resolved deterministically by the earliest timestamp.\n    Strict completeness is applied by the caller.\n    """\n    direction_numeric = pd.to_numeric(direction, errors="coerce").astype(float)\n    magnitude_numeric = pd.to_numeric(magnitude, errors="coerce").astype(float)\n    hour_key = pd.DatetimeIndex(direction_numeric.index).floor("h")\n    hourly_max = magnitude_numeric.groupby(hour_key).transform("max")\n    candidates = (\n        direction_numeric.notna()\n        & magnitude_numeric.notna()\n        & magnitude_numeric.eq(hourly_max)\n    )\n    selected = direction_numeric[candidates]\n    if selected.empty:\n        return pd.Series(dtype="float64", index=pd.DatetimeIndex([], name=direction_numeric.index.name))\n    selected_hour = pd.DatetimeIndex(selected.index).floor("h")\n    result = selected.groupby(selected_hour).first().astype(float).mod(360.0)\n    result.index.name = direction_numeric.index.name\n    return result\n\n\ndef _hourly_reduce(values: pd.Series, semantics: str) -> pd.Series:\n    if semantics == "circular mean":\n        return _circular_hourly_mean(values)\n    if semantics == "paired max direction":\n        raise ValueError("Paired maximum-direction reduction requires the paired magnitude series.")\n    grouped = values.resample("h", label="left", closed="left")\n    if semantics == "sum":\n        return grouped.sum(min_count=1)\n    if semantics == "max":\n        return grouped.max()\n    if semantics == "min":\n        return grouped.min()\n    return grouped.mean()\n''',
        "quantity reducers",
    )
    source = replace_once(
        source,
        '''    for column in data.columns:\n        values = pd.to_numeric(data[column], errors="coerce")\n        values.index = index\n        semantics = aggregation_semantics_for(column)\n        reduced = _hourly_reduce(values, semantics).reindex(hourly_index)\n        valid_counts = values.resample("h", label="left", closed="left").count().reindex(hourly_index, fill_value=0)\n        complete = complete_timeline & (valid_counts == expected)\n        hourly[column] = reduced.where(complete)\n        incomplete_by_variable[str(column)] = int((~complete).sum())\n''',
        '''    for column in data.columns:\n        values = pd.to_numeric(data[column], errors="coerce")\n        values.index = index\n        semantics = aggregation_semantics_for(column)\n        valid_counts = values.resample("h", label="left", closed="left").count().reindex(hourly_index, fill_value=0)\n        complete = complete_timeline & (valid_counts == expected)\n        if semantics == "paired max direction":\n            companion_column = "wind_gust_speed_m_s"\n            if companion_column not in data.columns:\n                reduced = pd.Series(float("nan"), index=hourly_index, dtype="float64")\n                complete = complete & False\n            else:\n                companion = pd.to_numeric(data[companion_column], errors="coerce")\n                companion.index = index\n                companion_counts = companion.resample("h", label="left", closed="left").count().reindex(hourly_index, fill_value=0)\n                complete = complete & (companion_counts == expected)\n                reduced = _paired_direction_at_hourly_max(values, companion).reindex(hourly_index)\n        else:\n            reduced = _hourly_reduce(values, semantics).reindex(hourly_index)\n        hourly[column] = reduced.where(complete)\n        incomplete_by_variable[str(column)] = int((~complete).sum())\n''',
        "paired gust hourly reduction",
    )
    HOURLY.write_text(source, encoding="utf-8")


def patch_historical() -> None:
    source = HISTORICAL.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''    hourly = canonical_hourly_analysis_frame(\n        dataset.data,\n        source_interval_minutes=dataset.temporal.native_interval_minutes,\n    )\n''',
        '''    canonical_columns = list(dataset.available_canonical_variables)\n    source_frame = dataset.data[canonical_columns].copy()\n    source_frame.attrs.update(dict(dataset.data.attrs))\n    hourly = canonical_hourly_analysis_frame(\n        source_frame,\n        source_interval_minutes=dataset.temporal.native_interval_minutes,\n    )\n''',
        "exclude diagnostic extras from hourly normalization",
    )
    HISTORICAL.write_text(source, encoding="utf-8")


def patch_capabilities() -> None:
    source = CAPS.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''    has_temperature = has_numeric_observations(df, "dry_bulb_temperature_c")\n    has_humidity = has_numeric_observations(df, "relative_humidity_pct")\n    has_wind = has_numeric_observations(df, "wind_speed_m_s") or has_numeric_observations(df, "wind_direction_deg")\n    has_solar = has_numeric_observations(df, "global_horizontal_radiation_wh_m2") or has_numeric_observations(\n        df, "diffuse_horizontal_radiation_wh_m2"\n    )\n''',
        '''    has_mean_temperature = has_numeric_observations(df, "dry_bulb_temperature_c")\n    has_temperature = has_mean_temperature or any(\n        has_numeric_observations(df, column)\n        for column in ("dry_bulb_temperature_min_c", "dry_bulb_temperature_max_c")\n    )\n    has_humidity = has_numeric_observations(df, "relative_humidity_pct")\n    has_wind = any(\n        has_numeric_observations(df, column)\n        for column in ("wind_speed_m_s", "wind_direction_deg", "wind_gust_speed_m_s", "wind_gust_direction_deg")\n    )\n    has_solar = any(\n        has_numeric_observations(df, column)\n        for column in ("global_horizontal_radiation_wh_m2", "diffuse_horizontal_radiation_wh_m2", "sunshine_duration_s")\n    )\n''',
        "expanded historical capability inputs",
    )
    source = source.replace('if has_temperature and has_humidity:', 'if has_mean_temperature and has_humidity:')
    CAPS.write_text(source, encoding="utf-8")


def patch_geosphere() -> None:
    source = GEOSPHERE.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''    ProviderFieldSpec("tl", "dry_bulb_temperature_c", ("°c", "c", "degc"), description="Lufttemperatur 2m"),\n''',
        '''    ProviderFieldSpec("tl", "dry_bulb_temperature_c", ("°c", "c", "degc"), description="Lufttemperatur 2m"),\n    ProviderFieldSpec("tlmin", "dry_bulb_temperature_min_c", ("°c", "c", "degc"), description="Lufttemperatur 2m Minimalwert"),\n    ProviderFieldSpec("tlmax", "dry_bulb_temperature_max_c", ("°c", "c", "degc"), description="Lufttemperatur 2m Maximalwert"),\n''',
        "GeoSphere temperature extrema specs",
    )
    source = replace_once(
        source,
        '''    ProviderFieldSpec("dd", "wind_direction_deg", ("°", "deg", "degree"), description="Windrichtung"),\n''',
        '''    ProviderFieldSpec("dd", "wind_direction_deg", ("°", "deg", "degree"), description="Windrichtung"),\n    ProviderFieldSpec("ffx", "wind_gust_speed_m_s", ("m/s", "m s-1", "m s^-1"), description="Maximale Windgeschwindigkeit (Spitzenböe)"),\n    ProviderFieldSpec("ddx", "wind_gust_direction_deg", ("°", "deg", "degree"), description="Windrichtung zur Spitzenböe"),\n''',
        "GeoSphere gust specs",
    )
    source = replace_once(
        source,
        '''    ProviderFieldSpec("sh", "snow_depth_cm", ("cm",), description="Gesamtschneehöhe"),\n''',
        '''    ProviderFieldSpec("sh", "snow_depth_cm", ("cm",), description="Gesamtschneehöhe"),\n    ProviderFieldSpec("so", "sunshine_duration_s", ("s",), description="Sonnenscheindauer"),\n''',
        "GeoSphere sunshine spec",
    )
    source = replace_once(
        source,
        '''DEFAULT_PROVIDER_PARAMETERS = tuple(item.provider_name for item in _PROVIDER_FIELD_SPECS)\n''',
        '''DEFAULT_PROVIDER_PARAMETERS = tuple(item.provider_name for item in _PROVIDER_FIELD_SPECS)\nQUALITY_FLAG_COLUMN_PREFIX = "quality_flag__"\nQUALITY_FLAG_PROVIDER_NAMES = frozenset(f"{name}_flag" for name in FIELD_SPEC_BY_PROVIDER)\nSUPPORTED_QUERY_PARAMETERS = frozenset(FIELD_SPEC_BY_PROVIDER) | QUALITY_FLAG_PROVIDER_NAMES\n\n\ndef quality_flag_column(provider_name: str) -> str:\n    return f"{QUALITY_FLAG_COLUMN_PREFIX}{str(provider_name).strip()}"\n\n\ndef provider_parameters_with_quality_flags(\n    metadata: Mapping[str, Any],\n    provider_parameters: Iterable[str],\n) -> tuple[str, ...]:\n    """Return selected physical parameters plus their live provider quality flags.\n\n    Flags are requested only when the live metadata exposes the exact matching\n    ``<parameter>_flag`` field with unit ``code``. They remain native diagnostic\n    metadata and are never promoted to physical canonical variables.\n    """\n    parameters = parse_parameters(metadata)\n    result: list[str] = []\n    for name in dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()):\n        if name not in FIELD_SPEC_BY_PROVIDER:\n            raise ValueError(f"Unsupported GeoSphere physical parameter: {name}")\n        result.append(name)\n        flag_name = f"{name}_flag"\n        flag = parameters.get(flag_name)\n        if flag is None:\n            continue\n        if _normalise_unit(flag.unit) != "code":\n            raise ValueError(\n                f"GeoSphere quality flag '{flag_name}' unit changed: expected 'code', got '{_normalise_unit(flag.unit)}'."\n            )\n        result.append(flag_name)\n    return tuple(result)\n''',
        "quality flag contract",
    )
    source = source.replace('unknown = sorted(set(parameters) - set(FIELD_SPEC_BY_PROVIDER))', 'unknown = sorted(set(parameters) - set(SUPPORTED_QUERY_PARAMETERS))')
    source = replace_once(
        source,
        '''    for provider_name, spec in mapping.items():\n        if provider_name not in provider_frame.columns:\n            continue\n        values = pd.to_numeric(provider_frame[provider_name], errors="coerce")\n        canonical[spec.canonical_name] = values * float(spec.scale)\n    if canonical.empty:\n''',
        '''    for provider_name, spec in mapping.items():\n        if provider_name not in provider_frame.columns:\n            continue\n        values = pd.to_numeric(provider_frame[provider_name], errors="coerce")\n        canonical[spec.canonical_name] = values * float(spec.scale)\n        flag_name = f"{provider_name}_flag"\n        if flag_name in provider_frame.columns:\n            canonical[quality_flag_column(provider_name)] = pd.to_numeric(\n                provider_frame[flag_name], errors="coerce"\n            )\n    if canonical.empty:\n''',
        "retain quality flag columns",
    )
    source = replace_once(
        source,
        '''    provider_frame, request_references = fetch_station_provider_frame(\n        station_id=station.station_id,\n        start=start,\n        end=end,\n        provider_parameters=selected.keys(),\n        timeout_s=timeout_s,\n        progress_callback=progress_callback,\n    )\n''',
        '''    query_parameters = provider_parameters_with_quality_flags(metadata_payload, selected.keys())\n    provider_frame, request_references = fetch_station_provider_frame(\n        station_id=station.station_id,\n        start=start,\n        end=end,\n        provider_parameters=query_parameters,\n        timeout_s=timeout_s,\n        progress_callback=progress_callback,\n    )\n''',
        "automatic quality flag retrieval",
    )
    GEOSPHERE.write_text(source, encoding="utf-8")


def patch_app() -> None:
    source = APP.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''    global supported_geosphere_parameter_mapping, fetch_geosphere_station_dataset\n    global plan_geosphere_queries, estimate_geosphere_datapoints\n''',
        '''    global supported_geosphere_parameter_mapping, fetch_geosphere_station_dataset\n    global plan_geosphere_queries, estimate_geosphere_datapoints, provider_parameters_with_quality_flags\n''',
        "GeoSphere dependency globals",
    )
    source = replace_once(
        source,
        '''        plan_data_queries as plan_geosphere_queries,\n        station_catalog as geosphere_station_catalog,\n''',
        '''        plan_data_queries as plan_geosphere_queries,\n        provider_parameters_with_quality_flags,\n        station_catalog as geosphere_station_catalog,\n''',
        "GeoSphere quality flag helper import",
    )
    source = replace_once(
        source,
        '''    "Dry-bulb temperature": ("dry_bulb_temperature_c", "°C"),\n''',
        '''    "Dry-bulb temperature": ("dry_bulb_temperature_c", "°C"),\n    "Dry-bulb temperature minimum": ("dry_bulb_temperature_min_c", "°C"),\n    "Dry-bulb temperature maximum": ("dry_bulb_temperature_max_c", "°C"),\n''',
        "app temperature extrema variables",
    )
    source = replace_once(
        source,
        '''    "Wind direction": ("wind_direction_deg", "deg"),\n''',
        '''    "Wind direction": ("wind_direction_deg", "deg"),\n    "Wind gust speed": ("wind_gust_speed_m_s", "m/s"),\n    "Wind gust direction": ("wind_gust_direction_deg", "deg"),\n''',
        "app gust variables",
    )
    source = replace_once(
        source,
        '''    "Snow depth": ("snow_depth_cm", "cm"),\n''',
        '''    "Snow depth": ("snow_depth_cm", "cm"),\n    "Sunshine duration": ("sunshine_duration_s", "s"),\n''',
        "app sunshine variable",
    )
    source = replace_once(
        source,
        '''    estimated = estimate_geosphere_datapoints(start_ts, end_ts, len(provider_parameters), 1)\n    batches = plan_geosphere_queries(station.station_id, start_ts, end_ts, provider_parameters)\n    st.caption(\n        f"Requested interval: {selected_days} day(s), 10-minute source data, {len(provider_parameters)} selected measured variables. "\n        f"Estimated provider datapoints: {estimated:,}; bounded API batches: {len(batches)}. "\n''',
        '''    query_parameters = provider_parameters_with_quality_flags(metadata, provider_parameters)\n    estimated = estimate_geosphere_datapoints(start_ts, end_ts, len(query_parameters), 1)\n    batches = plan_geosphere_queries(station.station_id, start_ts, end_ts, query_parameters)\n    loaded_flag_count = len(query_parameters) - len(provider_parameters)\n    st.caption(\n        f"Requested interval: {selected_days} day(s), 10-minute source data, {len(provider_parameters)} selected measured variables "\n        f"plus {loaded_flag_count} matching provider quality flag(s). "\n        f"Estimated provider datapoints: {estimated:,}; bounded API batches: {len(batches)}. "\n''',
        "accurate query estimate including flags",
    )
    source = replace_once(
        source,
        '''            ["Dry-bulb temperature", "Dew-point temperature", "Wet-bulb temperature"],\n''',
        '''            [\n                "Dry-bulb temperature",\n                "Dry-bulb temperature minimum",\n                "Dry-bulb temperature maximum",\n                "Dew-point temperature",\n                "Wet-bulb temperature",\n            ],\n''',
        "temperature explorer extrema",
    )
    source = replace_once(
        source,
        '''    has_speed = has_numeric_observations(df, "wind_speed_m_s")\n    has_direction = has_numeric_observations(df, "wind_direction_deg")\n    has_nv_inputs = (\n''',
        '''    has_speed = has_numeric_observations(df, "wind_speed_m_s")\n    has_direction = has_numeric_observations(df, "wind_direction_deg")\n    has_gust_speed = has_numeric_observations(df, "wind_gust_speed_m_s")\n    has_gust_direction = has_numeric_observations(df, "wind_gust_direction_deg")\n    has_nv_inputs = (\n''',
        "historical gust capability flags",
    )
    source = replace_once(
        source,
        '''    if has_speed:\n        options.append("Wind speed explorer")\n    if has_speed and has_direction:\n''',
        '''    if has_speed:\n        options.append("Wind speed explorer")\n    if has_gust_speed:\n        options.append("Wind gust explorer")\n    if has_gust_direction:\n        options.append("Gust direction histogram")\n    if has_speed and has_direction:\n''',
        "historical gust options",
    )
    source = replace_once(
        source,
        '''    if chart_group == "Wind speed explorer":\n        render_generic_variable_page(df, ["Wind speed"], "Wind speed", "Measured wind", None)\n    elif chart_group == "Wind rose":\n''',
        '''    if chart_group == "Wind speed explorer":\n        render_generic_variable_page(df, ["Wind speed"], "Wind speed", "Measured wind", None)\n    elif chart_group == "Wind gust explorer":\n        render_generic_variable_page(df, ["Wind gust speed"], "Wind gust speed", "Measured wind gust", None)\n    elif chart_group == "Gust direction histogram":\n        fig = histogram_chart(df, "wind_gust_direction_deg", "Direction of maximum measured gust", "deg", bins=36)\n        render_plot(\n            fig,\n            "Each hourly direction remains paired with the largest measured source-interval gust in that hour; it is not independently circular-averaged.",\n        )\n    elif chart_group == "Wind rose":\n''',
        "historical gust routes",
    )
    source = replace_once(
        source,
        '''    if not specs:\n        st.info("No measured horizontal radiation observations are available in the selected interval.")\n        return\n\n    st.caption(\n''',
        '''    has_sunshine = has_numeric_observations(df, "sunshine_duration_s")\n    if not specs and not has_sunshine:\n        st.info("No measured horizontal radiation or sunshine-duration observations are available in the selected interval.")\n        return\n\n    st.caption(\n''',
        "historical sunshine capability",
    )
    source = replace_once(
        source,
        '''    options = ["Horizontal irradiance explorer", "Monthly horizontal irradiation"]\n    has_ghi = any(source == "global_horizontal_radiation_wh_m2" for _, _, source in specs)\n''',
        '''    options: list[str] = []\n    if specs:\n        options.extend(["Horizontal irradiance explorer", "Monthly horizontal irradiation"])\n    if has_sunshine:\n        options.append("Sunshine duration explorer")\n    has_ghi = any(source == "global_horizontal_radiation_wh_m2" for _, _, source in specs)\n''',
        "historical sunshine option",
    )
    source = replace_once(
        source,
        '''    if chart_group == "Horizontal irradiance explorer":\n''',
        '''    if chart_group == "Sunshine duration explorer":\n        render_generic_variable_page(df, ["Sunshine duration"], "Sunshine duration", "Measured sunshine", None)\n    elif chart_group == "Horizontal irradiance explorer":\n''',
        "historical sunshine route",
    )
    source = replace_once(
        source,
        '''    st.subheader("Native missing values by measured field")\n    missing = df[list(dataset.available_canonical_variables)].isna().sum().reset_index()\n''',
        '''    flag_columns = [column for column in df.columns if str(column).startswith("quality_flag__")]\n    if flag_columns:\n        flag_rows: list[dict[str, object]] = []\n        for column in flag_columns:\n            values = pd.to_numeric(df[column], errors="coerce")\n            counts = values.value_counts(dropna=True).sort_index()\n            code_summary = ", ".join(f"{float(code):g}: {int(count):,}" for code, count in counts.items())\n            flag_rows.append(\n                {\n                    "Provider parameter": str(column).split("__", 1)[1],\n                    "Flag records": int(values.notna().sum()),\n                    "Missing flags": int(values.isna().sum()),\n                    "Observed provider codes": code_summary or "none",\n                }\n            )\n        st.subheader("Provider quality-flag diagnostics")\n        st.dataframe(pd.DataFrame(flag_rows), hide_index=True, use_container_width=True)\n        st.caption(\n            "GeoSphere quality codes are retained verbatim at native source cadence. Climate Analyzer reports their observed distributions but does not invent an accept/reject meaning for undocumented code values."\n        )\n\n    st.subheader("Native missing values by measured field")\n    missing = df[list(dataset.available_canonical_variables)].isna().sum().reset_index()\n''',
        "Data Quality flag diagnostics",
    )
    APP.write_text(source, encoding="utf-8")


def patch_old_audit_test() -> None:
    source = AUDIT_TEST.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''            {"tl", "rf", "p", "ffam", "dd", "rr", "rrm", "sh", "cglo", "chim"},\n''',
        '''            {"tl", "tlmin", "tlmax", "rf", "p", "ffam", "dd", "ffx", "ddx", "rr", "rrm", "sh", "so", "cglo", "chim"},\n''',
        "updated adapter boundary expectation",
    )
    source = replace_once(
        source,
        '''    def test_priority_a_provider_fields_are_not_silently_claimed_as_used(self) -> None:\n        self.assertTrue({"ffx", "ddx", "so", "tlmin", "tlmax"}.isdisjoint(FIELD_SPEC_BY_PROVIDER))\n        doc = DOC.read_text(encoding="utf-8")\n        for name in ("ffx", "ddx", "so", "tlmin", "tlmax", "*_flag"):\n            self.assertIn(name, doc)\n''',
        '''    def test_priority_a_provider_fields_from_audit_are_now_explicitly_mapped(self) -> None:\n        self.assertTrue({"ffx", "ddx", "so", "tlmin", "tlmax"}.issubset(FIELD_SPEC_BY_PROVIDER))\n        doc = DOC.read_text(encoding="utf-8")\n        for name in ("ffx", "ddx", "so", "tlmin", "tlmax", "*_flag"):\n            self.assertIn(name, doc)\n''',
        "updated Priority-A audit expectation",
    )
    AUDIT_TEST.write_text(source, encoding="utf-8")


def write_new_test() -> None:
    NEW_TEST.write_text('''from __future__ import annotations\n\nimport unittest\n\nimport pandas as pd\n\nfrom epw_climate_analyzer.canonical_hourly import canonical_hourly_analysis_frame\nfrom epw_climate_analyzer.geosphere import (\n    FIELD_SPEC_BY_PROVIDER,\n    provider_frame_to_canonical,\n    provider_parameters_with_quality_flags,\n    quality_flag_column,\n)\nfrom epw_climate_analyzer.historical_capabilities import available_historical_pages\n\n\nclass PriorityAGeoSphere073Tests(unittest.TestCase):\n    def test_priority_a_provider_fields_have_quantity_correct_canonical_targets(self) -> None:\n        self.assertEqual(FIELD_SPEC_BY_PROVIDER["ffx"].canonical_name, "wind_gust_speed_m_s")\n        self.assertEqual(FIELD_SPEC_BY_PROVIDER["ddx"].canonical_name, "wind_gust_direction_deg")\n        self.assertEqual(FIELD_SPEC_BY_PROVIDER["so"].canonical_name, "sunshine_duration_s")\n        self.assertEqual(FIELD_SPEC_BY_PROVIDER["tlmin"].canonical_name, "dry_bulb_temperature_min_c")\n        self.assertEqual(FIELD_SPEC_BY_PROVIDER["tlmax"].canonical_name, "dry_bulb_temperature_max_c")\n\n    def test_hourly_extrema_sunshine_and_paired_gust_direction(self) -> None:\n        index = pd.date_range("2026-01-01T00:00:00Z", periods=6, freq="10min", name="timestamp")\n        frame = pd.DataFrame(\n            {\n                "dry_bulb_temperature_min_c": [1.0, 0.5, -1.0, 0.0, 0.2, 0.1],\n                "dry_bulb_temperature_max_c": [2.0, 2.5, 3.0, 2.2, 2.4, 2.1],\n                "sunshine_duration_s": [0.0, 60.0, 120.0, 180.0, 240.0, 300.0],\n                "wind_gust_speed_m_s": [5.0, 7.0, 12.0, 9.0, 8.0, 6.0],\n                "wind_gust_direction_deg": [10.0, 20.0, 210.0, 40.0, 50.0, 60.0],\n            },\n            index=index,\n        )\n        hourly = canonical_hourly_analysis_frame(frame, source_interval_minutes=10)\n        self.assertEqual(len(hourly), 1)\n        self.assertAlmostEqual(float(hourly.iloc[0]["dry_bulb_temperature_min_c"]), -1.0)\n        self.assertAlmostEqual(float(hourly.iloc[0]["dry_bulb_temperature_max_c"]), 3.0)\n        self.assertAlmostEqual(float(hourly.iloc[0]["sunshine_duration_s"]), 900.0)\n        self.assertAlmostEqual(float(hourly.iloc[0]["wind_gust_speed_m_s"]), 12.0)\n        self.assertAlmostEqual(float(hourly.iloc[0]["wind_gust_direction_deg"]), 210.0)\n\n    def test_equal_hourly_gust_maxima_choose_earliest_source_pair(self) -> None:\n        index = pd.date_range("2026-01-01T00:00:00Z", periods=6, freq="10min", name="timestamp")\n        frame = pd.DataFrame(\n            {\n                "wind_gust_speed_m_s": [5.0, 12.0, 12.0, 9.0, 8.0, 6.0],\n                "wind_gust_direction_deg": [10.0, 30.0, 220.0, 40.0, 50.0, 60.0],\n            },\n            index=index,\n        )\n        hourly = canonical_hourly_analysis_frame(frame, source_interval_minutes=10)\n        self.assertAlmostEqual(float(hourly.iloc[0]["wind_gust_direction_deg"]), 30.0)\n\n    def test_quality_flags_are_requested_and_retained_as_diagnostics(self) -> None:\n        metadata = {\n            "parameters": [\n                {"name": "tl", "unit": "°C"},\n                {"name": "tl_flag", "unit": "code"},\n                {"name": "ffx", "unit": "m/s"},\n                {"name": "ffx_flag", "unit": "code"},\n            ]\n        }\n        query = provider_parameters_with_quality_flags(metadata, ["tl", "ffx"])\n        self.assertEqual(query, ("tl", "tl_flag", "ffx", "ffx_flag"))\n        index = pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="10min", name="timestamp")\n        provider = pd.DataFrame(\n            {"tl": [1.0, 2.0], "tl_flag": [0, 1], "ffx": [5.0, 6.0], "ffx_flag": [0, 0]},\n            index=index,\n        )\n        canonical = provider_frame_to_canonical(\n            provider,\n            {"tl": FIELD_SPEC_BY_PROVIDER["tl"], "ffx": FIELD_SPEC_BY_PROVIDER["ffx"]},\n        )\n        self.assertIn(quality_flag_column("tl"), canonical.columns)\n        self.assertIn(quality_flag_column("ffx"), canonical.columns)\n        self.assertEqual(canonical[quality_flag_column("tl")].tolist(), [0, 1])\n\n    def test_new_measurements_enable_temperature_wind_and_solar_pages_without_fabrication(self) -> None:\n        index = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")\n        frame = pd.DataFrame(\n            {\n                "dry_bulb_temperature_min_c": [0.0, 1.0],\n                "dry_bulb_temperature_max_c": [4.0, 5.0],\n                "wind_gust_speed_m_s": [8.0, 9.0],\n                "wind_gust_direction_deg": [250.0, 260.0],\n                "sunshine_duration_s": [1200.0, 1800.0],\n            },\n            index=index,\n        )\n        pages = set(available_historical_pages(frame))\n        self.assertIn("Temperature", pages)\n        self.assertIn("Wind and Ventilation", pages)\n        self.assertIn("Solar and Radiation", pages)\n        self.assertNotIn("Humidity and Psychrometrics", pages)\n        self.assertNotIn("Natural Ventilation", pages)\n        self.assertNotIn("Sky and Daylight", pages)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")


def main() -> None:
    patch_model()
    patch_hourly()
    patch_historical()
    patch_capabilities()
    patch_geosphere()
    patch_app()
    patch_old_audit_test()
    write_new_test()
    print("Applied Climate Analyzer 0.7.3 Priority-A GeoSphere patch")


if __name__ == "__main__":
    main()
