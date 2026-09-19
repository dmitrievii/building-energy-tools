"""Resolution policy for the source-parity Streamlit migration.

Provider-native resolution is intentionally a Time Series feature only.  Every
other scientific/graphical analysis uses the canonical hourly frame for stable
performance on long multi-year sub-hourly datasets.  Data Quality is unaffected:
it uses the separate native diagnostic entry point and therefore still audits
real provider timestamps and gaps.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


TIME_SERIES_PAGE = "Time Series and Overlay"


def enforce_native_timeseries_only(parity: Any) -> None:
    """Guard the native analysis helper so only Time Series may use it."""
    if hasattr(parity, "_source_parity_unrestricted_native_analysis"):
        return

    original_native = parity.prepare_historical_native_analysis_frame
    parity._source_parity_unrestricted_native_analysis = original_native

    def native_timeseries_only(dataset: Any, **kwargs: Any):
        active_page = st.session_state.get("climate_analyzer_navigation")
        if active_page == TIME_SERIES_PAGE:
            return original_native(dataset, **kwargs)

        # Temperature/ground and precipitation used to request the provider-
        # native frame as a secondary input.  Preserve the same calculation
        # options, but route them through the canonical hourly engine.  The
        # hourly function accepts the shared keyword contract used by those
        # calls; pressure_override remains intentionally unset here.
        return parity.prepare_historical_analysis_frame(dataset, **kwargs)

    parity.prepare_historical_native_analysis_frame = native_timeseries_only
