"""Interactive views of native EPB Rhino V3 physical/spatial evidence.

No energy calculation, surrogate values, or automatic certificate assessment.
Chart families follow the native Grasshopper Energy Charts component wherever
source data exists; unavailable hourly/control signals remain unavailable.
"""
from __future__ import annotations

from hashlib import sha256

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .bundle import BundleValidationError
from .charts import ChartSettings, plotly_configuration
from .evidence_data import (
    MONTH_AXIS, MONTH_NAMES, NON_ADDITIVE_UNITS, available_quantities,
    building_area, coverage_table, is_present, load_evidence,
    monthly_series, orientation_summary, quantity_unit, zone_annual_intensity,
)


def _evidence(payload: bytes) -> dict:
    """Cache uploaded evidence only in the current user's Streamlit session."""
    digest = sha256(payload).hexdigest()
    cache = st.session_state.setdefault("epb_v3_evidence_cache", {})
    if digest not in cache:
        cache[digest] = load_evidence(payload)
    return cache[digest]


def _chart(fig: go.Figure, settings: ChartSettings, name: str,
           frame: pd.DataFrame | None = None, ylabel: str = ""):
    fig.update_layout(template="plotly_white", height=settings.height,
                      font=dict(size=settings.font_size),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0) if settings.legend == "Top"
                      else dict(orientation="v", xanchor="left", x=1.02, y=1),
                      margin=dict(l=40, r=35, t=65, b=40))
    if ylabel:
        fig.update_yaxes(title_text=ylabel)
    st.plotly_chart(fig, use_container_width=True, config=plotly_configuration(settings),
                    key="evidence-" + name)
    if frame is not None and not frame.empty:
        st.download_button("Download plotted data · CSV",
                           frame.to_csv(index=False).encode("utf-8-sig"),
                           file_name=name + ".csv", mime="text/csv", key="evidence-dl-" + name)


def _line(data: pd.DataFrame, settings: ChartSettings, key: str, unit: str,
          *, kind: str = "line", title: str = ""):
    if data.empty:
        st.info("No source values for the selected quantity.")
        return
    if kind == "bar":
        fig = px.bar(data, x="month", y="value", color="series",
                     barmode="group", title=title)
    else:
        fig = px.line(data, x="month", y="value", color="series",
                      markers=True, title=title)
    fig.update_xaxes(tickvals=MONTH_AXIS, ticktext=MONTH_NAMES, title_text="Month")
    _chart(fig, settings, key, data, unit)


def _coverage(data: dict, settings: ChartSettings):
    st.subheader("Evidence coverage & chart availability")
    coverage = coverage_table(data)
    st.dataframe(coverage, use_container_width=True, hide_index=True)
    available = coverage[coverage.Available]
    st.metric("Available evidence datasets", str(len(available)) + "/" + str(len(coverage)))
    st.caption("The viewer does not infer a physical quantity from a different one. "
               "An empty hourly table is not an hourly simulation.")
    quality = data.get("quality", {})
    if isinstance(quality, dict) and isinstance(quality.get("datasets"), dict):
        details = []
        for member, info in quality["datasets"].items():
            if isinstance(info, dict):
                details.append({"Dataset": member,
                                "Present": bool(info.get("present")),
                                "Rows": info.get("rows"),
                                "Reason if unavailable": info.get("reason")})
        if details:
            st.markdown("**Native export availability and source reasons**")
            st.dataframe(pd.DataFrame(details), hide_index=True, use_container_width=True)
    st.markdown("**Grasshopper Energy Charts parity**")
    catalog = [
        ("Thermal Need", "Monthly thermal + hourly when exported", "monthly_thermal"),
        ("Heating / Cooling Balance", "Monthly zonal physical terms", "zone_physics"),
        ("Gains Utilization", "Solar/internal gains and utilization factor", "zone_physics"),
        ("Orientation Rose", "Directional facade buckets", "orientation"),
        ("Envelope Loss Breakdown", "Monthly facade/roof/window losses", "surface_physics"),
        ("Zone Comparison", "Annual/area-normalized zonal demand", "zone_physics"),
        ("Thermal Solar Gains", "Monthly solar heat gains", "surface_physics"),
        ("Energy Balance / Summary Indicators", "National monthly metrics", "monthly_metrics"),
        ("Heating/DHW/Cooling System Flow", "Source system-stage metrics, no synthetic Sankey", "monthly_metrics"),
        ("Electricity Balance / PV Flows", "Native electrical metric lines", "monthly_metrics"),
        ("Energy Carrier Mix / by Service", "Native carrier ledger", "carrier"),
        ("Environmental Indicators", "CO2eq and primary energy metrics", "monthly_metrics"),
        ("Thermal Loads / Temperatures / Humidity", "Only actual hourly thermal vectors", None),
    ]
    records = []
    for name, description, source in catalog:
        records.append({"Chart family": name, "Native evidence": description,
                        "Available": is_present(data, source) if source else False})
    st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
    signals = data.get("signals", pd.DataFrame())
    if not signals.empty:
        st.markdown("**Exported signal catalog**")
        st.dataframe(signals, hide_index=True, use_container_width=True)
    st.caption("Research traces, dynamic blind states, zone temperatures, CO₂, and AHU "
               "controls require explicit hourly/Trace Settings exports. "
               "Absent signals are never displayed as zero.")


def _envelope(data: dict, settings: ChartSettings):
    st.subheader("Envelope · facades, WWR and geometry")
    orient = orientation_summary(data)
    windows = data["windows"]
    surfaces = data["surfaces"]
    if orient.empty:
        st.info("No orientation-buckets.csv exported.")
    else:
        total = orient.facade_total_m2.sum() if "facade_total_m2" in orient else np.nan
        glazing = orient.opening_gross_m2.sum() if "opening_gross_m2" in orient else np.nan
        a, b, c = st.columns(3)
        a.metric("Facade area", f"{total:,.1f} m²" if np.isfinite(total) else "—")
        b.metric("Window area", f"{glazing:,.1f} m²" if np.isfinite(glazing) else "—")
        c.metric("Facade WWR", f"{100*glazing/total:.1f}%" if total > 0 else "—")
        long = orient.melt(id_vars=["direction"], value_vars=[
            k for k in ("opening_gross_m2", "opaque_net_wall_m2") if k in orient],
            var_name="component", value_name="area_m2")
        fig = px.bar(long, x="direction", y="area_m2", color="component",
                     title="Facades · opaque and transparent area", barmode="stack",
                     category_orders={"direction":["N","NE","E","SE","S","SW","W","NW"]})
        _chart(fig, settings, "envelope-by-direction", long, "m²")
        rose = go.Figure()
        azimuth = {"N":0,"NE":45,"E":90,"SE":135,"S":180,"SW":225,"W":270,"NW":315}
        rose.add_trace(go.Barpolar(theta=orient.direction.map(azimuth).tolist(),
                                    r=orient.opening_gross_m2.fillna(0).tolist(),
                                    width=[40]*len(orient), name="Glazed facade, m²"))
        rose.update_layout(title="Glazing orientation rose",
                           polar=dict(angularaxis=dict(direction="clockwise", rotation=90)))
        _chart(rose, settings, "glazing-rose", orient)
    if not surfaces.empty and {"surface_class", "area_m2"}.issubset(surfaces):
        st.markdown("**Envelope surface inventory**")
        grouped = (surfaces.groupby("surface_class", as_index=False)
                   .area_m2.sum(min_count=1).sort_values("area_m2", ascending=False))
        _chart(px.bar(grouped, x="surface_class", y="area_m2", title="Physical surface area by class"),
               settings, "surface-areas", grouped, "m²")
    st.caption("WWR is area-weighted, derived from exported gross facade and opening "
               "areas. 100% WWR is a valid source geometry; it is not treated as an error.")


def _windows(data: dict, settings: ChartSettings):
    st.subheader("Windows · inventory and glazing characteristics")
    windows = data["windows"]
    if windows.empty:
        st.info("No window inventory exported.")
        return
    w = windows.copy()
    st.metric("Exported window fragments", len(w))
    if "area_m2" in w:
        st.metric("Window fragment area", f"{w.area_m2.sum():,.1f} m²")
    if "azimuth_deg" in w and "area_m2" in w:
        w["orientation"] = (((w.azimuth_deg.fillna(0) + 22.5) // 45) % 8).astype(int).map(
            dict(enumerate(["N", "NE", "E", "SE", "S", "SW", "W", "NW"])))
        g = w.groupby("orientation", as_index=False).area_m2.sum()
        fig = px.bar(g, x="orientation", y="area_m2", title="Window area by azimuth bucket",
                     category_orders={"orientation":["N","NE","E","SE","S","SW","W","NW"]})
        _chart(fig, settings, "windows-orientation", g, "m²")
    if "area_m2" in w:
        _chart(px.histogram(w, x="area_m2", nbins=35,
                            title="Window fragment size distribution"),
               settings, "window-size", w[["area_m2"]], "Number of fragments")
    st.markdown("**Thermal and optical parameters actually included in the ZIP**")
    params = ["u_value_w_m2k", "solar_g_value", "construction_id",
              "fixed_shading_factor_heating", "fixed_shading_factor_cooling",
              "shading_control_mode"]
    counts = pd.DataFrame([{"Parameter": p, "Populated fragments":
                            int(w[p].notna().sum()) if p in w else 0,
                            "Total fragments":len(w)} for p in params])
    st.dataframe(counts, hide_index=True, use_container_width=True)
    if "u_value_w_m2k" in w and w.u_value_w_m2k.notna().any():
        _chart(px.histogram(w.dropna(subset=["u_value_w_m2k"]), x="u_value_w_m2k",
                            title="Window U-values provided by exporter"),
               settings, "window-u", w[["u_value_w_m2k"]], "Fragments")
    if "solar_g_value" in w and w.solar_g_value.notna().any():
        _chart(px.histogram(w.dropna(subset=["solar_g_value"]), x="solar_g_value",
                            title="Window g-values provided by exporter"),
               settings, "window-g", w[["solar_g_value"]], "Fragments")
    st.caption("Blank values remain unknown. The visualizer does not replace missing "
               "Uw/g/gTot/shading controls with catalog guesses.")
    with st.expander("Window inventory"):
        st.dataframe(w, hide_index=True, use_container_width=True)


def _zone_physics(data: dict, settings: ChartSettings, *, solar: bool = False):
    frame, zones = data["zone_physics"], data["zones"]
    st.subheader("Solar and internal gains" if solar else "Zone energy and thermal balance")
    if frame.empty:
        st.info("No monthly-physical-zones.csv exported.")
        return
    quantities = available_quantities(frame)
    if solar:
        priorities = ["solar_gains_hourly_integrated", "solar_gains_heating", "solar_gains_cooling",
                      "internal_gains_heating", "internal_gains_cooling"]
    else:
        priorities = ["heating_demand", "cooling_demand"]
    options = [q for q in priorities if q in quantities] or quantities[:2]
    units = sorted(frame.unit.dropna().astype(str).unique())
    default_unit = "kWh" if "kWh" in units else units[0]
    unit = st.selectbox("Unit / physical kind", units, index=units.index(default_unit),
                        key="zg-unit-" + str(solar))
    matching = available_quantities(frame, unit=unit)
    initial = [q for q in options if q in matching] or matching[:1]
    picked = st.multiselect("Physical terms", matching, default=initial,
                            key="zg-quantity-" + str(solar))
    if not picked:
        return
    names = {}
    if not zones.empty and "zone_id" in zones and "zone_name" in zones:
        names = dict(zip(zones.zone_id.astype(str), zones.zone_name.astype(str)))
    all_zones = sorted(frame.zone_id.dropna().astype(str).unique().tolist())
    scope = st.radio("Zone scope", ["Building (all zones)", "One zone"],
                     horizontal=True, key="zg-scope-" + str(solar))
    selected = all_zones
    if scope == "One zone":
        chosen_zone = st.selectbox("Zone", all_zones,
                                   format_func=lambda z: names.get(z, z),
                                   key="zg-zone-" + str(solar))
        selected = [chosen_zone]
    mode = "mean" if unit in NON_ADDITIVE_UNITS else "sum"
    if mode == "mean":
        st.caption("Dimensionless factors are shown as unweighted arithmetic means "
                   "across selected zone observations, never summed.")
    series = monthly_series(frame, picked, zones=selected, mode=mode)
    _line(series, settings, "zone-physical-" + str(solar), unit)
    if not solar and mode == "sum":
        metric = st.selectbox("Zone comparison / intensity", matching,
                              index=matching.index("heating_demand")
                              if "heating_demand" in matching else 0)
        intensity = zone_annual_intensity(data, metric)
        if not intensity.empty:
            intensity = intensity.sort_values("intensity", ascending=False)
            top = st.slider("Zones shown in ranking", 5, min(100,len(intensity)),
                            min(20,len(intensity)), key="zone-rank-count") if len(intensity)>=5 else len(intensity)
            fig = px.bar(intensity.head(top), x="zone_name" if "zone_name" in intensity else "zone_id",
                         y="intensity", title="Annual " + metric + " by zone · area-normalized")
            _chart(fig, settings, "zonal-intensity", intensity.head(top),
                   unit + "/m²")
    if solar:
        util = frame[frame.quantity.astype(str).str.startswith("utilization_factor")]
        if not util.empty:
            _line(monthly_series(util, available_quantities(util), mode="mean"),
                  settings, "gains-utilization", "1",
                  title="Mean utilization factors · non-additive")


def _surface_physics(data: dict, settings: ChartSettings):
    st.subheader("Surfaces · transmission losses and solar gains")
    f = data["surface_physics"]
    if f.empty:
        st.info("No monthly-physical-surfaces.csv exported.")
        return
    quantities = available_quantities(f, unit="kWh")
    if not quantities:
        st.info("No additive surface energy quantities exported.")
        return
    q = st.selectbox("Surface physical term", quantities,
                     index=quantities.index("transmission_heating")
                     if "transmission_heating" in quantities else 0)
    classes = sorted(f.surface_class.dropna().astype(str).unique().tolist())
    selected = st.multiselect("Surface classes", classes, default=classes)
    subset = f[(f.quantity == q) & f.surface_class.isin(selected)].copy()
    if subset.empty:
        st.info("No selected surface rows.")
        return
    d = monthly_series(subset, [q], group="surface_class")
    _line(d, settings, "surface-monthly", "kWh")
    annual = (subset.groupby("surface_class", as_index=False).value.sum(min_count=1)
              .sort_values("value", ascending=False))
    _chart(px.bar(annual, x="surface_class", y="value",
                  title="Annual contribution by surface class"),
           settings, "surface-class-contribution", annual, "kWh")
    pivot = (subset.groupby(["surface_class", "month"]).value.sum()
             .unstack(fill_value=np.nan).reindex(columns=MONTH_AXIS))
    if not pivot.empty:
        heat = go.Figure(go.Heatmap(z=pivot.to_numpy(), x=MONTH_NAMES,
                                    y=pivot.index.tolist(), colorbar=dict(title="kWh")))
        heat.update_layout(title="Surface class × month · " + q)
        _chart(heat, settings, "surface-heatmap", subset, "kWh")
    st.caption("Surface terms refer to physical source surfaces. Do not add overlapping "
               "source contributions to national H5050 final-energy ledger values.")


def _systems(data: dict, settings: ChartSettings):
    st.subheader("Energy systems, PV and environmental indicators")
    frame = data["monthly_metrics"]
    if frame.empty:
        st.info("No national monthly-metrics.csv exported.")
        return
    scenarios = sorted(frame.scenario.dropna().astype(str).unique())
    scenario = st.selectbox("Scenario", scenarios, key="sys-evidence-scenario")
    group = st.selectbox("Chart family", ["Heating system", "DHW system",
                                          "Cooling system", "Electricity / PV",
                                          "Environmental / summary"])
    starts = {"Heating system": ("SYS.HEATING.",),
              "DHW system": ("SYS.DHW.",),
              "Cooling system": ("SYS.COOLING.",),
              "Electricity / PV": ("PV", "GridElectricity", "OperationalElectricity",
                                    "Battery", "BefEB", "BelEB"),
              "Environmental / summary": ("CO2eq", "PEB", "EEB", "HEB", "KEB")}
    f = frame[(frame.scenario.astype(str) == scenario) &
              frame.metric.astype(str).str.startswith(starts[group])].copy()
    if f.empty:
        st.info("No exported indicators for this chart family.")
        return
    units = sorted(f.unit.dropna().astype(str).unique())
    unit = st.selectbox("Units (separate non-comparable series)", units, key="sys-evidence-units")
    f = f[f.unit.astype(str) == unit]
    choices = sorted(f.metric.dropna().astype(str).unique())
    picked = st.multiselect("Physical stages / metrics", choices,
                            default=choices[:min(6, len(choices))], key="sys-evidence-metrics")
    if not picked:
        return
    d = (f[f.metric.isin(picked)].groupby(["month", "metric"], as_index=False)
         .value.sum(min_count=1).rename(columns={"metric":"series"}))
    _line(d, settings, "systems-stage-metrics", unit)
    st.caption("System stages often share physical energy flows. Lines are displayed "
               "separately; they must not be stacked or summed into an invented Sankey balance.")
    if group == "Environmental / summary" and not data["scenarios"].empty:
        st.dataframe(data["scenarios"], hide_index=True, use_container_width=True)


def _studio(data: dict, settings: ChartSettings):
    st.subheader("Chart Studio · source-grounded overlay")
    datasets = {"Zone physical quantities": "zone_physics",
                "Surface physical quantities": "surface_physics",
                "National monthly metrics": "monthly_metrics",
                "Monthly thermal needs": "monthly_thermal"}
    source = st.selectbox("Source table", list(datasets))
    f = data[datasets[source]]
    if f.empty:
        st.info("This dataset is not present in the ZIP.")
        return
    if source == "Monthly thermal needs":
        quantities = [c for c in ("heating_need_kwh", "cooling_need_kwh") if c in f]
        if not quantities:
            st.info("No thermal need series.")
            return
        selected = st.multiselect("Quantities", quantities, default=quantities)
        d = f.melt(id_vars=["zone_id", "month"], value_vars=selected,
                   var_name="series", value_name="value")
        d["value"] = pd.to_numeric(d.value, errors="coerce")
        unit, group = "kWh", "Building sum"
    else:
        item = "metric" if source == "National monthly metrics" else "quantity"
        if not {item, "unit", "value", "month"}.issubset(f):
            st.info("The source table is missing required fields.")
            return
        units = sorted(f.unit.dropna().astype(str).unique())
        unit = st.selectbox("Unit", units, key="studio-units")
        choices = sorted(f.loc[f.unit.astype(str)==unit, item].dropna().astype(str).unique())
        selected = st.multiselect("Overlay series (same units only)", choices,
                                  default=choices[:min(3,len(choices))])
        d = f[(f.unit.astype(str)==unit) & f[item].isin(selected)].copy()
        d["series"] = d[item].astype(str)
        group = st.selectbox("Group", ["Building sum", "Zone", "Surface class"]
                             if "surface_class" in d else
                             ["Building sum", "Zone"] if "zone_id" in d else ["Building sum"])
        if group == "Zone" and "zone_id" in d:
            names = sorted(d.zone_id.dropna().astype(str).unique())
            chosen = st.selectbox("One zone ID", names, key="studio-zone")
            d = d[d.zone_id.astype(str) == chosen]
            d["series"] = d.zone_id.astype(str) + " · " + d["series"]
        if group == "Surface class" and "surface_class" in d:
            d["series"] = d.surface_class.fillna("Other").astype(str) + " · " + d["series"]
    if not selected or d.empty:
        st.info("Choose at least one available series.")
        return
    mode = "mean" if unit in NON_ADDITIVE_UNITS else "sum"
    if mode == "mean":
        st.caption("Non-additive ratios are averaged, not summed.")
    if "scenario" in d:
        available = sorted(d.scenario.dropna().astype(str).unique())
        chosen = st.selectbox("Scenario", available, key="studio-scenario")
        d = d[d.scenario.astype(str)==chosen]
    d = d[d.month.isin(MONTH_AXIS)].dropna(subset=["value"])
    operation = "mean" if mode == "mean" else "sum"
    d = d.groupby(["month","series"],as_index=False).value.agg(operation)
    chart = st.radio("Plot type", ["Line overlay", "Grouped bars", "Monthly heatmap"],
                     horizontal=True, key="studio-type")
    if chart == "Monthly heatmap":
        pivot = d.pivot(index="series", columns="month", values="value").reindex(columns=MONTH_AXIS)
        fig = go.Figure(go.Heatmap(z=pivot.to_numpy(), y=pivot.index.tolist(),
                                    x=MONTH_NAMES, colorbar=dict(title=unit)))
        _chart(fig, settings, "studio-heatmap", d)
    else:
        _line(d, settings, "studio-plot", unit,
              kind="bar" if chart == "Grouped bars" else "line")
    st.caption("All displayed points are source data or declared month/zone aggregations. "
               "No synthetic hourly values, glazing parameters, or regulatory compliance results.")


def render_evidence(page: str, payload: bytes, settings: ChartSettings):
    data = _evidence(payload)
    routes = {
        "Envelope & WWR": _envelope,
        "Windows & glazing": _windows,
        "Zone physics": lambda d, s: _zone_physics(d, s, solar=False),
        "Solar & gains": lambda d, s: _zone_physics(d, s, solar=True),
        "Surface physics": _surface_physics,
        "Systems & electricity": _systems,
        "Chart Studio": _studio,
        "Evidence coverage": _coverage,
    }
    try:
        routes[page](data, settings)
    except (BundleValidationError, ValueError, KeyError) as exc:
        st.error("Source evidence cannot be charted: " + str(exc))


def render_evidence_compare(studies, payloads: dict[str, bytes], settings: ChartSettings):
    st.subheader("Physical evidence · building and design comparison")
    st.caption("Compare different ZIPs without mixing source thermal need, system stages "
               "and H5050 final-energy accounting.")
    rows, charts = [], []
    for study in studies:
        payload = payloads.get(study.key)
        if payload is None:
            continue
        evidence = _evidence(payload)
        area = study.area_m2 or building_area(evidence)
        directions = orientation_summary(evidence)
        facade = (directions.facade_total_m2.sum()
                  if not directions.empty and "facade_total_m2" in directions else np.nan)
        opening = (directions.opening_gross_m2.sum()
                   if not directions.empty and "opening_gross_m2" in directions else np.nan)
        rows.append({"Variant": study.label, "Area m²": area,
                     "Zones":len(evidence["zones"]), "Facade m²": facade,
                     "Windows m²": opening,
                     "WWR %":100 * opening/facade if facade > 0 else np.nan,
                     "Climate fingerprint": study.bundle.visualization_manifest.get("climate_fingerprint"),
                     "Profile": study.bundle.visualization_manifest.get("calculation_profile_id")})
        df = evidence["zone_physics"]
        if not df.empty:
            subset = df[df.unit.astype(str)=="kWh"]
            agg = subset.groupby(["month","quantity"],as_index=False).value.sum()
            agg["Variant"] = study.label
            agg["Area m²"] = area
            charts.append(agg)
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    if not charts:
        st.info("No common monthly physical quantities for comparison.")
        return
    provenance = pd.DataFrame(rows)
    for col in ("Climate fingerprint", "Profile"):
        ids = provenance[col].dropna().astype(str).unique()
        if len(ids)>1 or provenance[col].isna().any():
            st.warning(col + " differs or is unconfirmed. Comparisons are descriptive, not controlled experiments.")
    d = pd.concat(charts, ignore_index=True)
    common = (d.groupby("quantity").Variant.nunique())
    common = sorted(common[common==d.Variant.nunique()].index.tolist())
    if not common:
        st.info("No metric shared by all selected exports.")
        return
    q = st.selectbox("Comparable physical quantity", common,
                     index=common.index("cooling_demand") if "cooling_demand" in common else 0)
    normalize = st.checkbox("Per conditioned floor area (kWh/m²)", value=True,
                            key="compare-evidence-normalize")
    selected = d[d.quantity==q].copy()
    if normalize:
        if selected["Area m²"].isna().any() or (selected["Area m²"]<=0).any():
            st.warning("One or more buildings lack a valid area; showing absolute kWh.")
            normalize=False
        else:
            selected["value"] = selected.value / selected["Area m²"]
    selected = selected.rename(columns={"Variant":"series"})
    _line(selected, settings, "evidence-compare", "kWh/m²" if normalize else "kWh")
    st.caption("Only source-matched quantities with identical units are compared. "
               "Normalized values use the stated conditioned floor-area basis.")
