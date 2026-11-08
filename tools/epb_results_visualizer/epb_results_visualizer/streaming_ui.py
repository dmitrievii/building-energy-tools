"""Streamlit view: explicitly choose ONE zone or whole-building aggregates."""
from __future__ import annotations

import hashlib

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from .bundle import BundleValidationError, METRICS
from .charts import ChartSettings, plotly_configuration
from .streaming import (
    available_source_signals, select_series, time_aggregate,
)

SOURCES = {
    "Hourly ISO 52016 thermal": "thermal",
    "Ventilation execution": "ventilation",
    "Other Validation Trace signals": "trace",
}


def _render_lines(data: pd.DataFrame, units: dict[str, str], cfg: ChartSettings,
                  *, title: str, key: str):
    keys = list(units)
    if not keys or data.empty:
        st.info("No numerical observations in the selected range.")
        return
    axes = list(dict.fromkeys(units.values()))
    if len(axes) > 2:
        st.warning("Choose signals with at most two distinct units to avoid an ambiguous chart.")
        return
    fig = make_subplots(specs=[[{"secondary_y": len(axes) == 2}]])
    for q in keys:
        axis2 = len(axes) == 2 and units[q] == axes[1]
        fig.add_trace(go.Scatter(x=data.time, y=data[q], mode="lines",
                                 name=q, connectgaps=False),
                      secondary_y=axis2)
    fig.update_yaxes(title_text=axes[0], secondary_y=False)
    if len(axes) == 2:
        fig.update_yaxes(title_text=axes[1], secondary_y=True)
    fig.update_layout(template="plotly_white", height=cfg.height,
                      title=title, hovermode="x unified",
                      font=dict(size=cfg.font_size),
                      legend=dict(orientation="h") if cfg.legend == "Top"
                      else dict(orientation="v", x=1.06, y=1))
    st.plotly_chart(fig, use_container_width=True,
                    config=plotly_configuration(cfg), key="stream-chart-" + key)
    st.download_button("Download selected data · CSV",
                       data.to_csv(index=False).encode("utf-8-sig"),
                       file_name="epb_" + key.replace(" ", "_") + ".csv",
                       mime="text/csv", key="stream-dl-" + key)


def section_streaming(payload: bytes, bundle, cfg: ChartSettings,
                      *, trace_only: bool = False):
    """No heavy CSV is decoded until the user explicitly requests a selection."""
    st.subheader("On-demand hourly explorer · ISO 52016 & Validation Trace")
    st.caption("Only a selected zone OR verified building aggregates are kept in memory. "
               "Raw EPW timestamps are retained in the export but the graph uses a "
               "sequential 8760/8784-hour reference calendar.")
    large = len(payload) > 90 * 1024 * 1024
    if large:
        st.info("Large evidence bundle: metadata loaded. "
                "The 2.14 GB Trace and 1.35 GB ventilation tables are NOT inflated on upload.")
    c1, c2 = st.columns([2, 2])
    with c1:
        scope_label = st.radio("Analysis scope", ["Whole building", "One thermal zone"],
                               horizontal=True, key="stream-scope")
    scope = "building" if scope_label == "Whole building" else "zone"
    choices = list(SOURCES)
    if trace_only:
        choices = choices[1:]
    with c2:
        source_label = st.selectbox("Source evidence", choices, key="stream-source")
    source = SOURCES[source_label]
    zone_id = None
    if scope == "zone":
        zones = bundle.zone_metadata or {}
        if not zones:
            st.error("Zone metadata is missing; cannot safely select a zone.")
            return
        ids = sorted(zones)
        zone_id = st.selectbox("Zone (only ONE zone is loaded)", ids,
                               format_func=lambda z: (
                                   str(zones[z].get("zoneName") or z) + " · " + z),
                               key="stream-zone")
    try:
        available = available_source_signals(payload, source, scope)
    except (BundleValidationError, ValueError, KeyError) as exc:
        st.error("Archive metadata error: " + str(exc))
        return
    if not available:
        st.info("This source contains no numeric signals permitted for the selected scope. "
                "Missing CO₂/AHU measurements are not reconstructed.")
        return
    options = list(available)
    if source == "thermal":
        preferred = (["heating_load_w", "cooling_load_w"] if scope == "building"
                     else ["air_temp_c", "operative_temp_c", "heating_load_w"])
    elif source == "ventilation":
        preferred = ["ventilation.actual_m3s", "ventilation.design_m3s"]
    else:
        preferred = ["thermal.air_c", "thermal.mrt_c"] if scope == "zone" else ["load.heating_w"]
    defaults = [q for q in preferred if q in options][:3] or options[:1]
    selected = st.multiselect("Signals (maximum four)", options, default=defaults,
                              format_func=lambda q: q + "  [" + available[q] + "]",
                              max_selections=4, key="stream-signals")
    if not selected:
        st.info("Select at least one signal.")
        return
    if len(set(available[q] for q in selected)) > 2:
        st.warning("Choose signals with no more than two different units.")
        return
    request_key = (hashlib.sha256(payload).hexdigest(), source, scope, zone_id, tuple(selected))
    if st.button("Read selected evidence", type="primary", key="stream-read"):
        try:
            with st.spinner("Streaming source CSV into the selected time series..."):
                result = select_series(payload, source=source, scope=scope,
                                       quantities=selected, zone_id=zone_id)
            st.session_state["epb_active_stream"] = (request_key, result)
        except (BundleValidationError, ValueError, KeyError, OSError) as exc:
            st.error("Selected evidence rejected: " + str(exc))
            st.session_state.pop("epb_active_stream", None)
            return
    cached = st.session_state.get("epb_active_stream")
    if not cached or cached[0] != request_key:
        st.caption("No heavy data has been read for this selection. "
                   "Click 'Read selected evidence' to build exactly one cache entry.")
        return
    result = cached[1]
    a, b, c = st.columns(3)
    a.metric("Building zones", str(result.n_zones))
    b.metric("Reporting hours", f"{result.annual_hours:,}")
    c.metric("Selected CSV records scanned", f"{result.scanned_rows:,}")
    missing = [q + ": " + str(n) for q, n in result.missing.items() if n]
    if missing:
        st.warning("Unavailable reporting hours (not zero-filled): " + "; ".join(missing))
    hours = st.slider("Reporting hour range", 1, result.annual_hours,
                      (1, result.annual_hours), key="stream-hour-range")
    cadence = st.radio("Time resolution", ["Hour", "Day", "Month", "Year"],
                       horizontal=True, key="stream-cadence")
    power_mode = st.radio("Power in W", ["Energy", "Mean", "Peak"],
                          horizontal=True, key="stream-power-mode")
    st.caption("Energy: 1-hour integral in kWh; Mean: mean W; Peak: maximum W. "
               "Airflow is averaged in m³/s. Building boolean values show the "
               "percentage of reporting zones in that state, not summed flags.")
    filtered = result.frame.loc[result.frame.hour_index.between(*hours)].copy()
    filtered.attrs = result.frame.attrs.copy()
    try:
        chart, units = time_aggregate(filtered, result.units, cadence, power_mode)
    except (BundleValidationError, ValueError) as exc:
        st.error(str(exc))
        return
    if all(chart[q].isna().all() for q in selected):
        st.warning("No valid numeric observations for the selected quantities.")
        return
    _render_lines(chart, units, cfg,
                  title=("Whole building" if scope == "building" else zone_id) +
                        " · " + source_label,
                  key=source + "-" + scope)
    st.caption("Whole-building loads and solar gains are added by hour without "
               "cancellation of separate heating/cooling series. "
               "Non-additive temperatures, setpoints and states are available "
               "for one zone only. Physical trace heat flows are not additional "
               "H5050 final-energy postings.")
