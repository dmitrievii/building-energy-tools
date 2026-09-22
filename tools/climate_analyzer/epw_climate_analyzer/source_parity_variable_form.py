"""Transactional GeoSphere measured-variable form runtime contract.

The visible form stages DataEditor changes client-side. A valid submit snapshots
Streamlit's submitted DataEditor state in the form-submit callback, then forwards
one resource/station-scoped request into the mature provider-load button in the
same script run. Capturing the editor delta in the callback is deliberate: form
callbacks run before the post-submit script rerun can re-instantiate the editor
and normalize its widget state.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable

import pandas as pd


_GEOSPHERE_FORM_INSTALLED = "_GEOSPHERE_VARIABLE_FORM_INSTALLED_V1"
_FORM_KEY_PREFIX = "geosphere_variable_load_form_v1"
_FORM_REQUEST_KEY = "_geosphere_variable_form_load_requested_v2"
_FORM_ACTIVE_SCOPE_KEY = "_geosphere_variable_form_active_scope_v1"
_FORM_SUBMITTED_EDITOR_STATE_KEY = "_geosphere_variable_form_submitted_editor_state_v1"
_RESOURCE_KEY = "geosphere_resource_id"
_STATION_KEY = "geosphere_selected_station_id"


def _selected_count(data: Any) -> int:
    if not isinstance(data, pd.DataFrame) or "Selected" not in data.columns:
        return 0
    return int(data["Selected"].fillna(False).astype(bool).sum())


def _editor_state_snapshot(state: Any) -> dict[str, Any]:
    """Copy the immutable Streamlit DataEditorState into plain Python data."""
    getter = getattr(state, "get", None)
    if not callable(getter):
        return {"edited_rows": {}}

    edited_rows = getter("edited_rows", {})
    items = getattr(edited_rows, "items", None)
    if not callable(items):
        return {"edited_rows": {}}

    copied: dict[int, dict[str, Any]] = {}
    for raw_row, changes in items():
        try:
            row = int(raw_row)
        except (TypeError, ValueError):
            continue
        change_items = getattr(changes, "items", None)
        if not callable(change_items):
            continue
        copied[row] = {str(column): value for column, value in change_items()}
    return {"edited_rows": copied}


def _capture_submitted_editor_state(
    st: Any,
    editor_key: str,
    submit_scope: tuple[str, str],
) -> None:
    """Snapshot form widget state before Streamlit starts the submit rerun."""
    st.session_state[_FORM_SUBMITTED_EDITOR_STATE_KEY] = {
        "editor_key": str(editor_key),
        "scope": (str(submit_scope[0]), str(submit_scope[1])),
        "state": _editor_state_snapshot(st.session_state.get(editor_key)),
    }


def _consume_submitted_editor_state(
    st: Any,
    editor_key: str,
    submit_scope: tuple[str, str],
) -> Any:
    """Consume only the callback snapshot belonging to this exact form scope."""
    payload = st.session_state.pop(_FORM_SUBMITTED_EDITOR_STATE_KEY, None)
    getter = getattr(payload, "get", None)
    if not callable(getter):
        return None
    if str(getter("editor_key", "")) != str(editor_key):
        return None
    scope = getter("scope")
    if not isinstance(scope, (tuple, list)) or len(scope) != 2:
        return None
    normalized_scope = (str(scope[0]), str(scope[1]))
    if normalized_scope != (str(submit_scope[0]), str(submit_scope[1])):
        return None
    return getter("state")


def _apply_submitted_editor_state(data: Any, state: Any) -> Any:
    """Overlay a submitted DataEditor ``edited_rows`` delta onto ``data``."""
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
    """Restore routing state without mutating Streamlit-owned widget state."""
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
    """Consume exactly one valid form-submit request at the mature load boundary."""
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
            # stale provider token from a previously abandoned render must not fire.
            st.session_state.pop(_FORM_REQUEST_KEY, None)
            resource_id, station_id = _scope(st)
            submit_scope = (resource_id, station_id)
            form_signature = sha1(f"{resource_id}\0{station_id}".encode("utf-8")).hexdigest()[:12]
            form_key = f"{_FORM_KEY_PREFIX}::{form_signature}"
            form_rendered["value"] = True
            st.session_state[_FORM_ACTIVE_SCOPE_KEY] = submit_scope

            def capture_submit() -> None:
                _capture_submitted_editor_state(st, editor_key, submit_scope)

            with st.form(form_key, clear_on_submit=False):
                edited = real_editor(data, *args, **kwargs)
                st.caption(
                    "Variable choices are staged locally. Checking or unchecking rows does not reload this page and does not request GeoSphere data."
                )
                submitted = st.form_submit_button(
                    "Load measured GeoSphere interval",
                    type="primary",
                    help="Submit the current variable selection and start the provider request.",
                    on_click=capture_submit,
                )

            if submitted:
                # The form-submit callback runs before this script rerun. Consume
                # that immutable snapshot instead of inspecting the editor widget
                # after it has already been re-instantiated in the current run.
                submitted_state = _consume_submitted_editor_state(
                    st,
                    editor_key,
                    submit_scope,
                )
                if submitted_state is None:
                    # Defensive fallback for synthetic/unit runtimes where form
                    # callbacks may not execute like real Streamlit callbacks.
                    submitted_state = st.session_state.get(editor_key)
                edited = _apply_submitted_editor_state(edited, submitted_state)
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
