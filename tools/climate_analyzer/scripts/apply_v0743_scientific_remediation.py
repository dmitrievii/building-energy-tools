from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
DIST = ROOT / "epw_climate_analyzer" / "psychrometric_distribution.py"
COMPARE = ROOT / "epw_climate_analyzer" / "comparison.py"
TEST_INTEGRATION = ROOT / "tests" / "test_psychrometric_integration_0_7_4_1.py"
TEST_REDESIGN = ROOT / "tests" / "test_psychrometric_redesign_0_7_4.py"
TEST_REFERENCE = ROOT / "tests" / "test_psychrometric_reference_pressure_0_7_4_3.py"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# A) Make the physical saturation boundary a rendering boundary, not merely a
# zero-density numerical cell. Plotly must never interpolate an iso-line into
# RH > 100 % between a positive physical cell and a zero impossible cell.
# ---------------------------------------------------------------------------
replace_once(
    DIST,
    "    group = legendgroup or label\n    mask = field.mask\n",
    "    group = legendgroup or label\n    physical_mask = _physical_psychrometric_mask(\n        field.x, field.y, chart_type=chart_type, pressure_pa=float(pressure_pa)\n    )\n    mask = field.mask & physical_mask\n",
    "outer render physical mask",
)
replace_once(
    DIST,
    "            z=field.mass_hours.T,\n            autocontour=False,\n",
    "            z=np.where(physical_mask, field.mass_hours, np.nan).T,\n            autocontour=False,\n",
    "outer contour NaN boundary",
)
replace_once(
    DIST,
    "        if inner.threshold_hours <= 0.0:\n            continue\n        fig.add_trace(\n",
    "        if inner.threshold_hours <= 0.0:\n            continue\n        inner_physical_mask = _physical_psychrometric_mask(\n            inner.x, inner.y, chart_type=chart_type, pressure_pa=float(pressure_pa)\n        )\n        fig.add_trace(\n",
    "inner render physical mask",
)
replace_once(
    DIST,
    "                z=inner.mass_hours.T,\n                autocontour=False,\n",
    "                z=np.where(inner_physical_mask, inner.mass_hours, np.nan).T,\n                autocontour=False,\n",
    "inner contour NaN boundary",
)


# ---------------------------------------------------------------------------
# B) Compare Climates must have one psychrometric coordinate system. Preserve
# source station-pressure data, but project T/RH states to one selected display
# pressure before drawing points, density contours, grid cells and RH curves.
# ---------------------------------------------------------------------------
projection_helper = '''def _project_comparison_frame_to_pressure(\n    data: pd.DataFrame,\n    reference_pressure_pa: float,\n) -> pd.DataFrame:\n    \"\"\"Project psychrometric display coordinates to one common pressure.\n\n    Dry-bulb temperature and relative humidity are pressure-independent source\n    state descriptors for this purpose. Humidity ratio and enthalpy are rebuilt\n    at ``reference_pressure_pa`` only in the returned display frame. The input\n    climate data are never mutated.\n    \"\"\"\n    target_pressure = float(reference_pressure_pa)\n    if not 30000.0 <= target_pressure <= 120000.0:\n        raise ValueError(\"reference_pressure_pa must be between 30000 and 120000 Pa\")\n\n    frame = data.copy()\n    temperature = pd.to_numeric(\n        frame.get(\"dry_bulb_temperature_c\", pd.Series(np.nan, index=frame.index)),\n        errors=\"coerce\",\n    )\n    rh_pct = pd.to_numeric(\n        frame.get(\"relative_humidity_pct\", pd.Series(np.nan, index=frame.index)),\n        errors=\"coerce\",\n    )\n\n    # Defensive fallback for canonical frames that carry d but no RH.\n    if not rh_pct.notna().any() and \"humidity_ratio_g_kg\" in frame.columns:\n        source_w = pd.to_numeric(frame[\"humidity_ratio_g_kg\"], errors=\"coerce\") / 1000.0\n        source_pressure = pd.to_numeric(\n            frame.get(\"atmospheric_station_pressure_pa\", pd.Series(target_pressure, index=frame.index)),\n            errors=\"coerce\",\n        ).fillna(target_pressure)\n        recovered = np.full(len(frame), np.nan, dtype=float)\n        for position, (t_c, w, p_pa) in enumerate(\n            zip(temperature.to_numpy(dtype=float), source_w.to_numpy(dtype=float), source_pressure.to_numpy(dtype=float), strict=True)\n        ):\n            if not (np.isfinite(t_c) and np.isfinite(w) and np.isfinite(p_pa) and w >= 0.0):\n                continue\n            try:\n                recovered[position] = 100.0 * psychrolib.GetRelHumFromHumRatio(float(t_c), float(w), float(p_pa))\n            except Exception:\n                continue\n        rh_pct = pd.Series(recovered, index=frame.index, dtype=float)\n\n    rh_fraction = (rh_pct / 100.0).clip(lower=0.0, upper=1.0)\n    target_w = np.full(len(frame), np.nan, dtype=float)\n    target_h = np.full(len(frame), np.nan, dtype=float)\n    for position, (t_c, rh) in enumerate(\n        zip(temperature.to_numpy(dtype=float), rh_fraction.to_numpy(dtype=float), strict=True)\n    ):\n        if not (np.isfinite(t_c) and np.isfinite(rh)):\n            continue\n        try:\n            w = psychrolib.GetHumRatioFromRelHum(float(t_c), float(rh), target_pressure)\n            target_w[position] = float(w)\n            target_h[position] = psychrolib.GetMoistAirEnthalpy(float(t_c), float(w)) / 1000.0\n        except Exception:\n            continue\n\n    frame[\"relative_humidity_pct\"] = rh_fraction.to_numpy(dtype=float) * 100.0\n    frame[\"humidity_ratio_g_kg\"] = target_w * 1000.0\n    frame[\"moist_air_enthalpy_kj_kg\"] = target_h\n    frame[\"atmospheric_station_pressure_pa\"] = target_pressure\n    frame.attrs.update(data.attrs)\n    frame.attrs[\"psychrometric_display_pressure_pa\"] = target_pressure\n    return frame\n\n\n'''
replace_once(
    COMPARE,
    "def _comparison_distribution_tiles(climate: ClimateDataset) -> pd.DataFrame:\n",
    projection_helper + "def _comparison_distribution_tiles(climate: ClimateDataset) -> pd.DataFrame:\n",
    "common-pressure projection helper",
)
replace_once(
    COMPARE,
    "    fallback_pressure_pa: float,\n) -> None:\n",
    "    reference_pressure_pa: float,\n) -> None:\n",
    "distribution-grid common pressure signature",
)
replace_once(
    COMPARE,
    "        pressure_pa = _comparison_climate_pressure_pa(climate, fallback_pressure_pa)\n",
    "        pressure_pa = float(reference_pressure_pa)\n",
    "distribution-grid common pressure use",
)
replace_once(
    COMPARE,
    '''    Climate zones are the primary representation. Their geometry comes only\n    from each climate's already calculated T-d / i-d states. ``reference_pressure_pa``\n    controls the common RH construction grid only and cannot move a climate zone.\n''',
    '''    All comparison representations use one explicitly selected display pressure.\n    Source station-pressure states are preserved in the climate datasets; T/RH is\n    projected to ``reference_pressure_pa`` only for common T-d / i-d rendering.\n''',
    "comparison docstring pressure semantics",
)
replace_once(
    COMPARE,
    '''    shared_ranges = psychrometric_axis_ranges([climate.data for climate in climates], chart_type)\n    grid_pressure = float(reference_pressure_pa if reference_pressure_pa is not None else pressure_pa)\n    temperature_values = pd.concat(\n        [pd.to_numeric(climate.data.get("dry_bulb_temperature_c"), errors="coerce") for climate in climates],\n        ignore_index=True,\n    ).dropna()\n''',
    '''    grid_pressure = float(reference_pressure_pa if reference_pressure_pa is not None else pressure_pa)\n    projected_frames = {\n        climate.climate_id: _project_comparison_frame_to_pressure(climate.data, grid_pressure)\n        for climate in climates\n    }\n    shared_ranges = psychrometric_axis_ranges(list(projected_frames.values()), chart_type)\n    temperature_values = pd.concat(\n        [pd.to_numeric(projected_frames[climate.climate_id].get("dry_bulb_temperature_c"), errors="coerce") for climate in climates],\n        ignore_index=True,\n    ).dropna()\n''',
    "comparison projected shared axes",
)
replace_once(
    COMPARE,
    '''    # One explicitly chosen reference grid keeps the psychrometric background\n    # readable. It is a visual construction reference only; climate state points\n    # and density zones retain the pressure used when each dataset was derived.\n''',
    '''    # One explicitly chosen pressure defines the complete display coordinate\n    # system: RH curves, points, distribution cells and density contours. Source\n    # station-pressure psychrometric states remain untouched in each dataset.\n''',
    "comparison reference-pressure comment",
)
replace_once(
    COMPARE,
    "            fallback_pressure_pa=float(pressure_pa),\n",
    "            reference_pressure_pa=grid_pressure,\n",
    "comparison distribution-grid common pressure call",
)
old_loop = '''        for climate in climates:\n            color = colors[climate.display_name]\n            if representation == "Climate contour":\n                climate_pressure = _comparison_climate_pressure_pa(climate, float(pressure_pa))\n                add_climate_zone_traces(\n                    fig,\n                    climate.data,\n                    chart_type=chart_type,\n                    label=climate.display_name,\n                    color=color,\n                    coverage=float(zone_coverage),\n                    interior_style=zone_interior_style,\n                    axis_ranges=shared_ranges,\n                    show_core=bool(show_core_zone),\n                    core_coverage=0.50,\n                    additional_coverages=additional_contour_coverages,\n                    pressure_pa=float(climate_pressure),\n                    legendgroup=f"climate-{climate.climate_id}",\n                )\n            else:\n                data = climate.data[[x_col, y_col]].replace([np.inf, -np.inf], np.nan).dropna()\n                fig.add_trace(\n                    go.Scattergl(\n                        x=data[x_col],\n                        y=data[y_col],\n                        mode="markers",\n                        name=climate.display_name,\n                        marker=dict(size=3.5, opacity=0.22, color=color),\n                        hovertemplate=f"{climate.display_name}<br>x: %{{x:.2f}}<br>y: %{{y:.2f}}<extra></extra>",\n                    )\n                )\n'''
new_loop = '''        for climate in climates:\n            color = colors[climate.display_name]\n            display_data = projected_frames[climate.climate_id]\n            if representation == "Climate contour":\n                add_climate_zone_traces(\n                    fig,\n                    display_data,\n                    chart_type=chart_type,\n                    label=climate.display_name,\n                    color=color,\n                    coverage=float(zone_coverage),\n                    interior_style=zone_interior_style,\n                    axis_ranges=shared_ranges,\n                    show_core=bool(show_core_zone),\n                    core_coverage=0.50,\n                    additional_coverages=additional_contour_coverages,\n                    pressure_pa=grid_pressure,\n                    legendgroup=f"climate-{climate.climate_id}",\n                )\n            else:\n                data = display_data[[x_col, y_col]].replace([np.inf, -np.inf], np.nan).dropna()\n                fig.add_trace(\n                    go.Scattergl(\n                        x=data[x_col],\n                        y=data[y_col],\n                        mode="markers",\n                        name=climate.display_name,\n                        marker=dict(size=3.5, opacity=0.22, color=color),\n                        hovertemplate=f"{climate.display_name}<br>x: %{{x:.2f}}<br>y: %{{y:.2f}}<extra></extra>",\n                    )\n                )\n'''
replace_once(COMPARE, old_loop, new_loop, "comparison contour/point projected data")


# ---------------------------------------------------------------------------
# C) UI semantics: 50% is no longer special, and reference pressure describes
# the full psychrometric display rather than only the grey construction grid.
# ---------------------------------------------------------------------------
for old, new, label in [
    (
        "            contour_options = [value for value in range(10, 100, 5) if value < coverage_pct]\n            contour_defaults = [50] if 50 in contour_options else []\n",
        "            contour_options = list(range(1, coverage_pct))\n            contour_defaults: list[int] = []\n",
        "single contour levels no fixed 50 default",
    ),
    (
        "            contour_options = [value for value in range(10, 100, 5) if value < coverage_pct]\n            contour_defaults = [50] if 50 in contour_options else []\n",
        "            contour_options = list(range(1, coverage_pct))\n            contour_defaults: list[int] = []\n",
        "comparison contour levels no fixed 50 default",
    ),
]:
    replace_once(APP, old, new, label)

replace_once(
    APP,
    '                "Each climate zone is clipped to its own physical 0...100% RH domain before density contours are calculated. "\n                "The common reference grid below is only a visual construction aid."\n',
    '                "Each contour is clipped to the physical 0...100% RH domain at the selected common psychrometric pressure. "\n                "Additional contour levels are optional and can be combined freely."\n',
    "comparison contour physical caption",
)
replace_once(
    APP,
    '            "Reference psychrometric grid pressure",\n',
    '            "Reference psychrometric pressure",\n',
    "comparison pressure label",
)
replace_once(
    APP,
    '                "This pressure controls only the grey RH construction grid. Every climate keeps its own station-pressure psychrometric state and physical saturation limit."\n',
    '                "This pressure defines one common psychrometric display coordinate system for RH curves, points, grid cells and contours. Source station-pressure data remain unchanged."\n',
    "comparison pressure help",
)
replace_once(
    APP,
    '                "Reference grid pressure [Pa]",\n',
    '                "Reference pressure [Pa]",\n',
    "comparison custom pressure label",
)
replace_once(
    APP,
    '            f"Shared axes are fixed across representations. Reference grid: {float(reference_grid_pressure):,.0f} Pa. "\n            "Changing this reference does not move climate observations, distribution cells or contours."\n',
    '            f"Shared axes are fixed across representations. Common psychrometric pressure: {float(reference_grid_pressure):,.0f} Pa. "\n            "Points, distribution-grid cells, contours and the RH background are all projected to this same display pressure; source data are not modified."\n',
    "comparison pressure caption",
)


# ---------------------------------------------------------------------------
# D) Reconcile regression contracts with the restored peer representations and
# physically correct common-pressure comparison semantics.
# ---------------------------------------------------------------------------
TEST_INTEGRATION.write_text('''from __future__ import annotations\n\nfrom pathlib import Path\nimport unittest\n\n\nROOT = Path(__file__).resolve().parents[1]\nREPO_ROOT = ROOT.parents[1]\nAPP = ROOT / "app.py"\nCHARTS = ROOT / "epw_climate_analyzer" / "charts.py"\nCOMPARISON = ROOT / "epw_climate_analyzer" / "comparison.py"\nDISTRIBUTION = ROOT / "epw_climate_analyzer" / "psychrometric_distribution.py"\n\n\nclass PsychrometricIntegration0741Tests(unittest.TestCase):\n    def test_release_tree_contains_no_old_temporary_transport(self) -> None:\n        for workflow in (\n            "v0741-full-test-diagnostic.yml",\n            "v0741-ci-diagnose.yml",\n            "v0741-psychrometric-patch.yml",\n            "v0741-pressure-fallback-patch.yml",\n        ):\n            self.assertFalse((REPO_ROOT / ".github" / "workflows" / workflow).exists(), workflow)\n        for script in (\n            "apply_v0741_psychrometric.py",\n            "apply_v0741_pressure_fallback.py",\n        ):\n            self.assertFalse((ROOT / "scripts" / script).exists(), script)\n\n    def test_runtime_has_no_old_selected_cell_envelope_api(self) -> None:\n        runtime = "\\n".join(path.read_text(encoding="utf-8") for path in (CHARTS, COMPARISON, DISTRIBUTION))\n        self.assertNotIn("PsychrometricOccupancyEnvelope", runtime)\n        self.assertNotIn("psychrometric_occupancy_envelope", runtime)\n        self.assertNotIn("envelope_polygon_coordinates", runtime)\n        self.assertNotIn("selected_tiles", runtime)\n\n    def test_single_climate_ui_exposes_all_three_peer_representations(self) -> None:\n        source = APP.read_text(encoding="utf-8")\n        self.assertIn('["Points", "Distribution grid", "Climate contour"]', source)\n        self.assertIn('"Outer contour coverage [%]"', source)\n        self.assertIn('"Additional contour levels [%]"', source)\n        self.assertNotIn('"Show 50% core contour"', source)\n        self.assertIn('"All years combined"', source)\n        self.assertIn('"Single year"', source)\n        self.assertIn('"Compare selected years"', source)\n\n    def test_comparison_ui_uses_one_common_reference_pressure(self) -> None:\n        source = APP.read_text(encoding="utf-8")\n        self.assertIn('"Psychrometric climate zones"', source)\n        self.assertIn('["Climate contour", "Distribution grid", "Points"]', source)\n        self.assertIn('"Reference psychrometric pressure"', source)\n        self.assertIn('"Standard atmosphere — 101325 Pa"', source)\n        self.assertIn('"Reference climate — {reference_name}"', source)\n        self.assertIn("points, grid cells and contours", source.lower())\n        self.assertIn("source station-pressure data remain unchanged", source.lower())\n\n    def test_missing_pressure_fallbacks_are_location_specific(self) -> None:\n        source = APP.read_text(encoding="utf-8")\n        self.assertGreaterEqual(source.count("pressure_from_altitude_m(float(epw.location.elevation_m or 0.0))"), 2)\n        self.assertIn("else pressure_from_altitude_m(float(dataset.location.elevation_m or 0.0))", source)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")

redesign = TEST_REDESIGN.read_text(encoding="utf-8")
old_pressure_test = '''    def test_reference_grid_pressure_does_not_move_comparison_zone_density(self) -> None:\n        climate_a = _psych_frame(2026, pressure_pa=101325.0)\n        climate_b = _psych_frame(2026, offset_c=3.0, pressure_pa=85000.0)\n        climates = [\n            ClimateDataset("a", "Climate A", "test", None, climate_a, []),\n            ClimateDataset("b", "Climate B", "test", None, climate_b, []),\n        ]\n        sea = psychrometric_comparison_chart(climates, data_display="Climate zones", reference_pressure_pa=101325.0)\n        high = psychrometric_comparison_chart(climates, data_display="Climate zones", reference_pressure_pa=85000.0)\n        sea_zone = [trace for trace in sea.data if trace.type == "contour" and "% zone" in str(trace.name)]\n        high_zone = [trace for trace in high.data if trace.type == "contour" and "% zone" in str(trace.name)]\n        self.assertEqual(len(sea_zone), 2)\n        self.assertEqual(len(high_zone), 2)\n        for left, right in zip(sea_zone, high_zone, strict=True):\n            np.testing.assert_allclose(np.asarray(left.z, dtype=float), np.asarray(right.z, dtype=float), rtol=0.0, atol=0.0)\n            np.testing.assert_allclose(np.asarray(left.x, dtype=float), np.asarray(right.x, dtype=float), rtol=0.0, atol=0.0)\n            np.testing.assert_allclose(np.asarray(left.y, dtype=float), np.asarray(right.y, dtype=float), rtol=0.0, atol=0.0)\n        self.assertEqual(tuple(sea.layout.xaxis.range), tuple(high.layout.xaxis.range))\n        self.assertEqual(tuple(sea.layout.yaxis.range), tuple(high.layout.yaxis.range))\n'''
new_pressure_test = '''    def test_reference_pressure_moves_all_comparison_coordinates_consistently(self) -> None:\n        climate_a = _psych_frame(2026, pressure_pa=101325.0)\n        climate_b = _psych_frame(2026, offset_c=3.0, pressure_pa=85000.0)\n        climates = [\n            ClimateDataset("a", "Climate A", "test", None, climate_a, []),\n            ClimateDataset("b", "Climate B", "test", None, climate_b, []),\n        ]\n        sea = psychrometric_comparison_chart(climates, data_display="Points", reference_pressure_pa=101325.0)\n        high = psychrometric_comparison_chart(climates, data_display="Points", reference_pressure_pa=85000.0)\n        sea_points = {str(trace.name): trace for trace in sea.data if trace.type == "scattergl"}\n        high_points = {str(trace.name): trace for trace in high.data if trace.type == "scattergl"}\n        self.assertEqual(set(sea_points), {"Climate A", "Climate B"})\n        self.assertEqual(set(high_points), {"Climate A", "Climate B"})\n        for name in sea_points:\n            np.testing.assert_allclose(np.asarray(sea_points[name].x, dtype=float), np.asarray(high_points[name].x, dtype=float))\n            sea_y = np.asarray(sea_points[name].y, dtype=float)\n            high_y = np.asarray(high_points[name].y, dtype=float)\n            self.assertGreater(float(np.nanmean(high_y)), float(np.nanmean(sea_y)))\n            self.assertFalse(np.allclose(sea_y, high_y))\n'''
if old_pressure_test not in redesign:
    raise RuntimeError("redesign pressure regression anchor missing")
redesign = redesign.replace(old_pressure_test, new_pressure_test, 1)
redesign = redesign.replace('self.assertIn(\'["Climate zone", "Points"]\', source)', 'self.assertIn(\'["Points", "Distribution grid", "Climate contour"]\', source)')
redesign = redesign.replace('self.assertIn(\'["Climate zones", "Points"]\', source)', 'self.assertIn(\'["Climate contour", "Distribution grid", "Points"]\', source)')
redesign = redesign.replace('self.assertIn(\'"Zone coverage [%]"\', source)', 'self.assertIn(\'"Outer contour coverage [%]"\', source)')
redesign = redesign.replace('self.assertIn(\'"Reference psychrometric grid pressure"\', source)', 'self.assertIn(\'"Reference psychrometric pressure"\', source)')
redesign = redesign.replace('self.assertIn(\'"Density gradient"\', source)', 'self.assertIn(\'"Density gradient"\', source)\n        self.assertIn(\'"Additional contour levels [%]"\', source)\n        self.assertNotIn(\'"Show 50% core contour"\', source)')
TEST_REDESIGN.write_text(redesign, encoding="utf-8")

TEST_REFERENCE.write_text('''from __future__ import annotations\n\nimport unittest\n\nimport numpy as np\nimport pandas as pd\nimport psychrolib\n\nfrom epw_climate_analyzer.comparison import ClimateDataset, psychrometric_comparison_chart\nfrom epw_climate_analyzer.psychrometrics import add_psychrometric_properties\n\npsychrolib.SetUnitSystem(psychrolib.SI)\n\n\ndef _same_state_frame(pressure_pa: float) -> pd.DataFrame:\n    index = pd.date_range("2026-01-01", periods=240, freq="h")\n    phase = np.linspace(0.0, 5.0 * np.pi, len(index))\n    t = 14.0 + 10.0 * np.sin(phase)\n    rh = np.clip(55.0 + 30.0 * np.cos(phase * 0.67), 8.0, 98.0)\n    frame = pd.DataFrame(\n        {\n            "dry_bulb_temperature_c": t,\n            "relative_humidity_pct": rh,\n            "atmospheric_station_pressure_pa": pressure_pa,\n            "month_index": index.month,\n            "month_name": index.strftime("%b"),\n            "hour_of_day": index.hour,\n        },\n        index=index,\n    )\n    frame.attrs["native_interval_minutes"] = 60.0\n    return add_psychrometric_properties(frame, fallback_pressure_pa=pressure_pa)\n\n\nclass PsychrometricReferencePressure0743Tests(unittest.TestCase):\n    def test_same_t_rh_states_overlay_after_projection_despite_different_source_pressures(self) -> None:\n        sea_source = _same_state_frame(101325.0)\n        mountain_source = _same_state_frame(82000.0)\n        sea_before = sea_source["humidity_ratio_g_kg"].copy()\n        mountain_before = mountain_source["humidity_ratio_g_kg"].copy()\n        climates = [\n            ClimateDataset("sea", "Sea source", "test", None, sea_source, []),\n            ClimateDataset("mountain", "Mountain source", "test", None, mountain_source, []),\n        ]\n        fig = psychrometric_comparison_chart(\n            climates, data_display="Points", reference_pressure_pa=95000.0\n        )\n        points = {str(trace.name): trace for trace in fig.data if trace.type == "scattergl"}\n        np.testing.assert_allclose(\n            np.asarray(points["Sea source"].x, dtype=float),\n            np.asarray(points["Mountain source"].x, dtype=float),\n            rtol=0.0, atol=1e-12,\n        )\n        np.testing.assert_allclose(\n            np.asarray(points["Sea source"].y, dtype=float),\n            np.asarray(points["Mountain source"].y, dtype=float),\n            rtol=1e-12, atol=1e-12,\n        )\n        pd.testing.assert_series_equal(sea_source["humidity_ratio_g_kg"], sea_before)\n        pd.testing.assert_series_equal(mountain_source["humidity_ratio_g_kg"], mountain_before)\n\n    def test_contour_trace_has_no_numeric_density_above_100_percent_rh(self) -> None:\n        source = _same_state_frame(85000.0)\n        climate = ClimateDataset("a", "A", "test", None, source, [])\n        reference_pressure = 93000.0\n        fig = psychrometric_comparison_chart(\n            [climate],\n            data_display="Climate contour",\n            reference_pressure_pa=reference_pressure,\n            zone_interior_style="Contour only",\n            zone_coverage=0.90,\n            additional_contour_coverages=[0.50, 0.70],\n        )\n        zone = next(trace for trace in fig.data if trace.type == "contour" and "90% zone" in str(trace.name))\n        x = np.asarray(zone.x, dtype=float)\n        y = np.asarray(zone.y, dtype=float)\n        z = np.asarray(zone.z, dtype=float)\n        for ix, t_c in enumerate(x):\n            saturation = psychrolib.GetSatHumRatio(float(t_c), reference_pressure) * 1000.0\n            impossible = y > saturation + max(1e-8, abs(saturation) * 1e-8)\n            if impossible.any():\n                self.assertTrue(np.isnan(z[impossible, ix]).all())\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")

print("0.7.4.3 scientific psychrometric remediation applied")
