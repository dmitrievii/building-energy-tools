"""Transactional GeoSphere measured-variable form runtime contract.

The visible form stages DataEditor changes client-side. A valid submit commits a
resource/station-scoped one-shot request and forwards that request directly into
the mature provider-load button later in the same Streamlit script run. The
submitted scope remains authoritative while the one-shot request is consumed,
so nested compatibility wrappers cannot invalidate a committed submit by
mutating routing state.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable

import pandas as pd


_GEOSPHERE_FORM_INSTALLED = "_GEOSPHERE_VARIABLE_FORM_INSTALLED_V1"
_FORM_KEY_PREFIX = "geosphere_variable_load_form_v1"
_FORM_REQUEST_KEY = "_geosphere_variable_form_load_requested_v2"
_FORM_ACTIVE_SCOPE_KEY = "_geosphere_variable_form_active_scope_v1"
_RESOURCE_KEY = "geosphere_resource_id"
_STATION_KEY = "geosphere_selected_station_id"


def _selected_count(data: Any) -> int:
    if not isinstance(data, pd.DataFrame) or "Selected" not in data.columns:
        return 0
    return int(data["Selected"].fillna(False).astype(bool).sum())


def _apply_submitted_editor_state(data: Any, state: Any) -> Any:
    """Overlay Streamlit's submitted DataEditor delta onto its returned frame.

    ``st.session_state[editor_key]`` is a Streamlit ``DataEditorState`` in the
    production runtime. It is intentionally a read-only dictionary-like object,
    not necessarily a built-in ``dict``. Use the mapping protocol instead of
    concrete-type checks so the submitted ``edited_rows`` payload is accepted.
    """
    if not isinstance(data, pd.DataFrame):
        return data

    getter = getattr(state, "get", None)
    if not callable(getter):
        return data
    edited_rows = getter("edited_rows")
    items = getattr(edited_rows, "items", None)
    if not callable(items):
        return data

    out = data.copy()
    changed = False
    for raw_row, changes in items():
        try:
            row = int(raw_row)
        except (TypeError, ValueError):
            continue
        change_items = getattr(changes, "items", None)
        if row < 0 or row >= len(out) or not callable(change_items):
            continue
        for column, value in change_items():
            if column not in out.columns:
                continue
            out.iat[row, out.columns.get_loc(column)] = value
            changed = True
    return out if changed else data


def _scope(st: Any) -> tuple[str, str]:
    return (
        str(st.session_state.get(_RESOURCE_KEY, "klima-v2-10min")),
        str(st.session_state.get(_STATION_KEY, "")),
    )


def _request_scope(st: Any) -> tuple[str, str] | None:
    request = st.session_state.get(_FORM_REQUEST_KEY)
    if not isinstance(request, (tuple, list)) or len(request) != 2:
        return None
    return (str(request[0]), str(request[1]))


def _restore_scope(st: Any, request: tuple[str, str]) -> bool:
    """Restore routing state without mutating Streamlit-owned widget state.

    This function can run after the GeoSphere resource selectbox has already
    been instantiated in the current script run. Streamlit forbids assigning to
    that widget's session-state key at that point. The provider-load handoff only
    needs the canonical routing resource/station keys, so leave the widget-owned
    selector key untouched.
    """
    resource_id, station_id = request
    if not resource_id or not station_id:
        return False
    st.session_state[_RESOURCE_KEY] = resource_id
    st.session_state[_STATION_KEY] = station_id
    return True


def restore_geosphere_variable_form_request_scope(st: Any) -> bool:
    """Restore the exact submitted routing resource/station while a request is pending."""
    request = _request_scope(st)
    if request is None:
        return False
    return _restore_scope(st, request)


def geosphere_variable_form_owns_load_action(st: Any) -> bool:
    """Return whether the current resource/station uses the transactional form action."""
    return st.session_state.get(_FORM_ACTIVE_SCOPE_KEY) == _scope(st)


def consume_geosphere_variable_form_load_request(st: Any) -> bool:
    """Consume exactly one valid form-submit request at the mature load boundary.

    The request is created only by a successful form submit. The submitted
    routing scope is restored immediately before consumption, then the one-shot
    token is removed. Widget-owned state is deliberately never written here
    because the resource selectbox already exists by the time the mature load
    button is evaluated in the same Streamlit run.
    """
    request = _request_scope(st)
    if request is None:
        return False
    if not _restore_scope(st, request):
        st.session_state.pop(_FORM_REQUEST_KEY, None)
        return False
    st.session_state.pop(_FORM_REQUEST_KEY, None)
    return True


def install_geosphere_variable_form(parity: Any) -> None:
    """Stage editor changes and forward one valid submit to the mature loader."""
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
            editor_key = str(kwargs.get("key", ""))
            qualifies = (
                isinstance(data, pd.DataFrame)
                and {"Provider", "Selected", "Measured variable"}.issubset(data.columns)
                and editor_key.startswith("geosphere_variable_editor")
            )
            if not qualifies:
                return real_editor(data, *args, **kwargs)

            # A fresh form render owns the load action for this exact scope. Any
            # stale token from a previously abandoned render must not fire later.
            st.session_state.pop(_FORM_REQUEST_KEY, None)
            resource_id, station_id = _scope(st)
            submit_scope = (resource_id, station_id)
            form_signature = sha1(f"{resource_id}\0{station_id}".encode("utf-8")).hexdigest()[:12]
            form_key = f"{_FORM_KEY_PREFIX}::{form_signature}"
            form_rendered["value"] = True
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
                # On a real Streamlit form submit the visible Glide edits can be
                # represented by the DataEditorState delta. Reconstruct before
                # validation *and* return the reconstructed frame so the mature
                # loader computes its parameter list from submitted checkboxes.
                edited = _apply_submitted_editor_state(
                    edited,
                    st.session_state.get(editor_key),
                )
                if _selected_count(edited) <= 0:
                    st.session_state.pop(_FORM_REQUEST_KEY, None)
                    real_warning("Select at least one measured GeoSphere variable to load.")
                else:
                    st.session_state[_FORM_REQUEST_KEY] = submit_scope
            return edited

        def button(label: Any, *args: Any, **kwargs: Any):
            is_mature_load = (
                str(label) == "Load measured GeoSphere interval"
                and str(kwargs.get("key", "")) == "load_geosphere_interval"
            )
            if is_mature_load:
                if consume_geosphere_variable_form_load_request(st):
                    return True
                if form_rendered["value"] or geosphere_variable_form_owns_load_action(st):
                    return False
            return real_button(label, *args, **kwargs)

        def warning(body: Any, *args: Any, **kwargs: Any):
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
