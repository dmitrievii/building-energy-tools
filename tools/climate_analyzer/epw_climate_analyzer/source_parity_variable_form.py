"""Transactional GeoSphere measured-variable form runtime contract.

The visible form stages DataEditor changes client-side and hands a valid submit
directly to the mature provider loader later in the same Streamlit script run.
No persistent request flag is used: the form submit and the mature load-button
branch are part of one execution, so a one-shot closure is both simpler and
immune to session-state reconciliation between nested runtime wrappers.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable

import pandas as pd


_GEOSPHERE_FORM_INSTALLED = "_GEOSPHERE_VARIABLE_FORM_INSTALLED_V1"
_FORM_KEY_PREFIX = "geosphere_variable_load_form_v1"
_MATURE_LOAD_BUTTON_KEY = "load_geosphere_interval"
_MATURE_LOAD_BUTTON_LABEL = "Load measured GeoSphere interval"


def _selected_count(data: Any) -> int:
    if not isinstance(data, pd.DataFrame) or "Selected" not in data.columns:
        return 0
    return int(data["Selected"].fillna(False).astype(bool).sum())


def _scope(st: Any) -> tuple[str, str]:
    return (
        str(st.session_state.get("geosphere_resource_id", "klima-v2-10min")),
        str(st.session_state.get("geosphere_selected_station_id", "")),
    )


def install_geosphere_variable_form(parity: Any) -> None:
    """Stage editor changes in a form and trigger the mature loader once."""
    if bool(getattr(parity, _GEOSPHERE_FORM_INSTALLED, False)):
        return
    setattr(parity, _GEOSPHERE_FORM_INSTALLED, True)

    previous = parity._render_geosphere_resource_selector
    st = parity.st

    def selector(legacy: Any, original: Callable) -> Any:
        real_editor = st.data_editor
        real_button = st.button
        real_warning = st.warning
        form_rendered = {"value": False}
        load_requested = {"value": False}

        def editor(data: Any, *args: Any, **kwargs: Any):
            qualifies = (
                isinstance(data, pd.DataFrame)
                and {"Provider", "Selected", "Measured variable"}.issubset(data.columns)
                and str(kwargs.get("key", "")).startswith("geosphere_variable_editor")
            )
            if not qualifies:
                return real_editor(data, *args, **kwargs)

            resource_id, station_id = _scope(st)
            form_signature = sha1(f"{resource_id}\0{station_id}".encode("utf-8")).hexdigest()[:12]
            form_key = f"{_FORM_KEY_PREFIX}::{form_signature}"
            form_rendered["value"] = True

            with st.form(form_key, clear_on_submit=False):
                edited = real_editor(data, *args, **kwargs)
                st.caption(
                    "Variable choices are staged locally. Checking or unchecking rows does not reload this page and does not request GeoSphere data."
                )
                submitted = st.form_submit_button(
                    _MATURE_LOAD_BUTTON_LABEL,
                    type="primary",
                    help="Submit the current variable selection and start the provider request.",
                )
                if submitted:
                    if _selected_count(edited) <= 0:
                        real_warning("Select at least one measured GeoSphere variable to load.")
                    else:
                        # The mature loader is evaluated later in this same
                        # selector execution. Keep the event pending until the
                        # exact mature action is reached; matching only the label
                        # is unsafe because composed wrappers may probe/render the
                        # same user-facing action before the real load branch.
                        load_requested["value"] = True
            return edited

        def button(label: Any, *args: Any, **kwargs: Any):
            key = str(kwargs.get("key", ""))
            if key != _MATURE_LOAD_BUTTON_KEY:
                return real_button(label, *args, **kwargs)

            # The mature provider-load branch has a stable explicit key in the
            # source-of-truth app. Consume the staged form submit only here, so
            # no earlier wrapper/button probe can steal the one-shot event.
            requested = bool(load_requested["value"])
            load_requested["value"] = False
            return requested

        def warning(body: Any, *args: Any, **kwargs: Any):
            # The form owns empty-selection validation. Suppress the mature
            # renderer's always-visible copy while the form is on screen.
            if (
                form_rendered["value"]
                and str(body).strip() == "Select at least one measured GeoSphere variable to load."
            ):
                return None
            return real_warning(body, *args, **kwargs)

        st.data_editor = editor
        st.button = button
        st.warning = warning
        try:
            return previous(legacy, original)
        finally:
            st.data_editor = real_editor
            st.button = real_button
            st.warning = real_warning

    parity._render_geosphere_resource_selector = selector
