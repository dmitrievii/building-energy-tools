"""Lazy runtime installer for Climate Analyzer source parity.

The mature Streamlit entrypoint intentionally remains the source-of-truth UI
module because regression and deployment contracts inspect its source/AST. This
module is imported only from the navigation hand-off at runtime, after all app
functions are defined. Heavy scientific/UI dependencies therefore remain lazy.
"""

from __future__ import annotations

import importlib
from threading import RLock
from typing import Any, MutableMapping


_RUNTIME_PATCH_LOCK = RLock()


class _GlobalsProxy:
    """Attribute facade over a module globals dictionary."""

    def __init__(self, namespace: MutableMapping[str, Any]) -> None:
        object.__setattr__(self, "_namespace", namespace)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._namespace[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self._namespace[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self._namespace[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def looks_like_climate_analyzer_app(namespace: MutableMapping[str, Any]) -> bool:
    """Return true only for the fully defined mature Streamlit app namespace."""
    required = {
        "VARIABLES",
        "load_epw_from_bytes",
        "render_geosphere_source",
        "render_canonical_climate_analysis",
        "render_compare_climates",
        "render_data_quality",
    }
    return required.issubset(namespace)


def _reset_persistent_source_parity_modules() -> None:
    """Reset modules whose callables are mutated by runtime patch installers."""
    module_names = (
        "aggregations",
        "chart_theme",
        "timeseries",
        "charts",
        "source_parity_fixes",
        "source_parity_ground",
        "source_parity_resolution",
        "source_parity_longterm_hotfix",
        "source_parity_overview_compat",
        "source_parity_resource_bounds",
        "source_parity_longterm_followup",
        "source_parity_monthly",
        "source_parity_monthly_canonical",
        "source_parity_monthly_cleanup",
        "source_parity_monthly_catalogue",
        "source_parity_monthly_visual_contract",
        "source_parity_contract_closure",
        "source_parity_contract_guidance_hotfix",
        "source_parity_monthly_selection_state",
        "source_parity_contract_guard",
        "source_parity_monthly_overlay_hotfix",
        "source_parity_monthly_surface_guard",
        "source_parity_ux_followup",
    )
    package = __package__ or "epw_climate_analyzer"
    for name in module_names:
        module = importlib.import_module(f"{package}.{name}")
        importlib.reload(module)


def _fresh_source_parity_ui() -> Any:
    """Return a pristine source-parity runtime stack for this script run."""
    from .source_parity_streamlit_surface import restore_streamlit_surface

    restore_streamlit_surface()
    _reset_persistent_source_parity_modules()
    from . import source_parity_ui as parity

    return importlib.reload(parity)


def _freeze_session_geosphere_selector(proxy: Any, parity: Any) -> None:
    """Bind the fully composed GeoSphere selector to this app-script session."""
    final_selector = parity._render_geosphere_resource_selector
    original_geosphere = proxy._source_parity_original_geosphere

    def render_geosphere_source() -> Any:
        with _RUNTIME_PATCH_LOCK:
            return final_selector(proxy, original_geosphere)

    proxy.render_geosphere_source = render_geosphere_source


def _install_into_app_globals_locked(namespace: MutableMapping[str, Any]) -> bool:
    """Install source-parity runtime while the process-wide patch lock is held."""
    if not looks_like_climate_analyzer_app(namespace):
        return False

    from .source_parity_streamlit_surface import restore_streamlit_surface

    restore_streamlit_surface()
    if bool(namespace.get("_SOURCE_PARITY_RUNTIME_INSTALLED", False)):
        return True

    from .geosphere_resource_overlay import apply_geosphere_resource_overlay
    parity = _fresh_source_parity_ui()
    from .source_parity_fixes import apply_source_parity_fixes
    from .source_parity_ground import install_ground_depth_contract
    from .source_parity_resolution import enforce_native_timeseries_only
    from .source_parity_longterm_hotfix import install_longterm_hourly_hotfix
    from .source_parity_overview_compat import install_overview_pandas_compat
    from .source_parity_resource_bounds import install_resource_temporal_bounds
    from .source_parity_longterm_followup import install_longterm_followup
    from .source_parity_monthly import install_monthly_resource
    from .source_parity_monthly_canonical import install_monthly_canonical_ui
    from .source_parity_monthly_cleanup import install_monthly_cleanup
    from .source_parity_monthly_catalogue import install_monthly_catalogue_adapter
    from .source_parity_monthly_visual_contract import install_monthly_visual_contract
    from .source_parity_contract_closure import install_contract_closure
    from .source_parity_contract_guidance_hotfix import patch_contract_guidance
    from .source_parity_monthly_selection_state import install_monthly_selection_state
    from .source_parity_contract_guard import install_contract_guards
    from .source_parity_monthly_overlay_hotfix import install_monthly_overlay_timezone_guard
    from .source_parity_monthly_surface_guard import install_monthly_surface_guard
    from .source_parity_ux_followup import install_geosphere_variable_form, install_interannual_overlay

    apply_geosphere_resource_overlay()

    proxy = _GlobalsProxy(namespace)
    parity.install_source_parity_ui(proxy)
    apply_source_parity_fixes(proxy, parity)
    install_ground_depth_contract(proxy)
    enforce_native_timeseries_only(parity)
    install_longterm_hourly_hotfix(proxy, parity)
    # Replace the final enhanced Overview renderer after the long-term wrapper is
    # composed, so both chronological and non-chronological paths use the
    # pandas-safe Series.reset_index contract before later wrappers capture it.
    install_overview_pandas_compat(parity)
    install_resource_temporal_bounds(proxy, parity)
    install_monthly_selection_state(parity)
    install_longterm_followup(proxy, parity)
    install_monthly_resource(proxy, parity)
    install_monthly_canonical_ui(proxy, parity)
    install_monthly_cleanup(proxy, parity)
    install_monthly_catalogue_adapter()
    install_monthly_visual_contract()
    patch_contract_guidance()
    install_contract_closure(proxy, parity)
    install_contract_guards()
    install_monthly_overlay_timezone_guard()
    install_monthly_surface_guard(parity)

    # These contracts existed in the package and tests but were never composed
    # into the production runtime installer. Install them after the canonical
    # monthly/source wrappers so Time basis is extended on the final renderers.
    install_geosphere_variable_form(parity)
    install_interannual_overlay(proxy)

    _freeze_session_geosphere_selector(proxy, parity)

    namespace["_SOURCE_PARITY_RUNTIME_INSTALLED"] = True
    return True


def install_into_app_globals(namespace: MutableMapping[str, Any]) -> bool:
    """Install source-parity runtime patches once into the mature app globals."""
    with _RUNTIME_PATCH_LOCK:
        return _install_into_app_globals_locked(namespace)
