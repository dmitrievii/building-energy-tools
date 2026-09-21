"""Final monthly-only Streamlit surface guard.

This module is installed last in the source-parity runtime chain. Inner wrappers
can still emit legacy shared-shell wording/widgets because they were written for
10-minute/hourly resources. Keeping the final normalization here makes the
user-visible monthly contract independent of wrapper composition order without
moving scientific calculations into the UI layer.
"""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable, Iterable

import pandas as pd

from . import source_parity_monthly_canonical as monthly_ui
from .geosphere_monthly import MONTHLY_DOI, MONTHLY_RESOURCE_ID

_RESOURCE_KEY = "geosphere_resource_id"
_PARAMETER_SET_KEY = "geosphere_monthly_parameter_catalogue_v2"
_MONTHLY_CONTEXT_LABEL = "About this GeoSphere monthly dataset"
_LEGACY_CATALOGUE_OPTIONS = ("Recommended", "All parameters")


def _monthly_active(st: Any) -> bool:
    return str(st.session_state.get(_RESOURCE_KEY, "")) == MONTHLY_RESOURCE_ID


def _canonical_parameter_set_active(st: Any) -> bool:
    """Return true only after the canonical Parameter set has rendered once.

    The first monthly render must remain untouched so the outer resource wrapper
    can commit the private dataset widget into the legacy routing key. Legacy
    suppression is needed only on later Parameter-set reruns, where the canonical
    key is already present and the old Recommended/All wrapper can otherwise
    reappear beside the new control.
    """
    return _monthly_active(st) and _PARAMETER_SET_KEY in st.session_state


def _dataset_has_station_pressure(dataset: Any) -> bool:
    data = getattr(dataset, "data", None)
    if not isinstance(data, pd.DataFrame):
        return False
    for column in ("p", "atmospheric_station_pressure_pa"):
        if column in data.columns and pd.to_numeric(data[column], errors="coerce").notna().any():
            return True
    return False


def _install_monthly_analysis_capability_note(st: Any) -> None:
    """Expose measured monthly pressure capability on the moisture page."""
    if bool(getattr(monthly_ui, "_MONTHLY_SURFACE_ANALYSIS_GUARD_INSTALLED", False)):
        return
    previous = monthly_ui.render_monthly_canonical_analysis

    def render(legacy: Any, dataset: Any) -> None:
        page = str(st.session_state.get(getattr(legacy, "NAVIGATION_KEY", ""), ""))
        if page == "Humidity and Psychrometrics" and _dataset_has_station_pressure(dataset):
            st.caption(
                "Station pressure — published monthly mean is available and is used by the monthly psychrometric route."
            )
        previous(legacy, dataset)

    monthly_ui.render_monthly_canonical_analysis = render
    monthly_ui._MONTHLY_SURFACE_ANALYSIS_GUARD_INSTALLED = True


def install_monthly_surface_guard(parity: Any) -> None:
    """Normalize the final native-monthly Streamlit surface."""
    previous = parity._render_geosphere_resource_selector
    st = parity.st

    def selector(legacy: Any, original: Callable) -> None:
        real_caption = st.caption
        real_info = st.info
        real_radio = st.radio
        real_expander = st.expander
        context_seen = {"value": False}

        def caption(body: Any, *args: Any, **kwargs: Any):
            text = str(body)
            if _monthly_active(st):
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
            if _monthly_active(st) and text.startswith("Air temperature is not selected."):
                return None
            return real_info(body, *args, **kwargs)

        def radio(label: str, options: Iterable[Any], *args: Any, **kwargs: Any):
            values = list(options)
            if (
                _canonical_parameter_set_active(st)
                and label == "Parameter catalogue"
                and tuple(values) == _LEGACY_CATALOGUE_OPTIONS
            ):
                # On Parameter-set reruns the canonical selector owns filtering;
                # keep the legacy layer transparent and preserve the full provider
                # vocabulary for the provider-keyed selection adapter.
                return "All parameters"
            return real_radio(label, values, *args, **kwargs)

        def expander(label: str, *args: Any, **kwargs: Any):
            if _canonical_parameter_set_active(st) and label == _MONTHLY_CONTEXT_LABEL:
                if context_seen["value"]:
                    return nullcontext()
                context_seen["value"] = True
            return real_expander(label, *args, **kwargs)

        st.caption = caption
        st.info = info
        st.radio = radio
        st.expander = expander
        try:
            if _canonical_parameter_set_active(st):
                real_caption(
                    "Native monthly source data · Parameter set changes catalogue visibility only; Load/Flag selections are retained by provider."
                )
            previous(legacy, original)
        finally:
            st.caption = real_caption
            st.info = real_info
            st.radio = real_radio
            st.expander = real_expander

    parity._render_geosphere_resource_selector = selector
    _install_monthly_analysis_capability_note(st)
