"""Lightweight presentation-layer internationalization for Climate Analyzer.

The scientific/runtime model deliberately remains locale-neutral. This module
contains only small Python dictionaries, locale resolution helpers and a
``ContextVar`` for the active presentation locale, so adding translations does
not add startup-heavy dependencies to the Streamlit app.

Internal page IDs, DataFrame column names, provider parameter names and other
calculation/routing identifiers must never be translated. Callers translate
only presentation strings at the UI boundary.
"""

from __future__ import annotations

from contextvars import ContextVar


DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "de", "es", "ru")
LOCALE_SESSION_KEY = "climate_analyzer_locale"

LOCALE_DISPLAY_NAMES = {
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "ru": "Русский",
}

_ACTIVE_LOCALE: ContextVar[str] = ContextVar(
    "climate_analyzer_active_locale",
    default=DEFAULT_LOCALE,
)


TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "app.tagline": "Climate analysis for building design and building performance",
        "ui.language": "Language",
        "ui.analysis_section": "Analysis section",
        "sidebar.explore": "Explore",
        "sidebar.choose_source": "Choose a climate source to start the analysis.",
        "nav.climate_file_source": "Start — Climate source",
        "nav.overview": "Summary — Overview",
        "nav.temperature": "Climate — Temperature",
        "nav.humidity_psychrometrics": "Climate — Moisture & psychrometrics",
        "nav.solar_radiation": "Climate — Solar radiation",
        "nav.wind_ventilation": "Climate — Wind",
        "nav.sky_daylight": "Climate — Sky & daylight",
        "nav.precipitation_snow": "Climate — Precipitation & snow",
        "nav.time_series_overlay": "Explore — Time series & overlay",
        "nav.natural_ventilation": "Design — Natural ventilation",
        "nav.hvac_passive_design": "Design — Passive strategies & HVAC",
        "nav.compare_climates": "Compare — Multiple climates",
        "nav.data_quality": "Data — Quality & metadata",
    },
    "de": {
        "app.tagline": "Klimaanalyse für Gebäudeentwurf und Gebäudeperformance",
        "ui.language": "Sprache",
        "ui.analysis_section": "Analysebereich",
        "sidebar.explore": "Analyse",
        "sidebar.choose_source": "Wählen Sie eine Klimaquelle, um die Analyse zu starten.",
        "nav.climate_file_source": "Start — Klimaquelle",
        "nav.overview": "Zusammenfassung — Übersicht",
        "nav.temperature": "Klima — Temperatur",
        "nav.humidity_psychrometrics": "Klima — Feuchte & Psychrometrie",
        "nav.solar_radiation": "Klima — Solarstrahlung",
        "nav.wind_ventilation": "Klima — Wind",
        "nav.sky_daylight": "Klima — Himmel & Tageslicht",
        "nav.precipitation_snow": "Klima — Niederschlag & Schnee",
        "nav.time_series_overlay": "Analyse — Zeitreihen & Überlagerung",
        "nav.natural_ventilation": "Entwurf — Natürliche Lüftung",
        "nav.hvac_passive_design": "Entwurf — Passive Strategien & HVAC",
        "nav.compare_climates": "Vergleich — Mehrere Klimata",
        "nav.data_quality": "Daten — Qualität & Metadaten",
    },
    "es": {
        "app.tagline": "Análisis climático para diseño y rendimiento de edificios",
        "ui.language": "Idioma",
        "ui.analysis_section": "Sección de análisis",
        "sidebar.explore": "Explorar",
        "sidebar.choose_source": "Seleccione una fuente climática para iniciar el análisis.",
        "nav.climate_file_source": "Inicio — Fuente climática",
        "nav.overview": "Resumen — Vista general",
        "nav.temperature": "Clima — Temperatura",
        "nav.humidity_psychrometrics": "Clima — Humedad y psicrometría",
        "nav.solar_radiation": "Clima — Radiación solar",
        "nav.wind_ventilation": "Clima — Viento",
        "nav.sky_daylight": "Clima — Cielo y luz natural",
        "nav.precipitation_snow": "Clima — Precipitación y nieve",
        "nav.time_series_overlay": "Explorar — Series temporales y superposición",
        "nav.natural_ventilation": "Diseño — Ventilación natural",
        "nav.hvac_passive_design": "Diseño — Estrategias pasivas y HVAC",
        "nav.compare_climates": "Comparar — Múltiples climas",
        "nav.data_quality": "Datos — Calidad y metadatos",
    },
    "ru": {
        "app.tagline": "Климатический анализ для проектирования и оценки зданий",
        "ui.language": "Язык",
        "ui.analysis_section": "Раздел анализа",
        "sidebar.explore": "Анализ",
        "sidebar.choose_source": "Выберите источник климатических данных, чтобы начать анализ.",
        "nav.climate_file_source": "Старт — Источник климатических данных",
        "nav.overview": "Сводка — Обзор",
        "nav.temperature": "Климат — Температура",
        "nav.humidity_psychrometrics": "Климат — Влажность и психрометрия",
        "nav.solar_radiation": "Климат — Солнечная радиация",
        "nav.wind_ventilation": "Климат — Ветер",
        "nav.sky_daylight": "Климат — Небо и естественное освещение",
        "nav.precipitation_snow": "Климат — Осадки и снег",
        "nav.time_series_overlay": "Анализ — Временные ряды и наложение",
        "nav.natural_ventilation": "Проектирование — Естественная вентиляция",
        "nav.hvac_passive_design": "Проектирование — Пассивные стратегии и HVAC",
        "nav.compare_climates": "Сравнение — Несколько климатов",
        "nav.data_quality": "Данные — Качество и метаданные",
    },
}


def normalize_locale(locale: str | None) -> str:
    """Resolve a locale or language tag to one of the supported base locales.

    Region/script suffixes are intentionally ignored for this i18n stage,
    e.g. ``de-AT`` -> ``de`` and ``es_ES`` -> ``es``. Unknown or empty values
    fall back deterministically to English.
    """
    if locale is None:
        return DEFAULT_LOCALE
    normalized = str(locale).strip().replace("_", "-").lower()
    if not normalized:
        return DEFAULT_LOCALE
    base = normalized.split("-", 1)[0]
    return base if base in SUPPORTED_LOCALES else DEFAULT_LOCALE


def set_active_locale(locale: str | None) -> str:
    """Set the locale for the current execution context and return its base code."""
    resolved = normalize_locale(locale)
    _ACTIVE_LOCALE.set(resolved)
    return resolved


def active_locale() -> str:
    """Return the locale bound to the current execution context."""
    return normalize_locale(_ACTIVE_LOCALE.get())


def translate(key: str, locale: str | None = None) -> str:
    """Return a localized presentation string with deterministic EN fallback.

    Omitting ``locale`` uses the active execution-context locale. Explicit
    locale arguments remain deterministic and independent of the active context.
    """
    resolved = active_locale() if locale is None else normalize_locale(locale)
    english = TRANSLATIONS[DEFAULT_LOCALE]
    return TRANSLATIONS[resolved].get(key, english.get(key, key))


def translation_key_sets() -> dict[str, frozenset[str]]:
    """Expose immutable key sets for validation without exposing mutable views."""
    return {locale: frozenset(catalog) for locale, catalog in TRANSLATIONS.items()}
