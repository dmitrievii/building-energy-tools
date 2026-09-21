"""Lazy runtime installer for Climate Analyzer source parity.

The mature Streamlit entrypoint intentionally remains the source-of-truth UI
module because regression and deployment contracts inspect its source/AST. This
module is imported only from the navigation hand-off at runtime, after all app
functions are defined. Heavy scientific/UI dependencies therefore remain lazy.
"""

from __future__ import annotations

import importlib
from typing import Any, MutableMapping


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


_STREAMLIT_SURFACE_NAMES = (
    "info",
    "caption",
    "write",
    "expander",
    "radio",
    "selectbox",
    "data_editor",
    "slider",
)
_STREAMLIT_BASELINE: dict[str, Any] | None = None


def _restore_streamlit_surface() -> None:
    """Restore Streamlit callables that source-parity layers patch temporarily.

    Streamlit reruns execute a fresh ``app.py`` globals dictionary but keep the
    imported ``streamlit`` module alive. Normally each wrapper restores its
    temporary monkey patches in ``finally``. A rerun interrupted while a widget
    callback/reconciliation is in flight can nevertheless leave an old wrapper
    attached to ``st``. Rebuilding the Python modules alone does not clear that
    module-level mutation, so a later run can traverse an old and a new wrapper
    and register the same widget key twice.

    Capture the pristine runtime surface on the first source-parity install and
    restore it before every later install. This is intentionally limited to the
    small set of Streamlit callables patched by the compatibility stack.
    """
    import streamlit as st

    global _STREAMLIT_BASELINE
    if _STREAMLIT_BASELINE is None:
        _STREAMLIT_BASELINE = {
            name: getattr(st, name)
            for name in _STREAMLIT_SURFACE_NAMES
        }
        return
    for name, value in _STREAMLIT_BASELINE.items():
        setattr(st, name, value)


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
    """Reset modules whose callables are mutated by runtime patch installers.

    Streamlit reruns ``app.py`` with fresh script globals but keeps imported
    package modules alive. Reload every persistent mutation target before the
    patch chain is composed again; otherwise monthly/chart wrappers accumulate
    even when ``source_parity_ui`` itself is reloaded.
    """
    module_names = (
        "aggregations",
        "chart_theme",
        "timeseries",
        "charts",
        "source_parity_fixes",
        "source_parity_ground",
        "source_parity_resolution",
        "source_parity_longterm_hotfix",
        "source_parity_resource_bounds",
        "source_parity_longterm_followup",
        "source_parity_monthly",
        "source_parity_monthly_canonical",
        "source_parity_monthly_cleanup",
        "source_parity_monthly_catalogue",
        "source_parity_monthly_visual_contract",
        "source_parity_contract_closure",
        "source_parity_contract_guidance_hotfix",
        "source_parity_contract_guard",
    )
    package = __package__ or "epw_climate_analyzer"
    for name in module_names:
        module = importlib.import_module(f"{package}.{name}")
        importlib.reload(module)


def _fresh_source_parity_ui() -> Any:
    """Return an unwrapped source-parity runtime stack for this script run."""
    _restore_streamlit_surface()
    _reset_persistent_source_parity_modules()
    from . import source_parity_ui as parity

    return importlib.reload(parity)


def install_into_app_globals(namespace: MutableMapping[str, Any]) -> bool:
    """Install source-parity runtime patches once into the mature app globals."""
    if not looks_like_climate_analyzer_app(namespace):
        return False
    if bool(namespace.get("_SOURCE_PARITY_RUNTIME_INSTALLED", False)):
        return True

    # Import only at runtime. Keeping these imports out of app.py module scope
    # preserves the established lightweight-startup contract.
    from .geosphere_resource_overlay import apply_geosphere_resource_overlay
    parity = _fresh_source_parity_ui()
    from .source_parity_fixes import apply_source_parity_fixes
    from .source_parity_ground import install_ground_depth_contract
    from .source_parity_resolution import enforce_native_timeseries_only
    from .source_parity_longterm_hotfix import install_longterm_hourly_hotfix
    from .source_parity_resource_bounds import install_resource_temporal_bounds
    from .source_parity_longterm_followup import install_longterm_followup
    from .source_parity_monthly import install_monthly_resource
    from .source_parity_monthly_canonical import install_monthly_canonical_ui
    from .source_parity_monthly_cleanup import install_monthly_cleanup
    from .source_parity_monthly_catalogue import install_monthly_catalogue_adapter
    from .source_parity_monthly_visual_contract import install_monthly_visual_contract
    from .source_parity_contract_closure import install_contract_closure
    from .source_parity_contract_guidance_hotfix import patch_contract_guidance
    from .source_parity_contract_guard import install_contract_guards

    # Provider vocabulary is installed before the shared resource selector builds
    # metadata mappings. Scientific engines remain provider-neutral.
    apply_geosphere_resource_overlay()

    proxy = _GlobalsProxy(namespace)
    parity.install_source_parity_ui(proxy)
    apply_source_parity_fixes(proxy, parity)
    install_ground_depth_contract(proxy)
    enforce_native_timeseries_only(parity)
    install_longterm_hourly_hotfix(proxy, parity)
    install_resource_temporal_bounds(proxy, parity)
    install_longterm_followup(proxy, parity)
    install_monthly_resource(proxy, parity)
    install_monthly_canonical_ui(proxy, parity)
    install_monthly_cleanup(proxy, parity)
    install_monthly_catalogue_adapter()
    install_monthly_visual_contract()
    # The final guidance installer must be wrapper-order independent before the
    # contract closure composes the outermost source selector.
    patch_contract_guidance()
    install_contract_closure(proxy, parity)
    install_contract_guards()
    namespace["_SOURCE_PARITY_RUNTIME_INSTALLED"] = True
    return True
