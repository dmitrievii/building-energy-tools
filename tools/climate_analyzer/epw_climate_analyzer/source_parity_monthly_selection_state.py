"""Stable provider-keyed selection state for the native-monthly source editor.

The mature source UI reuses ``geosphere_variable_editor`` for 10-minute, hourly
and monthly datasets. Streamlit keys identify widget state, so reusing one key
for different provider vocabularies (and for filtered Core/Additional/All views)
can reconcile an old DataEditor state into the new table. In the monthly path
that manifested as hundreds of stale selected rows, a missing visible table,
and the contradictory warning that air temperature was not selected.

This adapter is installed after the composed source-selector stack. It therefore
acts as the final DataEditor boundary: it decorates/filters the monthly catalogue
again if necessary, assigns a resource/view-specific widget key, and keeps the
actual checkbox state in provider-keyed session maps. The catalogue radio changes
visibility only; provider selection never leaks from another GeoSphere resource
or from an incompatible DataEditor table shape.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable

import pandas as pd

from .geosphere_monthly import MONTHLY_RESOURCE_ID
from .source_parity_contract_guidance_hotfix import _decorate_monthly_table

_RESOURCE_KEY = "geosphere_resource_id"
_PARAMETER_SET_KEY = "geosphere_monthly_parameter_catalogue_v2"
_SELECTION_STATE_KEY = "_geosphere_monthly_provider_selection_v1"
_FLAG_STATE_KEY = "_geosphere_monthly_provider_flag_selection_v1"
_LAST_VIEW_KEY = "_geosphere_monthly_provider_selection_last_view_v1"


def _bool_value(value: Any) -> bool:
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return False
    except (TypeError, ValueError):
        pass
    return bool(value)


def _provider_state(st: Any, key: str, data: pd.DataFrame, column: str) -> dict[str, bool]:
    """Return/update one provider-keyed boolean state map."""
    raw = st.session_state.get(key, {})
    state = (
        {str(provider): _bool_value(value) for provider, value in raw.items()}
        if isinstance(raw, dict)
        else {}
    )
    if {"Provider", column}.issubset(data.columns):
        for _, row in data.iterrows():
            provider = str(row.get("Provider", "") or "").strip()
            if provider:
                state.setdefault(provider, _bool_value(row.get(column, False)))
    st.session_state[key] = state
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


def _visible_catalogue(parity: Any, data: pd.DataFrame, view: str) -> pd.DataFrame:
    """Return the requested monthly catalogue slice from raw or decorated input."""
    prepared = _decorate_monthly_table(parity, data)
    if "Role" not in prepared.columns:
        return prepared
    if view == "Core variables":
        prepared = prepared.loc[prepared["Role"] == "Core variable"].copy()
    elif view == "Core + additional statistics":
        prepared = prepared.loc[
            prepared["Role"].isin(["Core variable", "Additional statistic"])
        ].copy()
    return prepared


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
                and {"Provider", "Selected"}.issubset(data.columns)
            ):
                return real_editor(data, *args, **kwargs)

            view = str(st.session_state.get(_PARAMETER_SET_KEY, "Core variables"))
            if view not in {
                "Core variables",
                "Core + additional statistics",
                "All provider parameters",
            }:
                view = "Core variables"

            # Own decoration/filtering at this final boundary instead of relying
            # on wrapper order. This is intentionally idempotent for an already
            # decorated table.
            full = _decorate_monthly_table(parity, data)
            selection_state = _provider_state(st, _SELECTION_STATE_KEY, full, "Selected")
            flag_state = _provider_state(st, _FLAG_STATE_KEY, full, "Quality flag")
            prepared = _visible_catalogue(parity, full, view)

            providers = prepared["Provider"].fillna("").astype(str).tolist()
            prepared["Selected"] = [selection_state.get(provider, False) for provider in providers]
            if "Quality flag" in prepared.columns:
                prepared["Quality flag"] = [flag_state.get(provider, False) for provider in providers]

            widget_key = _editor_key(view, providers)
            previous_view = str(st.session_state.get(_LAST_VIEW_KEY, ""))
            if previous_view != view:
                # Re-entering an existing view must start from the provider map,
                # not a stale DataEditor snapshot created before another view
                # changed the same providers.
                st.session_state.pop(widget_key, None)
            st.session_state[_LAST_VIEW_KEY] = view

            kwargs["key"] = widget_key
            edited = real_editor(prepared.reset_index(drop=True), *args, **kwargs)
            if not isinstance(edited, pd.DataFrame):
                return edited

            # Fail closed against any unexpected stale Streamlit reconciliation:
            # the legacy loader may receive only providers visible in the active
            # parameter set, never rows from another resource/table shape.
            visible = set(providers)
            if "Provider" in edited.columns:
                edited = edited.loc[
                    edited["Provider"].fillna("").astype(str).isin(visible)
                ].copy()
            else:
                edited = prepared.reset_index(drop=True)

            if {"Provider", "Selected"}.issubset(edited.columns):
                updated = dict(selection_state)
                for _, row in edited.iterrows():
                    provider = str(row.get("Provider", "") or "").strip()
                    if provider:
                        updated[provider] = _bool_value(row.get("Selected", False))
                st.session_state[_SELECTION_STATE_KEY] = updated

            if {"Provider", "Quality flag"}.issubset(edited.columns):
                updated_flags = dict(flag_state)
                for _, row in edited.iterrows():
                    provider = str(row.get("Provider", "") or "").strip()
                    if provider:
                        updated_flags[provider] = _bool_value(row.get("Quality flag", False))
                st.session_state[_FLAG_STATE_KEY] = updated_flags
            return edited.reset_index(drop=True)

        st.data_editor = editor
        try:
            previous(legacy, original)
        finally:
            st.data_editor = real_editor

    parity._render_geosphere_resource_selector = selector
