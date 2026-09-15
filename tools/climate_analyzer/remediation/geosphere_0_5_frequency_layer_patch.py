from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ROOT / "epw_climate_analyzer" / "charts.py"
APP = ROOT / "app.py"
TEST = ROOT / "tests" / "test_cadence_frequency_visuals.py"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


charts = CHARTS.read_text(encoding="utf-8")
charts = replace_once(
    charts,
    "from .aggregations import aggregate_summary, aggregate_sum, calendar_matrix, duration_curve, monthly_box_data, monthly_hour_matrix",
    "from .aggregations import aggregate_summary, aggregate_sum, calendar_matrix, duration_curve, monthly_box_data, monthly_hour_matrix, native_interval_hours",
    label="charts aggregation import",
)
charts = replace_once(
    charts,
    '''def duration_chart(df: pd.DataFrame, column: str, title: str, unit: str, ascending: bool = False) -> go.Figure:\n    """Create a sorted duration curve."""\n    values = duration_curve(df, column, ascending=ascending)\n    fig = px.line(values, x="rank_hour", y=column, title=title, labels={"rank_hour": "Sorted hour", column: unit})\n    fig.update_traces(line_color=metric_color(column), hovertemplate="Sorted hour: %{x}<br>Value: %{y:.2f} " + unit + "<extra></extra>")\n    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))\n    return _apply_axis_constraints(fig, column=column, x_values=values["rank_hour"], y_values=values[column])\n''',
    '''def duration_chart(df: pd.DataFrame, column: str, title: str, unit: str, ascending: bool = False) -> go.Figure:\n    """Create a sorted duration curve on a physical-hours axis."""\n    values = duration_curve(df, column, ascending=ascending)\n    fig = px.line(values, x="duration_hours", y=column, title=title, labels={"duration_hours": "Sorted duration [h]", column: unit})\n    fig.update_traces(line_color=metric_color(column), hovertemplate="Sorted duration: %{x:.2f} h<br>Value: %{y:.2f} " + unit + "<extra></extra>")\n    fig.update_layout(template=PLOT_TEMPLATE, margin=dict(l=40, r=20, t=70, b=45))\n    return _apply_axis_constraints(fig, column=column, x_values=values["duration_hours"], y_values=values[column])\n''',
    label="duration chart",
)
charts = replace_once(
    charts,
    '''def histogram_chart(df: pd.DataFrame, column: str, title: str, unit: str, bins: int = 40) -> go.Figure:\n    """Create an interactive histogram."""\n    data = df[[column]].dropna()\n    fig = px.histogram(data, x=column, nbins=bins, title=title, labels={column: unit}, color_discrete_sequence=[metric_color(column)])\n    fig.update_layout(template=PLOT_TEMPLATE, yaxis_title="Hours", margin=dict(l=40, r=20, t=70, b=45))\n    lo, hi = _axis_limits_for_column(column, data[column], pad_fraction=0.03)\n    if lo is not None or hi is not None:\n        fig.update_xaxes(range=[lo, hi], autorangeoptions=dict(minallowed=lo, maxallowed=hi))\n    return fig\n''',
    '''def histogram_chart(df: pd.DataFrame, column: str, title: str, unit: str, bins: int = 40) -> go.Figure:\n    """Create an interactive histogram weighted by physical source-record duration."""\n    data = df[[column]].dropna().copy()\n    data["_duration_hours"] = native_interval_hours(df)\n    fig = px.histogram(\n        data,\n        x=column,\n        y="_duration_hours",\n        histfunc="sum",\n        nbins=bins,\n        title=title,\n        labels={column: unit, "_duration_hours": "Hours"},\n        color_discrete_sequence=[metric_color(column)],\n    )\n    fig.update_layout(template=PLOT_TEMPLATE, yaxis_title="Hours", margin=dict(l=40, r=20, t=70, b=45))\n    lo, hi = _axis_limits_for_column(column, data[column], pad_fraction=0.03)\n    if lo is not None or hi is not None:\n        fig.update_xaxes(range=[lo, hi], autorangeoptions=dict(minallowed=lo, maxallowed=hi))\n    return fig\n''',
    label="histogram chart",
)
charts = replace_once(
    charts,
    '''def givoni_milne_zone_table(df: pd.DataFrame) -> pd.DataFrame:\n    """Return hourly counts for each manually mapped Givoni-Milne zone.\n\n    The zones overlap by design.  Therefore percentages are not mutually\n    exclusive and should be read as strategy-potential counts, not as a sum to\n    100 percent.\n    """\n    data = df[["dry_bulb_temperature_c", "humidity_ratio_g_kg"]].dropna()\n    if data.empty:\n        return pd.DataFrame(columns=["zone", "hours", "share_pct", "design_response"])\n    x = data["dry_bulb_temperature_c"].to_numpy(dtype=float)\n    y = data["humidity_ratio_g_kg"].to_numpy(dtype=float)\n    rows = []\n    for zone_id in GIVONI_DRAW_ORDER:\n        t_path, w_path = _build_givoni_zone_path(zone_id, DEFAULT_PRESSURE_PA, use_clip=True)\n        mask = _point_in_polygon(x, y, list(zip(t_path, w_path, strict=False)))\n        hours = int(mask.sum())\n        rows.append(\n            {\n                "zone": f"{zone_id}. {GIVONI_ZONE_NAMES[zone_id]}",\n                "hours": hours,\n                "share_pct": hours / max(len(data), 1) * 100.0,\n                "design_response": GIVONI_ZONE_STRATEGIES[zone_id],\n            }\n        )\n    return pd.DataFrame(rows).sort_values("hours", ascending=False)\n''',
    '''def givoni_milne_zone_table(df: pd.DataFrame) -> pd.DataFrame:\n    """Return physical-duration hours for each manually mapped Givoni-Milne zone.\n\n    The zones overlap by design. Therefore percentages are not mutually\n    exclusive and should be read as strategy-potential durations, not as a sum\n    to 100 percent.\n    """\n    data = df[["dry_bulb_temperature_c", "humidity_ratio_g_kg"]].dropna()\n    if data.empty:\n        return pd.DataFrame(columns=["zone", "hours", "share_pct", "design_response"])\n    hours_per_record = native_interval_hours(df)\n    x = data["dry_bulb_temperature_c"].to_numpy(dtype=float)\n    y = data["humidity_ratio_g_kg"].to_numpy(dtype=float)\n    rows = []\n    for zone_id in GIVONI_DRAW_ORDER:\n        t_path, w_path = _build_givoni_zone_path(zone_id, DEFAULT_PRESSURE_PA, use_clip=True)\n        mask = _point_in_polygon(x, y, list(zip(t_path, w_path, strict=False)))\n        matching_records = int(mask.sum())\n        hours = float(matching_records) * hours_per_record\n        rows.append(\n            {\n                "zone": f"{zone_id}. {GIVONI_ZONE_NAMES[zone_id]}",\n                "hours": hours,\n                "share_pct": matching_records / max(len(data), 1) * 100.0,\n                "design_response": GIVONI_ZONE_STRATEGIES[zone_id],\n            }\n        )\n    return pd.DataFrame(rows).sort_values("hours", ascending=False)\n''',
    label="givoni zone table",
)
charts = replace_once(
    charts,
    '''    group_cols = ["temperature_bin_c", "rh_bin_pct"]\n    if color_metric_column and color_metric_column in data.columns:\n        tiles = data.groupby(group_cols, observed=True).agg(hours=("dry_bulb_temperature_c", "size"), value=(color_metric_column, "mean")).reset_index()\n    else:\n        tiles = data.groupby(group_cols, observed=True).size().reset_index(name="hours")\n        tiles["value"] = tiles["hours"]\n        color_metric_label = "Frequency [h]"\n''',
    '''    group_cols = ["temperature_bin_c", "rh_bin_pct"]\n    hours_per_record = native_interval_hours(df)\n    if color_metric_column and color_metric_column in data.columns:\n        tiles = data.groupby(group_cols, observed=True).agg(records=("dry_bulb_temperature_c", "size"), value=(color_metric_column, "mean")).reset_index()\n        tiles["hours"] = tiles["records"].astype(float) * hours_per_record\n    else:\n        tiles = data.groupby(group_cols, observed=True).size().reset_index(name="records")\n        tiles["hours"] = tiles["records"].astype(float) * hours_per_record\n        tiles["value"] = tiles["hours"]\n        color_metric_label = "Frequency [h]"\n''',
    label="psychrometric tile frequency",
)
charts = replace_once(
    charts,
    '                    f"Hours: {int(row[\'hours\'])}<br>"\n',
    '                    f"Hours: {float(row[\'hours\']):.2f}<br>"\n',
    label="psychrometric tile hover hours",
)
CHARTS.write_text(charts, encoding="utf-8")

app = APP.read_text(encoding="utf-8")
app = replace_once(
    app,
    "    global aggregate_sum, duration_curve, filter_by_months_and_hours, threshold_count_by_period\n",
    "    global aggregate_sum, duration_curve, filter_by_months_and_hours, native_interval_hours, threshold_count_by_period\n",
    label="app aggregation globals",
)
app = replace_once(
    app,
    '''        from epw_climate_analyzer.aggregations import (\n            aggregate_sum,\n            duration_curve,\n            filter_by_months_and_hours,\n            threshold_count_by_period,\n        )\n''',
    '''        from epw_climate_analyzer.aggregations import (\n            aggregate_sum,\n            duration_curve,\n            filter_by_months_and_hours,\n            native_interval_hours,\n            threshold_count_by_period,\n        )\n''',
    label="app aggregation import",
)
app = replace_once(
    app,
    '''    top = table.head(3)\n    total_tagged = int(table["hours"].sum())\n    total_hours = max(len(df.dropna(subset=["dry_bulb_temperature_c", "humidity_ratio_g_kg"])), 1)\n    leader = top.iloc[0]\n    st.info(\n        f"The largest Givoni-Milne-style strategy region is **{leader['zone']}** "\n        f"with {int(leader['hours']):,} hours ({float(leader['share_pct']):.1f}% of valid psychrometric hours). "\n        f"The reported zones are overlapping design-potential regions, so their hour counts should be interpreted as strategy opportunities rather than mutually exclusive classes. "\n        f"Across all displayed strategy regions, {total_tagged:,} zone-hours were detected over {total_hours:,} valid EPW hours."\n    )\n''',
    '''    top = table.head(3)\n    total_tagged = float(table["hours"].sum())\n    valid_records = len(df.dropna(subset=["dry_bulb_temperature_c", "humidity_ratio_g_kg"]))\n    total_hours = float(valid_records) * native_interval_hours(df)\n    leader = top.iloc[0]\n\n    def format_hours(value: float) -> str:\n        numeric = float(value)\n        if abs(numeric - round(numeric)) < 1e-9:\n            return f"{int(round(numeric)):,}"\n        return f"{numeric:,.2f}".rstrip("0").rstrip(".")\n\n    st.info(\n        f"The largest Givoni-Milne-style strategy region is **{leader['zone']}** "\n        f"with {format_hours(float(leader['hours']))} hours ({float(leader['share_pct']):.1f}% of valid psychrometric duration). "\n        f"The reported zones are overlapping design-potential regions, so their hour totals should be interpreted as strategy opportunities rather than mutually exclusive classes. "\n        f"Across all displayed strategy regions, {format_hours(total_tagged)} zone-hours were detected over {format_hours(total_hours)} valid climate-data hours."\n    )\n''',
    label="bioclimatic report duration",
)
app = replace_once(
    app,
    '        data_mode = st.radio("Loaded climate data mode", ["Hourly values", "Distributive grid"], horizontal=True)\n',
    '        source_interval_mode = "Hourly values" if abs(native_interval_hours(df) - 1.0) < 1e-9 else "Source interval values"\n        data_mode = st.radio("Loaded climate data mode", [source_interval_mode, "Distributive grid"], horizontal=True)\n',
    label="psychrometric data-mode label",
)
app = replace_once(
    app,
    '''            if data_mode == "Hourly values" and color_mode == "Frequency":\n                st.caption("Frequency is only meaningful for the distributive grid. Hourly values will be shown by month.")\n                color_mode = "Month"\n''',
    '''            if data_mode != "Distributive grid" and color_mode == "Frequency":\n                st.caption("Frequency is only meaningful for the distributive grid. Source interval values will be shown by month.")\n                color_mode = "Month"\n''',
    label="psychrometric frequency guard",
)
APP.write_text(app, encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
test = replace_once(
    test,
    '''        fig = go.Figure()\n        _add_psychrometric_tile_occupancy(\n            fig,\n            sample_frame(interval_minutes=10),\n''',
    '''        fig = go.Figure()\n        frame = sample_frame(interval_minutes=10)\n        frame["dry_bulb_temperature_c"] = 22.0\n        _add_psychrometric_tile_occupancy(\n            fig,\n            frame,\n''',
    label="psychrometric tile test setup",
)
test = replace_once(test, "        self.assertEqual(len(tile_traces), 6)\n", "        self.assertEqual(len(tile_traces), 1)\n", label="psychrometric tile trace count")
TEST.write_text(test, encoding="utf-8")

print("GeoSphere 0.5 cadence-frequency patch applied")
