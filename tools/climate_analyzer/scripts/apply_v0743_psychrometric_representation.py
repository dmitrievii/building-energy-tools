from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
CHARTS = ROOT / "epw_climate_analyzer" / "charts.py"
DIST = ROOT / "epw_climate_analyzer" / "psychrometric_distribution.py"
COMPARE = ROOT / "epw_climate_analyzer" / "comparison.py"
GUARD = ROOT / "epw_climate_analyzer" / "runtime_module_guard.py"
TEST = ROOT / "tests" / "test_psychrometric_representation_0_7_4_3.py"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_block(path: Path, start_marker: str, next_marker: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker missing")
    end = text.find(next_marker, start + len(start_marker))
    if end < 0:
        raise RuntimeError(f"{label}: next marker missing")
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


# ---------------------------------------------------------------------------
# 1) Physically constrained smooth climate zones + arbitrary contour levels.
# ---------------------------------------------------------------------------
replace_once(
    DIST,
    "import plotly.graph_objects as go\n\nfrom .aggregations import native_interval_hours",
    "import plotly.graph_objects as go\nimport psychrolib\n\nfrom .aggregations import native_interval_hours\n\npsychrolib.SetUnitSystem(psychrolib.SI)",
    "PsychroLib import",
)

insert_before_density = '''def _physical_psychrometric_mask(\n    x: np.ndarray,\n    y: np.ndarray,\n    *,\n    chart_type: str,\n    pressure_pa: float,\n) -> np.ndarray:\n    \"\"\"Return grid cells that represent physically possible 0...100% RH states.\n\n    Gaussian smoothing is performed on a rectangular numerical domain. Without\n    this mask, a small amount of smoothed density can leak above the saturation\n    curve even though every source observation is physically valid.\n    \"\"\"\n    xx, yy = np.meshgrid(np.asarray(x, dtype=float), np.asarray(y, dtype=float), indexing=\"ij\")\n    if chart_type == \"i-d\":\n        d_g_kg = xx\n        w = d_g_kg / 1000.0\n        denominator = 1.006 + 1.86 * w\n        t_c = (yy - 2501.0 * w) / np.maximum(denominator, 1e-12)\n    else:\n        t_c = xx\n        d_g_kg = yy\n\n    valid = np.isfinite(t_c) & np.isfinite(d_g_kg) & (d_g_kg >= 0.0)\n    saturation = np.full(t_c.shape, np.nan, dtype=float)\n    flat_t = t_c.ravel()\n    flat_sat = saturation.ravel()\n    flat_valid = valid.ravel()\n    for idx in np.where(flat_valid)[0]:\n        try:\n            flat_sat[idx] = psychrolib.GetSatHumRatio(float(flat_t[idx]), float(pressure_pa)) * 1000.0\n        except Exception:\n            flat_valid[idx] = False\n    saturation = flat_sat.reshape(t_c.shape)\n    valid = flat_valid.reshape(t_c.shape) & np.isfinite(saturation)\n    tolerance = np.maximum(1e-9, np.abs(saturation) * 1e-8)\n    return valid & (d_g_kg <= saturation + tolerance)\n\n\n'''
replace_once(
    DIST,
    "def psychrometric_density_field(\n",
    insert_before_density + "def psychrometric_density_field(\n",
    "physical psychrometric mask helper",
)
replace_once(
    DIST,
    "    grid_shape: tuple[int, int] = (140, 120),\n) -> PsychrometricDensityField:",
    "    grid_shape: tuple[int, int] = (140, 120),\n    pressure_pa: float = 101325.0,\n) -> PsychrometricDensityField:",
    "density pressure parameter",
)
replace_once(
    DIST,
    "    smooth_mass = _smooth_2d(raw_mass, float(sigma_x), float(sigma_y))\n\n    flat = smooth_mass.ravel()",
    "    smooth_mass = _smooth_2d(raw_mass, float(sigma_x), float(sigma_y))\n\n    # Remove the purely numerical Gaussian tail outside the physical\n    # psychrometric domain (RH > 100% or negative humidity ratio). The removed\n    # mass is smoothing leakage, not observed duration, so renormalize the\n    # remaining physical field back to the represented source duration.\n    physical_mask = _physical_psychrometric_mask(\n        x_centers,\n        y_centers,\n        chart_type=chart_type,\n        pressure_pa=float(pressure_pa),\n    )\n    smooth_mass = np.where(physical_mask, smooth_mass, 0.0)\n    physical_mass = float(smooth_mass.sum())\n    if physical_mass > 0.0:\n        smooth_mass *= total_hours / physical_mass\n\n    flat = smooth_mass.ravel()",
    "mask smoothed density to physical RH domain",
)
replace_once(
    DIST,
    "    show_core: bool = True,\n    core_coverage: float = 0.50,\n    legendgroup: str | None = None,\n) -> PsychrometricDensityField:",
    "    show_core: bool = False,\n    core_coverage: float = 0.50,\n    additional_coverages: list[float] | tuple[float, ...] | None = None,\n    pressure_pa: float = 101325.0,\n    legendgroup: str | None = None,\n) -> PsychrometricDensityField:",
    "zone arbitrary contour parameters",
)
replace_once(
    DIST,
    "        axis_ranges=axis_ranges,\n    )\n    if field.total_hours <= 0.0",
    "        axis_ranges=axis_ranges,\n        pressure_pa=float(pressure_pa),\n    )\n    if field.total_hours <= 0.0",
    "outer zone physical pressure",
)
old_core = '''    if show_core and 0.0 < float(core_coverage) < float(coverage):\n        core = psychrometric_density_field(\n            df,\n            chart_type=chart_type,\n            target_share=float(core_coverage),\n            axis_ranges=axis_ranges,\n        )\n        if core.threshold_hours > 0.0:\n            fig.add_trace(\n                go.Contour(\n                    x=core.x,\n                    y=core.y,\n                    z=core.mass_hours.T,\n                    autocontour=False,\n                    contours=dict(\n                        start=float(core.threshold_hours),\n                        end=float(core.threshold_hours),\n                        size=max(float(core.threshold_hours) * 0.02, 1e-12),\n                        coloring=\"lines\",\n                        showlabels=False,\n                    ),\n                    line=dict(color=rgba(color, 0.78), width=1.3, dash=\"dot\"),\n                    showscale=False,\n                    hoverinfo=\"skip\",\n                    connectgaps=False,\n                    name=f\"{label} {core_coverage * 100.0:.0f}% core\",\n                    legendgroup=group,\n                    showlegend=False,\n                )\n            )\n'''
new_core = '''    contour_levels: list[float] = []\n    if additional_coverages is not None:\n        contour_levels.extend(float(value) for value in additional_coverages)\n    elif show_core:\n        # Backward-compatible API only; current UI supplies explicit levels.\n        contour_levels.append(float(core_coverage))\n    contour_levels = sorted({value for value in contour_levels if 0.0 < value < float(coverage)})\n    dash_cycle = [\"dot\", \"dash\", \"dashdot\", \"longdash\"]\n    for level_index, contour_coverage in enumerate(contour_levels):\n        inner = psychrometric_density_field(\n            df,\n            chart_type=chart_type,\n            target_share=float(contour_coverage),\n            axis_ranges=axis_ranges,\n            pressure_pa=float(pressure_pa),\n        )\n        if inner.threshold_hours <= 0.0:\n            continue\n        fig.add_trace(\n            go.Contour(\n                x=inner.x,\n                y=inner.y,\n                z=inner.mass_hours.T,\n                autocontour=False,\n                contours=dict(\n                    start=float(inner.threshold_hours),\n                    end=float(inner.threshold_hours),\n                    size=max(float(inner.threshold_hours) * 0.02, 1e-12),\n                    coloring=\"lines\",\n                    showlabels=False,\n                ),\n                line=dict(\n                    color=rgba(color, 0.78),\n                    width=1.35,\n                    dash=dash_cycle[level_index % len(dash_cycle)],\n                ),\n                showscale=False,\n                hoverinfo=\"skip\",\n                connectgaps=False,\n                name=f\"{label} {contour_coverage * 100.0:.0f}% contour\",\n                legendgroup=group,\n                showlegend=False,\n            )\n        )\n'''
replace_once(DIST, old_core, new_core, "replace fixed 50% core with arbitrary contours")

# ---------------------------------------------------------------------------
# 2) Restore Points + Distribution grid + Climate contour in single climate.
# ---------------------------------------------------------------------------
replace_once(
    CHARTS,
    "    show_core_zone: bool = True,\n    year_mode: str = \"All years combined\",\n    selected_years: list[int] | None = None,\n) -> go.Figure:",
    "    show_core_zone: bool = False,\n    additional_contour_coverages: list[float] | None = None,\n    year_mode: str = \"All years combined\",\n    selected_years: list[int] | None = None,\n) -> go.Figure:",
    "chart arbitrary contour parameter",
)
replace_once(
    CHARTS,
    '''    if data_mode in {"Hourly values", "Source interval values", "Monthly points", "All observations", "Points"}:\n        representation = "Points"\n    else:\n        representation = "Climate zone"\n''',
    '''    if data_mode in {"Hourly values", "Source interval values", "Monthly points", "All observations", "Points"}:\n        representation = "Points"\n    elif data_mode in {"Distribution grid", "Distributive grid"}:\n        representation = "Distribution grid"\n    else:\n        representation = "Climate contour"\n''',
    "chart representation routing",
)
replace_once(
    CHARTS,
    "    if representation == \"Climate zone\":\n",
    "    if representation == \"Climate contour\":\n",
    "chart contour branch name",
)
replace_once(
    CHARTS,
    "                show_core=bool(show_core_zone),\n                core_coverage=0.50,\n                legendgroup=f\"psych-zone-{label}\",\n            )\n    else:\n        base_cols = _unique_existing_columns",
    "                show_core=bool(show_core_zone),\n                core_coverage=0.50,\n                additional_coverages=additional_contour_coverages,\n                pressure_pa=float(pressure_pa),\n                legendgroup=f\"psych-zone-{label}\",\n            )\n    elif representation == \"Distribution grid\":\n        metric_col = None if color_mode == \"Frequency\" else color_metric_column\n        _add_psychrometric_tile_occupancy(\n            fig,\n            plot_df,\n            chart_type,\n            pressure_pa,\n            t_range,\n            d_range,\n            h_range,\n            metric_col,\n            color_metric_label,\n        )\n    else:\n        base_cols = _unique_existing_columns",
    "restore single climate distribution grid branch",
)
replace_once(
    CHARTS,
    '''    elif representation == "Climate zone":\n        legend_title = "Climate data"\n    else:\n        legend_title = "Month" if color_mode == "Month" else "Climate data"\n''',
    '''    elif representation == "Climate contour":\n        legend_title = "Climate data"\n    elif representation == "Distribution grid":\n        legend_title = "Distribution"\n    else:\n        legend_title = "Month" if color_mode == "Month" else "Climate data"\n''',
    "chart legend titles",
)

# ---------------------------------------------------------------------------
# 3) UI: restore old grid as a peer representation, make contours configurable.
# ---------------------------------------------------------------------------
old_single_controls = '''        representation = st.radio(\n            "Representation",\n            ["Climate zone", "Points"],\n            horizontal=True,\n            help="Climate zone is the recommended view. Points are retained for inspecting individual observations and outliers.",\n        )\n\n        zone_coverage = 0.90\n        zone_interior_style = "Density gradient"\n        show_core_zone = True\n        if representation == "Climate zone":\n            z1, z2, z3 = st.columns([1, 1.4, 1])\n            coverage_pct = z1.slider("Zone coverage [%]", 50, 99, 90, 1, key="psych_zone_coverage")\n            zone_coverage = float(coverage_pct) / 100.0\n            zone_interior_style = z2.selectbox(\n                "Zone interior",\n                ["Density gradient", "Sparse points", "Solid fill", "Contour only"],\n                index=0,\n                key="psych_zone_interior",\n            )\n            show_core_zone = z3.checkbox("Show 50% core contour", value=True, key="psych_zone_core")\n            st.caption(\n                "The zone boundary is a smooth two-dimensional iso-density contour containing the selected share of represented climate duration. "\n                "The density gradient shows where states occur most frequently inside that contour; no selected-cell mosaic is used."\n            )\n'''
new_single_controls = '''        representation = st.radio(\n            "Representation",\n            ["Points", "Distribution grid", "Climate contour"],\n            index=0,\n            horizontal=True,\n            help=(\n                "Points shows individual observations. Distribution grid restores the original 1 °C × 5 %RH frequency/metric cells. "\n                "Climate contour adds a smooth duration-density zone without replacing either original representation."\n            ),\n        )\n\n        zone_coverage = 0.90\n        zone_interior_style = "Density gradient"\n        show_core_zone = False\n        additional_contour_coverages: list[float] = []\n        if representation == "Climate contour":\n            z1, z2 = st.columns([1, 1.4])\n            coverage_pct = z1.slider("Outer contour coverage [%]", 50, 99, 90, 1, key="psych_zone_coverage")\n            zone_coverage = float(coverage_pct) / 100.0\n            zone_interior_style = z2.selectbox(\n                "Zone interior",\n                ["Density gradient", "Sparse points", "Solid fill", "Contour only"],\n                index=0,\n                key="psych_zone_interior",\n            )\n            contour_options = [value for value in range(10, 100, 5) if value < coverage_pct]\n            contour_defaults = [50] if 50 in contour_options else []\n            selected_levels = st.multiselect(\n                "Additional contour levels [%]",\n                contour_options,\n                default=contour_defaults,\n                key="psych_zone_additional_contours",\n                help="Choose any number of nested duration contours below the outer coverage, for example 50%, 70%, or both.",\n            )\n            additional_contour_coverages = [float(value) / 100.0 for value in selected_levels]\n            st.caption(\n                "Contours are calculated from a smooth two-dimensional duration density. Density outside the physical 0...100% RH domain is forced to zero before contour thresholds are calculated. "\n                "The density gradient shows where states occur most frequently inside the outer contour."\n            )\n        elif representation == "Distribution grid":\n            st.caption(\n                "Original distribution-grid representation restored: 1 °C × 5 %RH cells on the real psychrometric geometry. "\n                "Zero/low-frequency cells remain pale and the most frequent cells are saturated blue."\n            )\n'''
replace_once(APP, old_single_controls, new_single_controls, "single psychrometric representation controls")

old_year_and_color = '''            if chronological_multiyear:\n                years = available_years(df)\n                year_mode = st.selectbox(\n                    "Year display",\n                    ["All years combined", "Single year", "Compare selected years"],\n                    index=0,\n                    key="psych_year_mode",\n                )\n                if year_mode == "Single year":\n                    selected_years = [int(st.selectbox("Year", years, index=len(years) - 1, key="psych_single_year"))]\n                elif year_mode == "Compare selected years":\n                    default_years = years if len(years) <= 5 else years[-5:]\n                    selected_years = [int(value) for value in st.multiselect("Years", years, default=default_years, key="psych_compare_years")]\n                    if not selected_years:\n                        st.info("Select at least one real source year for the psychrometric comparison.")\n                        return\n                    st.caption("Each selected year is drawn independently on the same fixed psychrometric axes.")\n\n            color_mode = "Month"\n            color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]\n            if representation == "Points" and year_mode != "Compare selected years":\n                metric_options = [name for name in PSYCHROMETRIC_COLOR_METRICS if name != "Frequency"]\n                color_mode = st.selectbox("Colour mapped metric", metric_options, index=metric_options.index("Month"))\n                color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]\n            elif representation == "Points" and year_mode == "Compare selected years":\n                st.caption("Point colours identify real source years; metric colouring is disabled while years are being compared.")\n'''
new_year_and_color = '''            if chronological_multiyear:\n                years = available_years(df)\n                year_choices = ["All years combined", "Single year"]\n                if representation != "Distribution grid":\n                    year_choices.append("Compare selected years")\n                year_mode = st.selectbox(\n                    "Year display",\n                    year_choices,\n                    index=0,\n                    key="psych_year_mode",\n                )\n                if year_mode == "Single year":\n                    selected_years = [int(st.selectbox("Year", years, index=len(years) - 1, key="psych_single_year"))]\n                elif year_mode == "Compare selected years":\n                    default_years = years if len(years) <= 5 else years[-5:]\n                    selected_years = [int(value) for value in st.multiselect("Years", years, default=default_years, key="psych_compare_years")]\n                    if not selected_years:\n                        st.info("Select at least one real source year for the psychrometric comparison.")\n                        return\n                    st.caption("Each selected year is drawn independently on the same fixed psychrometric axes.")\n\n            color_mode = "Month"\n            color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]\n            if representation == "Points" and year_mode != "Compare selected years":\n                metric_options = [name for name in PSYCHROMETRIC_COLOR_METRICS if name != "Frequency"]\n                color_mode = st.selectbox("Colour mapped metric", metric_options, index=metric_options.index("Month"))\n                color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]\n            elif representation == "Points" and year_mode == "Compare selected years":\n                st.caption("Point colours identify real source years; metric colouring is disabled while years are being compared.")\n            elif representation == "Distribution grid":\n                metric_options = [name for name in PSYCHROMETRIC_COLOR_METRICS if name != "Month"]\n                color_mode = st.selectbox("Colour mapped metric", metric_options, index=metric_options.index("Frequency"))\n                color_metric_column, color_metric_label = PSYCHROMETRIC_COLOR_METRICS[color_mode]\n'''
replace_once(APP, old_year_and_color, new_year_and_color, "single year and grid metric controls")
replace_once(
    APP,
    "            show_core_zone=show_core_zone,\n            year_mode=year_mode,",
    "            show_core_zone=show_core_zone,\n            additional_contour_coverages=additional_contour_coverages,\n            year_mode=year_mode,",
    "single chart contour levels call",
)

# ---------------------------------------------------------------------------
# 4) Compare Climates: keep contour primary, but restore grid and points peers.
# ---------------------------------------------------------------------------
compare_block = '''    elif chart == "Psychrometric climate zones":\n        chart_type = st.radio("Psychrometric axes", ["T-d", "i-d"], horizontal=True, key="compare_psych_axes")\n        representation = st.radio(\n            "Representation",\n            ["Climate contour", "Distribution grid", "Points"],\n            index=0,\n            horizontal=True,\n            key="compare_psych_representation",\n            help=(\n                "Climate contour is the primary comparison view. Distribution grid and Points remain available as secondary diagnostic representations; the contour does not replace them."\n            ),\n        )\n        zone_coverage = 0.90\n        zone_interior_style = "Density gradient"\n        additional_contour_coverages: list[float] = []\n        if representation == "Climate contour":\n            c1, c2 = st.columns([1, 1.4])\n            coverage_pct = int(c1.slider("Outer contour coverage [%]", 50, 99, 90, 1, key="compare_psych_coverage"))\n            zone_coverage = float(coverage_pct) / 100.0\n            zone_interior_style = c2.selectbox(\n                "Zone interior",\n                ["Density gradient", "Sparse points", "Solid fill", "Contour only"],\n                index=0,\n                key="compare_psych_interior",\n            )\n            contour_options = [value for value in range(10, 100, 5) if value < coverage_pct]\n            contour_defaults = [50] if 50 in contour_options else []\n            selected_levels = st.multiselect(\n                "Additional contour levels [%]",\n                contour_options,\n                default=contour_defaults,\n                key="compare_psych_additional_contours",\n                help="Multiple nested contours can be displayed simultaneously, for example 50% and 70% inside a 90% outer zone.",\n            )\n            additional_contour_coverages = [float(value) / 100.0 for value in selected_levels]\n            st.caption(\n                "Each climate zone is clipped to its own physical 0...100% RH domain before density contours are calculated. "\n                "The common reference grid below is only a visual construction aid."\n            )\n        elif representation == "Distribution grid":\n            st.caption(\n                "Distribution-grid comparison uses the original 1 °C × 5 %RH psychrometric cells. Climate hue identifies the dataset; cell opacity follows represented hours on one shared scale."\n            )\n\n        reference = next((climate for climate in climates if climate.display_name == reference_name), climates[0])\n        pressure_values = pd.to_numeric(reference.data.get("atmospheric_station_pressure_pa"), errors="coerce").dropna()\n        if not pressure_values.empty:\n            reference_climate_pressure = float(pressure_values.median())\n        else:\n            reference_climate_pressure = pressure_from_altitude_m(float(reference.epw.location.elevation_m or 0.0))\n        grid_mode = st.selectbox(\n            "Reference psychrometric grid pressure",\n            [f"Reference climate — {reference_name}", "Standard atmosphere — 101325 Pa", "Custom pressure"],\n            index=0,\n            key="compare_psych_grid_pressure_mode",\n            help=(\n                "This pressure controls only the grey RH construction grid. Every climate keeps its own station-pressure psychrometric state and physical saturation limit."\n            ),\n        )\n        if grid_mode == "Standard atmosphere — 101325 Pa":\n            reference_grid_pressure = DEFAULT_PRESSURE_PA\n        elif grid_mode.startswith("Reference climate"):\n            reference_grid_pressure = reference_climate_pressure\n        else:\n            reference_grid_pressure = st.number_input(\n                "Reference grid pressure [Pa]",\n                min_value=30000.0,\n                max_value=120000.0,\n                value=float(round(reference_climate_pressure / 100.0) * 100.0),\n                step=100.0,\n                key="compare_psych_grid_pressure_custom",\n            )\n        st.caption(\n            f"Shared axes are fixed across representations. Reference grid: {float(reference_grid_pressure):,.0f} Pa. "\n            "Changing this reference does not move climate observations, distribution cells or contours."\n        )\n\n        fig = psychrometric_comparison_chart(\n            climates,\n            chart_type=chart_type,\n            mode=display_mode,\n            pressure_pa=reference_climate_pressure,\n            data_display=representation,\n            zone_coverage=zone_coverage,\n            zone_interior_style=zone_interior_style,\n            show_core_zone=False,\n            additional_contour_coverages=additional_contour_coverages,\n            reference_pressure_pa=float(reference_grid_pressure),\n        )\n        render_plot(fig, comparison_interpretation(climate_summary_metrics(climates), reference_name))\n'''
replace_block(
    APP,
    '    elif chart == "Psychrometric climate zones":\n',
    '    elif chart == "Outdoor-air enthalpy duration curve":\n',
    compare_block,
    "compare psychrometric UI block",
)

# ---------------------------------------------------------------------------
# 5) Comparison renderer: contour + shared distribution grid + points.
# ---------------------------------------------------------------------------
replace_once(
    COMPARE,
    "import plotly.graph_objects as go\nfrom plotly.subplots import make_subplots",
    "import plotly.graph_objects as go\nfrom plotly.subplots import make_subplots\nimport psychrolib",
    "comparison PsychroLib import",
)
replace_once(
    COMPARE,
    "from .aggregations import SEASON_ORDER, aggregate_summary, aggregate_sum, calendar_matrix, monthly_hour_matrix",
    "from .aggregations import SEASON_ORDER, aggregate_summary, aggregate_sum, calendar_matrix, monthly_hour_matrix, native_interval_hours",
    "comparison native interval import",
)
replace_once(
    COMPARE,
    "from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves",
    "from .psychrometrics import DEFAULT_PRESSURE_PA, pressure_from_altitude_m, psychrometric_rh_curves",
    "comparison pressure fallback import",
)
replace_once(
    COMPARE,
    "PLOT_TEMPLATE = \"plotly_white\"",
    "psychrolib.SetUnitSystem(psychrolib.SI)\n\nPLOT_TEMPLATE = \"plotly_white\"",
    "comparison psychrolib SI init",
)

helpers = '''def _comparison_climate_pressure_pa(climate: ClimateDataset, fallback_pressure_pa: float) -> float:\n    if "atmospheric_station_pressure_pa" in climate.data.columns:\n        values = pd.to_numeric(climate.data["atmospheric_station_pressure_pa"], errors="coerce")\n        values = values[(values >= 30000.0) & (values <= 120000.0)].dropna()\n        if not values.empty:\n            return float(values.median())\n    elevation = float(climate.epw.location.elevation_m or 0.0)\n    try:\n        return float(pressure_from_altitude_m(elevation))\n    except Exception:\n        return float(fallback_pressure_pa)\n\n\ndef _comparison_distribution_tiles(climate: ClimateDataset) -> pd.DataFrame:\n    data = climate.data[["dry_bulb_temperature_c", "relative_humidity_pct"]].replace([np.inf, -np.inf], np.nan).dropna().copy()\n    if data.empty:\n        return pd.DataFrame(columns=["temperature_bin_c", "rh_bin_pct", "hours"])\n    data["temperature_bin_c"] = np.floor(data["dry_bulb_temperature_c"]).astype(int)\n    data["rh_bin_pct"] = (np.floor(data["relative_humidity_pct"] / 5.0) * 5.0).clip(0, 95).astype(int)\n    tiles = data.groupby(["temperature_bin_c", "rh_bin_pct"], observed=True).size().reset_index(name="records")\n    tiles["hours"] = tiles["records"].astype(float) * float(native_interval_hours(climate.data))\n    return tiles\n\n\ndef _add_comparison_distribution_grid(\n    fig: go.Figure,\n    climates: list[ClimateDataset],\n    *,\n    chart_type: str,\n    colors: dict[str, str],\n    fallback_pressure_pa: float,\n) -> None:\n    tables = [(climate, _comparison_distribution_tiles(climate)) for climate in climates]\n    global_max = max((float(table["hours"].max()) for _climate, table in tables if not table.empty), default=1.0)\n    global_max = max(global_max, 1e-12)\n    for climate, tiles in tables:\n        if tiles.empty:\n            continue\n        color = colors[climate.display_name]\n        pressure_pa = _comparison_climate_pressure_pa(climate, fallback_pressure_pa)\n        group = f"grid-{climate.climate_id}"\n        for _, row in tiles.iterrows():\n            t0 = float(row["temperature_bin_c"])\n            t1 = t0 + 1.0\n            rh0 = float(row["rh_bin_pct"])\n            rh1 = min(100.0, rh0 + 5.0)\n            corners: list[tuple[float, float]] = []\n            for t_c, rh_pct in [(t0, rh0), (t1, rh0), (t1, rh1), (t0, rh1), (t0, rh0)]:\n                try:\n                    w = psychrolib.GetHumRatioFromRelHum(float(t_c), float(rh_pct) / 100.0, float(pressure_pa))\n                    d = float(w) * 1000.0\n                    h = psychrolib.GetMoistAirEnthalpy(float(t_c), float(w)) / 1000.0\n                except Exception:\n                    continue\n                corners.append((d, h) if chart_type == "i-d" else (float(t_c), d))\n            if len(corners) != 5:\n                continue\n            intensity = float(row["hours"]) / global_max\n            alpha = 0.05 + 0.66 * max(0.0, min(1.0, intensity))\n            fig.add_trace(\n                go.Scatter(\n                    x=[point[0] for point in corners],\n                    y=[point[1] for point in corners],\n                    mode="lines",\n                    line=dict(width=0.25, color=rgba(color, 0.25)),\n                    fill="toself",\n                    fillcolor=rgba(color, alpha),\n                    name=climate.display_name,\n                    legendgroup=group,\n                    showlegend=False,\n                    hovertemplate=(\n                        f"{climate.display_name}<br>Temperature bin: {t0:.0f}...{t1:.0f} °C<br>"\n                        f"RH bin: {rh0:.0f}...{rh1:.0f} %<br>Hours: {float(row['hours']):.2f}<extra></extra>"\n                    ),\n                )\n            )\n        fig.add_trace(\n            go.Scatter(\n                x=[None],\n                y=[None],\n                mode="lines",\n                line=dict(color=color, width=5.0),\n                name=climate.display_name,\n                legendgroup=group,\n                showlegend=True,\n                hoverinfo="skip",\n            )\n        )\n\n\n'''
replace_once(
    COMPARE,
    "def psychrometric_comparison_chart(\n",
    helpers + "def psychrometric_comparison_chart(\n",
    "comparison grid helpers",
)
replace_once(
    COMPARE,
    "    show_core_zone: bool = True,\n    reference_pressure_pa: float | None = None,\n) -> go.Figure:",
    "    show_core_zone: bool = False,\n    additional_contour_coverages: list[float] | None = None,\n    reference_pressure_pa: float | None = None,\n) -> go.Figure:",
    "comparison arbitrary contour signature",
)
replace_once(
    COMPARE,
    '''    if data_display in {"All observations", "Points"}:\n        representation = "Points"\n    elif data_display in {"Climate zones", "Middle 90% envelopes"}:\n        representation = "Climate zones"\n    else:\n        raise ValueError(f"Unsupported psychrometric comparison display: {data_display}")\n''',
    '''    if data_display in {"All observations", "Points"}:\n        representation = "Points"\n    elif data_display in {"Distribution grid", "Distributive grid"}:\n        representation = "Distribution grid"\n    elif data_display in {"Climate contour", "Climate zones", "Middle 90% envelopes"}:\n        representation = "Climate contour"\n    else:\n        raise ValueError(f"Unsupported psychrometric comparison display: {data_display}")\n''',
    "comparison representation routing",
)
old_compare_loop = '''    for climate in climates:\n        color = colors[climate.display_name]\n        if representation == "Climate zones":\n            add_climate_zone_traces(\n                fig,\n                climate.data,\n                chart_type=chart_type,\n                label=climate.display_name,\n                color=color,\n                coverage=float(zone_coverage),\n                interior_style=zone_interior_style,\n                axis_ranges=shared_ranges,\n                show_core=bool(show_core_zone),\n                core_coverage=0.50,\n                legendgroup=f"climate-{climate.climate_id}",\n            )\n        else:\n            data = climate.data[[x_col, y_col]].replace([np.inf, -np.inf], np.nan).dropna()\n            fig.add_trace(\n                go.Scattergl(\n                    x=data[x_col],\n                    y=data[y_col],\n                    mode="markers",\n                    name=climate.display_name,\n                    marker=dict(size=3.5, opacity=0.22, color=color),\n                    hovertemplate=f"{climate.display_name}<br>x: %{{x:.2f}}<br>y: %{{y:.2f}}<extra></extra>",\n                )\n            )\n\n    title_mode = "climate zones" if representation == "Climate zones" else "observations"\n'''
new_compare_loop = '''    if representation == "Distribution grid":\n        _add_comparison_distribution_grid(\n            fig,\n            climates,\n            chart_type=chart_type,\n            colors=colors,\n            fallback_pressure_pa=float(pressure_pa),\n        )\n    else:\n        for climate in climates:\n            color = colors[climate.display_name]\n            if representation == "Climate contour":\n                climate_pressure = _comparison_climate_pressure_pa(climate, float(pressure_pa))\n                add_climate_zone_traces(\n                    fig,\n                    climate.data,\n                    chart_type=chart_type,\n                    label=climate.display_name,\n                    color=color,\n                    coverage=float(zone_coverage),\n                    interior_style=zone_interior_style,\n                    axis_ranges=shared_ranges,\n                    show_core=bool(show_core_zone),\n                    core_coverage=0.50,\n                    additional_coverages=additional_contour_coverages,\n                    pressure_pa=float(climate_pressure),\n                    legendgroup=f"climate-{climate.climate_id}",\n                )\n            else:\n                data = climate.data[[x_col, y_col]].replace([np.inf, -np.inf], np.nan).dropna()\n                fig.add_trace(\n                    go.Scattergl(\n                        x=data[x_col],\n                        y=data[y_col],\n                        mode="markers",\n                        name=climate.display_name,\n                        marker=dict(size=3.5, opacity=0.22, color=color),\n                        hovertemplate=f"{climate.display_name}<br>x: %{{x:.2f}}<br>y: %{{y:.2f}}<extra></extra>",\n                    )\n                )\n\n    title_mode = {\n        "Climate contour": "climate contours",\n        "Distribution grid": "distribution grid",\n        "Points": "observations",\n    }[representation]\n'''
replace_once(COMPARE, old_compare_loop, new_compare_loop, "comparison rendering branches")

# ---------------------------------------------------------------------------
# 6) Hot-reload guard: new caller/API must not repeat the 0.7.4.2 mismatch.
# ---------------------------------------------------------------------------
replace_once(
    GUARD,
    '        "show_core_zone",\n        "year_mode",',
    '        "show_core_zone",\n        "additional_contour_coverages",\n        "year_mode",',
    "guard chart extra contour parameter",
)
replace_once(
    GUARD,
    "_REQUIRED_CHART_PARAMETERS = frozenset(\n",
    "_REQUIRED_COMPARISON_PARAMETERS = frozenset({\"additional_contour_coverages\"})\n\n_REQUIRED_CHART_PARAMETERS = frozenset(\n",
    "guard comparison required parameters constant",
)
# Inject comparison signature verification before returning from the guard.
old_return = '''    if missing_parameters:\n        raise RuntimeError(\n            "Psychrometric chart runtime API is stale after reload; missing parameters: "\n            + ", ".join(sorted(missing_parameters))\n        )\n\n    return distribution, charts\n'''
new_return = '''    if missing_parameters:\n        raise RuntimeError(\n            "Psychrometric chart runtime API is stale after reload; missing parameters: "\n            + ", ".join(sorted(missing_parameters))\n        )\n\n    comparison = importlib.import_module("epw_climate_analyzer.comparison")\n    compare_fn = getattr(comparison, "psychrometric_comparison_chart", None)\n    try:\n        compare_parameters = inspect.signature(compare_fn).parameters if compare_fn is not None else {}\n    except (TypeError, ValueError):\n        compare_parameters = {}\n    missing_compare = set(_REQUIRED_COMPARISON_PARAMETERS).difference(compare_parameters)\n    if missing_compare:\n        comparison = importlib.reload(comparison)\n        compare_fn = getattr(comparison, "psychrometric_comparison_chart", None)\n        try:\n            compare_parameters = inspect.signature(compare_fn).parameters if compare_fn is not None else {}\n        except (TypeError, ValueError):\n            compare_parameters = {}\n        missing_compare = set(_REQUIRED_COMPARISON_PARAMETERS).difference(compare_parameters)\n    if missing_compare:\n        raise RuntimeError(\n            "Psychrometric comparison runtime API is stale after reload; missing parameters: "\n            + ", ".join(sorted(missing_compare))\n        )\n\n    return distribution, charts\n'''
replace_once(GUARD, old_return, new_return, "guard comparison module reload")

# ---------------------------------------------------------------------------
# 7) Focused regressions.
# ---------------------------------------------------------------------------
TEST.write_text(r'''from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import psychrolib

from epw_climate_analyzer.charts import psychrometric_chart
from epw_climate_analyzer.psychrometric_distribution import add_climate_zone_traces, psychrometric_density_field
from epw_climate_analyzer.psychrometrics import add_psychrometric_properties

psychrolib.SetUnitSystem(psychrolib.SI)
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def sample_frame() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=24 * 40, freq="h")
    phase = np.linspace(0.0, 8.0 * np.pi, len(index))
    t = 16.0 + 12.0 * np.sin(phase)
    rh = np.clip(68.0 + 26.0 * np.cos(phase * 0.73), 10.0, 99.0)
    pressure = np.full(len(index), 94000.0)
    base = pd.DataFrame(
        {
            "dry_bulb_temperature_c": t,
            "relative_humidity_pct": rh,
            "atmospheric_station_pressure_pa": pressure,
            "month_index": index.month,
            "month_name": index.strftime("%b"),
            "hour_of_day": index.hour,
        },
        index=index,
    )
    base.attrs["native_interval_minutes"] = 60.0
    return add_psychrometric_properties(base, fallback_pressure_pa=94000.0)


class PsychrometricRepresentation0743Tests(unittest.TestCase):
    def test_distribution_grid_is_restored_as_peer_representation(self) -> None:
        frame = sample_frame()
        fig = psychrometric_chart(
            frame,
            data_mode="Distribution grid",
            pressure_pa=94000.0,
            color_mode="Frequency",
            color_metric_column=None,
            color_metric_label="Frequency [h]",
        )
        filled = [trace for trace in fig.data if getattr(trace, "fill", None) == "toself"]
        self.assertGreater(len(filled), 5)
        self.assertTrue(any(getattr(getattr(trace, "marker", None), "showscale", False) for trace in fig.data))

    def test_smoothed_density_is_zero_above_saturation_curve(self) -> None:
        frame = sample_frame()
        field = psychrometric_density_field(frame, chart_type="T-d", target_share=0.90, pressure_pa=94000.0)
        for ix, t_c in enumerate(field.x):
            try:
                saturation = psychrolib.GetSatHumRatio(float(t_c), 94000.0) * 1000.0
            except Exception:
                continue
            impossible = field.y > saturation + max(1e-7, abs(saturation) * 1e-7)
            if impossible.any():
                self.assertTrue(np.allclose(field.mass_hours[ix, impossible], 0.0))

    def test_multiple_nested_contours_are_user_configurable(self) -> None:
        frame = sample_frame()
        fig = go.Figure()
        add_climate_zone_traces(
            fig,
            frame,
            chart_type="T-d",
            label="Test climate",
            color="#2563eb",
            coverage=0.90,
            interior_style="Contour only",
            additional_coverages=[0.50, 0.70],
            pressure_pa=94000.0,
        )
        names = [str(getattr(trace, "name", "")) for trace in fig.data]
        self.assertTrue(any("50% contour" in name for name in names))
        self.assertTrue(any("70% contour" in name for name in names))
        self.assertTrue(any("90% zone" in name for name in names))

    def test_app_exposes_points_grid_and_contour_without_fixed_core_checkbox(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn('["Points", "Distribution grid", "Climate contour"]', source)
        self.assertIn('["Climate contour", "Distribution grid", "Points"]', source)
        self.assertIn('"Additional contour levels [%]"', source)
        self.assertNotIn('"Show 50% core contour"', source)
        self.assertIn('"Distribution grid"', source)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

print("0.7.4.3 psychrometric representation restoration applied")
