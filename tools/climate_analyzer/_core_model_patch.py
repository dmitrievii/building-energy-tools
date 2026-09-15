from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "epw_climate_analyzer" / "climate_model.py"
TS = ROOT / "epw_climate_analyzer" / "timeseries.py"

model = MODEL.read_text(encoding="utf-8")
old_model = '''        inferred = infer_native_resolution_minutes(validated.index)\n        # Gaps are allowed in historical observations, therefore only reject an\n        # explicit cadence that is finer than the actually represented minimum\n        # positive spacing. A declared 10-minute station remains valid even if\n        # some observations are missing and the median gap becomes 20 minutes.\n        positive = _positive_interval_minutes(validated.index)\n        if positive and self.temporal.native_interval_minutes < min(positive):\n            raise ValueError(\n                "Declared native interval is finer than any timestamp spacing present in the canonical frame."\n            )\n        validated.attrs.setdefault("canonical_native_interval_minutes", self.temporal.native_interval_minutes)\n'''
new_model = '''        inferred = infer_native_resolution_minutes(validated.index)\n        # The declared cadence belongs to the source contract. Historical\n        # observations may have arbitrary gaps, so observed timestamp spacing\n        # must not rewrite or invalidate a provider-declared native interval.\n        validated.attrs.setdefault("canonical_native_interval_minutes", self.temporal.native_interval_minutes)\n'''
if old_model not in model:
    raise SystemExit("climate_model cadence block not found")
MODEL.write_text(model.replace(old_model, new_model, 1), encoding="utf-8")

ts = TS.read_text(encoding="utf-8")
old_import = 'from .chart_theme import metric_color\n'
new_import = '''from .chart_theme import metric_color\nfrom .climate_model import (\n    aggregation_semantics_for,\n    infer_native_resolution_minutes,\n    unit_family_for,\n)\n'''
if old_import not in ts:
    raise SystemExit("timeseries import anchor not found")
ts = ts.replace(old_import, new_import, 1)

start = ts.index('# Aggregation semantics are quantity-specific.')
end = ts.index('@dataclass(frozen=True)\nclass OverlaySeries:', start)
ts = ts[:start] + ts[end:]

ts = ts.replace(
    '        return UNIT_FAMILY_BY_COLUMN.get(self.column, self.unit)\n',
    '        return unit_family_for(self.column, self.unit)\n',
    1,
)
old_native = '''def native_resolution_minutes(index: pd.DatetimeIndex) -> int:\n    """Infer the median positive native timestep in whole minutes."""\n    idx = pd.DatetimeIndex(index).sort_values().unique()\n    if len(idx) < 2:\n        return 60\n    deltas = pd.Series(idx[1:] - idx[:-1])\n    positive = deltas[deltas > pd.Timedelta(0)]\n    if positive.empty:\n        return 60\n    minutes = float(positive.median() / pd.Timedelta(minutes=1))\n    return max(1, int(round(minutes)))\n'''
new_native = '''def native_resolution_minutes(index: pd.DatetimeIndex) -> int:\n    """Compatibility wrapper around the canonical source-resolution inference."""\n    return infer_native_resolution_minutes(index)\n'''
if old_native not in ts:
    raise SystemExit("timeseries native resolution function not found")
ts = ts.replace(old_native, new_native, 1)
old_semantics = '''def aggregation_semantics(column: str) -> str:\n    if column in SUM_COLUMNS:\n        return "sum"\n    if column in CIRCULAR_COLUMNS:\n        return "circular mean"\n    return "mean"\n'''
new_semantics = '''def aggregation_semantics(column: str) -> str:\n    """Compatibility wrapper around canonical quantity aggregation semantics."""\n    return aggregation_semantics_for(column)\n'''
if old_semantics not in ts:
    raise SystemExit("timeseries aggregation semantics function not found")
ts = ts.replace(old_semantics, new_semantics, 1)
TS.write_text(ts, encoding="utf-8")

print("CLIMATE-CORE-0.2 integration patch applied")
