"""Public product copy and navigation contract for Climate Analyzer.

Keeping user-facing navigation labels and state transitions outside ``app.py``
makes the product structure testable without importing Streamlit and separates
stable public terminology from internal page identifiers used by calculation
routing.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from .release_info import (
    ENGINEERING_DISCLAIMER,
    INDEPENDENCE_NOTICE,
    PROJECT_NAME,
    TOOL_NAME,
    TOOL_VERSION,
)


RUNTIME_UI_SCHEMA = "MEM-PERF-R6"
PUBLIC_UX_STAGE = "WEB-0.7"
APP_NAME = TOOL_NAME
APP_BROWSER_TITLE = f"{TOOL_NAME} | {PROJECT_NAME}"
APP_TAGLINE = "Climate analysis for building design and building performance"
APP_INTRO = (
    "Explore EPW weather files and measured station data for temperature, moisture, solar radiation, wind, precipitation, "
    "passive-design potential and early HVAC decision support."
)
APP_RELEASE_LABEL = f"{TOOL_NAME} {TOOL_VERSION} · Beta candidate"
APP_INDEPENDENCE_NOTICE = INDEPENDENCE_NOTICE
APP_ENGINEERING_DISCLAIMER = ENGINEERING_DISCLAIMER

NAVIGATION_KEY = "climate_analyzer_navigation"
PENDING_NAVIGATION_KEY = "_climate_analyzer_pending_navigation"
RESET_NAVIGATION_KEY = "_climate_analyzer_reset_navigation"

NAVIGATION_PAGES = (
    "Climate File Source",
    "Overview",
    "Temperature",
    "Humidity and Psychrometrics",
    "Solar and Radiation",
    "Wind and Ventilation",
    "Sky and Daylight",
    "Precipitation and Snow",
    "Time Series and Overlay",
    "Natural Ventilation",
    "Shading analysis",
    "HVAC and Passive Design",
    "Outdoor Thermal Comfort",
    "Compare Climates",
    "Report",
    "Data Quality",
)

NAVIGATION_LABELS = {
    "Climate File Source": "Start — Climate source",
    "Overview": "Summary — Overview",
    "Temperature": "Climate — Temperature",
    "Humidity and Psychrometrics": "Climate — Moisture & psychrometrics",
    "Solar and Radiation": "Climate — Solar radiation",
    "Wind and Ventilation": "Climate — Wind",
    "Sky and Daylight": "Climate — Sky & daylight",
    "Precipitation and Snow": "Climate — Precipitation & snow",
    "Time Series and Overlay": "Explore — Time series & overlay",
    "Natural Ventilation": "Design — Natural ventilation",
    "Shading analysis": "Design — Shading analysis",
    "HVAC and Passive Design": "Design — Passive strategies & HVAC",
    "Outdoor Thermal Comfort": "Design — Outdoor thermal comfort",
    "Compare Climates": "Compare — Multiple climates",
    "Report": "Report — Climate assessment",
    "Data Quality": "Data — Quality & metadata",
}


def navigation_label(page: str) -> str:
    """Return the public label for an internal page identifier."""
    return NAVIGATION_LABELS.get(page, page)


def queue_navigation(state: MutableMapping[str, Any], page: str) -> None:
    """Request navigation for the next render cycle without mutating a live widget key."""
    if page not in NAVIGATION_PAGES:
        raise ValueError(f"Unknown Climate Analyzer page: {page}")
    state[PENDING_NAVIGATION_KEY] = page
    state.pop(RESET_NAVIGATION_KEY, None)


def queue_navigation_reset(state: MutableMapping[str, Any]) -> None:
    """Request removal of the navigation widget state on the next render cycle."""
    state[RESET_NAVIGATION_KEY] = True
    state.pop(PENDING_NAVIGATION_KEY, None)


def needs_source_parity(state: MutableMapping[str, Any]) -> bool:
    """Inactive Upload EPW and OneBuilding map do not require GeoSphere parity."""
    return (state.get("active_climate_file") is not None or
            state.get("active_canonical_climate") is not None or
            state.get("climate_source_mode","Upload EPW") not in ("Upload EPW","Find climate"))


def _install_source_parity_for_app_caller(state: MutableMapping[str, Any]) -> None:
    """Install source-parity and chart-presentation routing for the full app.

    ``app.py`` is deliberately kept as the mature source/AST contract. The
    navigation hand-off is the earliest runtime call made by ``main`` after all
    renderer functions have been defined, so it is a safe place to install the
    source-neutral routing and global Plotly presentation boundary. R5 warms
    scientific libraries separately, once per process. Ordinary unit tests
    of this module do not satisfy the app sentinel and therefore do not load
    either runtime layer.
    """
    import sys

    caller_globals = sys._getframe(2).f_globals
    if not {
        "VARIABLES",
        "load_epw_from_bytes",
        "render_geosphere_source",
        "render_canonical_climate_analysis",
        "render_compare_climates",
        "render_data_quality",
    }.issubset(caller_globals):
        return

    from .chart_presentation import install_global_chart_presentation

    # Libraries are warmed once independently of the route. Do not reset and
    # recompose the large compatibility stack for a plain inactive file form.
    if needs_source_parity(state):
        from .source_parity_runtime import install_into_app_globals
        from .startup_runtime import profile_install
        profile_install(install_into_app_globals,caller_globals)
    elif "epw_climate_analyzer.source_parity_runtime" in sys.modules:
        # A preceding source render may have aborted with temporary Streamlit
        # wrappers installed. Restore the surface under the selector lock,
        # without loading or composing parity on an idle upload/map route.
        runtime=sys.modules["epw_climate_analyzer.source_parity_runtime"]
        restore=getattr(runtime,"restore_inactive_surface",None)
        if callable(restore):restore()
    install_global_chart_presentation()


def apply_queued_navigation(state: MutableMapping[str, Any]) -> None:
    """Apply queued navigation before the Streamlit navigation widget is instantiated."""
    _install_source_parity_for_app_caller(state)
    reset = bool(state.pop(RESET_NAVIGATION_KEY, False))
    pending = state.pop(PENDING_NAVIGATION_KEY, None)
    if reset:
        state.pop(NAVIGATION_KEY, None)
        return
    if pending is not None:
        if pending not in NAVIGATION_PAGES:
            raise ValueError(f"Unknown queued Climate Analyzer page: {pending}")
        state[NAVIGATION_KEY] = pending
