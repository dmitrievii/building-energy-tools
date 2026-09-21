"""Stable provider-keyed selection state for the native-monthly source editor.

The mature source UI reuses ``geosphere_variable_editor`` for 10-minute, hourly
and monthly datasets.  Streamlit keys identify widget state, so reusing one key
for different provider vocabularies (and for filtered Core/Additional/All views)
can reconcile an old DataEditor state into the new table.  In the monthly path
that manifested as hundreds of stale selected rows, a missing visible table,
and the contradictory warning that air temperature was not selected.

This adapter is installed *after* the final contract-guidance wrapper.  It sees
the already filtered monthly table, gives each visible provider-set shape its own
widget key, and keeps the actual checkbox state in a provider-keyed session map.
Changing the catalogue view therefore changes visibility only; it does not let a
previous resource or a previous table shape overwrite the active selection.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable

import pandas as pd

from .geosphere_monthly import MONTHLY_RESOURCE_ID

_RESOURCE_KEY = "geosphere_resource_id"
_PARAMETER_SET_KEY = "geosphere_monthly_parameter_catalogue_v2"
_SELECTION_STATE_KEY = "_geosphere_monthly_provider_selection_v1"
_LAST_VIEW_KEY = "_geosphere_monthly_provider_selection_last_view_v1"


def _bool_value(value: Any) -> bool:
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return bool(value)


def _selection_state(st: Any, data: pd.DataFrame) -> dict[str, bool]:
    """Return/update the provider-keyed monthly selection map."""
    raw = st.session_state.get(_SELECTION_STATE_KEY, {})
    state = (
        {str(provider): _bool_value(value) for provider, value in raw.items()}
        if isinstance(raw, dict)
        else {}
    )
    if {"Provider", "Selected"}.issubset(data.columns):
        for _, row in data.iterrows():
            provider = str(row.get("Provider", "") or "").strip()
            if provider:
                state.setdefault(provider, _bool_value(row.get("Selected", False)))
    st.session_state[_SELECTION_STATE_KEY] = state
    return state


def _editor_key(view: str, providers: list[str]) -> str:
    """Return a widget key stable for one catalogue view/provider vocabulary."""
    slug = {
        "Core variables": "core",
        "Core + additional statistics": "core_additional",
        "All provider parameters": "all",
    }.get(str(view), "custom")
    signature = sha1("\0".join(providers).encode("utf-8")).hexdigest()[:12]
    return f"geosphere_variable_editor__monthly__{slug}__{signature}"


def install_monthly_selection_state(parity: Any) -> None:
    """Wrap the final GeoSphere selector with resource/view-safe DataEditor state."""
    previous = parity._render_geosphere_resource_selector
    st = parity.st

    def selector(legacy: Any, original: Callable) -> None:
        real_editor = st.data_editor

        def editor(data: Any, *args: Any, **kwargs: Any):
            if not (
                str(st.session_state.get(_RESOURCE_KEY, "")) == MONTHLY_RESOURCE_ID
                and isinstance(data, pd.DataFrame)
                and {"Provider", "Selected", "Role"}.issubset(data.columns)
            ):
                return real_editor(data, *args, **kwargs)

            prepared = data.copy()
            providers = prepared["Provider"].fillna("").astype(str).tolist()
            state = _selection_state(st, prepared)
            prepared["Selected"] = [state.get(provider, False) for provider in providers]

            view = str(st.session_state.get(_PARAMETER_SET_KEY, "Core variables"))
            widget_key = _editor_key(view, providers)

            # A view change must reconcile from the provider-keyed state rather
            # than resurrect a previously mounted DataEditor snapshot for that
            # view.  The next render then starts from ``prepared`` above.
            previous_view = str(st.session_state.get(_LAST_VIEW_KEY, ""))
            if previous_view != view:
                st.session_state.pop(widget_key, None)
            st.session_state[_LAST_VIEW_KEY] = view

            kwargs["key"] = widget_key
            edited = real_editor(prepared.reset_index(drop=True), *args, **kwargs)
            if not isinstance(edited, pd.DataFrame):
                return edited

            if {"Provider", "Selected"}.issubset(edited.columns):
                updated = dict(state)
                for _, row in edited.iterrows():
                    provider = str(row.get("Provider", "") or "").strip()
                    if provider:
                        updated[provider] = _bool_value(row.get("Selected", False))
                st.session_state[_SELECTION_STATE_KEY] = updated
            return edited

        st.data_editor = editor
        try:
            previous(legacy, original)
        finally:
            st.data_editor = real_editor

    parity._render_geosphere_resource_selector = selector
