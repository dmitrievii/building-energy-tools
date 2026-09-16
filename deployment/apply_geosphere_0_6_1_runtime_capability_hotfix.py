from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "tools/climate_analyzer/app.py"
TEST = ROOT / "tools/climate_analyzer/tests/test_geosphere_0_6_1_overview_range_coverage.py"

text = APP.read_text(encoding="utf-8")
marker = "can_derive_psychrometrics = ("
if marker not in text:
    old = '''    variable_label = st.selectbox("Variable", variable_labels, index=variable_labels.index(default_variable))
    column, unit = VARIABLES[variable_label]
'''
    new = '''    available_labels = [
        label
        for label in variable_labels
        if VARIABLES[label][0] in df.columns
        and pd.to_numeric(df[VARIABLES[label][0]], errors="coerce").notna().any()
    ]
    if not available_labels:
        st.info("No measured numeric variables required by this explorer are available in the loaded dataset.")
        return
    selected_default = default_variable if default_variable in available_labels else available_labels[0]
    variable_label = st.selectbox("Variable", available_labels, index=available_labels.index(selected_default))
    column, unit = VARIABLES[variable_label]
'''
    if text.count(old) != 1:
        raise RuntimeError(f"generic variable selector block matches: {text.count(old)}")
    text = text.replace(old, new, 1)

    old = '''    from epw_climate_analyzer.historical_capabilities import available_historical_pages

    historical_pages = available_historical_pages(dataset.data)
'''
    new = '''    from epw_climate_analyzer.historical_capabilities import available_historical_pages, has_numeric_observations

    historical_pages = available_historical_pages(dataset.data)
'''
    if text.count(old) != 1:
        raise RuntimeError(f"historical capability import block matches: {text.count(old)}")
    text = text.replace(old, new, 1)

    old = '''    include_psychrometrics = page in {"Temperature", "Humidity and Psychrometrics", "Time Series and Overlay"}
'''
    new = '''    can_derive_psychrometrics = (
        has_numeric_observations(dataset.data, "dry_bulb_temperature_c")
        and has_numeric_observations(dataset.data, "relative_humidity_pct")
    )
    include_psychrometrics = can_derive_psychrometrics and page in {
        "Temperature", "Humidity and Psychrometrics", "Time Series and Overlay"
    }
'''
    if text.count(old) != 1:
        raise RuntimeError(f"psychrometric route block matches: {text.count(old)}")
    text = text.replace(old, new, 1)
    APP.write_text(text, encoding="utf-8")


test = TEST.read_text(encoding="utf-8")
test_marker = "test_temperature_only_runtime_does_not_require_humidity"
if test_marker not in test:
    insertion = '''

class GeoSphere061RuntimeCapabilityTests(unittest.TestCase):
    def test_temperature_only_runtime_does_not_require_humidity(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("can_derive_psychrometrics = (", source)
        self.assertIn('has_numeric_observations(dataset.data, "dry_bulb_temperature_c")', source)
        self.assertIn('has_numeric_observations(dataset.data, "relative_humidity_pct")', source)
        self.assertIn("include_psychrometrics = can_derive_psychrometrics", source)

    def test_generic_explorer_filters_to_actual_numeric_columns(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("available_labels = [", source)
        self.assertIn("VARIABLES[label][0] in df.columns", source)
        self.assertIn("selected_default = default_variable if default_variable in available_labels", source)

    def test_temperature_only_historical_preparation_is_valid_without_psychrometrics(self) -> None:
        from epw_climate_analyzer.climate_model import (
            CanonicalClimateDataset,
            ClimateLocation,
            ClimateProvenance,
            ClimateTemporalMetadata,
        )
        from epw_climate_analyzer.historical import prepare_historical_analysis_frame

        index = pd.date_range("2025-01-01T00:00:00Z", periods=6, freq="10min")
        data = pd.DataFrame({"dry_bulb_temperature_c": [1, 2, 3, 4, 5, 6]}, index=index)
        data.attrs["canonical_native_interval_minutes"] = 10
        dataset = CanonicalClimateDataset(
            climate_id="temp-only",
            display_name="Temperature only",
            data=data,
            location=ClimateLocation(47.0, 15.0, 350.0, "Test", "", "Austria", "1"),
            temporal=ClimateTemporalMetadata(10, "historical", "UTC", "unknown"),
            provenance=ClimateProvenance("GeoSphere Austria", "test", "Dataset API JSON", "test"),
        )
        prepared = prepare_historical_analysis_frame(dataset, include_psychrometrics=False)
        self.assertIn("dry_bulb_temperature_c", prepared.columns)
        self.assertNotIn("humidity_ratio_g_kg", prepared.columns)
        self.assertIn("Temperature", available_historical_pages(prepared))

'''
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in test:
        raise RuntimeError("test insertion point missing")
    # The existing test module imported individual helpers; make the new helper reference explicit.
    test = test.replace(
        '    historical_variable_coverage,\n)',
        '    historical_variable_coverage,\n)',
        1,
    )
    test = test.replace(needle, insertion + needle, 1)
    TEST.write_text(test, encoding="utf-8")

print("CLIMATE_GEOSPHERE_0_6_1_RUNTIME_CAPABILITY_HOTFIX_APPLIED")
