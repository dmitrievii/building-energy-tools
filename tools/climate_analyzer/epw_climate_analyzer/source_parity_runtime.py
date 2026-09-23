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


# Streamlit browser sessions share imported Python modules while executing their
# app-script bodies on separate threads. Source-parity installation intentionally
# reloads and composes several package modules, so installation and selector
# execution must not overlap across sessions. RLock is used because the frozen
# selector can re-enter helper paths in the same thread.
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
    """Reset modules whose callables are mutated by runtime patch installers.

    Streamlit reruns ``app.py`` with fresh script globals but keeps imported
    package modules alive. Reload every persistent mutation target before the
    patch chain is composed again; otherwise monthly/chart wrappers accumulate
    even when ``source_parity_ui`` itself is reloaded.
    """
    module_names = (
        "aggregations",
        "chart_theme",
        "temporal_filtering",
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
        "source_parity_monthly_selection_state",
        "source_parity_contract_guard",
        "source_parity_monthly_overlay_hotfix",
        "source_parity_monthly_surface_guard",
    )
    package = __package__ or "epw_climate_analyzer"
    for name in module_names:
        module = importlib.import_module(f"{package}.{name}")
        importlib.reload(module)


def _fresh_source_parity_ui() -> Any:
    """Return a pristine source-parity runtime stack for this script run.

    Reset the persistent Streamlit module surface *before* reloading source-
    parity modules. Widget-triggered reruns can interrupt a nested selector
    while ``st.data_editor``/``st.radio``/``DeltaGenerator.date_input`` are
    temporarily replaced; without this reset those leaked wrappers become the
    next run's apparent originals and the chain accumulates.
    """
    from .source_parity_streamlit_surface import restore_streamlit_surface

    restore_streamlit_surface()
    _reset_persistent_source_parity_modules()
    from . import source_parity_ui as parity

    return importlib.reload(parity)


def _freeze_session_geosphere_selector(proxy: Any, parity: Any) -> None:
    """Bind the fully composed GeoSphere selector to this app-script session.

    ``install_source_parity_ui`` initially routes ``render_geosphere_source``
    through a lambda whose ``_render_geosphere_resource_selector`` name is looked
    up in the process-global ``source_parity_ui`` module at call time. Streamlit
    browser sessions share that imported module, so another session can reload
    and recompose the module after this session has installed its own app globals.
    The older session would then execute the other session's selector chain.

    Capture the final composed selector and original legacy source renderer after
    every wrapper has been installed. Execution is protected by the same process-
    wide lock as installation so another session cannot reload shared module
    globals while this selector chain is active.
    """
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
    from .source_parity_monthly_selection_state import install_monthly_selection_state
    from .source_parity_contract_guard import install_contract_guards
    from .source_parity_monthly_overlay_hotfix import install_monthly_overlay_timezone_guard
    from .source_parity_monthly_surface_guard import install_monthly_surface_guard

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

    # The monthly editor-state adapter must sit inside the later selection
    # wrappers. At the DataEditor call boundary this lets it assign the
    # resource/view-specific key and provider-filtered table *before* the legacy
    # long-term wrapper can reinterpret ``geosphere_variable_editor`` as an
    # hourly/10-minute widget. Installing it at the end of the chain is too late:
    # the legacy wrapper has already changed the data/key by then.
    install_monthly_selection_state(parity)

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
    install_monthly_overlay_timezone_guard()
    # Final sink for user-visible monthly-only wording/warnings. Installing this
    # last makes the cleanup independent of whichever inner wrapper emitted the
    # legacy shared-shell text.
    install_monthly_surface_guard(parity)

    # Freeze the fully composed selector into this Streamlit app-script namespace.
    # Without this final binding, the lambda installed by source_parity_ui performs
    # a process-global module lookup and can be redirected by another browser
    # session that reloads/recomposes source_parity_ui concurrently.
    _freeze_session_geosphere_selector(proxy, parity)

    namespace["_SOURCE_PARITY_RUNTIME_INSTALLED"] = True
    return True


def install_into_app_globals(namespace: MutableMapping[str, Any]) -> bool:
    """Install source-parity runtime patches once into the mature app globals.

    Streamlit sessions share the imported source-parity modules. Serializing the
    complete reset/reload/composition transaction prevents two browser sessions
    from interleaving wrapper installation and producing a mixed selector chain.
    The same lock protects execution of each frozen GeoSphere selector.
    """
    with _RUNTIME_PATCH_LOCK:
        return _install_into_app_globals_locked(namespace)
