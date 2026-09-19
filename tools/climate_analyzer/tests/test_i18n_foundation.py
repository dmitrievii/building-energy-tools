from __future__ import annotations

import ast
import unittest
from pathlib import Path

from epw_climate_analyzer.i18n import (
    DEFAULT_LOCALE,
    LOCALE_DISPLAY_NAMES,
    LOCALE_SESSION_KEY,
    SUPPORTED_LOCALES,
    active_locale,
    normalize_locale,
    set_active_locale,
    translate,
    translation_key_sets,
)
from epw_climate_analyzer.ui_contract import (
    NAVIGATION_LABELS,
    NAVIGATION_PAGES,
    NAVIGATION_TRANSLATION_KEYS,
    apply_queued_navigation,
    navigation_label,
)


TOOL_ROOT = Path(__file__).resolve().parents[1]
I18N_PATH = TOOL_ROOT / "epw_climate_analyzer" / "i18n.py"
APP_PATH = TOOL_ROOT / "app.py"


class _FakeSidebar:
    def __init__(self, state: dict[str, object], selected: str) -> None:
        self.state = state
        self.selected = selected
        self.calls: list[dict[str, object]] = []

    def selectbox(self, label: str, options: tuple[str, ...], **kwargs: object) -> str:
        self.calls.append({"label": label, "options": options, **kwargs})
        key = str(kwargs["key"])
        self.state[key] = self.selected
        return self.selected


class _FakeStreamlit:
    def __init__(self, state: dict[str, object], selected: str) -> None:
        self.sidebar = _FakeSidebar(state, selected)


class I18nFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        set_active_locale(DEFAULT_LOCALE)

    def tearDown(self) -> None:
        set_active_locale(DEFAULT_LOCALE)
        globals().pop("st", None)

    def test_supported_locale_contract(self) -> None:
        self.assertEqual(DEFAULT_LOCALE, "en")
        self.assertEqual(SUPPORTED_LOCALES, ("en", "de", "es", "ru"))
        self.assertEqual(LOCALE_SESSION_KEY, "climate_analyzer_locale")
        self.assertEqual(set(LOCALE_DISPLAY_NAMES), set(SUPPORTED_LOCALES))
        self.assertEqual(LOCALE_DISPLAY_NAMES["de"], "Deutsch")
        self.assertEqual(LOCALE_DISPLAY_NAMES["es"], "Español")
        self.assertEqual(LOCALE_DISPLAY_NAMES["ru"], "Русский")

    def test_locale_normalization_is_region_tolerant_and_fail_safe(self) -> None:
        cases = {
            None: "en",
            "": "en",
            "EN": "en",
            "de-AT": "de",
            "de_AT": "de",
            "es-ES": "es",
            "ru-RU": "ru",
            "fr-FR": "en",
            "unknown": "en",
        }
        for supplied, expected in cases.items():
            with self.subTest(supplied=supplied):
                self.assertEqual(normalize_locale(supplied), expected)

    def test_active_locale_is_execution_context_local_and_normalized(self) -> None:
        self.assertEqual(active_locale(), "en")
        self.assertEqual(set_active_locale("de-AT"), "de")
        self.assertEqual(active_locale(), "de")
        self.assertEqual(translate("nav.temperature"), "Klima — Temperatur")
        self.assertEqual(translate("nav.temperature", "es-ES"), "Clima — Temperatura")

    def test_all_locale_catalogs_have_identical_key_coverage(self) -> None:
        key_sets = translation_key_sets()
        self.assertEqual(set(key_sets), set(SUPPORTED_LOCALES))
        english_keys = key_sets[DEFAULT_LOCALE]
        self.assertGreater(len(english_keys), 10)
        for locale in SUPPORTED_LOCALES:
            self.assertEqual(key_sets[locale], english_keys, locale)

    def test_translate_uses_english_and_key_fallbacks_deterministically(self) -> None:
        self.assertEqual(
            translate("nav.temperature", "de-AT"),
            "Klima — Temperatur",
        )
        self.assertEqual(
            translate("nav.temperature", "fr-FR"),
            "Climate — Temperature",
        )
        self.assertEqual(translate("missing.translation.key", "ru"), "missing.translation.key")

    def test_navigation_ids_remain_stable_and_translation_mapping_is_complete(self) -> None:
        self.assertEqual(set(NAVIGATION_TRANSLATION_KEYS), set(NAVIGATION_PAGES))
        self.assertEqual(set(NAVIGATION_LABELS), set(NAVIGATION_PAGES))
        self.assertEqual(NAVIGATION_PAGES[0], "Climate File Source")
        self.assertEqual(NAVIGATION_PAGES[-1], "Data Quality")

    def test_default_english_navigation_is_exact_legacy_contract(self) -> None:
        for page in NAVIGATION_PAGES:
            with self.subTest(page=page):
                self.assertEqual(navigation_label(page), NAVIGATION_LABELS[page])
                self.assertEqual(navigation_label(page, "en"), NAVIGATION_LABELS[page])
        self.assertEqual(
            navigation_label("Time Series and Overlay"),
            "Explore — Time series & overlay",
        )

    def test_navigation_localizes_presentation_only(self) -> None:
        expected = {
            "de": "Vergleich — Mehrere Klimata",
            "es": "Comparar — Múltiples climas",
            "ru": "Сравнение — Несколько климатов",
        }
        for locale, label in expected.items():
            with self.subTest(locale=locale):
                self.assertEqual(navigation_label("Compare Climates", locale), label)
        self.assertEqual(navigation_label("Unknown page", "de"), "Unknown page")

    def test_navigation_without_explicit_locale_uses_active_context(self) -> None:
        set_active_locale("ru")
        self.assertEqual(navigation_label("Overview"), "Сводка — Обзор")
        self.assertEqual(navigation_label("Overview", "en"), "Summary — Overview")

    def test_shared_runtime_handoff_binds_sidebar_language_selector(self) -> None:
        state: dict[str, object] = {}
        fake = _FakeStreamlit(state, "de")
        globals()["st"] = fake

        apply_queued_navigation(state)

        self.assertEqual(state[LOCALE_SESSION_KEY], "de")
        self.assertEqual(active_locale(), "de")
        self.assertEqual(navigation_label("Temperature"), "Klima — Temperatur")
        self.assertEqual(len(fake.sidebar.calls), 1)
        call = fake.sidebar.calls[0]
        self.assertEqual(call["label"], "Language")
        self.assertEqual(call["options"], SUPPORTED_LOCALES)
        self.assertEqual(call["key"], LOCALE_SESSION_KEY)
        self.assertEqual(call["label_visibility"], "collapsed")

    def test_invalid_stored_locale_is_normalized_before_widget_creation(self) -> None:
        state: dict[str, object] = {LOCALE_SESSION_KEY: "de-AT"}
        fake = _FakeStreamlit(state, "de")
        globals()["st"] = fake

        apply_queued_navigation(state)

        self.assertEqual(fake.sidebar.calls[0]["label"], "Sprache")
        self.assertEqual(state[LOCALE_SESSION_KEY], "de")
        self.assertEqual(active_locale(), "de")

    def test_mature_app_source_remains_unchanged_for_selector_stage(self) -> None:
        source = APP_PATH.read_text(encoding="utf-8")
        self.assertIn("apply_queued_navigation(st.session_state)", source)
        self.assertIn("format_func=navigation_label", source)
        self.assertNotIn("LOCALE_SESSION_KEY", source)
        self.assertNotIn("SUPPORTED_LOCALES", source)

    def test_i18n_module_has_no_heavy_or_third_party_imports(self) -> None:
        tree = ast.parse(I18N_PATH.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        forbidden_prefixes = (
            "pandas",
            "numpy",
            "plotly",
            "streamlit",
            "folium",
            "babel",
            "gettext",
        )
        self.assertFalse(
            [name for name in imports if name.startswith(forbidden_prefixes)],
            sorted(imports),
        )


if __name__ == "__main__":
    unittest.main()
