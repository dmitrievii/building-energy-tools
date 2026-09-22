"""Stable provider-keyed selection state for the native-monthly source editor.

The mature source UI reuses ``geosphere_variable_editor`` for 10-minute, hourly
and monthly datasets. Streamlit keys identify widget state, so reusing one key
for different provider vocabularies (and for filtered Core/Additional/All views)
can reconcile an old DataEditor state into the new table.

This adapter owns monthly selection semantics independently of the mature shell's
legacy ``Selected=True`` table default. A fresh monthly session starts with every
measured-variable checkbox cleared. The catalogue radio changes visibility only,
and later user edits are retained by provider ID across Core/Additional/All views.
The loader is always fed a table reconstructed in the original provider order;
therefore UI sorting/filtering can never change provider identity by row position.
"""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Callable

import pandas as pd

from .geosphere_monthly import MONTHLY_RESOURCE_ID
from .source_parity_contract_closure import CORE_MONTHLY_PROVIDERS
from .source_parity_contract_guidance_hotfix import _decorate_monthly_table

_RESOURCE_KEY = "geosphere_resource_id"
_PARAMETER_SET_KEY = "geosphere_monthly_parameter_catalogue_v2"
# v4 deliberately invalidates the former v3 Core-selected session state. Without
# a version bump, an already-open production browser could resurrect the old
# checked defaults after deployment even though the new contract starts empty.
_SELECTION_STATE_KEY = "_geosphere_monthly_provider_selection_v4"
_FLAG_STATE_KEY = "_geosphere_monthly_provider_flag_selection_v4"
_LAST_VIEW_KEY = "_geosphere_monthly_provider_selection_last_view_v4"
_EDITOR_KEY_VERSION = "v2"


def _bool_value(value: Any) -> bool:
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return False
    except (TypeError, ValueError):
        pass
    return bool(value)


def _provider_state(
    st: Any,
    key: str,
    data: pd.DataFrame,
    column: str,
    *,
    default: bool | Callable[[pd.Series], bool] | None = None,
) -> dict[str, bool]:
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
            if not provider or provider in state:
                continue
            if callable(default):
                state[provider] = _bool_value(default(row))
            elif default is not None:
                state[provider] = _bool_value(default)
            else:
                state[provider] = _bool_value(row.get(column, False))
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
    return f"geosphere_variable_editor__monthly__{_EDITOR_KEY_VERSION}__{slug}__{signature}"


def _normalize_catalogue_roles(data: pd.DataFrame) -> pd.DataFrame:
    """Enforce the user-facing Core/Additional contract deterministically."""
    out = data.copy()
    if {"Provider", "Role"}.issubset(out.columns):
        providers = out["Provider"].fillna("").astype(str)
        demote = out["Role"].astype(str).eq("Core variable") & ~providers.isin(CORE_MONTHLY_PROVIDERS)
        out.loc[demote, "Role"] = "Additional statistic"
        role_order = {"Core variable": 0, "Additional statistic": 1, "Other provider parameter": 2}
        out["_normalized_role_order"] = out["Role"].map(role_order).fillna(9)
        sort_columns = [
            column
            for column in ("_normalized_role_order", "Category", "Measured variable", "Provider")
            if column in out.columns
        ]
        if sort_columns:
            out = out.sort_values(sort_columns, kind="stable")
        out = out.drop(columns=["_normalized_role_order"], errors="ignore")
    return out


def _visible_catalogue(parity: Any, data: pd.DataFrame, view: str) -> pd.DataFrame:
    """Return the requested monthly catalogue slice from raw or decorated input."""
    prepared = _normalize_catalogue_roles(_decorate_monthly_table(parity, data))
    if "Role" not in prepared.columns:
        return prepared
    if view == "Core variables":
        prepared = prepared.loc[prepared["Role"] == "Core variable"].copy()
    elif view == "Core + additional statistics":
        prepared = prepared.loc[
            prepared["Role"].isin(["Core variable", "Additional statistic"])
        ].copy()
    return prepared


def _loader_table_from_provider_state(
    data: pd.DataFrame,
    selection_state: dict[str, bool],
    flag_state: dict[str, bool],
) -> pd.DataFrame:
    """Rebuild the shell-facing loader table in original provider order.

    The DataEditor may be sorted, filtered or reconciled by Streamlit. The mature
    loader derives its provider query directly from the DataFrame it receives back
    from ``st.data_editor``. Reconstructing that result from the original table and
    provider-keyed state makes provider identity independent of UI row position.
    """
    out = data.copy()
    if "Provider" not in out.columns:
        return out
    providers = out["Provider"].fillna("").astype(str)
    if "Selected" in out.columns:
        out["Selected"] = [bool(selection_state.get(provider, False)) for provider in providers]
    if "Quality flag" in out.columns:
        out["Quality flag"] = [bool(flag_state.get(provider, False)) for provider in providers]
    return out.reset_index(drop=True)


def install_monthly_selection_state(parity: Any) -> None:
    """Wrap the GeoSphere selector with resource/view-safe DataEditor state."""
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

            full = _normalize_catalogue_roles(_decorate_monthly_table(parity, data))
            # Selection is opt-in for every GeoSphere resolution. Core/Additional
            # describes catalogue visibility and engineering relevance only; it
            # must not silently turn provider downloads on.
            selection_state = _provider_state(
                st,
                _SELECTION_STATE_KEY,
                full,
                "Selected",
                default=False,
            )
            flag_state = _provider_state(
                st,
                _FLAG_STATE_KEY,
                full,
                "Quality flag",
                default=False,
            )
            prepared = _visible_catalogue(parity, full, view)

            providers = prepared["Provider"].fillna("").astype(str).tolist()
            prepared["Selected"] = [selection_state.get(provider, False) for provider in providers]
            if "Quality flag" in prepared.columns:
                prepared["Quality flag"] = [flag_state.get(provider, False) for provider in providers]

            widget_key = _editor_key(view, providers)
            previous_view = str(st.session_state.get(_LAST_VIEW_KEY, ""))
            view_changed = previous_view != view
            if view_changed:
                # The rerun was caused by changing Parameter set, not by editing
                # a checkbox. Drop any old widget snapshot and do not ingest its
                # row-position deltas into provider state on this render.
                st.session_state.pop(widget_key, None)
            st.session_state[_LAST_VIEW_KEY] = view

            kwargs["key"] = widget_key
            edited = real_editor(prepared.reset_index(drop=True), *args, **kwargs)

            if isinstance(edited, pd.DataFrame) and not view_changed:
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
                    selection_state = updated
                    st.session_state[_SELECTION_STATE_KEY] = updated

                if {"Provider", "Quality flag"}.issubset(edited.columns):
                    updated_flags = dict(flag_state)
                    for _, row in edited.iterrows():
                        provider = str(row.get("Provider", "") or "").strip()
                        if provider:
                            updated_flags[provider] = _bool_value(row.get("Quality flag", False))
                    flag_state = updated_flags
                    st.session_state[_FLAG_STATE_KEY] = updated_flags

            return _loader_table_from_provider_state(data, selection_state, flag_state)

        st.data_editor = editor
        try:
            previous(legacy, original)
        finally:
            st.data_editor = real_editor

    parity._render_geosphere_resource_selector = selector
