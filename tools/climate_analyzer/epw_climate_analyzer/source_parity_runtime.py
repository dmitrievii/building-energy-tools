"""Lazy runtime installer for Climate Analyzer source parity.

The mature Streamlit entrypoint intentionally remains the source-of-truth UI
module because regression and deployment contracts inspect its source/AST.  This
module is imported only from the navigation hand-off at runtime, after all app
functions are defined.  Heavy scientific/UI dependencies therefore remain lazy.
"""

from __future__ import annotations

from typing import Any, MutableMapping


class _GlobalsProxy:
    """Attribute facade over a module globals dictionary.

    The parity installer was designed against a module-like object.  Streamlit
    can execute the app under runner-specific module names, so forwarding
    attributes directly to the caller globals is more robust than relying on a
    particular entry in ``sys.modules``.
    """

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


def install_into_app_globals(namespace: MutableMapping[str, Any]) -> bool:
    """Install parity patches once into a mature app globals dictionary.

    Returns ``True`` when the namespace is the Climate Analyzer app (whether the
    patches were newly installed or were already present) and ``False`` for
    unrelated callers such as unit tests of the navigation contract.
    """
    if not looks_like_climate_analyzer_app(namespace):
        return False
    if bool(namespace.get("_SOURCE_PARITY_RUNTIME_INSTALLED", False)):
        return True

    # Import only at runtime.  Keeping these imports out of app.py module scope
    # preserves the established lightweight-startup contract.
    from . import source_parity_ui as parity
    from .source_parity_fixes import apply_source_parity_fixes

    proxy = _GlobalsProxy(namespace)
    parity.install_source_parity_ui(proxy)
    apply_source_parity_fixes(proxy, parity)
    namespace["_SOURCE_PARITY_RUNTIME_INSTALLED"] = True
    return True
