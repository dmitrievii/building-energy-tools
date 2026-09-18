from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()
APP = ROOT / "app.py"
COMPARISON = ROOT / "epw_climate_analyzer" / "comparison.py"
TEST = ROOT / "tests" / "test_psychrometric_redesign_0_7_4.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one anchor, found {count}: {old[:140]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    COMPARISON,
    '            xs, ys = envelope_polygon_coordinates(envelope, chart_type=chart_type, pressure_pa=pressure_pa)\n',
    '''            if "atmospheric_station_pressure_pa" in climate.data.columns:
                observed_pressure = pd.to_numeric(climate.data["atmospheric_station_pressure_pa"], errors="coerce").dropna()
                climate_pressure_pa = float(observed_pressure.median()) if not observed_pressure.empty else float(pressure_pa)
            else:
                climate_pressure_pa = float(pressure_pa)
            xs, ys = envelope_polygon_coordinates(envelope, chart_type=chart_type, pressure_pa=climate_pressure_pa)
''',
)
replace_once(
    COMPARISON,
    '''    if chart_type == "T-d":
        for curve in psychrometric_rh_curves("T-d", pressure_pa=pressure_pa):
            fig.add_trace(
                go.Scatter(
                    x=curve["x"], y=curve["y"], mode="lines",
                    line=dict(width=0.55, color="rgba(75,85,99,0.34)"),
                    showlegend=False, hoverinfo="skip",
                )
            )
''',
    '''    # Do not draw one shared relative-humidity construction grid here.
    # Different comparison climates can sit at different station pressures, so
    # a single RH grid would imply one pressure state that is not valid for all
    # datasets. Actual T/d or i/d observations remain directly comparable.
''',
)
replace_once(
    APP,
    '            "All selected climates use one shared psychrometric axis. Middle 90% retains the densest 1 °C × 5 %RH cells containing at least 90% of each climate\'s represented duration."\n',
    '            "All selected climates use one shared psychrometric axis. Middle 90% retains the densest 1 °C × 5 %RH cells containing at least 90% of each climate\'s represented duration. A common RH construction grid is omitted because comparison climates may have different station pressures."\n',
)
replace_once(
    TEST,
    '        self.assertEqual(fig.layout.legend.title.text, "Climate")\n        self.assertFalse(any(str(key).startswith("xaxis2") or str(key).startswith("yaxis2") for key in fig.layout))\n',
    '        self.assertEqual(fig.layout.legend.title.text, "Climate")\n        self.assertFalse(any(str(key).startswith("xaxis2") or str(key).startswith("yaxis2") for key in fig.layout))\n        self.assertFalse(any(getattr(trace, "showlegend", None) is False and getattr(trace, "hoverinfo", None) == "skip" for trace in fig.data))\n',
)

print("0.7.4-D comparison-pressure remediation applied")
