from pathlib import Path

TOOL = Path(__file__).resolve().parents[1]
APP = TOOL / "app.py"
PRECIP = TOOL / "epw_climate_analyzer" / "precipitation.py"
TEST = TOOL / "tests" / "test_pressure_precipitation_contract.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


p = PRECIP.read_text(encoding="utf-8")
p = p.replace('"wet_hours": int((liquid >= wet_threshold_mm).sum()) if liquid_available else None,',
              '"precipitation_records": int((liquid >= wet_threshold_mm).sum()) if liquid_available else None,')
PRECIP.write_text(p, encoding="utf-8")

a = APP.read_text(encoding="utf-8")
a = replace_once(a, '"Wet hours ≥ 0.1 mm",\n        "N/A" if summary["wet_hours"] is None else f"{summary[\'wet_hours\']:,}",',
                 '"Precipitation records ≥ 0.1 mm",\n        "N/A" if summary["precipitation_records"] is None else f"{summary[\'precipitation_records\']:,}",',
                 "summary metric")
a = replace_once(a, 'options.extend(["Precipitation totals", "Wet-hour occurrence", "Liquid precipitation explorer"])',
                 'options.extend(["Precipitation totals", "Precipitation-record occurrence", "Liquid precipitation explorer"])',
                 "options")
a = replace_once(a, 'elif chart_group == "Wet-hour occurrence":',
                 'elif chart_group == "Precipitation-record occurrence":',
                 "branch")
a = replace_once(a, 'threshold = st.number_input("Wet-hour threshold [mm]", min_value=0.0, value=0.1, step=0.1)',
                 'threshold = st.number_input("Precipitation-record threshold [mm]", min_value=0.0, value=0.1, step=0.1)',
                 "threshold label")
a = replace_once(a, 'title=f"Wet-hour occurrence ≥ {threshold:g} mm",\n            labels={x_column: "Period", "hours": "Wet hours"},',
                 'title=f"Precipitation-record occurrence ≥ {threshold:g} mm",\n            labels={x_column: "Period", "hours": "Records meeting threshold"},',
                 "chart labels")
a = replace_once(a, 'fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Wet hours")\n        render_plot(fig, "Counts only EPW records with valid precipitation data that meet the selected depth threshold.")',
                 'fig.update_layout(template="plotly_white", xaxis_title="Period", yaxis_title="Records meeting threshold")\n        render_plot(\n            fig,\n            "Counts EPW precipitation records meeting the selected depth threshold. This is an observation-record occurrence metric, not exact rainfall duration: EPW liquid precipitation depth may refer to the measurement interval reported by Liquid Precipitation Quantity.",\n        )',
                 "interpretation")
APP.write_text(a, encoding="utf-8")

t = TEST.read_text(encoding="utf-8")
t = t.replace('self.assertEqual(summary["wet_hours"], 3)', 'self.assertEqual(summary["precipitation_records"], 3)')
t = t.replace('def test_occurrence_counts_do_not_treat_missing_as_events(self) -> None:',
              'def test_occurrence_counts_do_not_treat_missing_as_events(self) -> None:')
TEST.write_text(t, encoding="utf-8")
print("Precipitation occurrence semantics refined")
