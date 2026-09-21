"""Final monthly-only Streamlit surface guard.

This module is installed last in the source-parity runtime chain. Inner wrappers
can still emit legacy 10-minute wording or the generic air-temperature selection
warning because they were written for the shared hourly shell. Keeping this
normalization at the outermost sink makes the result independent of wrapper
composition order and avoids duplicating monthly science logic.
"""
from __future__ import annotations

from typing import Any, Callable

from .geosphere_monthly import MONTHLY_DOI, MONTHLY_RESOURCE_ID

_RESOURCE_KEY = "geosphere_resource_id"


def install_monthly_surface_guard(parity: Any) -> None:
    """Normalize final captions/info for the native-monthly source route."""
    previous = parity._render_geosphere_resource_selector
    st = parity.st

    def selector(legacy: Any, original: Callable) -> None:
        real_caption = st.caption
        real_info = st.info

        def caption(body: Any, *args: Any, **kwargs: Any):
            text = str(body)
            if str(st.session_state.get(_RESOURCE_KEY, "")) == MONTHLY_RESOURCE_ID:
                text = text.replace("`klima-v2-10min`", f"`{MONTHLY_RESOURCE_ID}`")
                text = text.replace("`klima-v2-1h`", f"`{MONTHLY_RESOURCE_ID}`")
                text = text.replace("10.60669/8fya-7x87", "10.60669/923n-p390")
                text = text.replace("10.60669/9bdm-yq93", "10.60669/923n-p390")
                text = text.replace("10-minute source data", "monthly source data")
                text = text.replace("hourly source data", "monthly source data")
                text = text.replace("10-minute source", "monthly source")
                text = text.replace("hourly source", "monthly source")
                if text.startswith("Source: GeoSphere Austria"):
                    text = f"Source: GeoSphere Austria `{MONTHLY_RESOURCE_ID}` · CC BY 4.0 · DOI {MONTHLY_DOI}"
            return real_caption(text, *args, **kwargs)

        def info(body: Any, *args: Any, **kwargs: Any):
            text = str(body)
            if (
                str(st.session_state.get(_RESOURCE_KEY, "")) == MONTHLY_RESOURCE_ID
                and text.startswith("Air temperature is not selected.")
            ):
                # The shared shell derives this warning from its hourly selection
                # cache. Monthly capability is evaluated from the returned native
                # monthly observations, so this warning is both stale and false.
                return None
            return real_info(body, *args, **kwargs)

        st.caption = caption
        st.info = info
        try:
            previous(legacy, original)
        finally:
            st.caption = real_caption
            st.info = real_info

    parity._render_geosphere_resource_selector = selector
