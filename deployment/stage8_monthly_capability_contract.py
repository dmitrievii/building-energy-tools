from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} block, found {count}")
    return text.replace(old, new, 1)


cleanup_path = Path("tools/climate_analyzer/epw_climate_analyzer/source_parity_monthly_cleanup.py")
cleanup = cleanup_path.read_text(encoding="utf-8")

cleanup = replace_once(
    cleanup,
    'MONTHLY_OVERLAY_RESOLUTIONS = ("Monthly", "Annual")\n',
    'MONTHLY_OVERLAY_RESOLUTIONS = ("Native", "Monthly", "Seasonal", "Annual")\n',
    "monthly overlay resolution capability",
)

helper_anchor = '''def monthly_semantics_from_column(column: str) -> str | None:\n    value = str(column)\n    if not value.startswith("monthly__"):\n        return None\n    parts = value.split("__", 3)\n    if len(parts) < 4:\n        return None\n    semantics = parts[1].replace("_", " ")\n    return semantics if semantics in {"mean", "sum", "min", "max", "circular mean"} else None\n\n\n'''
helper_replacement = helper_anchor + '''def monthly_overlay_resolution_options(column: str) -> tuple[str, ...]:\n    """Return scientifically valid overlay resolutions for a native-monthly field.\n\n    Native always preserves the provider-published monthly observation/statistic.\n    Coarser aggregation is exposed only when the quantity semantics are known.\n    """\n    known_semantics = (\n        monthly_semantics_from_column(column) is not None\n        or column in monthly_ui._MONTHLY_CANONICAL_ALIASES.values()\n    )\n    return MONTHLY_OVERLAY_RESOLUTIONS if known_semantics else ("Native",)\n\n\ndef monthly_overlay_resolution_key(index: int) -> str:\n    """Return a monthly-only widget key that cannot inherit generic overlay state."""\n    return f"monthly_overlay_resolution_{int(index)}"\n\n\n'''
cleanup = replace_once(cleanup, helper_anchor, helper_replacement, "monthly overlay capability helper insertion")

cleanup = replace_once(
    cleanup,
    '''        resolution_options = list(MONTHLY_OVERLAY_RESOLUTIONS)\n        if monthly_semantics_from_column(column) is None and column not in monthly_ui._MONTHLY_CANONICAL_ALIASES.values():\n            # Unknown provider statistics can still be plotted monthly. Do not\n            # invent an annual meaning until their provider contract is known.\n            resolution_options = ["Monthly"]\n''',
    '''        resolution_options = list(monthly_overlay_resolution_options(column))\n        resolution_key = monthly_overlay_resolution_key(i)\n''',
    "monthly overlay resolution selection",
)

cleanup = replace_once(
    cleanup,
    '''            f"Series {i + 1} resolution", resolution_options, index=0, key=f"overlay_resolution_{i}",\n''',
    '''            f"Series {i + 1} resolution", resolution_options, index=0, key=resolution_key,\n''',
    "monthly overlay isolated widget key",
)

cleanup = replace_once(
    cleanup,
    '''            help=(\n                "Monthly preserves the published value. Annual applies the canonical quantity semantics "\n                f"({semantics}) to the twelve published months when available."\n            ),\n''',
    '''            help=(\n                "Native preserves each provider-published monthly value. Monthly keeps calendar-month bins without "\n                "reconstructing finer data. Seasonal and Annual aggregate only published monthly records using the "\n                f"canonical quantity semantics ({semantics}) when that semantics is known."\n            ),\n''',
    "monthly overlay help text",
)

cleanup_path.write_text(cleanup, encoding="utf-8")


test_path = Path("tools/climate_analyzer/tests/test_geosphere_monthly_cleanup_0_7_5_4.py")
test = test_path.read_text(encoding="utf-8")

test = replace_once(
    test,
    '''from epw_climate_analyzer.source_parity_monthly_cleanup import (\n    MONTHLY_GENERIC_AGGREGATIONS,\n    _forward_monthly_overlay,\n    describe_monthly_parameter,\n    monthly_semantics_from_column,\n    semantic_analysis_column,\n)\n''',
    '''from epw_climate_analyzer.source_parity_monthly_cleanup import (\n    MONTHLY_GENERIC_AGGREGATIONS,\n    MONTHLY_OVERLAY_RESOLUTIONS,\n    _forward_monthly_overlay,\n    describe_monthly_parameter,\n    monthly_overlay_resolution_key,\n    monthly_overlay_resolution_options,\n    monthly_semantics_from_column,\n    semantic_analysis_column,\n)\n''',
    "monthly cleanup imports",
)

test = replace_once(
    test,
    '''    def test_monthly_and_annual_are_the_only_generic_periods(self) -> None:\n        self.assertEqual(MONTHLY_GENERIC_AGGREGATIONS, ("Monthly", "Annual"))\n\n''',
    '''    def test_monthly_and_annual_are_the_only_generic_periods(self) -> None:\n        self.assertEqual(MONTHLY_GENERIC_AGGREGATIONS, ("Monthly", "Annual"))\n\n    def test_native_monthly_overlay_exposes_identity_and_only_valid_coarser_periods(self) -> None:\n        self.assertEqual(\n            MONTHLY_OVERLAY_RESOLUTIONS,\n            ("Native", "Monthly", "Seasonal", "Annual"),\n        )\n        self.assertEqual(\n            monthly_overlay_resolution_options("dry_bulb_temperature_c"),\n            ("Native", "Monthly", "Seasonal", "Annual"),\n        )\n        self.assertEqual(\n            monthly_overlay_resolution_options("monthly__mean__temperature__tl_mittel"),\n            ("Native", "Monthly", "Seasonal", "Annual"),\n        )\n        self.assertEqual(\n            monthly_overlay_resolution_options("provider_defined_unknown_statistic"),\n            ("Native",),\n        )\n\n    def test_monthly_resolution_widget_state_isolated_from_generic_overlay(self) -> None:\n        self.assertEqual(monthly_overlay_resolution_key(0), "monthly_overlay_resolution_0")\n        self.assertNotEqual(monthly_overlay_resolution_key(0), "overlay_resolution_0")\n\n''',
    "native monthly capability regression",
)

test_path.write_text(test, encoding="utf-8")
