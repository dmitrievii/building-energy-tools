from __future__ import annotations

import inspect
import unittest

import epw_climate_analyzer.charts as charts
import epw_climate_analyzer.psychrometric_distribution as distribution
from epw_climate_analyzer.runtime_module_guard import ensure_current_psychrometric_runtime


REQUIRED_CHART_PARAMETERS = {
    "zone_coverage",
    "zone_interior_style",
    "show_core_zone",
    "additional_contour_coverages",
    "year_mode",
    "selected_years",
}
REQUIRED_DISTRIBUTION_PARAMETERS = {"additional_coverages", "pressure_pa"}


class PsychrometricRuntimeGuard0742Tests(unittest.TestCase):
    def test_current_runtime_is_accepted_without_contract_loss(self) -> None:
        current_distribution, current_charts = ensure_current_psychrometric_runtime()
        self.assertTrue(
            REQUIRED_CHART_PARAMETERS.issubset(inspect.signature(current_charts.psychrometric_chart).parameters)
        )
        self.assertTrue(
            REQUIRED_DISTRIBUTION_PARAMETERS.issubset(
                inspect.signature(current_distribution.add_climate_zone_traces).parameters
            )
        )

    def test_stale_old_chart_signature_is_reloaded(self) -> None:
        def old_psychrometric_chart(
            df,
            chart_type="T-d",
            pressure_pa=101325.0,
            show_rh_curves=True,
            show_comfort_zone=True,
            data_mode="Hourly values",
        ):
            return None

        charts.psychrometric_chart = old_psychrometric_chart
        _, refreshed = ensure_current_psychrometric_runtime()

        self.assertIsNot(refreshed.psychrometric_chart, old_psychrometric_chart)
        self.assertTrue(
            REQUIRED_CHART_PARAMETERS.issubset(inspect.signature(refreshed.psychrometric_chart).parameters)
        )

    def test_stale_distribution_dependency_is_reloaded_before_charts(self) -> None:
        original_zone_helper = distribution.add_climate_zone_traces
        delattr(distribution, "add_climate_zone_traces")
        refreshed_distribution, refreshed_charts = ensure_current_psychrometric_runtime()

        self.assertTrue(hasattr(refreshed_distribution, "add_climate_zone_traces"))
        self.assertTrue(callable(refreshed_distribution.add_climate_zone_traces))
        self.assertTrue(callable(refreshed_charts.psychrometric_chart))
        self.assertEqual(
            inspect.signature(refreshed_distribution.add_climate_zone_traces),
            inspect.signature(original_zone_helper),
        )

    def test_stale_distribution_helper_signature_is_reloaded_and_rebound(self) -> None:
        def old_add_climate_zone_traces(
            fig,
            df,
            *,
            chart_type,
            label,
            color,
            coverage=0.90,
            interior_style="Density gradient",
            axis_ranges=None,
            show_core=False,
            core_coverage=0.50,
            legendgroup=None,
        ):
            return None

        distribution.add_climate_zone_traces = old_add_climate_zone_traces
        charts.add_climate_zone_traces = old_add_climate_zone_traces

        refreshed_distribution, refreshed_charts = ensure_current_psychrometric_runtime()

        self.assertIsNot(refreshed_distribution.add_climate_zone_traces, old_add_climate_zone_traces)
        self.assertIsNot(refreshed_charts.add_climate_zone_traces, old_add_climate_zone_traces)
        self.assertIs(refreshed_charts.add_climate_zone_traces, refreshed_distribution.add_climate_zone_traces)
        self.assertTrue(
            REQUIRED_DISTRIBUTION_PARAMETERS.issubset(
                inspect.signature(refreshed_distribution.add_climate_zone_traces).parameters
            )
        )


if __name__ == "__main__":
    unittest.main()
