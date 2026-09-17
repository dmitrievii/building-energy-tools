from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"

text = APP.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# --- Data Quality: native-resolution source truth + explicit analysis cadence ---
replace_once(
    '    st.subheader("Temporal/source contract")\n    st.dataframe(',
    '    st.subheader("Temporal/source contract")\n'
    '    source_interval = float(dataset.temporal.native_interval_minutes)\n'
    '    analysis_interval = float(df.attrs.get("canonical_analysis_interval_minutes", 60.0))\n'
    '    st.dataframe(',
    "data-quality cadence variables",
)
replace_once(
    '                "Field": ["Provider", "Dataset", "Calendar mode", "Native interval", "Timezone", "First timestamp", "Last timestamp", "Records"],\n'
    '                "Value": [\n'
    '                    dataset.provenance.provider, dataset.provenance.dataset, dataset.temporal.calendar_mode,\n'
    '                    f"{dataset.temporal.native_interval_minutes} min", dataset.temporal.timezone_name,\n'
    '                    str(dataset.start), str(dataset.end), len(df),\n'
    '                ],',
    '                "Field": [\n'
    '                    "Provider", "Dataset", "Calendar mode", "Source cadence", "Canonical analysis cadence",\n'
    '                    "Timezone", "First source timestamp", "Last source timestamp", "Source records in current view",\n'
    '                ],\n'
    '                "Value": [\n'
    '                    dataset.provenance.provider, dataset.provenance.dataset, dataset.temporal.calendar_mode,\n'
    '                    f"{source_interval:g} min", f"{analysis_interval:g} min", dataset.temporal.timezone_name,\n'
    '                    str(dataset.start), str(dataset.end), len(df),\n'
    '                ],',
    "data-quality temporal contract",
)
replace_once(
    '    st.subheader("Timeline coverage and gaps")',
    '    st.caption(\n'
    '        "This page is calculated from provider-native source observations. Ordinary Climate Analyzer pages use the "\n'
    '        "canonical hourly analysis series; hourly normalization is not used to calculate the diagnostics below."\n'
    '    )\n'
    '    st.subheader("Native timeline coverage and gaps")',
    "data-quality native caption",
)
replace_once(
    '        "Coverage is measured against the requested source interval at the declared native cadence. Missing timestamp gaps "\n'
    '        "are not interpolated and therefore contribute no duration to threshold/frequency metrics."',
    '        "Coverage is measured against the requested source interval at the provider-native cadence. Missing source "\n'
    '        "timestamps are not interpolated. Ordinary hourly analyses omit physically incomplete source hours."',
    "data-quality coverage wording",
)
replace_once(
    '        st.subheader("Per-variable measured coverage")',
    '        st.subheader("Native per-variable measured coverage")',
    "data-quality variable coverage heading",
)
replace_once(
    '    st.subheader("Missing values by field")\n    missing = df[list(dataset.available_canonical_variables)].isna().sum().reset_index()',
    '    st.subheader("Native missing values by measured field")\n    missing = df[list(dataset.available_canonical_variables)].isna().sum().reset_index()',
    "data-quality missing heading",
)
replace_once(
    '        st.success("No missing values occur in the loaded canonical measured variables.")',
    '        st.success("No missing values occur in the native measured variables in the current Data filter.")',
    "data-quality missing success",
)

# --- Historical overview: make the hourly analysis role explicit ---
replace_once(
    '    st.header("Measured climate overview")\n'
    '    st.caption(\n'
    '        "This overview describes the loaded historical observations as measured. Missing timestamps and missing variable "\n'
    '        "values are not interpolated or converted to a typical year."\n'
    '    )',
    '    st.header("Hourly climate overview")\n'
    '    st.caption(\n'
    '        "This overview uses the canonical hourly analysis series derived from provider-native observations. "\n'
    '        "Physically incomplete source hours are omitted and variable-local missing values remain missing; native-resolution "\n'
    '        "coverage and gaps are reported on Data Quality."\n'
    '    )',
    "historical overview role",
)
replace_once('    m1.metric("Timeline coverage",', '    m1.metric("Hourly timeline coverage",', "overview coverage metric")
replace_once('    m2.metric("Observed records",', '    m2.metric("Hourly analysis records",', "overview records metric")
replace_once('    m3.metric("Missing source intervals",', '    m3.metric("Missing analysis hours",', "overview missing metric")
replace_once('    m4.metric("Longest missing gap",', '    m4.metric("Longest analysis gap",', "overview gap metric")
replace_once(
    '        f"native cadence {float(coverage[\'native_interval_minutes\']):g} min · "',
    '        f"analysis cadence {float(coverage[\'native_interval_minutes\']):g} min · "',
    "overview cadence caption",
)
replace_once('        st.subheader("Measured-variable availability")', '        st.subheader("Hourly-variable availability")', "overview availability heading")
replace_once('(\"Mean temperature\", f\"{temp.mean():.1f} °C\")', '(\"Hourly mean temperature\", f\"{temp.mean():.1f} °C\")', "overview mean label")
replace_once('(\"Minimum temperature\", f\"{temp.min():.1f} °C\")', '(\"Hourly minimum temperature\", f\"{temp.min():.1f} °C\")', "overview min label")
replace_once('(\"Maximum temperature\", f\"{temp.max():.1f} °C\")', '(\"Hourly maximum temperature\", f\"{temp.max():.1f} °C\")', "overview max label")
replace_once(
    '        fig = profile_ribbon_chart(df, "dry_bulb_temperature_c", "Monthly", "Measured monthly outdoor temperature", "°C")',
    '        fig = profile_ribbon_chart(df, "dry_bulb_temperature_c", "Monthly", "Canonical hourly monthly outdoor temperature", "°C")',
    "overview profile title",
)

# --- Wind: ordinary historical page is canonical hourly, not native 10-minute ---
replace_once(
    '        "GeoSphere historical wind values are measured source-interval observations. Wind-rose radii and histogram "\n'
    '        "frequencies are integrated in physical hours from the declared native cadence; missing timestamp gaps are not filled."',
    '        "GeoSphere wind observations are normalized to canonical hourly analysis values before this page is rendered. "\n'
    '        "Wind-rose radii and histogram frequencies therefore integrate physical hours from the 60-minute analysis cadence; "\n'
    '        "native 10-minute source coverage remains available on Data Quality."',
    "historical wind cadence wording",
)
replace_once(
    '            "The histogram integrates the physical duration represented by each observed wind-direction record. "',
    '            "The histogram integrates the physical duration represented by each canonical hourly wind-direction record. "',
    "wind histogram wording",
)

# --- Solar: explain source-to-hourly energy-preserving conversion ---
replace_once(
    '        "GeoSphere cglo/chim are measured 10-minute mean horizontal irradiances. The adapter stores canonical interval "\n'
    '        "irradiation [Wh/m²]; this page converts it back to mean irradiance [W/m²] using the declared native interval. "\n'
    '        "DNI and plane-of-array routes are intentionally unavailable in measured historical mode."',
    '        "GeoSphere cglo/chim originate as measured 10-minute mean horizontal irradiances. The adapter first stores "\n'
    '        "interval irradiation [Wh/m²], and the canonical hourly layer sums those interval energies without changing the "\n'
    '        "energy total. This page converts the hourly Wh/m² value to hourly mean irradiance [W/m²]. DNI and plane-of-array "\n'
    '        "routes remain intentionally unavailable in measured historical mode."',
    "historical solar cadence wording",
)
replace_once(
    '            "Values are measured mean horizontal irradiance over each source interval. Duration/frequency views use physical hours, not record counts."',
    '            "Values are canonical hourly mean horizontal irradiance derived from measured source intervals. Duration/frequency views use physical hours, not record counts."',
    "solar explorer wording",
)
replace_once(
    '            "Monthly irradiation sums the measured interval energy [Wh/m²]. Missing source records are excluded rather than interpolated."',
    '            "Monthly irradiation sums canonical hourly interval energy [Wh/m²]. A physically incomplete source hour is absent rather than interpolated."',
    "solar monthly wording",
)
replace_once(
    '            "Hours combine measured outdoor temperature with measured mean global horizontal irradiance. Missing timestamp gaps do not contribute duration."',
    '            "Hours combine canonical hourly outdoor temperature with canonical hourly mean global horizontal irradiance. Incomplete source hours do not contribute duration."',
    "solar threshold wording",
)
replace_once(
    '        render_plot(fig, "Each point combines coincident measured temperature and global horizontal irradiance at the source timestamp.")',
    '        render_plot(fig, "Each point combines coincident canonical hourly temperature and global horizontal irradiance at the analysis timestamp.")',
    "solar scatter wording",
)

# --- Provider-neutral precipitation/snow wording on the active analysis frame ---
replace_once(
    '        options.extend(["Precipitation totals", "Precipitation-record occurrence", "Liquid precipitation explorer"])',
    '        options.extend(["Precipitation totals", "Precipitation-interval occurrence", "Liquid precipitation explorer"])',
    "precipitation option",
)
replace_once(
    '            "Period totals sum valid interval precipitation-depth records. Missing source values and missing timestamp gaps are excluded rather than treated as zero.",',
    '            "Period totals sum valid interval precipitation-depth values from the active analysis frame. Missing values and missing intervals are excluded rather than treated as zero.",',
    "precipitation totals wording",
)
replace_once(
    '    elif chart_group == "Precipitation-record occurrence":\n'
    '        threshold = st.number_input("Precipitation-record threshold [mm]", min_value=0.0, value=0.1, step=0.1)',
    '    elif chart_group == "Precipitation-interval occurrence":\n'
    '        threshold = st.number_input("Precipitation-interval threshold [mm]", min_value=0.0, value=0.1, step=0.1)',
    "precipitation occurrence branch",
)
replace_once(
    '            title=f"Precipitation-record occurrence ≥ {threshold:g} mm",\n'
    '            labels={x_column: "Period", "records": "Source records meeting threshold"},',
    '            title=f"Precipitation-interval occurrence ≥ {threshold:g} mm",\n'
    '            labels={x_column: "Period", "records": "Analysis intervals meeting threshold"},',
    "precipitation occurrence chart labels",
)
replace_once(
    '        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Source records meeting threshold")',
    '        fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Analysis intervals meeting threshold")',
    "precipitation occurrence axis",
)
replace_once(
    '            "Counts source precipitation-depth records meeting the selected threshold. This is deliberately a record-occurrence metric, not exact rainfall duration: an interval precipitation amount does not reveal how long rain occurred inside that source interval.",',
    '            "Counts records in the active analysis frame whose interval precipitation depth meets the threshold. This is deliberately an interval-occurrence metric, not exact rainfall duration: an interval precipitation amount does not reveal how long rain occurred inside that interval.",',
    "precipitation occurrence interpretation",
)
replace_once(
    '            "Snow depth is a state variable. Each valid record with snow depth greater than zero contributes exactly one native source interval: 1 h for hourly EPW and 1/6 h for 10-minute GeoSphere data. Missing timestamp gaps contribute no duration.",',
    '            "Snow depth is a state variable. Each valid record with snow depth greater than zero contributes the physical duration declared by the active frame. Ordinary GeoSphere analysis uses the canonical 1-hour cadence; native 10-minute source gaps remain a Data Quality diagnostic.",',
    "snow duration interpretation",
)

# --- Historical route: native Data Quality vs canonical hourly ordinary analysis ---
replace_once(
    '                "Default: use the measured GeoSphere station pressure for each 10-minute record. "\n'
    '                "The median valid measured pressure is only a fallback for missing/invalid records."',
    '                "Default: normalize measured GeoSphere station pressure to the canonical hourly analysis cadence. "\n'
    '                "The measured-pressure median is used only as a fallback where an hourly pressure value is unavailable."',
    "historical pressure help",
)
replace_once(
    '    from epw_climate_analyzer.historical import prepare_historical_analysis_frame\n'
    '    try:\n'
    '        full_df = prepare_historical_analysis_frame(\n'
    '            dataset,\n'
    '            include_psychrometrics=include_psychrometrics,\n'
    '            fallback_pressure_pa=fallback_pressure,\n'
    '            pressure_override_pa=pressure_override,\n'
    '        )',
    '    from epw_climate_analyzer.historical import (\n'
    '        prepare_historical_analysis_frame,\n'
    '        prepare_historical_native_diagnostic_frame,\n'
    '    )\n'
    '    try:\n'
    '        if page == "Data Quality":\n'
    '            full_df = prepare_historical_native_diagnostic_frame(dataset)\n'
    '        else:\n'
    '            full_df = prepare_historical_analysis_frame(\n'
    '                dataset,\n'
    '                include_psychrometrics=include_psychrometrics,\n'
    '                fallback_pressure_pa=fallback_pressure,\n'
    '                pressure_override_pa=pressure_override,\n'
    '            )',
    "historical native/hourly route",
)
replace_once(
    '    st.sidebar.markdown("### Current climate")\n'
    '    st.sidebar.write(f"**{dataset.location.city}, {dataset.location.country}**")\n'
    '    st.sidebar.caption("GeoSphere Austria · measured 10-minute historical data")\n'
    '    st.sidebar.write(f"Rows in current view: {len(filtered_df):,}")\n'
    '    with st.sidebar.expander("Data provenance", expanded=False):\n'
    '        st.caption(dataset.provenance.dataset)\n'
    '        st.caption(f"Calendar: real historical UTC · native interval {dataset.temporal.native_interval_minutes} min")',
    '    source_interval = float(dataset.temporal.native_interval_minutes)\n'
    '    analysis_interval = float(full_df.attrs.get("canonical_analysis_interval_minutes", 60.0))\n'
    '    frame_role = str(full_df.attrs.get("canonical_frame_role", "hourly-analysis"))\n'
    '    st.sidebar.markdown("### Current climate")\n'
    '    st.sidebar.write(f"**{dataset.location.city}, {dataset.location.country}**")\n'
    '    if frame_role == "native-diagnostics":\n'
    '        st.sidebar.caption(f"GeoSphere Austria · native source diagnostics · {source_interval:g} min")\n'
    '        st.sidebar.write(f"Source rows in current view: {len(filtered_df):,}")\n'
    '    else:\n'
    '        st.sidebar.caption(\n'
    '            f"GeoSphere Austria · source {source_interval:g} min → canonical analysis {analysis_interval:g} min"\n'
    '        )\n'
    '        st.sidebar.write(f"Hourly analysis rows in current view: {len(filtered_df):,}")\n'
    '    with st.sidebar.expander("Data provenance", expanded=False):\n'
    '        st.caption(dataset.provenance.dataset)\n'
    '        st.caption(f"Source cadence: {source_interval:g} min")\n'
    '        st.caption(f"Canonical analysis cadence: {analysis_interval:g} min")\n'
    '        st.caption(f"Active frame: {\'native source diagnostics\' if frame_role == \'native-diagnostics\' else \'canonical hourly analysis\'}")\n'
    '        st.caption(f"Calendar: real historical UTC · {dataset.temporal.calendar_mode}")',
    "historical sidebar provenance",
)
replace_once(
    '        st.caption("Measured-data threshold hours are integrated from the declared native interval; missing timestamp gaps are not counted as observed duration.")',
    '        st.caption("Threshold hours are evaluated on the canonical hourly analysis series. Physically incomplete source hours are absent and contribute no duration.")',
    "temperature hourly caption",
)
replace_once(
    '        st.caption("Measured-data moisture-threshold hours are integrated from the declared native interval; missing timestamp gaps are not counted as observed duration.")',
    '        st.caption("Moisture-threshold hours are evaluated on the canonical hourly analysis series. Physically incomplete source hours are absent and contribute no duration.")',
    "humidity hourly caption",
)
replace_once(
    '            "Liquid precipitation is an interval-depth measurement; threshold occurrence therefore counts source records, not rainfall duration. "\n'
    '            "Snow-cover duration integrates the declared native cadence, and missing timestamp gaps contribute no observed time."',
    '            "Liquid precipitation is aggregated to canonical hourly interval depth before ordinary analysis; interval occurrence is not rainfall duration. "\n'
    '            "Snow-cover duration is evaluated on the canonical hourly state series. Native 10-minute source coverage remains available on Data Quality."',
    "historical precipitation caption",
)

APP.write_text(text, encoding="utf-8")
print("Climate 0.6.5 native diagnostics / cadence UI patch applied successfully")
