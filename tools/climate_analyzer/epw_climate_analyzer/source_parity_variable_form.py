"""Transactional GeoSphere measured-variable form runtime contract.

The visible form stages DataEditor changes client-side. A valid form submit is
committed synchronously in the same Streamlit run in which
``form_submit_button`` returns ``True``. The mature provider loader consumes the
resource/station-scoped one-shot request later in that same run. This avoids
using callback timing as event transport across reruns.
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
    """Stage editor changes in a form and publish a same-run one-shot load request."""
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
            # Mark ownership on every render. The production load boundary
            # compares this exact scope before suppressing the duplicate legacy
            # button, so stale state from another resource/station is inert.
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
                # ``submitted`` is true in the same script run that contains the
                # committed DataEditor values. Arm the exact current scope here,
                # immediately before the mature loader is reached. No callback
                # or cross-rerun closure is required.
                if _selected_count(edited) <= 0:
                    st.session_state.pop(_FORM_REQUEST_KEY, None)
                    real_warning("Select at least one measured GeoSphere variable to load.")
                else:
                    st.session_state[_FORM_REQUEST_KEY] = submit_scope
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
            # Presentation proxies are selector-local. Request/ownership state
            # survives only until the mature load boundary consumes it.
            st.data_editor = real_editor
            st.warning = real_warning

    parity._render_geosphere_resource_selector = selector
