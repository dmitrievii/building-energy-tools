"""Reload-safe final guidance patch for the composed GeoSphere source selector.

The final source selector owns the one visible GeoSphere dataset widget.  Older
runtime layers still call a legacy selector internally, but those calls are
suppressed and receive the already-selected resource.  The visible widget and
all downstream routing therefore share exactly one Streamlit session-state key.
"""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable, Iterable

import pandas as pd

from . import source_parity_contract_closure as contract
from . import source_parity_monthly_cleanup as monthly_cleanup
from .geosphere_monthly import (
    MONTHLY_DATASET_PAGE,
    MONTHLY_DOI,
    MONTHLY_OFFICIAL_CONTEXT_EN,
    MONTHLY_RESOURCE_ID,
)


PARAMETER_SET_OPTIONS = (
    "Core variables",
    "Core + additional statistics",
    "All provider parameters",
)
PARAMETER_SET_KEY = "geosphere_monthly_parameter_catalogue_v2"
_RESOURCE_KEY = "geosphere_resource_id"
# Retained as an exported compatibility constant for focused regression tests.
# It deliberately aliases the routing key: there is no second widget state.
_RESOURCE_WIDGET_KEY = _RESOURCE_KEY


def _decorate_monthly_table(parity: Any, data: pd.DataFrame) -> pd.DataFrame:
    """Return the final human-readable monthly selector table from raw/decorated input."""
    try:
        decorated = monthly_cleanup._decorate_parameter_table(parity, data)
    except Exception:
        decorated = data.copy()

    out = decorated.copy()
    descriptors: list[Any] = []
    for _, row in out.iterrows():
        provider = str(row.get("Provider", "") or "")
        original_name = str(
            row.get("Original GeoSphere name", row.get("Measured variable", provider)) or provider
        )
        descriptors.append(
            monthly_cleanup._metadata_descriptor(
                parity,
                provider,
                original_name,
                str(row.get("Unit", "") or ""),
            )
        )

    if "Category" not in out.columns:
        out["Category"] = [item.category for item in descriptors]
    if "Statistic" not in out.columns:
        out["Statistic"] = [item.statistic for item in descriptors]
    if "Notes" not in out.columns:
        out["Notes"] = [item.note for item in descriptors]
    if "Original GeoSphere name" not in out.columns:
        out["Original GeoSphere name"] = data["Measured variable"].astype(str)

    out["Role"] = [contract.monthly_catalogue_role(item) for item in descriptors]
    order = {"Core variable": 0, "Additional statistic": 1, "Other provider parameter": 2}
    out["_role"] = out["Role"].map(order).fillna(9)
    sort_columns = [column for column in ("_role", "Category", "Measured variable") if column in out.columns]
    if sort_columns:
        out = out.sort_values(sort_columns, kind="stable")
    return out.drop(columns=["_role", "_recommended"], errors="ignore")


def _install_guidance_safe(parity: Any) -> None:
    """Install the final source selector and monthly catalogue guidance layer."""
    st = parity.st
    previous = parity._render_geosphere_resource_selector

    def selector(legacy: Any, original: Callable) -> None:
        real_info = st.info
        real_caption = st.caption
        real_write = st.write
        real_expander = st.expander
        real_radio = st.radio
        real_editor = st.data_editor
        real_selectbox = st.selectbox

        specs = list(parity.available_resource_specs())
        resource_ids = [str(spec.resource_id) for spec in specs]
        if not resource_ids:
            raise RuntimeError("GeoSphere resource registry is empty.")

        current_resource = str(st.session_state.get(_RESOURCE_KEY, resource_ids[0]))
        if current_resource not in resource_ids:
            # This happens before the widget is instantiated, so clearing an
            # obsolete value is legal and lets Streamlit apply the default.
            st.session_state.pop(_RESOURCE_KEY, None)
            current_resource = resource_ids[0]

        # One source of truth: the visible widget owns the same key that all
        # provider-routing layers read.  Nested legacy dataset selectboxes are
        # suppressed below, so no second widget can overwrite this state.
        selected_resource = str(
            real_selectbox(
                "GeoSphere dataset",
                resource_ids,
                index=resource_ids.index(current_resource),
                format_func=lambda resource_id: parity.resource_spec(resource_id).label,
                key=_RESOURCE_KEY,
                help=(
                    "10-minute data are best for recent event/detail analysis. The 1-hour resource provides the "
                    "long-term historical series without resampling. The 1-month resource contains native "
                    "monthly climatological statistics and is never upsampled to sub-monthly resolution."
                ),
            )
        )

        seen_info: set[str] = set()
        seen_caption: set[str] = set()
        monthly_context = {"shown": False}
        parameter_set_rendered = {"value": False}
        view = {
            "value": str(st.session_state.get(PARAMETER_SET_KEY, "Core variables"))
            if str(st.session_state.get(PARAMETER_SET_KEY, "Core variables")) in PARAMETER_SET_OPTIONS
            else "Core variables"
        }

        def selectbox(label: str, options: Iterable[Any], *args: Any, **kwargs: Any):
            values = list(options)
            if label == "GeoSphere dataset":
                # Every legacy selector in the nested wrapper chain observes the
                # real visible widget value but renders no second widget.
                return selected_resource
            return real_selectbox(label, values, *args, **kwargs)

        def info(body: Any, *args: Any, **kwargs: Any):
            text = str(body)
            if text.strip() == MONTHLY_OFFICIAL_CONTEXT_EN.strip():
                return None
            if text.startswith("Official GeoSphere Austria availability context"):
                if text in seen_info:
                    return None
                seen_info.add(text)
            return real_info(body, *args, **kwargs)

        def caption(body: Any, *args: Any, **kwargs: Any):
            text = str(body)
            if text.startswith("Official source: GeoSphere Austria Station Data-v2 (1 m)"):
                return None
            if text.startswith("Authoritative source: GeoSphere Austria Stationsdaten-v2 (1 h)"):
                if text in seen_caption:
                    return None
                seen_caption.add(text)
            return real_caption(body, *args, **kwargs)

        def write(body: Any, *args: Any, **kwargs: Any):
            if selected_resource == MONTHLY_RESOURCE_ID and str(body).strip() == MONTHLY_OFFICIAL_CONTEXT_EN.strip():
                return None
            return real_write(body, *args, **kwargs)

        def expander(label: str, *args: Any, **kwargs: Any):
            if selected_resource == MONTHLY_RESOURCE_ID and label == "About this GeoSphere monthly dataset":
                return nullcontext()
            return real_expander(label, *args, **kwargs)

        def render_parameter_set() -> str:
            if parameter_set_rendered["value"]:
                return view["value"]
            current = view["value"] if view["value"] in PARAMETER_SET_OPTIONS else "Core variables"
            selected = real_radio(
                "Parameter set",
                list(PARAMETER_SET_OPTIONS),
                index=list(PARAMETER_SET_OPTIONS).index(current),
                horizontal=True,
                key=PARAMETER_SET_KEY,
                help=(
                    "Core variables are canonical/building-climate quantities. Additional statistics are "
                    "provider-published monthly counts, extrema and indicators. All provider parameters also "
                    "shows fields without normalized Seasonal/Annual semantics."
                ),
            )
            view["value"] = str(selected)
            parameter_set_rendered["value"] = True
            return view["value"]

        def radio(label: str, options: Iterable[Any], *args: Any, **kwargs: Any):
            values = list(options)
            if label == "Parameter catalogue" and values == ["Recommended", "All parameters"]:
                render_parameter_set()
                # The final editor performs the filtering.  Force the legacy
                # layer to pass its complete vocabulary downstream.
                return "All parameters"
            return real_radio(label, values, *args, **kwargs)

        def editor(data: Any, *args: Any, **kwargs: Any):
            if not (
                selected_resource == MONTHLY_RESOURCE_ID
                and isinstance(data, pd.DataFrame)
                and {"Provider", "Measured variable"}.issubset(data.columns)
            ):
                return real_editor(data, *args, **kwargs)

            if not monthly_context["shown"]:
                with real_expander("About this GeoSphere monthly dataset", expanded=False):
                    real_write(MONTHLY_OFFICIAL_CONTEXT_EN)
                    real_caption(
                        f"Official source: GeoSphere Austria Station Data-v2 (1 m) · {MONTHLY_DOI} · {MONTHLY_DATASET_PAGE}"
                    )
                monthly_context["shown"] = True

            selected_view = render_parameter_set()
            out = _decorate_monthly_table(parity, data)
            if selected_view == "Core variables":
                out = out.loc[out["Role"] == "Core variable"].copy()
            elif selected_view == "Core + additional statistics":
                out = out.loc[out["Role"].isin(["Core variable", "Additional statistic"])].copy()

            config = dict(kwargs.get("column_config") or {})
            config["Measured variable"] = st.column_config.TextColumn("Variable", width="large")
            config["Category"] = st.column_config.TextColumn("Category", width="medium")
            config["Statistic"] = st.column_config.TextColumn("Statistic", width="medium")
            config["Notes"] = st.column_config.TextColumn("Interpretation", width="large")
            config["Role"] = st.column_config.TextColumn("Role", width="medium")
            config["Canonical field"] = None
            if selected_view != "All provider parameters":
                config["Provider"] = None
                config["Original GeoSphere name"] = None
            else:
                config["Original GeoSphere name"] = st.column_config.TextColumn(
                    "Original GeoSphere name", width="large"
                )
            kwargs["column_config"] = config

            disabled = list(kwargs.get("disabled") or [])
            for name in ("Category", "Statistic", "Notes", "Role", "Original GeoSphere name"):
                if name not in disabled:
                    disabled.append(name)
            kwargs["disabled"] = disabled
            return real_editor(out, *args, **kwargs)

        st.info = info
        st.caption = caption
        st.write = write
        st.expander = expander
        st.radio = radio
        st.data_editor = editor
        st.selectbox = selectbox
        try:
            previous(legacy, original)
        finally:
            st.info = real_info
            st.caption = real_caption
            st.write = real_write
            st.expander = real_expander
            st.radio = real_radio
            st.data_editor = real_editor
            st.selectbox = real_selectbox

    parity._render_geosphere_resource_selector = selector


def patch_contract_guidance() -> None:
    """Replace the order-sensitive closure guidance installer before runtime installation."""
    contract._install_guidance = _install_guidance_safe
