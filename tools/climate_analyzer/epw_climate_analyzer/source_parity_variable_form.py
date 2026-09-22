"""Transactional GeoSphere measured-variable form runtime contract.

The visible form stages DataEditor changes client-side. A valid form submit is
committed by a Streamlit submit callback into one scoped request token. The
mature provider-load button can be rendered after the composed selector wrapper
has returned, so its exact button proxy intentionally survives that boundary and
restores itself only when the mature action is reached.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable

import pandas as pd


_GEOSPHERE_FORM_INSTALLED = "_GEOSPHERE_VARIABLE_FORM_INSTALLED_V1"
_FORM_KEY_PREFIX = "geosphere_variable_load_form_v1"
_FORM_REQUEST_KEY = "_geosphere_variable_form_load_requested_v2"
_MATURE_LOAD_KEY = "load_geosphere_interval"


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
    """Stage editor changes in a form and trigger the mature loader exactly once."""
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

        def editor(data: Any, *args: Any, **kwargs: Any):
            qualifies = (
                isinstance(data, pd.DataFrame)
                and {"Provider", "Selected", "Measured variable"}.issubset(data.columns)
                and str(kwargs.get("key", "")).startswith("geosphere_variable_editor")
            )
            if not qualifies:
                return real_editor(data, *args, **kwargs)

            resource_id, station_id = _scope(st)
            submit_scope = (resource_id, station_id)
            form_signature = sha1(f"{resource_id}\0{station_id}".encode("utf-8")).hexdigest()[:12]
            form_key = f"{_FORM_KEY_PREFIX}::{form_signature}"
            form_rendered["value"] = True

            def commit_submit() -> None:
                # Streamlit callbacks execute before the submit-triggered main
                # rerun. Keep the request until the exact mature loader consumes
                # it; selector.finally must not clear it prematurely.
                st.session_state[_FORM_REQUEST_KEY] = submit_scope

            with st.form(form_key, clear_on_submit=False):
                edited = real_editor(data, *args, **kwargs)
                st.caption(
                    "Variable choices are staged locally. Checking or unchecking rows does not reload this page and does not request GeoSphere data."
                )
                submitted = st.form_submit_button(
                    "Load measured GeoSphere interval",
                    type="primary",
                    help="Submit the current variable selection and start the provider request.",
                    on_click=commit_submit,
                )

            if submitted and _selected_count(edited) <= 0:
                # Empty submit must never arm a later provider request.
                if st.session_state.get(_FORM_REQUEST_KEY) == submit_scope:
                    st.session_state.pop(_FORM_REQUEST_KEY, None)
                real_warning("Select at least one measured GeoSphere variable to load.")
            return edited

        def button(label: Any, *args: Any, **kwargs: Any):
            # The mature action is rendered outside the composed selector in the
            # production source path. Forward all unrelated buttons unchanged and
            # consume the form token only at the exact mature key.
            if not (
                str(label) == "Load measured GeoSphere interval"
                and str(kwargs.get("key", "")) == _MATURE_LOAD_KEY
            ):
                return real_button(label, *args, **kwargs)

            request = st.session_state.pop(_FORM_REQUEST_KEY, None)
            # The bridge is one-shot. Restore the real Streamlit surface as soon
            # as the mature load boundary is reached, irrespective of token match.
            if st.button is button:
                st.button = real_button
            return request == _scope(st)

        def warning(body: Any, *args: Any, **kwargs: Any):
            # The form owns empty-selection validation. Suppress the mature
            # renderer's always-visible copy while the transactional form exists.
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
            # The data-editor and warning proxies are selector-local. The exact
            # button proxy deliberately survives this boundary because the mature
            # load button is rendered immediately afterwards in app.py; it
            # restores itself when that exact action is reached.
            st.data_editor = real_editor
            st.warning = real_warning

    parity._render_geosphere_resource_selector = selector
