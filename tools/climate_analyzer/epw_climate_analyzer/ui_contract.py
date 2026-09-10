"""Public product copy and navigation contract for Climate Analyzer.

Keeping user-facing navigation labels and state transitions outside ``app.py``
makes the product structure testable without importing Streamlit and separates
stable public terminology from internal page identifiers used by calculation
routing.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


PUBLIC_UX_STAGE = "WEB-0.6"
APP_NAME = "Climate Analyzer"
APP_BROWSER_TITLE = "Climate Analyzer | Building Energy Tools"
APP_TAGLINE = "Climate analysis for building design and building performance"
APP_INTRO = (
    "Explore EPW weather data for temperature, moisture, solar radiation, wind, "
    "passive-design potential and early HVAC decision support."
)

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
    "Natural Ventilation": "Design — Natural ventilation",
    "HVAC and Passive Design": "Design — Passive strategies & HVAC",
    "Compare Climates": "Compare — Multiple climates",
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


def apply_queued_navigation(state: MutableMapping[str, Any]) -> None:
    """Apply queued navigation before the Streamlit navigation widget is instantiated."""
    reset = bool(state.pop(RESET_NAVIGATION_KEY, False))
    pending = state.pop(PENDING_NAVIGATION_KEY, None)
    if reset:
        state.pop(NAVIGATION_KEY, None)
        return
    if pending is not None:
        if pending not in NAVIGATION_PAGES:
            raise ValueError(f"Unknown queued Climate Analyzer page: {pending}")
        state[NAVIGATION_KEY] = pending
