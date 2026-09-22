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


def _is_variable_editor(data: Any, key: object) -> bool:
    if not isinstance(data, pd.DataFrame):
        return False
    if not {"Provider", "Selected"}.issubset(data.columns):
        return False
    if not ({"Measured variable", "Variable"} & set(data.columns)):
        return False
    return str(key or "").startswith("geosphere_variable_editor")


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

        def editor(data: Any, *args: Any, **kwargs: Any):
            if not _is_variable_editor(data, kwargs.get("key")):
                return real_editor(data, *args, **kwargs)

            st.session_state.pop(ux._FORM_REQUEST_KEY, None)
            resource_id, station_id = ux._scope(st)
            form_signature = sha1(f"{resource_id}\0{station_id}".encode("utf-8")).hexdigest()[:12]
            form_key = f"{ux._FORM_KEY_PREFIX}::{form_signature}"
            form_rendered["value"] = True

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
                    if ux._selected_count(edited) <= 0:
                        real_warning("Select at least one measured GeoSphere variable to load.")
                    else:
                        st.session_state[ux._FORM_REQUEST_KEY] = (resource_id, station_id)
            return edited

        def button(label: Any, *args: Any, **kwargs: Any):
            if str(label) != "Load measured GeoSphere interval":
                return real_button(label, *args, **kwargs)
            request = st.session_state.pop(ux._FORM_REQUEST_KEY, None)
            return request == ux._scope(st)

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


def patch_variable_form_installer() -> None:
    """Publish the schema-compatible installer for a fresh runtime composition.

    ``importlib.reload(source_parity_ui)`` re-executes the module in its existing
    dictionary and therefore does not remove dynamically-added attributes. The
    form-installed marker is one such attribute: without clearing it, a second
    browser session in the same Streamlit process can inherit ``True`` from the
    first session and skip installing the form into its newly composed selector.
    Reset that marker here before the final monthly surface guard installs the
    form for the current app-script session.
    """
    from . import source_parity_ui as parity

    marker = ux._GEOSPHERE_FORM_INSTALLED
    if hasattr(parity, marker):
        delattr(parity, marker)
    ux.install_geosphere_variable_form = install_geosphere_variable_form_compat
