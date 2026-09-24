"""Schema-compatible transactional GeoSphere variable form installer.

The mature 10-minute/hourly selector exposes the display column as
``Measured variable`` while the native-monthly catalogue uses ``Variable``.
This compatibility layer replaces the follow-up installer before runtime
composition so both UI schemas enter the same Streamlit form contract.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable

import pandas as pd

from . import source_parity_ux_followup as ux
from .geosphere_monthly import MONTHLY_RESOURCE_ID
from .source_parity_monthly_selection_state import (
    _PARAMETER_SET_EPOCH_KEY,
    _PARAMETER_SET_RESET_PENDING_KEY,
)


_EMPTY_SELECTION_WARNING = "Select at least one measured GeoSphere variable to load."


def _is_variable_editor(data: Any, key: object) -> bool:
    if not isinstance(data, pd.DataFrame):
        return False
    if not {"Provider", "Selected"}.issubset(data.columns):
        return False
    if not ({"Measured variable", "Variable"} & set(data.columns)):
        return False
    return str(key or "").startswith("geosphere_variable_editor")


def _monthly_reset_pending(st: Any, epoch: int) -> bool:
    raw = st.session_state.get(_PARAMETER_SET_RESET_PENDING_KEY)
    if raw is None:
        return False
    try:
        return int(raw) == int(epoch)
    except (TypeError, ValueError):
        return False


def _clear_monthly_reset_barrier(st: Any, epoch: int) -> None:
    if not _monthly_reset_pending(st, epoch):
        return
    st.session_state.pop(_PARAMETER_SET_RESET_PENDING_KEY, None)


def install_geosphere_variable_form_compat(parity: Any) -> None:
    """Install the transactional variable form for every GeoSphere table schema."""
    marker = ux._GEOSPHERE_FORM_INSTALLED
    if bool(getattr(parity, marker, False)):
        return
    setattr(parity, marker, True)

    previous = parity._render_geosphere_resource_selector
    st = parity.st

    def selector(legacy: Any, original: Callable) -> Any:
        real_editor = st.data_editor
        real_button = st.button
        real_warning = st.warning
        form_rendered = {"value": False}
        empty_submit = {"value": False}

        def editor(data: Any, *args: Any, **kwargs: Any):
            if not _is_variable_editor(data, kwargs.get("key")):
                return real_editor(data, *args, **kwargs)

            st.session_state.pop(ux._FORM_REQUEST_KEY, None)
            resource_id, station_id = ux._scope(st)
            epoch = 0
            if resource_id == MONTHLY_RESOURCE_ID:
                try:
                    epoch = int(st.session_state.get(_PARAMETER_SET_EPOCH_KEY, 0))
                except (TypeError, ValueError):
                    epoch = 0
            reset_pending = (
                resource_id == MONTHLY_RESOURCE_ID
                and _monthly_reset_pending(st, epoch)
            )
            form_signature = sha1(
                f"{resource_id}\0{station_id}\0{epoch}".encode("utf-8")
            ).hexdigest()[:12]
            form_key = f"{ux._FORM_KEY_PREFIX}::{form_signature}"
            form_rendered["value"] = True

            with st.form(form_key, clear_on_submit=False):
                edited = real_editor(data, *args, **kwargs)
                # During the first render after a monthly Parameter-set change,
                # distrust any staged values reconciled from the retired form.
                # ``data`` is the clean server-owned table created for the new
                # reset epoch, so it is the only admissible submit payload until
                # that replacement form has completed one render.
                trusted = data.copy() if reset_pending and isinstance(data, pd.DataFrame) else edited
                st.caption(
                    "Variable choices are staged locally. Checking or unchecking rows does not reload this page and does not request GeoSphere data."
                )
                submitted = st.form_submit_button(
                    "Load measured GeoSphere interval",
                    type="primary",
                    help="Submit the current variable selection and start the provider request.",
                )
                if submitted:
                    if ux._selected_count(trusted) <= 0:
                        empty_submit["value"] = True
                    else:
                        st.session_state[ux._FORM_REQUEST_KEY] = (resource_id, station_id)

            if reset_pending:
                _clear_monthly_reset_barrier(st, epoch)
                return data.copy() if isinstance(data, pd.DataFrame) else edited
            return edited

        def button(label: Any, *args: Any, **kwargs: Any):
            if str(label) != "Load measured GeoSphere interval":
                return real_button(label, *args, **kwargs)
            request = st.session_state.pop(ux._FORM_REQUEST_KEY, None)
            return request == ux._scope(st)

        def warning(body: Any, *args: Any, **kwargs: Any):
            if (
                form_rendered["value"]
                and str(body).strip() == _EMPTY_SELECTION_WARNING
            ):
                return None
            return real_warning(body, *args, **kwargs)

        st.data_editor = editor
        st.button = button
        st.warning = warning
        try:
            result = previous(legacy, original)
            if empty_submit["value"]:
                real_warning(_EMPTY_SELECTION_WARNING)
            return result
        finally:
            st.data_editor = real_editor
            st.button = real_button
            st.warning = real_warning

    parity._render_geosphere_resource_selector = selector


def patch_variable_form_installer() -> None:
    """Publish the schema-compatible installer for a fresh runtime composition.

    ``importlib.reload(source_parity_ui)`` re-executes the module in its existing
    dictionary and therefore does not remove dynamically-added attributes. The
    form-installed marker is one such attribute: without clearing it, a second
    browser session in the same Streamlit process can inherit ``True`` from the
    first session and skip installing the form into its newly composed selector.
    Reset that marker before composition starts, then make every downstream call
    to the shared installer resolve to this compatibility owner.
    """
    from . import source_parity_ui as parity

    marker = ux._GEOSPHERE_FORM_INSTALLED
    if hasattr(parity, marker):
        delattr(parity, marker)
    ux.install_geosphere_variable_form = install_geosphere_variable_form_compat
