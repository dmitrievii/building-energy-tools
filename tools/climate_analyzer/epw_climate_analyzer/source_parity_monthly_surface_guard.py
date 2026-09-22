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
_PARAMETER_SET_OPTIONS = (
    "Core variables",
    "Core + additional statistics",
    "All provider parameters",
)
_PARAMETER_SET_HELP = (
    "Core variables are canonical/building-climate quantities. Additional statistics are "
    "provider-published monthly counts, extrema and indicators. All provider parameters also "
    "shows fields without normalized Seasonal/Annual semantics."
)


def _monthly_active(st: Any) -> bool:
    return str(st.session_state.get(_RESOURCE_KEY, "")) == MONTHLY_RESOURCE_ID


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
    """Normalize the final native-monthly Streamlit surface.

    The source-parity stack contains both the legacy ``Parameter catalogue``
    wrapper and the canonical ``Parameter set`` wrapper.  Streamlit sessions
    share imported Python modules, so a previous session can leave those wrappers
    composed in a different order for the next session even when the underlying
    Streamlit callables themselves have been restored.  This final guard therefore
    owns the user-visible monthly radio contract: whichever inner wrapper calls
    first, one canonical Parameter-set widget is rendered and every later call in
    the same selector pass returns that already selected value.
    """
    previous = parity._render_geosphere_resource_selector
    st = parity.st

    def selector(legacy: Any, original: Callable) -> None:
        real_caption = st.caption
        real_info = st.info
        real_radio = st.radio
        real_expander = st.expander
        context_seen = {"value": False}
        parameter_set_rendered = {"value": False}
        selected_parameter_set = {
            "value": str(st.session_state.get(_PARAMETER_SET_KEY, "Core variables"))
        }
        if selected_parameter_set["value"] not in _PARAMETER_SET_OPTIONS:
            selected_parameter_set["value"] = "Core variables"

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

        def render_parameter_set() -> str:
            if parameter_set_rendered["value"]:
                return selected_parameter_set["value"]
            current = selected_parameter_set["value"]
            chosen = real_radio(
                "Parameter set",
                list(_PARAMETER_SET_OPTIONS),
                index=list(_PARAMETER_SET_OPTIONS).index(current),
                horizontal=True,
                key=_PARAMETER_SET_KEY,
                help=_PARAMETER_SET_HELP,
            )
            selected_parameter_set["value"] = str(chosen)
            parameter_set_rendered["value"] = True
            return selected_parameter_set["value"]

        def radio(label: str, options: Iterable[Any], *args: Any, **kwargs: Any):
            values = list(options)
            if _monthly_active(st):
                if label == "Parameter catalogue" and tuple(values) == _LEGACY_CATALOGUE_OPTIONS:
                    # Never expose the obsolete Recommended/All control. Rendering
                    # the canonical selector here (rather than merely returning
                    # ``All parameters``) also makes the very first monthly render
                    # safe when legacy cleanup happens to be the outer wrapper.
                    render_parameter_set()
                    return "All parameters"
                if label == "Parameter set" and tuple(values) == _PARAMETER_SET_OPTIONS:
                    # The contract-guidance wrapper may independently ask for the
                    # same widget. Return the value already rendered by this final
                    # guard so duplicate widget IDs cannot be created.
                    return render_parameter_set()
            return real_radio(label, values, *args, **kwargs)

        def expander(label: str, *args: Any, **kwargs: Any):
            if _monthly_active(st) and label == _MONTHLY_CONTEXT_LABEL:
                if context_seen["value"]:
                    return nullcontext()
                context_seen["value"] = True
            return real_expander(label, *args, **kwargs)

        st.caption = caption
        st.info = info
        st.radio = radio
        st.expander = expander
        try:
            previous(legacy, original)
        finally:
            st.caption = real_caption
            st.info = real_info
            st.radio = real_radio
            st.expander = real_expander

    parity._render_geosphere_resource_selector = selector
    _install_monthly_analysis_capability_note(st)

    # This guard is the final source-selector composition step. Install the
    # transactional measured-variable form only now, so it becomes the outermost
    # DataEditor wrapper and cannot bypass the canonical monthly Parameter-set
    # layer above. The form remains source-neutral and therefore also applies to
    # 10-minute and hourly GeoSphere resources.
    from .source_parity_ux_followup import install_geosphere_variable_form

    install_geosphere_variable_form(parity)
