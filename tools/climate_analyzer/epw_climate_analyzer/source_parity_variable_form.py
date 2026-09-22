"""Transactional GeoSphere measured-variable selection runtime contract.

The mature GeoSphere selector still calls ``st.data_editor`` to present provider
metadata.  This wrapper replaces that *editable transport* with a read-only table
plus a form-native ``st.multiselect`` keyed by provider identity.  Streamlit forms
batch multiselect changes reliably, so the submitted provider IDs are available
atomically on the submit rerun without depending on ``DataEditorState`` internals.

A valid submit is converted into exactly one mature provider-load button event in
the same Streamlit script run.  No GeoSphere provider request is issued while the
user is only staging variable choices.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable, Iterable

import pandas as pd


_GEOSPHERE_FORM_INSTALLED = "_GEOSPHERE_VARIABLE_FORM_INSTALLED_V1"
_FORM_KEY_PREFIX = "geosphere_variable_load_form_v1"
_FORM_REQUEST_KEY = "_geosphere_variable_form_load_requested_v2"
_FORM_ACTIVE_SCOPE_KEY = "_geosphere_variable_form_active_scope_v1"
_RESOURCE_KEY = "geosphere_resource_id"
_STATION_KEY = "geosphere_selected_station_id"
_SELECTION_KEY_PREFIX = "_geosphere_variable_form_provider_selection_v3"


def _selected_count(data: Any) -> int:
    if not isinstance(data, pd.DataFrame) or "Selected" not in data.columns:
        return 0
    return int(data["Selected"].fillna(False).astype(bool).sum())


def _provider_ids(data: pd.DataFrame) -> list[str]:
    if "Provider" not in data.columns:
        return []
    values: list[str] = []
    for value in data["Provider"].tolist():
        provider = str(value)
        if provider and provider not in values:
            values.append(provider)
    return values


def _provider_labels(data: pd.DataFrame) -> dict[str, str]:
    labels: dict[str, str] = {}
    for _, row in data.iterrows():
        provider = str(row.get("Provider", ""))
        if not provider or provider in labels:
            continue
        variable = str(row.get("Measured variable", provider)).strip() or provider
        unit = str(row.get("Unit", "")).strip()
        suffix = f" · {unit}" if unit and unit.lower() not in {"nan", "none"} else ""
        labels[provider] = f"{variable}{suffix} [{provider}]"
    return labels


def _apply_provider_selection(data: Any, selected_providers: Iterable[Any]) -> Any:
    """Return a copy whose ``Selected`` column follows submitted provider IDs."""
    if not isinstance(data, pd.DataFrame) or "Provider" not in data.columns:
        return data
    selected = {str(value) for value in selected_providers}
    out = data.copy()
    out["Selected"] = out["Provider"].astype(str).isin(selected)
    return out


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
    request = _request_scope(st)
    if request is None:
        return False
    return _restore_scope(st, request)


def geosphere_variable_form_owns_load_action(st: Any) -> bool:
    return st.session_state.get(_FORM_ACTIVE_SCOPE_KEY) == _scope(st)


def consume_geosphere_variable_form_load_request(st: Any) -> bool:
    request = _request_scope(st)
    if request is None:
        return False
    if not _restore_scope(st, request):
        st.session_state.pop(_FORM_REQUEST_KEY, None)
        return False
    st.session_state.pop(_FORM_REQUEST_KEY, None)
    return True


def install_geosphere_variable_form(parity: Any) -> None:
    """Replace editable-table transport with a form-native provider selector."""
    if bool(getattr(parity, _GEOSPHERE_FORM_INSTALLED, False)):
        return
    setattr(parity, _GEOSPHERE_FORM_INSTALLED, True)

    previous = parity._render_geosphere_resource_selector
    st = parity.st

    def selector(legacy: Any, original: Callable) -> Any:
        real_editor = st.data_editor
        real_button = st.button
        real_warning = st.warning
        real_dataframe = getattr(st, "dataframe", None)
        real_multiselect = getattr(st, "multiselect", None)
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
            if not callable(real_dataframe) or not callable(real_multiselect):
                return real_editor(data, *args, **kwargs)

            st.session_state.pop(_FORM_REQUEST_KEY, None)
            resource_id, station_id = _scope(st)
            submit_scope = (resource_id, station_id)
            form_signature = sha1(f"{resource_id}\0{station_id}".encode("utf-8")).hexdigest()[:12]
            editor_signature = sha1(editor_key.encode("utf-8")).hexdigest()[:10]
            form_key = f"{_FORM_KEY_PREFIX}::{form_signature}"
            selection_key = f"{_SELECTION_KEY_PREFIX}::{form_signature}::{editor_signature}"
            form_rendered["value"] = True
            st.session_state[_FORM_ACTIVE_SCOPE_KEY] = submit_scope

            providers = _provider_ids(data)
            labels = _provider_labels(data)
            # Zero-default is deliberate. Streamlit owns persistence of the
            # keyed multiselect after first render; changing parameter set or
            # station gets a different selection key and cannot leak choices.
            default: list[str] = []
            existing = st.session_state.get(selection_key)
            if isinstance(existing, (tuple, list, set)):
                default = [str(value) for value in existing if str(value) in providers]

            with st.form(form_key, clear_on_submit=False):
                display = data.drop(columns=["Selected"], errors="ignore")
                real_dataframe(display, hide_index=True, use_container_width=True)
                selected_providers = real_multiselect(
                    "Select measured variables",
                    options=providers,
                    default=default,
                    format_func=lambda provider: labels.get(str(provider), str(provider)),
                    key=selection_key,
                    help="Choose the measured GeoSphere fields to request when you submit this form.",
                )
                st.caption(
                    "Variable choices are staged locally. No GeoSphere data request is sent until you submit the form."
                )
                submitted = st.form_submit_button(
                    "Load measured GeoSphere interval",
                    type="primary",
                    help="Submit the current variable selection and start the provider request.",
                )

            edited = _apply_provider_selection(data, selected_providers)
            if submitted:
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
