"""Public product copy and navigation contract for Climate Analyzer.

Keeping user-facing navigation labels and state transitions outside ``app.py``
makes the product structure testable without importing Streamlit and separates
stable public terminology from internal page identifiers used by calculation
routing.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from .i18n import (
    DEFAULT_LOCALE,
    LOCALE_DISPLAY_NAMES,
    LOCALE_SESSION_KEY,
    SUPPORTED_LOCALES,
    active_locale,
    normalize_locale,
    set_active_locale,
    translate,
)
from .release_info import (
    ENGINEERING_DISCLAIMER,
    INDEPENDENCE_NOTICE,
    PROJECT_NAME,
    TOOL_NAME,
    TOOL_VERSION,
)


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
    "HVAC and Passive Design",
    "Compare Climates",
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
    "HVAC and Passive Design": "Design — Passive strategies & HVAC",
    "Compare Climates": "Compare — Multiple climates",
    "Data Quality": "Data — Quality & metadata",
}

NAVIGATION_TRANSLATION_KEYS = {
    "Climate File Source": "nav.climate_file_source",
    "Overview": "nav.overview",
    "Temperature": "nav.temperature",
    "Humidity and Psychrometrics": "nav.humidity_psychrometrics",
    "Solar and Radiation": "nav.solar_radiation",
    "Wind and Ventilation": "nav.wind_ventilation",
    "Sky and Daylight": "nav.sky_daylight",
    "Precipitation and Snow": "nav.precipitation_snow",
    "Time Series and Overlay": "nav.time_series_overlay",
    "Natural Ventilation": "nav.natural_ventilation",
    "HVAC and Passive Design": "nav.hvac_passive_design",
    "Compare Climates": "nav.compare_climates",
    "Data Quality": "nav.data_quality",
}


def navigation_label(page: str, locale: str | None = None) -> str:
    """Return the localized public label for a stable internal page identifier.

    With no explicit locale, the active execution-context locale is used. This
    lets the unchanged EPW and canonical routing code share one localized
    ``format_func`` while keeping route IDs locale-neutral.
    """
    resolved = active_locale() if locale is None else normalize_locale(locale)
    if resolved == DEFAULT_LOCALE:
        return NAVIGATION_LABELS.get(page, page)
    key = NAVIGATION_TRANSLATION_KEYS.get(page)
    return translate(key, resolved) if key is not None else page


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


def _apply_locale_control_for_app_caller(state: MutableMapping[str, Any]) -> str:
    """Bind the per-session language selector without importing Streamlit here.

    ``app.py`` already calls :func:`apply_queued_navigation` before either the
    EPW or canonical navigation widget is rendered. Reusing that mature hand-off
    keeps the huge app source unchanged and makes one locale selection apply to
    both routing paths. The active locale lives in a ``ContextVar`` so concurrent
    Streamlit sessions do not share mutable module-global language state.
    """
    import sys

    current = normalize_locale(state.get(LOCALE_SESSION_KEY))
    set_active_locale(current)
    caller_globals = sys._getframe(2).f_globals
    streamlit = caller_globals.get("st")
    if streamlit is None:
        return current

    stored = state.get(LOCALE_SESSION_KEY)
    if stored not in SUPPORTED_LOCALES:
        state[LOCALE_SESSION_KEY] = current
    selected = streamlit.sidebar.selectbox(
        translate("ui.language", current),
        SUPPORTED_LOCALES,
        format_func=lambda locale: LOCALE_DISPLAY_NAMES.get(str(locale), str(locale)),
        key=LOCALE_SESSION_KEY,
        label_visibility="collapsed",
    )
    return set_active_locale(str(selected))


def _install_source_parity_for_app_caller() -> None:
    """Install source-parity routing when called from the fully defined app.

    ``app.py`` is deliberately kept as the mature source/AST contract. The
    navigation hand-off is the earliest runtime call made by ``main`` after all
    renderer functions have been defined, so it is a safe place to install the
    new source-neutral routing without importing pandas/numpy/plotly at module
    startup. Ordinary unit tests of this module do not satisfy the app sentinel
    and therefore do not load the parity layer.
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
    from .source_parity_runtime import install_into_app_globals

    install_into_app_globals(caller_globals)


def apply_queued_navigation(state: MutableMapping[str, Any]) -> None:
    """Apply locale/runtime hand-offs before the navigation widget is instantiated."""
    _apply_locale_control_for_app_caller(state)
    _install_source_parity_for_app_caller()
    reset = bool(state.pop(RESET_NAVIGATION_KEY, False))
    pending = state.pop(PENDING_NAVIGATION_KEY, None)
    if reset:
        state.pop(NAVIGATION_KEY, None)
        return
    if pending is not None:
        if pending not in NAVIGATION_PAGES:
            raise ValueError(f"Unknown queued Climate Analyzer page: {pending}")
        state[NAVIGATION_KEY] = pending
