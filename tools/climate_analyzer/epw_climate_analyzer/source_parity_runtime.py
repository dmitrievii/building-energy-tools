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


def _fresh_source_parity_ui() -> Any:
    """Return an unwrapped source-parity UI module for this Streamlit script run.

    Streamlit reruns ``app.py`` in a fresh globals dictionary while imported
    package modules remain alive in the Python process. Several source-parity
    capability layers intentionally wrap module-level routing callables. Without
    resetting this persistent module, every browser rerun would wrap the previous
    run again, duplicating captions/widgets and eventually producing duplicate
    Streamlit element keys.
    """
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
    # The monthly source changes temporal capabilities, not the application
    # information architecture. Bind its capability gates to the same canonical
    # analysis sections used by other climate sources.
    install_monthly_canonical_ui(proxy, parity)
    # Final monthly cleanup removes the provisional source-specific chart path,
    # curates the provider vocabulary and binds native-monthly semantics into the
    # shared canonical chart engines.
    install_monthly_cleanup(proxy, parity)
    install_monthly_catalogue_adapter()
    install_monthly_visual_contract()
    namespace["_SOURCE_PARITY_RUNTIME_INSTALLED"] = True
    return True
