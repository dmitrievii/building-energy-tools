"""Persist the chosen GeoSphere resource across nested Streamlit reruns.

The mature GeoSphere station browser can call ``st.rerun()`` from inside the
composed source-selector wrapper chain (for example after ``Use station from
list``).  Older layers still carry a 10-minute default routing key, while the
final visible dataset selector owns a private widget key.  If a nested rerun is
raised before the outer layer returns, the legacy routing key can be observed on
the next script run and the UI silently falls back to ``klima-v2-10min``.

This guard is installed after the final source-selector composition.  It stores
the visible widget choice in a non-widget session-state key immediately before
any nested rerun and restores that route before the next composed selector run.
"""
from __future__ import annotations

from typing import Any, Callable


RESOURCE_KEY = "geosphere_resource_id"
RESOURCE_WIDGET_KEY = "_geosphere_resource_selector_widget_v1"
RESOURCE_PERSIST_KEY = "_geosphere_resource_route_persist_v1"


def resolved_resource(
    resource_ids: list[str] | tuple[str, ...],
    *,
    widget_resource: object = "",
    persisted_resource: object = "",
    route_resource: object = "",
) -> str:
    """Resolve the effective route with the visible widget as highest authority."""
    values = [str(value) for value in resource_ids]
    if not values:
        raise RuntimeError("GeoSphere resource registry is empty.")
    for candidate in (widget_resource, persisted_resource, route_resource):
        value = str(candidate or "")
        if value in values:
            return value
    return values[0]


def install_resource_persistence(parity: Any) -> None:
    """Wrap the fully composed GeoSphere selector with rerun-safe route state."""
    if bool(getattr(parity, "_RESOURCE_PERSISTENCE_INSTALLED", False)):
        return

    st = parity.st
    previous = parity._render_geosphere_resource_selector

    def selector(legacy: Any, original: Callable) -> None:
        specs = list(parity.available_resource_specs())
        resource_ids = [str(spec.resource_id) for spec in specs]
        effective = resolved_resource(
            resource_ids,
            widget_resource=st.session_state.get(RESOURCE_WIDGET_KEY, ""),
            persisted_resource=st.session_state.get(RESOURCE_PERSIST_KEY, ""),
            route_resource=st.session_state.get(RESOURCE_KEY, ""),
        )
        st.session_state[RESOURCE_KEY] = effective
        st.session_state[RESOURCE_PERSIST_KEY] = effective

        real_rerun = st.rerun

        def rerun(*args: Any, **kwargs: Any):
            chosen = resolved_resource(
                resource_ids,
                widget_resource=st.session_state.get(RESOURCE_WIDGET_KEY, ""),
                persisted_resource=st.session_state.get(RESOURCE_PERSIST_KEY, ""),
                route_resource=st.session_state.get(RESOURCE_KEY, ""),
            )
            st.session_state[RESOURCE_KEY] = chosen
            st.session_state[RESOURCE_PERSIST_KEY] = chosen
            return real_rerun(*args, **kwargs)

        st.rerun = rerun
        try:
            previous(legacy, original)
            chosen = resolved_resource(
                resource_ids,
                widget_resource=st.session_state.get(RESOURCE_WIDGET_KEY, ""),
                persisted_resource=st.session_state.get(RESOURCE_PERSIST_KEY, ""),
                route_resource=st.session_state.get(RESOURCE_KEY, ""),
            )
            st.session_state[RESOURCE_KEY] = chosen
            st.session_state[RESOURCE_PERSIST_KEY] = chosen
        finally:
            st.rerun = real_rerun

    parity._render_geosphere_resource_selector = selector
    parity._RESOURCE_PERSISTENCE_INSTALLED = True
