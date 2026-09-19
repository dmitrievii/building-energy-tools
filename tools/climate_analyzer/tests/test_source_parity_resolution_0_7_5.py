from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from epw_climate_analyzer import source_parity_resolution


class SourceParityResolutionPolicyTests(unittest.TestCase):
    def _parity(self):
        calls: list[str] = []

        def native(dataset, **kwargs):
            calls.append("native")
            return ("native", dataset, kwargs)

        def hourly(dataset, **kwargs):
            calls.append("hourly")
            return ("hourly", dataset, kwargs)

        parity = SimpleNamespace(
            prepare_historical_native_analysis_frame=native,
            prepare_historical_analysis_frame=hourly,
        )
        return parity, calls

    def test_native_helper_is_available_on_time_series_only(self) -> None:
        parity, calls = self._parity()
        fake_streamlit = SimpleNamespace(
            session_state={"climate_analyzer_navigation": "Time Series and Overlay"}
        )
        with patch.object(source_parity_resolution, "st", fake_streamlit):
            source_parity_resolution.enforce_native_timeseries_only(parity)
            result = parity.prepare_historical_native_analysis_frame("dataset", include_solar=True)
        self.assertEqual(result[0], "native")
        self.assertEqual(calls, ["native"])

    def test_native_request_on_other_analysis_page_routes_to_hourly(self) -> None:
        parity, calls = self._parity()
        fake_streamlit = SimpleNamespace(
            session_state={"climate_analyzer_navigation": "Temperature"}
        )
        with patch.object(source_parity_resolution, "st", fake_streamlit):
            source_parity_resolution.enforce_native_timeseries_only(parity)
            result = parity.prepare_historical_native_analysis_frame(
                "dataset",
                analysis_clock_mode="source",
                include_psychrometrics=False,
            )
        self.assertEqual(result[0], "hourly")
        self.assertEqual(calls, ["hourly"])
        self.assertEqual(result[2]["analysis_clock_mode"], "source")

    def test_policy_installation_is_idempotent(self) -> None:
        parity, calls = self._parity()
        fake_streamlit = SimpleNamespace(
            session_state={"climate_analyzer_navigation": "Precipitation and Snow"}
        )
        with patch.object(source_parity_resolution, "st", fake_streamlit):
            source_parity_resolution.enforce_native_timeseries_only(parity)
            first = parity.prepare_historical_native_analysis_frame
            source_parity_resolution.enforce_native_timeseries_only(parity)
            second = parity.prepare_historical_native_analysis_frame
            second("dataset")
        self.assertIs(first, second)
        self.assertEqual(calls, ["hourly"])


if __name__ == "__main__":
    unittest.main()
