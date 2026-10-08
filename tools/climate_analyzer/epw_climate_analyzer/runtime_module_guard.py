"""Runtime compatibility guards for Streamlit hot-reload module state.

Streamlit can rerun a freshly updated ``app.py`` in a long-lived Python process
while package modules imported by the previous release remain in ``sys.modules``.
When a release changes a function call contract across files, that can leave the
new caller bound to an older callee implementation until the process restarts.

This module keeps that deployment concern separate from the scientific code. It
reloads only when the currently imported psychrometric modules do not expose the
API required by the current application source.
"""

from __future__ import annotations

import importlib
import inspect
from hashlib import sha256
from pathlib import Path
from types import ModuleType


_REQUIRED_DISTRIBUTION_API = frozenset(
    {
        "add_climate_zone_traces",
        "psychrometric_axis_ranges",
    }
)
_REQUIRED_DISTRIBUTION_PARAMETERS = frozenset({"additional_coverages", "pressure_pa"})
_REQUIRED_COMPARISON_PARAMETERS = frozenset({"additional_contour_coverages", "show_givoni_overlay", "show_heat_index_overlay"})

_REQUIRED_CHART_PARAMETERS = frozenset(
    {
        "zone_coverage",
        "zone_interior_style",
        "show_core_zone",
        "additional_contour_coverages",
        "year_mode",
        "selected_years",
    }
)


def _missing_attributes(module: ModuleType, names: frozenset[str]) -> set[str]:
    return {name for name in names if not hasattr(module, name)}


def _missing_callable_parameters(module: ModuleType, name: str, required: frozenset[str]) -> set[str]:
    callable_object = getattr(module, name, None)
    if callable_object is None:
        return set(required)
    try:
        parameters = inspect.signature(callable_object).parameters
    except (TypeError, ValueError):
        return set(required)
    return set(required).difference(parameters)


def _missing_psychrometric_chart_parameters(module: ModuleType) -> set[str]:
    return _missing_callable_parameters(module, "psychrometric_chart", _REQUIRED_CHART_PARAMETERS)


def _missing_distribution_helper_parameters(module: ModuleType) -> set[str]:
    return _missing_callable_parameters(
        module,
        "add_climate_zone_traces",
        _REQUIRED_DISTRIBUTION_PARAMETERS,
    )


def _stale_source(module: ModuleType) -> bool:
    """Check the source on disk against the source loaded into this process."""
    source_path = getattr(module, "__file__", None)
    if not source_path:
        raise RuntimeError(f"Missing source path for required module {module.__name__}.")
    disk_hash = sha256(Path(source_path).read_bytes()).hexdigest()
    return getattr(module, "_RUNTIME_SOURCE_SHA256", None) != disk_hash


def _refresh_physical_core() -> bool:
    """Refresh changed psychrometrics + historical bindings once per deploy.

    Reload historical *only* when its source or the imported psychrometric
    callable changes, preserving canonical-hourly caches during normal reruns.
    """
    psychrometrics = importlib.import_module("epw_climate_analyzer.psychrometrics")
    psychrometrics_changed = _stale_source(psychrometrics)
    if psychrometrics_changed:
        psychrometrics = importlib.reload(psychrometrics)
    historical = importlib.import_module("epw_climate_analyzer.historical")
    if psychrometrics_changed or _stale_source(historical):
        importlib.reload(historical)
    return psychrometrics_changed


def ensure_current_psychrometric_runtime() -> tuple[ModuleType, ModuleType]:
    """Return distribution/charts modules compatible with the current app call API.

    The dependency module is checked first because current ``charts.py`` imports
    the climate-zone helpers at module import time. If an older in-process
    ``psychrometric_distribution`` is retained, it must be refreshed before
    reloading ``charts``.

    No reload occurs during a normal fresh process. A reload is performed only
    when the imported module is demonstrably missing the API introduced by the
    current psychrometric integration release. Attribute presence alone is not
    sufficient: helper signatures are validated as well, because an older helper
    can keep the same name while lacking newly required keyword parameters. If
    the distribution dependency is refreshed, ``charts`` is refreshed as well
    so its imported helper references cannot remain bound to the previous
    distribution module implementation. The function fails closed if the
    expected API is still unavailable after reload.
    """
    physical_core_was_reloaded = _refresh_physical_core()

    distribution = importlib.import_module("epw_climate_analyzer.psychrometric_distribution")
    missing_distribution = _missing_attributes(distribution, _REQUIRED_DISTRIBUTION_API)
    missing_distribution_parameters = _missing_distribution_helper_parameters(distribution)
    distribution_was_reloaded = False
    if missing_distribution or missing_distribution_parameters:
        distribution = importlib.reload(distribution)
        distribution_was_reloaded = True
        missing_distribution = _missing_attributes(distribution, _REQUIRED_DISTRIBUTION_API)
        missing_distribution_parameters = _missing_distribution_helper_parameters(distribution)
    if missing_distribution or missing_distribution_parameters:
        details: list[str] = []
        if missing_distribution:
            details.append("missing attributes: " + ", ".join(sorted(missing_distribution)))
        if missing_distribution_parameters:
            details.append(
                "add_climate_zone_traces missing parameters: "
                + ", ".join(sorted(missing_distribution_parameters))
            )
        raise RuntimeError("Psychrometric distribution runtime API is stale after reload; " + "; ".join(details))

    charts = importlib.import_module("epw_climate_analyzer.charts")
    missing_parameters = _missing_psychrometric_chart_parameters(charts)
    charts_was_reloaded = False
    if physical_core_was_reloaded or distribution_was_reloaded or missing_parameters:
        charts = importlib.reload(charts)
        charts_was_reloaded = True
        missing_parameters = _missing_psychrometric_chart_parameters(charts)
    if missing_parameters:
        raise RuntimeError(
            "Psychrometric chart runtime API is stale after reload; missing parameters: "
            + ", ".join(sorted(missing_parameters))
        )

    comparison = importlib.import_module("epw_climate_analyzer.comparison")
    missing_compare = _missing_callable_parameters(
        comparison,
        "psychrometric_comparison_chart",
        _REQUIRED_COMPARISON_PARAMETERS,
    )
    if physical_core_was_reloaded or distribution_was_reloaded or charts_was_reloaded or missing_compare:
        comparison = importlib.reload(comparison)
        missing_compare = _missing_callable_parameters(
            comparison,
            "psychrometric_comparison_chart",
            _REQUIRED_COMPARISON_PARAMETERS,
        )
    if missing_compare:
        raise RuntimeError(
            "Psychrometric comparison runtime API is stale after reload; missing parameters: "
            + ", ".join(sorted(missing_compare))
        )

    return distribution, charts
