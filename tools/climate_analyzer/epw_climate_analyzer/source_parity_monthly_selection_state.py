"""Deterministic provider-keyed selection state for the native-monthly source editor.

The mature source UI reuses ``geosphere_variable_editor`` for 10-minute, hourly
and monthly datasets. Streamlit keys identify widget state, so reusing one key
for different provider vocabularies can reconcile an old DataEditor state into a
new table.

This adapter owns monthly selection semantics independently of the mature shell's
legacy ``Selected=True`` table default. A fresh monthly session starts with every
measured-variable checkbox cleared. Changing the Parameter set is an explicit
selection boundary: Core / Core+Additional / All never inherit checkboxes or
quality-flag choices from the previous view. Within one unchanged view, provider
IDs still own row identity so sorting/reordering cannot change which parameter is
selected. The loader is always fed a table reconstructed in original provider
order.
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
# v5 invalidates earlier cross-view selection preservation. Parameter-set changes
# now intentionally reset both variable and quality-flag selections.
_SELECTION_STATE_KEY = "_geosphere_monthly_provider_selection_v5"
_FLAG_STATE_KEY = "_geosphere_monthly_provider_flag_selection_v5"
_LAST_VIEW_KEY = "_geosphere_monthly_provider_selection_last_view_v5"
_PARAMETER_SET_EPOCH_KEY = "_geosphere_monthly_parameter_set_epoch_v1"
_EDITOR_KEY_VERSION = "v3"
_MONTHLY_EDITOR_KEY_PREFIX = "geosphere_variable_editor__monthly__"
_FORM_REQUEST_KEY = "_geosphere_variable_form_load_requested_v1"


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


def _parameter_set_epoch(st: Any) -> int:
    try:
        return max(0, int(st.session_state.get(_PARAMETER_SET_EPOCH_KEY, 0)))
    except (TypeError, ValueError):
        return 0


def _editor_key(view: str, providers: list[str], *, epoch: int = 0) -> str:
    """Return a widget key stable only inside one catalogue-view reset epoch."""
    slug = {
        "Core variables": "core",
        "Core + additional statistics": "core_additional",
        "All provider parameters": "all",
    }.get(str(view), "custom")
    signature = sha1("\0".join(providers).encode("utf-8")).hexdigest()[:12]
    return (
        f"{_MONTHLY_EDITOR_KEY_PREFIX}{_EDITOR_KEY_VERSION}__{slug}__{signature}"
        f"__epoch_{max(0, int(epoch))}"
    )


def reset_monthly_parameter_set_state(st: Any) -> int:
    """Clear every monthly selection surface and advance the reset epoch.

    ``st.data_editor`` lives inside a form, so browser-side staged edits are not
    available to the server when the external Parameter-set radio triggers a
    rerun. The reset therefore belongs to the monthly selection adapter itself:
    once that adapter observes that the catalogue view changed, it clears the
    provider state, discards every monthly editor snapshot, invalidates a latent
    form-load token and advances an epoch used by both the transactional form and
    the DataEditor widget identity.
    """
    state = st.session_state
    state[_SELECTION_STATE_KEY] = {}
    state[_FLAG_STATE_KEY] = {}
    state.pop(_LAST_VIEW_KEY, None)
    state.pop(_FORM_REQUEST_KEY, None)
    for key in list(state.keys()):
        if str(key).startswith(_MONTHLY_EDITOR_KEY_PREFIX):
            state.pop(key, None)
    try:
        epoch = int(state.get(_PARAMETER_SET_EPOCH_KEY, 0)) + 1
    except (TypeError, ValueError):
        epoch = 1
    state[_PARAMETER_SET_EPOCH_KEY] = epoch
    return epoch


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

    The DataEditor may be sorted or reconciled by Streamlit. The mature loader
    derives its provider query directly from the DataFrame it receives back from
    ``st.data_editor``. Reconstructing that result from the original table and
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


def _cleared_provider_state(data: pd.DataFrame) -> dict[str, bool]:
    if "Provider" not in data.columns:
        return {}
    return {
        str(provider): False
        for provider in data["Provider"].fillna("").astype(str).tolist()
        if str(provider).strip()
    }


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
            previous_view = str(st.session_state.get(_LAST_VIEW_KEY, ""))
            view_changed = bool(previous_view) and previous_view != view

            # Detect the catalogue transition on the server in the same rerun in
            # which the new view is rendered. This is intentionally independent
            # of ``radio(on_change=...)`` timing: the old view has already been
            # persisted by the previous completed render, while ``view`` comes
            # from the newly committed radio value. Resetting here guarantees
            # that the epoch changes before either the new form or DataEditor key
            # is constructed.
            if view_changed:
                reset_monthly_parameter_set_state(st)

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
            st.session_state[_LAST_VIEW_KEY] = view

            prepared = _visible_catalogue(parity, full, view)
            providers = prepared["Provider"].fillna("").astype(str).tolist()
            prepared["Selected"] = [selection_state.get(provider, False) for provider in providers]
            if "Quality flag" in prepared.columns:
                prepared["Quality flag"] = [flag_state.get(provider, False) for provider in providers]

            # A Parameter-set reset must invalidate the browser-side Glide widget
            # itself, not only its server-side session-state snapshot. Reusing the
            # same DataEditor key lets the frontend reconcile an old checked cell
            # back into the freshly-cleared DataFrame. The server-detected epoch
            # therefore forms part of the widget identity as well as the
            # surrounding transactional form identity.
            widget_key = _editor_key(view, providers, epoch=_parameter_set_epoch(st))
            if view_changed:
                st.session_state.pop(widget_key, None)

            kwargs["key"] = widget_key
            edited = real_editor(prepared.reset_index(drop=True), *args, **kwargs)

            # Do not ingest any value returned by the editor during the first
            # render of a newly selected Parameter set. A browser may still be
            # reconciling the old form subtree during that transition. The newly
            # generated form/editor identities become authoritative from the next
            # interaction onward.
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
