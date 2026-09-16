from pathlib import Path

path = Path(__file__).resolve().parents[1] / "tools/climate_analyzer/tests/test_geosphere_0_6_2_precip_map_variables.py"
text = path.read_text(encoding="utf-8")
broken = '''        self.assertNotIn('st.multiselect(
            "Measured variables to load"', self.source)
'''
fixed = '''        self.assertNotIn('key="geosphere_provider_parameters"', self.source)
'''
if broken not in text:
    raise RuntimeError("Expected generated-test syntax defect was not found")
path.write_text(text.replace(broken, fixed, 1), encoding="utf-8")
print("CLIMATE_GEOSPHERE_0_6_2_GENERATED_TEST_FIXED")
