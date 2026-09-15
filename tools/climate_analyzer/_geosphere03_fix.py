from pathlib import Path

root = Path(__file__).resolve().parents[2]
historical_path = root / "tools/climate_analyzer/epw_climate_analyzer/historical.py"
app_path = root / "tools/climate_analyzer/app.py"
geosphere_test_path = root / "tools/climate_analyzer/tests/test_geosphere_public_integration.py"
pressure_test_path = root / "tools/climate_analyzer/tests/test_pressure_precipitation_contract.py"

# ---------------------------------------------------------------------------
# Historical psychrometric pressure contract:
# - measured mode keeps per-record provider pressure and uses median only as fallback;
# - every explicit constant-pressure mode replaces the measured series.
# ---------------------------------------------------------------------------
historical = historical_path.read_text(encoding="utf-8")
old_signature = '''def prepare_historical_analysis_frame(
    dataset: CanonicalClimateDataset,
    *,
    include_psychrometrics: bool = False,
    fallback_pressure_pa: float = DEFAULT_PRESSURE_PA,
) -> pd.DataFrame:
    """Prepare a canonical historical dataset for source-agnostic analysis views."""
    data = add_historical_calendar_columns(dataset.data)
    if include_psychrometrics:
'''
new_signature = '''def prepare_historical_analysis_frame(
    dataset: CanonicalClimateDataset,
    *,
    include_psychrometrics: bool = False,
    fallback_pressure_pa: float = DEFAULT_PRESSURE_PA,
    pressure_override_pa: float | None = None,
) -> pd.DataFrame:
    """Prepare a canonical historical dataset for source-agnostic analysis views.

    ``pressure_override_pa`` is an explicit calculation-mode override. When it
    is ``None``, valid measured station pressure is retained record by record and
    ``fallback_pressure_pa`` is used only for missing/invalid values. When an
    override is supplied, the measured pressure series is deliberately replaced
    before psychrometric derivation.
    """
    data = add_historical_calendar_columns(dataset.data)
    if pressure_override_pa is not None:
        pressure_override = float(pressure_override_pa)
        if not 30_000.0 <= pressure_override <= 120_000.0:
            raise ValueError("Historical psychrometric pressure override must be within 30000...120000 Pa.")
        data["atmospheric_station_pressure_pa"] = pressure_override
    if include_psychrometrics:
'''
if old_signature not in historical:
    raise SystemExit("historical pressure signature anchor not found")
historical = historical.replace(old_signature, new_signature, 1)
historical_path.write_text(historical, encoding="utf-8")

# ---------------------------------------------------------------------------
# Make the pressure-mode branch explicit and pass the override through.
# ---------------------------------------------------------------------------
app = app_path.read_text(encoding="utf-8")
old_pressure_block = '''    measured_median = float(valid_pressure.median()) if not valid_pressure.empty else DEFAULT_PRESSURE_PA
    if pressure_mode == "Normal pressure: 101325 Pa":
        fallback_pressure = DEFAULT_PRESSURE_PA
    elif pressure_mode == "Altitude-derived standard atmosphere pressure":
        fallback_pressure = pressure_from_altitude_m(float(dataset.location.elevation_m or 0.0))
    elif pressure_mode == "Custom constant pressure":
        fallback_pressure = float(custom_pressure or DEFAULT_PRESSURE_PA)
    else:
        fallback_pressure = measured_median

    from epw_climate_analyzer.historical import prepare_historical_analysis_frame
    try:
        full_df = prepare_historical_analysis_frame(
            dataset,
            include_psychrometrics=include_psychrometrics,
            fallback_pressure_pa=fallback_pressure,
        )
'''
new_pressure_block = '''    measured_median = float(valid_pressure.median()) if not valid_pressure.empty else DEFAULT_PRESSURE_PA
    if pressure_mode == "Measured station pressure with fallback median":
        fallback_pressure = measured_median
        pressure_override = None
    elif pressure_mode == "Normal pressure: 101325 Pa":
        fallback_pressure = DEFAULT_PRESSURE_PA
        pressure_override = DEFAULT_PRESSURE_PA
    elif pressure_mode == "Altitude-derived standard atmosphere pressure":
        fallback_pressure = pressure_from_altitude_m(float(dataset.location.elevation_m or 0.0))
        pressure_override = fallback_pressure
    else:
        fallback_pressure = float(custom_pressure or DEFAULT_PRESSURE_PA)
        pressure_override = fallback_pressure

    from epw_climate_analyzer.historical import prepare_historical_analysis_frame
    try:
        full_df = prepare_historical_analysis_frame(
            dataset,
            include_psychrometrics=include_psychrometrics,
            fallback_pressure_pa=fallback_pressure,
            pressure_override_pa=pressure_override,
        )
'''
if old_pressure_block not in app:
    raise SystemExit("historical app pressure block anchor not found")
app = app.replace(old_pressure_block, new_pressure_block, 1)
app = app.replace(
    'st.caption(f"Calculation pressure fallback: {active_pressure:,.0f} Pa")',
    'st.caption(f"Calculation pressure: {active_pressure:,.0f} Pa")',
    1,
)
app_path.write_text(app, encoding="utf-8")

# ---------------------------------------------------------------------------
# Add regression proving explicit pressure modes really override measurements.
# ---------------------------------------------------------------------------
geosphere_tests = geosphere_test_path.read_text(encoding="utf-8")
anchor = '''    def test_psychrometric_derivation_uses_canonical_primary_observations(self) -> None:
        prepared = prepare_historical_analysis_frame(sample_dataset(), include_psychrometrics=True, fallback_pressure_pa=96500.0)
        self.assertIn("humidity_ratio_g_kg", prepared.columns)
        self.assertIn("wet_bulb_temperature_c", prepared.columns)
        self.assertTrue(prepared["humidity_ratio_g_kg"].notna().all())
        self.assertEqual(prepared.attrs["canonical_native_interval_minutes"], 10)
'''
replacement = anchor + '''
    def test_explicit_constant_pressure_replaces_measured_station_pressure(self) -> None:
        prepared = prepare_historical_analysis_frame(
            sample_dataset(),
            include_psychrometrics=True,
            fallback_pressure_pa=101325.0,
            pressure_override_pa=101325.0,
        )
        self.assertTrue((prepared["atmospheric_station_pressure_pa"] == 101325.0).all())
        self.assertTrue(prepared["humidity_ratio_g_kg"].notna().all())

    def test_invalid_constant_pressure_override_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "30000...120000 Pa"):
            prepare_historical_analysis_frame(
                sample_dataset(),
                include_psychrometrics=True,
                pressure_override_pa=200000.0,
            )
'''
if anchor not in geosphere_tests:
    raise SystemExit("GeoSphere pressure regression anchor not found")
geosphere_tests = geosphere_tests.replace(anchor, replacement, 1)
geosphere_test_path.write_text(geosphere_tests, encoding="utf-8")

# ---------------------------------------------------------------------------
# The old EPW contract test assumed there could only ever be one pressure-mode
# selectbox in app.py. Scope it to the selector whose option list is EPW-specific.
# ---------------------------------------------------------------------------
pressure_tests = pressure_test_path.read_text(encoding="utf-8")
old_method = '''    def test_epw_station_pressure_is_the_default_ui_mode(self) -> None:
        matches = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "selectbox":
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value != "Psychrometric pressure mode":
                continue
            matches.append(node)
        self.assertEqual(len(matches), 1)
        keywords = {kw.arg: kw.value for kw in matches[0].keywords if kw.arg}
        self.assertEqual(ast.literal_eval(keywords["index"]), 1)
        self.assertIn("atmospheric station pressure stored in the EPW", self.source)
        self.assertIn("hourly EPW station values; fallback median", self.source)
'''
new_method = '''    def test_epw_station_pressure_is_the_default_ui_mode(self) -> None:
        matches = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "selectbox":
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value != "Psychrometric pressure mode":
                continue
            if len(node.args) < 2:
                continue
            try:
                options = ast.literal_eval(node.args[1])
            except Exception:
                continue
            if "EPW station pressure with fallback median" in options:
                matches.append(node)
        self.assertEqual(len(matches), 1)
        keywords = {kw.arg: kw.value for kw in matches[0].keywords if kw.arg}
        self.assertEqual(ast.literal_eval(keywords["index"]), 1)
        self.assertIn("atmospheric station pressure stored in the EPW", self.source)
        self.assertIn("hourly EPW station values; fallback median", self.source)
'''
if old_method not in pressure_tests:
    raise SystemExit("EPW pressure contract test anchor not found")
pressure_tests = pressure_tests.replace(old_method, new_method, 1)
pressure_test_path.write_text(pressure_tests, encoding="utf-8")

print("CLIMATE-GEOSPHERE-0.3 pressure/test remediation applied")
