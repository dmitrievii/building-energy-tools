from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    source = APP.read_text(encoding="utf-8")

    source = replace_once(
        source,
        '''    include_psychrometrics = can_derive_psychrometrics and page in {
        "Temperature", "Humidity and Psychrometrics", "Time Series and Overlay"
    }
''',
        '''    include_psychrometrics = can_derive_psychrometrics and page in {
        "Temperature",
        "Humidity and Psychrometrics",
        "Wind and Ventilation",
        "Time Series and Overlay",
        "Natural Ventilation",
        "HVAC and Passive Design",
    }
''',
        "historical psychrometric page gate",
    )

    source = replace_once(
        source,
        '''    elif page == "Wind and Ventilation":
        render_historical_wind(filtered_df)
    elif page == "Precipitation and Snow":
''',
        '''    elif page == "Wind and Ventilation":
        render_historical_wind(filtered_df)
    elif page == "Natural Ventilation":
        st.caption(
            "GeoSphere natural-ventilation suitability uses canonical hourly T/RH-derived psychrometrics and, when available, measured hourly wind speed. "
            "No EPW-only field is required for this route."
        )
        render_natural_ventilation(filtered_df, pressure_pa=active_pressure)
    elif page == "HVAC and Passive Design":
        st.caption(
            "Historical HVAC/passive-design indicators use canonical hourly temperature and psychrometrics. "
            "Solar-shading indicators are included only when measured GHI exists in the selected GeoSphere interval."
        )
        render_hvac_passive(filtered_df)
    elif page == "Precipitation and Snow":
''',
        "historical route wiring",
    )

    source = replace_once(
        source,
        '''        st.caption("Occupied-hour filtering uses local EPW clock time. Intervals crossing midnight are supported, for example 22...6.")
    wind_filter = st.checkbox("Use wind-speed limits", value=False)
    wind_min = wind_max = None
    if wind_filter:
        wind_min = st.number_input("Minimum wind speed [m/s]", value=0.5, step=0.1)
        wind_max = st.number_input("Maximum wind speed [m/s]", value=6.0, step=0.1)
''',
        '''        st.caption("Occupied-hour filtering uses the active climate timestamps. Intervals crossing midnight are supported, for example 22...6.")
    wind_available = (
        "wind_speed_m_s" in df.columns
        and pd.to_numeric(df["wind_speed_m_s"], errors="coerce").notna().any()
    )
    wind_filter = st.checkbox(
        "Use wind-speed limits",
        value=False,
        disabled=not wind_available,
        help="Requires measured/available wind speed in the active climate dataset.",
    )
    if not wind_available:
        st.caption("Wind-speed limits are unavailable because this climate interval contains no usable wind-speed observations.")
    wind_min = wind_max = None
    if wind_filter:
        wind_min = st.number_input("Minimum wind speed [m/s]", value=0.5, step=0.1)
        wind_max = st.number_input("Maximum wind speed [m/s]", value=6.0, step=0.1)
''',
        "natural ventilation wind capability gate",
    )

    source = replace_once(
        source,
        '''def render_hvac_passive(df: pd.DataFrame) -> None:
    """Render HVAC and passive-design decision-support charts."""
    st.header("HVAC operation and passive strategies")
    chart_group = st.selectbox(
''',
        '''def render_hvac_passive(df: pd.DataFrame) -> None:
    """Render HVAC and passive-design decision-support charts."""
    st.header("HVAC operation and passive strategies")
    has_ghi = (
        "global_horizontal_radiation_wh_m2" in df.columns
        and pd.to_numeric(df["global_horizontal_radiation_wh_m2"], errors="coerce").notna().any()
    )
    if not has_ghi:
        st.caption("No usable GHI is available in this climate interval; solar-shading strategy rows are omitted rather than inferred.")
    chart_group = st.selectbox(
''',
        "HVAC solar capability caption",
    )

    source = replace_once(
        source,
        '''    elif chart_group == "Design-day candidates":
        daily = df.resample("D").agg(
            mean_t=("dry_bulb_temperature_c", "mean"),
            min_t=("dry_bulb_temperature_c", "min"),
            max_t=("dry_bulb_temperature_c", "max"),
            max_enthalpy=("moist_air_enthalpy_kj_kg", "max"),
            max_humidity_ratio=("humidity_ratio_g_kg", "max"),
            max_ghi=("global_horizontal_radiation_wh_m2", "max"),
        )
''',
        '''    elif chart_group == "Design-day candidates":
        daily_aggregation = {
            "mean_t": ("dry_bulb_temperature_c", "mean"),
            "min_t": ("dry_bulb_temperature_c", "min"),
            "max_t": ("dry_bulb_temperature_c", "max"),
            "max_enthalpy": ("moist_air_enthalpy_kj_kg", "max"),
            "max_humidity_ratio": ("humidity_ratio_g_kg", "max"),
        }
        if has_ghi:
            daily_aggregation["max_ghi"] = ("global_horizontal_radiation_wh_m2", "max")
        daily = df.resample("D").agg(**daily_aggregation)
''',
        "HVAC design-day GHI capability gate",
    )

    source = replace_once(
        source,
        '''    has_speed = has_numeric_observations(df, "wind_speed_m_s")
    has_direction = has_numeric_observations(df, "wind_direction_deg")
    options: list[str] = []
    if has_speed:
        options.append("Wind speed explorer")
    if has_speed and has_direction:
        options.extend(["Wind rose", "Monthly wind rose", "Day-night wind rose"])
    if has_direction:
        options.append("Wind direction histogram")
''',
        '''    has_speed = has_numeric_observations(df, "wind_speed_m_s")
    has_direction = has_numeric_observations(df, "wind_direction_deg")
    has_nv_inputs = (
        has_speed
        and has_direction
        and has_numeric_observations(df, "dry_bulb_temperature_c")
        and has_numeric_observations(df, "relative_humidity_pct")
        and has_numeric_observations(df, "humidity_ratio_g_kg")
    )
    options: list[str] = []
    if has_speed:
        options.append("Wind speed explorer")
    if has_speed and has_direction:
        options.extend(["Wind rose", "Monthly wind rose", "Day-night wind rose"])
        if has_nv_inputs:
            options.append("Wind during natural-ventilation hours")
    if has_direction:
        options.append("Wind direction histogram")
''',
        "historical wind NV option gate",
    )

    source = replace_once(
        source,
        '''    elif chart_group == "Day-night wind rose":
        period = st.radio("Period", ["Day", "Night"], horizontal=True, key="historical_wind_daynight")
        if period == "Day":
            data = df[df["hour_of_day"].between(7, 19)]
        else:
            data = df[(df["hour_of_day"] < 7) | (df["hour_of_day"] > 19)]
        fig = wind_rose_chart(data, f"Measured {period.lower()} wind rose")
        render_plot(fig, wind_interpretation(data))
    else:
''',
        '''    elif chart_group == "Day-night wind rose":
        period = st.radio("Period", ["Day", "Night"], horizontal=True, key="historical_wind_daynight")
        if period == "Day":
            data = df[df["hour_of_day"].between(7, 19)]
        else:
            data = df[(df["hour_of_day"] < 7) | (df["hour_of_day"] > 19)]
        fig = wind_rose_chart(data, f"Measured {period.lower()} wind rose")
        render_plot(fig, wind_interpretation(data))
    elif chart_group == "Wind during natural-ventilation hours":
        mask = natural_ventilation_condition(df)
        data = df[mask]
        if data.empty:
            st.info("No canonical hourly records satisfy the default natural-ventilation suitability limits in the current Data filter.")
            return
        fig = wind_rose_chart(data, "Measured wind during natural-ventilation-suitable hours")
        render_plot(fig, natural_ventilation_interpretation(df, mask))
    else:
''',
        "historical wind NV route",
    )

    APP.write_text(source, encoding="utf-8")
    print(f"Patched {APP}")


if __name__ == "__main__":
    main()
