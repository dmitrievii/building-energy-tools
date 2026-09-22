"""Transactional GeoSphere measured-variable form runtime contract.

The visible form stages DataEditor changes client-side. A valid submit commits a
resource/station-scoped one-shot request and immediately starts one clean
Streamlit rerun. The mature provider loader consumes that already-persisted
request on the following run. This deliberately separates form widget commit
from provider execution so the load action no longer depends on same-run wrapper
ordering.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable

import pandas as pd


_GEOSPHERE_FORM_INSTALLED = "_GEOSPHERE_VARIABLE_FORM_INSTALLED_V1"
_FORM_KEY_PREFIX = "geosphere_variable_load_form_v1"
_FORM_REQUEST_KEY = "_geosphere_variable_form_load_requested_v2"
_FORM_ACTIVE_SCOPE_KEY = "_geosphere_variable_form_active_scope_v1"


def _selected_count(data: Any) -> int:
    if not isinstance(data, pd.DataFrame) or "Selected" not in data.columns:
        return 0
    return int(data["Selected"].fillna(False).astype(bool).sum())


def _scope(st: Any) -> tuple[str, str]:
    return (
        str(st.session_state.get("geosphere_resource_id", "klima-v2-10min")),
        str(st.session_state.get("geosphere_selected_station_id", "")),
    )


def geosphere_variable_form_owns_load_action(st: Any) -> bool:
    """Return whether the current resource/station uses the transactional form action."""
    return st.session_state.get(_FORM_ACTIVE_SCOPE_KEY) == _scope(st)


def consume_geosphere_variable_form_load_request(st: Any) -> bool:
    """Consume one valid form-submit request for the current resource/station."""
    request = st.session_state.pop(_FORM_REQUEST_KEY, None)
    return request == _scope(st)


def install_geosphere_variable_form(parity: Any) -> None:
    """Stage editor changes and commit a valid submit for the next clean rerun."""
    if bool(getattr(parity, _GEOSPHERE_FORM_INSTALLED, False)):
        return
    setattr(parity, _GEOSPHERE_FORM_INSTALLED, True)

    previous = parity._render_geosphere_resource_selector
    st = parity.st

    def selector(legacy: Any, original: Callable) -> Any:
        real_editor = st.data_editor
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
            # Mark ownership on every render. Stale state from another
            # resource/station cannot suppress that scope's fallback action.
            st.session_state[_FORM_ACTIVE_SCOPE_KEY] = submit_scope

            with st.form(form_key, clear_on_submit=False):
                edited = real_editor(data, *args, **kwargs)
                st.caption(
                    "Variable choices are staged locally. Checking or unchecking rows does not reload this page and does not request GeoSphere data."
                )
                submitted = st.form_submit_button(
                    "Load measured GeoSphere interval",
                    type="primary",
                    help="Submit the current variable selection and start the provider request.",
                )

            if submitted:
                if _selected_count(edited) <= 0:
                    st.session_state.pop(_FORM_REQUEST_KEY, None)
                    real_warning("Select at least one measured GeoSphere variable to load.")
                else:
                    # Phase 1: persist the exact load request after Streamlit has
                    # committed the form's DataEditor values. End this script run
                    # deliberately. On the next run the request exists before any
                    # wrapper is composed, so the mature loader can consume it
                    # deterministically instead of depending on same-run widget
                    # return ordering.
                    st.session_state[_FORM_REQUEST_KEY] = submit_scope
                    st.rerun()
            return edited

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
        st.warning = warning
        try:
            return previous(legacy, original)
        finally:
            # Presentation proxies are selector-local. The scoped request is
            # intentionally durable across exactly one rerun until consumed.
            st.data_editor = real_editor
            st.warning = real_warning

    parity._render_geosphere_resource_selector = selector
