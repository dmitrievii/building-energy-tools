"""Public product copy and navigation contract for Climate Analyzer.

Keeping user-facing navigation labels outside ``app.py`` makes the product
structure testable without importing Streamlit and separates stable public
terminology from internal page identifiers used by calculation routing.
"""

from __future__ import annotations


PUBLIC_UX_STAGE = "WEB-0.6"
APP_NAME = "Climate Analyzer"
APP_BROWSER_TITLE = "Climate Analyzer | Building Energy Tools"
APP_TAGLINE = "Climate analysis for building design and building performance"
APP_INTRO = (
    "Explore EPW weather data for temperature, moisture, solar radiation, wind, "
    "passive-design potential and early HVAC decision support."
)

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
