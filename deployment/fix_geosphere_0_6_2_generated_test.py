from pathlib import Path

path = Path(__file__).resolve().parents[1] / "tools/climate_analyzer/tests/test_geosphere_0_6_2_precip_map_variables.py"
text = path.read_text(encoding="utf-8")

replacements = [
    (
        '''        self.assertNotIn('st.multiselect(
            "Measured variables to load"', self.source)
''',
        '''        self.assertNotIn('key="geosphere_provider_parameters"', self.source)
''',
    ),
    (
        '''        self.assertIn("station_catalog_persistent_map_layers(
            map_groups", self.source)
''',
        '''        self.assertIn("station_catalog_persistent_map_layers(", self.source)
        self.assertIn("marker_payload=marker_payload", self.source)
''',
    ),
]

for broken, fixed in replacements:
    if broken not in text:
        raise RuntimeError(f"Expected generated-test syntax defect was not found: {broken!r}")
    text = text.replace(broken, fixed, 1)

path.write_text(text, encoding="utf-8")
print("CLIMATE_GEOSPHERE_0_6_2_GENERATED_TEST_FIXED")
