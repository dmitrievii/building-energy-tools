from __future__ import annotations

import unittest
from pathlib import Path

from epw_climate_analyzer.ui_contract import (
    APP_BROWSER_TITLE,
    APP_NAME,
    APP_TAGLINE,
    NAVIGATION_KEY,
    NAVIGATION_LABELS,
    NAVIGATION_PAGES,
    PENDING_NAVIGATION_KEY,
    RESET_NAVIGATION_KEY,
    apply_queued_navigation,
    navigation_label,
    queue_navigation,
    queue_navigation_reset,
)


TOOL_ROOT = Path(__file__).resolve().parents[1]


class PublicUxContractTests(unittest.TestCase):
    def test_public_product_identity(self) -> None:
        self.assertEqual(APP_NAME, "Climate Analyzer")
        self.assertEqual(APP_BROWSER_TITLE, "Climate Analyzer | Building Energy Tools")
        self.assertIn("building design", APP_TAGLINE.lower())

    def test_navigation_contract_is_complete_and_unique(self) -> None:
        self.assertEqual(len(NAVIGATION_PAGES), 16)
        self.assertEqual(navigation_label("Report"),"Report — Climate assessment")
        self.assertEqual(navigation_label("Outdoor Thermal Comfort"),"Design — Outdoor thermal comfort")
        self.assertEqual(navigation_label("Shading analysis"),"Design — Shading analysis")
        self.assertEqual(len(set(NAVIGATION_PAGES)), len(NAVIGATION_PAGES))
        self.assertEqual(set(NAVIGATION_LABELS), set(NAVIGATION_PAGES))
        labels = [navigation_label(page) for page in NAVIGATION_PAGES]
        self.assertEqual(len(set(labels)), len(labels))
        self.assertNotIn("Ground Temperature", NAVIGATION_PAGES)
        self.assertIn("Temperature", NAVIGATION_PAGES)
        self.assertIn("Time Series and Overlay", NAVIGATION_PAGES)
        self.assertEqual(
            navigation_label("Time Series and Overlay"),
            "Explore — Time series & overlay",
        )

    def test_navigation_exposes_expected_groups(self) -> None:
        labels = [navigation_label(page) for page in NAVIGATION_PAGES]
        self.assertEqual(labels[0], "Start — Climate source")
        for prefix in ("Climate —", "Explore —", "Design —", "Compare —", "Data —"):
            self.assertTrue(any(label.startswith(prefix) for label in labels), prefix)

    def test_navigation_is_queued_before_widget_state_is_changed(self) -> None:
        state: dict[str, object] = {NAVIGATION_KEY: "Climate File Source"}
        queue_navigation(state, "Overview")
        self.assertEqual(state[NAVIGATION_KEY], "Climate File Source")
        self.assertEqual(state[PENDING_NAVIGATION_KEY], "Overview")
        apply_queued_navigation(state)
        self.assertEqual(state[NAVIGATION_KEY], "Overview")
        self.assertNotIn(PENDING_NAVIGATION_KEY, state)

    def test_navigation_reset_is_applied_on_next_render(self) -> None:
        state: dict[str, object] = {NAVIGATION_KEY: "Climate File Source"}
        queue_navigation_reset(state)
        self.assertEqual(state[NAVIGATION_KEY], "Climate File Source")
        self.assertTrue(state[RESET_NAVIGATION_KEY])
        apply_queued_navigation(state)
        self.assertNotIn(NAVIGATION_KEY, state)
        self.assertNotIn(RESET_NAVIGATION_KEY, state)

    def test_unknown_navigation_target_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            queue_navigation({}, "Unknown page")

    def test_climate_source_map_is_lazy_rendered(self) -> None:
        source = (TOOL_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('st.tabs(["Upload EPW", "Find climate"])', source)
        self.assertIn('source_mode = st.radio(', source)
        self.assertIn('if source_mode == "Upload EPW":', source)
        upload_branch = source.split('if source_mode == "Upload EPW":', 1)[1].split('st.subheader("Find a climate")', 1)[0]
        self.assertIn("return", upload_branch)

    def test_essential_landing_copy_does_not_use_low_contrast_caption(self) -> None:
        source = (TOOL_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("st.caption(APP_RELEASE_LABEL)", source)
        self.assertNotIn("st.write(APP_RELEASE_LABEL)", source)
        self.assertIn("st.markdown(ABOUT_MARKDOWN)", source)
        self.assertNotIn(
            'st.caption(\n        "Start with an EPW weather file from your computer or select a climate from the reviewed "',
            source,
        )


    def test_sidebar_navigation_and_settings_share_flat_left_alignment(self) -> None:
        from epw_climate_analyzer.sidebar_layout import NAV_CSS

        self.assertIn("justify-content:flex-start!important", NAV_CSS)
        self.assertIn("text-align:left!important", NAV_CSS)
        self.assertIn('button [data-testid="stMarkdownContainer"]', NAV_CSS)
        self.assertIn('[data-testid="stExpander"] summary', NAV_CSS)
        self.assertIn('[data-testid="stExpander"] details', NAV_CSS)
        self.assertIn("border:0!important", NAV_CSS)
        self.assertIn("summary:focus-visible", NAV_CSS)

    def test_epw_filename_is_provenance_not_sidebar_copy(self) -> None:
        source = (TOOL_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("climate_area.caption(epw.name)", source)
        self.assertNotIn('st.write(f"Selected file: `{local_file.name}`")', source)
        self.assertIn('st.caption(f"Source file: {epw.name}")', source)
        self.assertIn("source=epw.name", source)


    def test_overview_uses_global_filter_without_secondary_scope(self) -> None:
        source = (TOOL_ROOT / "app.py").read_text(encoding="utf-8")
        overview = source.split("def render_overview(", 1)[1].split("def render_temperature(", 1)[0]
        self.assertNotIn("Statistics scope", overview)
        self.assertNotIn("Current sidebar filter", overview)
        self.assertIn("metric_cards(df)", overview)
        self.assertIn("render_calculated_epw_statistics(df)", overview)
        self.assertIn("reference_df=full_df", overview)


    def test_calculated_humidity_ratio_reports_both_percentiles(self) -> None:
        import pandas as pd
        from epw_climate_analyzer.statistics import calculated_statistics_tables

        df = pd.DataFrame(
            {"humidity_ratio_g_kg": [1.0, 2.0, 3.0, 4.0, 5.0, float("nan")]},
            index=pd.date_range("2020-01-01", periods=6, freq="h"),
        )
        table = calculated_statistics_tables(df)["Humidity and psychrometrics"].set_index("Metric")
        self.assertEqual(table.loc["Humidity ratio P05 / P95", "Value"], "1.2 / 4.8")
        self.assertEqual(table.loc["Humidity ratio P05 / P95", "Unit"], "g/kg dry air")
        missing = calculated_statistics_tables(df.assign(humidity_ratio_g_kg=float("nan")))["Humidity and psychrometrics"].set_index("Metric")
        self.assertEqual(missing.loc["Humidity ratio P05 / P95", "Value"], "n/a / n/a")


    def test_calculated_wind_speed_reports_both_percentiles(self) -> None:
        import pandas as pd
        from epw_climate_analyzer.statistics import calculated_statistics_tables

        df = pd.DataFrame(
            {"wind_speed_m_s": [0.0, 1.0, 2.0, 3.0, 4.0, float("nan")]},
            index=pd.date_range("2020-01-01", periods=6, freq="h"),
        )
        table = calculated_statistics_tables(df)["Wind"].set_index("Metric")
        self.assertEqual(table.loc["Wind speed P05 / P95", "Value"], "0.2 / 3.8")
        self.assertEqual(table.loc["Wind speed P05 / P95", "Unit"], "m/s")
        missing = calculated_statistics_tables(df.assign(wind_speed_m_s=float("nan")))["Wind"].set_index("Metric")
        self.assertEqual(missing.loc["Wind speed P05 / P95", "Value"], "n/a / n/a")


    def test_compare_summary_renders_only_selected_ranking(self) -> None:
        source = (TOOL_ROOT / "app.py").read_text(encoding="utf-8")
        summary = source.split("def render_compare_summary(", 1)[1].split("def render_compare_temperature(", 1)[0]
        self.assertNotIn("hdd_cdd_grouped_chart(", summary)
        self.assertEqual(summary.count("render_plot("), 1)
        self.assertIn("ranked_metric_interpretation(metrics, metric, reference_name)", summary)

    def test_ranked_interpretation_uses_selected_quantity(self) -> None:
        import pandas as pd
        from epw_climate_analyzer.comparison import ranked_metric_interpretation

        metric = "Mean wind speed [m/s]"
        frame = pd.DataFrame({
            "Climate": ["A", "B", "C"],
            metric: [1.0, 3.5, float("nan")],
            "HDD18 [K·h]": [3000, 1000, 2000],
        })
        result = ranked_metric_interpretation(frame, metric, "A")
        self.assertIn("1 m/s in A", result)
        self.assertIn("3.5 m/s in B", result)
        self.assertIn("+2.5 m/s", result)
        self.assertNotIn("HDD", result)
        self.assertNotIn("K·h", result)
        self.assertIn("No valid values", ranked_metric_interpretation(frame.assign(**{metric: float("nan")}), metric))


    def test_comparison_wind_rose_title_band_and_compass(self) -> None:
        from types import SimpleNamespace
        import pandas as pd
        from epw_climate_analyzer.comparison import wind_rose_small_multiples

        data = pd.DataFrame({"wind_direction_deg": [0., 90., 180., 270.],
                             "wind_speed_m_s": [1., 3., 5., 7.]})
        climates = [SimpleNamespace(display_name=name, data=data) for name in
                    ("AUT_ST_Graz.AP.112400_TMYx.2004-2018.epw", "Dubai.Intl.AP — ARE", "Third climate")]
        fig = wind_rose_small_multiples(climates)
        self.assertEqual(len(fig.layout.annotations), 3)
        for i, annotation in enumerate(fig.layout.annotations):
            polar = fig.get_subplot(i // 2 + 1, i % 2 + 1)
            self.assertGreater(annotation.y, polar.domain.y[1])
            self.assertEqual(annotation.yanchor, "top")
            self.assertEqual(polar.angularaxis.rotation, 90)
            self.assertEqual(polar.angularaxis.direction, "clockwise")
            self.assertEqual(polar.angularaxis.ticktext[0], "N")
        self.assertIn("<br>", fig.layout.annotations[0].text)


    def test_comparison_management_and_analysis_are_lazy_routes(self) -> None:
        source = (TOOL_ROOT / "app.py").read_text(encoding="utf-8")
        route = source.split("def render_compare_climates(", 1)[1].split("def render_calculated_epw_statistics(", 1)[0]
        self.assertIn('"Manage climates"', route)
        self.assertIn('on_change="rerun"', route)
        self.assertIn('key="comparison_active_tab"', route)
        self.assertIn('if tabs[0].open:', route)
        self.assertIn('with tabs[0]:\n            render_comparison_basket_manager(active_file)\n        return', route)
        self.assertIn('if tab.open', route)
        self.assertIn('with tabs[active_index]:', route)
        self.assertLess(route.index('render_comparison_basket_manager(active_file)'), route.index('load_comparison_datasets('))
        self.assertIn('default="Manage climates" if len(payloads) < 2 else "Summary"', route)

    def test_comparison_shared_preferences_survive_hidden_management_controls(self) -> None:
        source = (TOOL_ROOT / "app.py").read_text(encoding="utf-8")
        controls = source.split("def comparison_controls(", 1)[1].split("def get_reference_and_target(", 1)[0]
        self.assertIn('state.get("_comparison_control_preferences", {})', controls)
        self.assertIn('state["_comparison_control_preferences"] = {', controls)
        self.assertIn('value=tuple(saved.get("hour_range", (0, 23)))', controls)
        self.assertIn('if reference not in climate_names:', controls)


if __name__ == "__main__":
    unittest.main()
