from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
APP = ROOT / "app.py"
DOC = ROOT / "CLIMATE_CORE_0_7_4.md"
TEST = ROOT / "tests" / "test_original_audit_closure_0_7_4_1.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


source = APP.read_text(encoding="utf-8")

source = replace_once(
    source,
    '            ["Relative humidity", "Humidity ratio", "Dew-point temperature", "Wet-bulb temperature", "Moist-air enthalpy", "Specific volume", "Moist-air density"],',
    '            ["Relative humidity", "Humidity ratio", "Dew-point temperature", "Moist-air enthalpy", "Specific volume", "Moist-air density"],',
    "remove generic Humidity wet-bulb duplicate",
)

old_passive = '''        if view == "Annual totals":
            table = passive_strategy_table(df)
            fig = px.bar(
                table,
                x="hours",
                y="strategy",
                orientation="h",
                title="Annual passive and HVAC strategy hours",
            )
            fig.update_layout(template="plotly_white", xaxis_title="Hours", yaxis_title="Strategy")
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displaylogo": False, "scrollZoom": True},
                key=next_plot_key(),
            )
            st.dataframe(table, hide_index=True, use_container_width=True)
            render_interpretation(hvac_interpretation(df))
'''

new_passive = '''        if view == "Annual totals":
            chronological_multiyear = time_basis(df) == CHRONOLOGICAL and len(available_years(df)) > 1
            annual_summary = "Selected-period summary"
            if chronological_multiyear:
                annual_summary = st.radio(
                    "Annual summary",
                    ["By year", "Selected-period summary"],
                    index=0,
                    horizontal=True,
                    key="passive_strategy_annual_summary",
                    help=(
                        "By year keeps every real source year separate in Chronological mode. "
                        "Selected-period summary deliberately pools the currently filtered interval."
                    ),
                )

            if annual_summary == "By year":
                annual_frames = []
                for year in available_years(df):
                    year_frame = filter_year(df, int(year))
                    year_table = passive_strategy_table(year_frame).copy()
                    year_table.insert(0, "year", str(int(year)))
                    annual_frames.append(year_table)
                table = pd.concat(annual_frames, ignore_index=True)
                fig = px.bar(
                    table,
                    x="hours",
                    y="strategy",
                    color="year",
                    barmode="group",
                    orientation="h",
                    title="Passive and HVAC strategy hours by year",
                    labels={"year": "Year"},
                )
                st.caption(
                    "Chronological multi-year mode: annual strategy hours are separated by real source year. "
                    "No climatological folding or cross-year pooling is applied in this default view."
                )
            else:
                table = passive_strategy_table(df)
                fig = px.bar(
                    table,
                    x="hours",
                    y="strategy",
                    orientation="h",
                    title="Passive and HVAC strategy hours — selected period",
                )
                if chronological_multiyear:
                    st.caption(
                        "Selected-period summary intentionally pools all currently filtered chronological years. "
                        "Use By year for interannual comparison."
                    )

            fig.update_layout(template="plotly_white", xaxis_title="Hours", yaxis_title="Strategy")
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displaylogo": False, "scrollZoom": True},
                key=next_plot_key(),
            )
            st.dataframe(table, hide_index=True, use_container_width=True)
            render_interpretation(hvac_interpretation(df))
'''

source = replace_once(source, old_passive, new_passive, "passive annual multi-year summary")
APP.write_text(source, encoding="utf-8")

# Replace the stale 0.7.4 psychrometric documentation with the actual 0.7.4.1 contract.
doc = DOC.read_text(encoding="utf-8")
doc = doc.replace(
    "# Climate Analyzer 0.7.4 — Temporal and source-neutral UX remediation\n\nStatus: Draft implementation branch. Parent production baseline: Climate 0.7.3 (`main` merge `88b0f0138e2942f37ff3432acf4508fe3e51c5e6`).",
    "# Climate Analyzer 0.7.4 / 0.7.4.1 — Temporal, source-neutral and psychrometric remediation\n\nStatus: 0.7.4.1 remediation on PR #69. Parent production baseline: Climate 0.7.4 (`main` merge `c0728c0771239fd8a77aa60bd2fdc55c254ae1e4`).",
    1,
)
marker = "## D — Psychrometric redesign\n"
if marker not in doc:
    raise RuntimeError("documentation D-section marker missing")
prefix = doc.split(marker, 1)[0]
new_d = '''## D — Psychrometric redesign — superseded by 0.7.4.1\n\nThe selected-cell 0.7.4 implementation is no longer the release contract. 0.7.4.1 replaces it with a continuous climate-zone representation:\n\n- **Climate zone** is the default representation for single-climate and Compare Climates psychrometrics.\n- The zone is calculated from a duration-weighted two-dimensional density field in the actual displayed `T–d` or `i–d` coordinates, smoothed deterministically with NumPy.\n- The outer contour is an iso-density region containing at least the requested share of represented physical duration. Coverage is user-selectable from 50–99%, default 90%.\n- The former 1 °C × 5 %RH selected-cell mosaic and its square-cell geometry are removed from the runtime contract.\n- Zone interior can be shown as **Density gradient**, **Sparse points**, **Solid fill** or **Contour only**; an optional 50% core contour is available.\n- Chronological multi-year analysis exposes **All years combined**, **Single year** and **Compare selected years**. Real source years remain explicit.\n- Compare Climates uses one fixed shared axis domain for all selected climates.\n- Climate-state coordinates retain each source's own pressure-derived psychrometric properties. **Reference psychrometric grid pressure** is a separate visual setting and cannot move the climate zones.\n- If measured/station pressure is completely unavailable, EPW and GeoSphere fall back to standard-atmosphere pressure derived from that climate location's own elevation, not an unrelated global 101325 Pa default.\n- A permanent **Climate Analyzer Psychrometric Integration** workflow guards the density-zone, year, shared-axis and pressure-separation contracts.\n\n## E — Original 0.7.4 audit closure\n\n0.7.4.1 re-audits the full original remediation scope rather than treating psychrometrics as an isolated hotfix. The retained closure contract is:\n\n- A — chronological/calendar heat-map semantics, safe temperature colour domains, plain-language P05/P95 terminology, real-year degree-metric labels, 20 °C default KGT cooling limit, explicit frost/nighttime-hour terminology and interannual interpretations remain regression-protected.\n- B — Ground Temperature remains nested under Temperature with stable annual axes and explicit chronological-year semantics; EPW and GeoSphere retain one capability-gated wind architecture.\n- C — Overview temperature duplication remains removed; precipitation zero/wet-interval semantics, per-series Time Series styling, Sky & Daylight consolidation, Natural Ventilation route consolidation and HVAC/Humidity de-duplication remain regression-protected.\n- **Wet-bulb temperature has one generic variable home: Temperature.** It remains available to psychrometric calculations/relationships but is no longer duplicated in the generic Humidity variable explorer.\n- **Passive-strategy annual totals preserve real years.** In Chronological multi-year mode, `By year` is the default; `Selected-period summary` is an explicit opt-in pooled view.\n- Compare Climates uses the 0.7.4.1 continuous climate-zone contract described above.\n\nThe release candidate must pass the full Climate Analyzer CI and the dedicated psychrometric integration gate on the same final head before PR #69 is marked Ready.\n'''
doc = prefix + new_d
DOC.write_text(doc, encoding="utf-8")

TEST.write_text(r'''from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from epw_climate_analyzer.charts import temporal_heatmap_chart
from epw_climate_analyzer.ground_temperature import AnnualHarmonic, animated_profile_figure, monthly_ground_profile, profile_figure
from epw_climate_analyzer.temporal_filtering import CHRONOLOGICAL, with_time_basis

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
DOC = ROOT / "CLIMATE_CORE_0_7_4.md"


def block(source: str, name: str, next_name: str) -> str:
    start = source.index(f"def {name}(")
    end = source.index(f"def {next_name}(", start)
    return source[start:end]


class OriginalAuditClosure0741Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8")

    def test_a_temporal_percentile_threshold_and_degree_contracts_remain(self) -> None:
        self.assertIn("Lower 5% boundary (P05)", self.source)
        self.assertIn("Upper 5% boundary (P95)", self.source)
        self.assertIn("Nighttime hours > 20 °C (20:00–06:59)", self.source)
        self.assertIn('"Cooling limit [°C]",\n            10.0,\n            35.0,\n            20.0', self.source)
        self.assertIn("Chronological heat maps keep every real day, week or month in sequence across years", self.source)

        idx = pd.date_range("2025-01-01", periods=48, freq="h")
        frame = pd.DataFrame({"dry_bulb_temperature_c": [-15.0] * 24 + [-10.0] * 24}, index=idx)
        frame["hour_of_day"] = frame.index.hour
        frame = with_time_basis(frame, CHRONOLOGICAL)
        fig = temporal_heatmap_chart(frame, "dry_bulb_temperature_c", "day", "Hour of day", "Minimum", "Minimum", "°C", temperature_thresholds=(18.0, 26.0))
        self.assertTrue(all(0.0 <= float(stop[0]) <= 1.0 for stop in fig.layout.coloraxis.colorscale))

    def test_b_ground_and_wind_source_neutral_contracts_remain(self) -> None:
        temperature = block(self.source, "render_temperature", "render_humidity")
        wind = block(self.source, "render_wind", "render_precipitation")
        self.assertIn('chart_options.append("Ground temperature")', temperature)
        for label in ("Wind speed", "Wind direction", "Wind gust speed", "Wind gust direction"):
            self.assertIn(label, wind)
        self.assertIn("Maximum gust", wind)

        profile = monthly_ground_profile(AnnualHarmonic(mean_c=10.0, sin_c=8.0, cos_c=2.0, amplitude_c=(68.0 ** 0.5)), [0.0, 1.0, 2.0, 5.0, 10.0, 15.0])
        self.assertEqual(tuple(profile_figure(profile).layout.xaxis.range), tuple(animated_profile_figure(profile).layout.xaxis.range))

    def test_c_overview_precip_overlay_daylight_nv_and_hvac_dedup_contracts_remain(self) -> None:
        overview = block(self.source, "render_overview", "render_temperature")
        humidity = block(self.source, "render_humidity", "render_wind")
        nv = block(self.source, "render_natural_ventilation", "render_hvac_passive")
        hvac = block(self.source, "render_hvac_passive", "render_time_series_overlay")
        daylight = block(self.source, "render_sky_daylight", "render_natural_ventilation")
        overlay = block(self.source, "render_time_series_overlay", "render_data_quality")

        self.assertNotIn("Monthly outdoor temperature profile", overview)
        self.assertIn('"Wet intervals only"', self.source)
        self.assertIn('"All intervals including dry periods"', self.source)
        for label in ("Line style", "Line width", "Line color", "Opacity"):
            self.assertIn(label, overlay)
        self.assertIn('"Measured sunshine duration"', daylight)
        self.assertIn('"Relative sunshine duration"', daylight)
        self.assertNotIn('"Month × hour suitability"', nv)
        self.assertIn('"Moisture thresholds"', humidity)
        self.assertNotIn('"Outdoor-air enthalpy duration curve"', hvac)
        self.assertNotIn('"Heating and cooling degree-hours"', hvac)

    def test_wet_bulb_generic_variable_has_temperature_as_single_home(self) -> None:
        temperature = block(self.source, "render_temperature", "render_humidity")
        humidity = block(self.source, "render_humidity", "render_wind")
        generic_humidity = humidity.split('if chart_group == "Humidity variable explorer":', 1)[1].split('elif chart_group == "Psychrometric chart":', 1)[0]
        self.assertIn('"Wet-bulb temperature"', temperature)
        self.assertNotIn('"Wet-bulb temperature"', generic_humidity)
        # Wet bulb remains available to psychrometric relationships; only the duplicate generic home is removed.
        self.assertIn('"Wet-bulb temperature"', humidity)

    def test_passive_annual_chronological_multiyear_defaults_to_by_year(self) -> None:
        hvac = block(self.source, "render_hvac_passive", "render_time_series_overlay")
        self.assertIn('chronological_multiyear = time_basis(df) == CHRONOLOGICAL and len(available_years(df)) > 1', hvac)
        self.assertIn('"Annual summary"', hvac)
        self.assertIn('["By year", "Selected-period summary"]', hvac)
        self.assertIn('index=0', hvac)
        self.assertIn('filter_year(df, int(year))', hvac)
        self.assertIn('title="Passive and HVAC strategy hours by year"', hvac)

    def test_compare_climates_uses_current_zone_contract_not_selected_cells(self) -> None:
        self.assertIn('["Climate zones", "Points"]', self.source)
        self.assertIn('"Reference psychrometric grid pressure"', self.source)
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("duration-weighted two-dimensional density field", doc)
        self.assertIn("former 1 °C × 5 %RH selected-cell mosaic", doc)
        self.assertIn("no longer the release contract", doc)
        self.assertIn("Wet-bulb temperature has one generic variable home", doc)
        self.assertIn("By year", doc)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

print("0.7.4.1 original-audit closure patch applied")
