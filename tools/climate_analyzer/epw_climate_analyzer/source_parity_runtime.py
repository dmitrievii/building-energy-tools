"""MEM-PERF R6: persistent pristine module bindings and run-local UI wrappers.

Scientific libraries and pristine application functions survive normal reruns.
The legacy compatibility layer still composes fresh wrappers around each
app-script namespace; no process-global cache of user/session namespaces is
introduced. Only the explicitly listed mutation targets are reset.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from threading import RLock
from typing import Any, MutableMapping


# Streamlit browser sessions share imported Python modules while executing their
# app-script bodies on separate threads. Source-parity installation intentionally
# reloads and composes several package modules, so installation and selector
# execution must not overlap across sessions. RLock is used because the frozen
# selector can re-enter helper paths in the same thread.
RUNTIME_PARITY_SCHEMA = "MEM-PERF-R6"
RUNTIME_INVALIDATION_SCHEMA = "MEM-PERF-R8"
_RUNTIME_PATCH_LOCK = RLock()
_PRISTINE_MODULES = ()
_PRISTINE_PARITY = None
_RUNTIME_STATS = {"baseline_builds":0,"module_reloads":0,"binding_resets":0,
                  "restored_bindings":0,"removed_bindings":0,"wrapper_compositions":0,
                  "baseline_invalidations":0}
_LAST_INVALIDATION=None
_PERSISTENT_NAMESPACE=None



def runtime_stats() -> dict[str, Any]:
    # Approximate counters only. Diagnostics must not wait for another
    # session's network request while its selector owns the patch lock.
    return {**_RUNTIME_STATS,"baseline_modules":len(_PRISTINE_MODULES),
            "last_baseline_invalidation":_LAST_INVALIDATION}


def restore_inactive_surface() -> None:
    """Restore a previously imported Streamlit surface without composing UI."""
    with _RUNTIME_PATCH_LOCK:
        from .source_parity_streamlit_surface import restore_streamlit_surface
        restore_streamlit_surface()


def release_idle_bindings():
    """Try idle binding recovery without ever blocking the runtime event loop.

    A script may own the compatibility lock while waiting for a WebSocket/
    event-loop operation. Even a zero-session observation is not a license
    to wait for that lock. False means the caller must defer recovery.
    """
    if not _RUNTIME_PATCH_LOCK.acquire(blocking=False):
        _RUNTIME_STATS["idle_binding_deferrals"]=_RUNTIME_STATS.get("idle_binding_deferrals",0)+1
        return False
    try:
        from .source_parity_streamlit_surface import restore_streamlit_surface
        restore_streamlit_surface()
        if _PERSISTENT_NAMESPACE is not None:
            _RUNTIME_STATS["persistent_idle_checks"]=_RUNTIME_STATS.get("persistent_idle_checks",0)+1
            return True
        if _baseline_current():
            _restore_bindings()
            _RUNTIME_STATS["idle_binding_releases"]=_RUNTIME_STATS.get("idle_binding_releases",0)+1
        return True
    finally:
        _RUNTIME_PATCH_LOCK.release()


def _module_token(module):
    """Detect source replacement and external importlib.reload calls.

    File metadata is checked on ordinary reruns. External reload changes the
    module spec; do not overlay the old function snapshot on a new module.
    """
    path=getattr(module,"__file__",None)
    try:
        stat=Path(path).stat()
        disk=(stat.st_mtime_ns,stat.st_size,stat.st_ino)
    except (OSError,ValueError,TypeError):
        disk=None
    return (getattr(module,"__spec__",None),disk)


def _snapshot(module):
    return (module,{key:value for key,value in vars(module).items()
                    if not key.startswith("__")},_module_token(module))


def _baseline_current():
    global _LAST_INVALIDATION
    if not _PRISTINE_MODULES:return False
    for module,bindings,token in _PRISTINE_MODULES:
        reason=None
        if sys.modules.get(module.__name__) is not module:
            reason="module replaced"
        else:
            current=_module_token(module)
            if current[1]!=token[1]:reason="source file changed"
            elif current[0] is not token[0]:reason="external reload or module spec replaced"
        if reason is not None:
            _RUNTIME_STATS["baseline_invalidations"]+=1
            _LAST_INVALIDATION={"module":module.__name__,"reason":reason}
            return False
    return True


def _restore_bindings():
    restored=removed=0
    for module,bindings,token in _PRISTINE_MODULES:
        namespace=vars(module)
        for key in tuple(namespace):
            if not key.startswith("__") and key not in bindings:
                namespace.pop(key,None)
                removed+=1
        for key,value in bindings.items():
            if key not in namespace or namespace[key] is not value:
                namespace[key]=value
                restored+=1
    _RUNTIME_STATS["binding_resets"]+=1
    _RUNTIME_STATS["restored_bindings"]+=restored
    _RUNTIME_STATS["removed_bindings"]+=removed


def _drop_legacy_patch_markers(module):
    """One-time migration of flags that importlib.reload does not delete."""
    try:namespace=vars(module)
    except TypeError:return
    for key,value in tuple(namespace.items()):
        if (key.startswith("_") and type(value) is bool and
            any(key.endswith(suffix) for suffix in ("_INSTALLED","_PATCHED","_INSTALLED_V1","_INSTALLED_V2"))):
            namespace.pop(key,None)
    for key in ("_source_parity_unfixed_analysis_clock",
                "_source_parity_unfixed_quality_policy",
                "_source_parity_unrestricted_native_analysis"):
        namespace.pop(key,None)


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


def _reset_persistent_source_parity_modules() -> tuple:
    """Cold/revision-change reset of the explicit compatibility mutation set.

    Ordinary reruns use the persistent binding snapshot instead. Pure
    request-state value objects are not reloaded.
    """
    module_names = (
        "aggregations",
        "chart_theme",
        "temporal_filtering",
        "timeseries",
        "interannual_year_highlight",
        "charts",
        "source_parity_ux_followup",
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
        "source_parity_variable_form_compat",
        "source_parity_contract_guard",
        "source_parity_monthly_overlay_hotfix",
        "source_parity_monthly_surface_guard",
    )
    package = __package__ or "epw_climate_analyzer"
    modules=[]
    for name in module_names:
        module = importlib.import_module(f"{package}.{name}")
        _drop_legacy_patch_markers(module)
        module=importlib.reload(module)
        modules.append(module)
        _RUNTIME_STATS["module_reloads"]+=1
    return tuple(modules)


def _fresh_source_parity_ui() -> Any:
    """Return a pristine source-parity runtime stack for this script run.

    Reset the persistent Streamlit module surface *before* reloading source-
    parity modules. Widget-triggered reruns can interrupt a nested selector
    while ``st.data_editor``/``st.radio``/``DeltaGenerator.date_input`` are
    temporarily replaced; without this reset those leaked wrappers become the
    next run's apparent originals and the chain accumulates.
    """
    from .source_parity_streamlit_surface import restore_streamlit_surface

    global _PRISTINE_MODULES,_PRISTINE_PARITY
    with _RUNTIME_PATCH_LOCK:
        restore_streamlit_surface()
        if _baseline_current():
            _restore_bindings()
            return _PRISTINE_PARITY
        # If an external reload or a deployment changed the source, rebuild
        # once from disk using the original ordered cold-reset path. Publish
        # the snapshot only after all imports succeed.
        _PRISTINE_MODULES=()
        _PRISTINE_PARITY=None
        modules=_reset_persistent_source_parity_modules()
        from . import source_parity_ui as parity
        _drop_legacy_patch_markers(parity)
        parity=importlib.reload(parity)
        _RUNTIME_STATS["module_reloads"]+=1
        _PRISTINE_MODULES=tuple(_snapshot(module) for module in (*modules,parity))
        _PRISTINE_PARITY=parity
        _RUNTIME_STATS["baseline_builds"]+=1
        return parity


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

    The station browser intentionally remains a normal Streamlit surface. A
    request-only rerun boundary must be introduced below station selection rather
    than fragmenting the entire GeoSphere selector; fragmenting the complete
    selector destabilizes map/search widget reconciliation in real browser flows.
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
    from .epw_download_surface import install_epw_download_surface
    from .interannual_year_highlight import install_interannual_year_highlight
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
    from .source_parity_variable_form_compat import (
        install_geosphere_variable_form_compat,
        patch_variable_form_installer,
    )
    from .geosphere_request_form import install_geosphere_request_form
    from .geosphere_monthly_request_surface import install_monthly_request_surface

    # The shared UX module is mutable: older installers resolve its variable-form
    # owner at runtime. Publish the compatibility owner before *any* source-parity
    # installer can compose a legacy form. Calling this only at the end can delete
    # an already-set marker and accidentally wrap a second transactional form over
    # the first one, which is nondeterministic across Streamlit browser sessions.
    patch_variable_form_installer()

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

    # Guarantee exactly one schema-compatible transactional form. If an earlier
    # installer already requested the shared form, the marker now refers to this
    # same compatibility owner and this call is a no-op. Do not clear the marker
    # here: doing so would duplicate the form wrapper.
    install_geosphere_variable_form_compat(parity)

    # One final request-state boundary is shared by all GeoSphere resources. It
    # observes the already-normalized editor/date widgets and the transactional
    # form submit, records one canonical request schema and never owns provider
    # transport or scientific conversion.
    install_geosphere_request_form(parity)

    # Native-monthly now owns one request fragment below the mature station
    # browser. The wrapper stops only the legacy request tail at its first date
    # widget, then renders Parameter set + dates + DataEditor + Load together.
    # 10-minute/hourly remain on the validated mature path.
    install_monthly_request_surface(parity)

    # EPW overview download control. The active ClimateFilePayload already keeps
    # the exact source bytes; expose those bytes next to the Dataset statistics
    # CSV rather than reconstructing an EPW from a filtered/derived DataFrame.
    install_epw_download_surface(proxy)

    # Source-neutral presentation control for Interannual overlay. Install it
    # after all provider-specific wrappers so every source uses the same final
    # shared time-series renderer and the same focused-year semantics.
    install_interannual_year_highlight(proxy)

    # Freeze the fully composed selector into this Streamlit app-script namespace.
    # Without this final binding, the lambda installed by source_parity_ui performs
    # a process-global module lookup and can be redirected by another browser
    # session that reloads/recomposes source_parity_ui concurrently.
    _freeze_session_geosphere_selector(proxy, parity)

    namespace["_SOURCE_PARITY_RUNTIME_INSTALLED"] = True
    _RUNTIME_STATS["wrapper_compositions"]+=1
    return True


def install_into_app_globals(namespace: MutableMapping[str, Any]) -> bool:
    """Install source-parity runtime patches once into the mature app globals.

    Streamlit sessions share the imported source-parity modules. Serializing the
    complete reset/reload/composition transaction prevents two browser sessions
    from interleaving wrapper installation and producing a mixed selector chain.
    The same lock protects execution of each frozen GeoSphere selector.
    """
    global _PERSISTENT_NAMESPACE
    with _RUNTIME_PATCH_LOCK:
        persistent=namespace.get("__name__")=="_ige_r143_persistent_app"
        if _PERSISTENT_NAMESPACE is not None and namespace is not _PERSISTENT_NAMESPACE:
            raise RuntimeError("Cannot switch persistent compatibility ownership inside one process")
        if persistent and _PERSISTENT_NAMESPACE is namespace:
            if not _baseline_current():
                raise RuntimeError("Persistent compatibility source changed; restart the candidate runtime")
            _RUNTIME_STATS["persistent_reuses"]=_RUNTIME_STATS.get("persistent_reuses",0)+1
            return True
        installed=_install_into_app_globals_locked(namespace)
        if installed and persistent:
            _PERSISTENT_NAMESPACE=namespace
            _RUNTIME_STATS["persistent_compositions"]=_RUNTIME_STATS.get("persistent_compositions",0)+1
        return installed