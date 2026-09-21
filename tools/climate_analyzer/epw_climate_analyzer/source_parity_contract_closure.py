"""Cross-source capability closure from the EPW/GeoSphere four-source audit."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import pandas as pd

from . import aggregations as agg, charts, timeseries
from . import source_parity_longterm_hotfix as longterm
from . import source_parity_monthly_canonical as monthly_ui
from . import source_parity_monthly_cleanup as monthly_cleanup
from .climate_model import aggregation_semantics_for as canonical_semantics
from .geosphere_monthly import MONTHLY_DATASET_PAGE, MONTHLY_DOI, MONTHLY_OFFICIAL_CONTEXT_EN, MONTHLY_RESOURCE_ID
from .psychrometrics import add_psychrometric_properties, pressure_from_altitude_m
from .temporal_filtering import CALENDAR_PROFILE, CHRONOLOGICAL, SEASON_ORDER, chronological_season_start, is_multiyear, season_name, time_basis

MONTHLY_REPRESENTATIVE_STATE_NOTE = (
    "Calculated monthly psychrometric properties are properties of the published monthly-mean "
    "temperature / relative-humidity / pressure state. They are representative monthly states, "
    "not arithmetic means of unobserved hourly humidity ratio, enthalpy or wet-bulb temperature."
)
CORE_MONTHLY_PROVIDERS = {
    "tl_mittel", "tlmin", "tlmax", "rf_mittel", "tp_mittel", "p", "rr", "so_h",
    "tb10_mittel", "tb20_mittel", "tb50_mittel", "tb100_mittel", "tb200_mittel",
}
GROUND_COLUMNS = (
    "ground_temperature_0_10m_c", "ground_temperature_0_20m_c", "ground_temperature_0_50m_c",
    "ground_temperature_1_00m_c", "ground_temperature_2_00m_c",
)


def _numeric(df: pd.DataFrame, column: str) -> bool:
    return column in df.columns and bool(pd.to_numeric(df[column], errors="coerce").notna().any())


def _monthly_semantics(column: str) -> str | None:
    value = str(column)
    monthly = monthly_cleanup.monthly_semantics_from_column(value)
    return monthly if value.startswith("monthly__") else canonical_semantics(value)


def monthly_catalogue_role(descriptor: Any) -> str:
    provider = str(getattr(descriptor, "provider", ""))
    if provider in CORE_MONTHLY_PROVIDERS or bool(getattr(descriptor, "recommended", False)):
        return "Core variable"
    if str(getattr(descriptor, "category", "")) != "Other monthly parameters" and getattr(descriptor, "annual_semantics", None):
        return "Additional statistic"
    return "Other provider parameter"


def _period_keys(index: pd.DatetimeIndex, aggregation: str) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(index)
    wall = idx.tz_localize(None) if idx.tz is not None else idx
    if aggregation == "Monthly":
        values = wall.to_period("M").start_time
    elif aggregation == "Seasonal":
        values = chronological_season_start(wall)
    elif aggregation == "Annual":
        values = wall.to_period("Y").start_time
    else:
        raise ValueError(f"Unsupported native-monthly aggregation: {aggregation}")
    return pd.DatetimeIndex(values, name="Period")


def _weighted_circular(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not bool(valid.any()):
        return float("nan")
    radians = np.deg2rad(np.mod(values.loc[valid].to_numpy(dtype=float), 360.0))
    w = weights.loc[valid].to_numpy(dtype=float)
    s, c = float(np.average(np.sin(radians), weights=w)), float(np.average(np.cos(radians), weights=w))
    return float("nan") if abs(s) < 1e-12 and abs(c) < 1e-12 else float(np.mod(np.rad2deg(np.arctan2(s, c)), 360.0))


def monthly_period_values(df: pd.DataFrame, column: str, aggregation: str) -> pd.Series:
    if aggregation not in {"Monthly", "Seasonal", "Annual"}:
        raise ValueError(f"Unsupported native-monthly aggregation: {aggregation}")
    if column not in df.columns:
        raise KeyError(column)
    semantics = _monthly_semantics(column)
    if semantics is None:
        raise ValueError(f"No safe seasonal/annual semantics are known for {column}.")
    idx = pd.DatetimeIndex(df.index)
    temp = pd.DataFrame({
        "value": pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float),
        "weight": idx.days_in_month.astype(float),
        "period": _period_keys(idx, aggregation).to_numpy(),
    }, index=df.index)
    grouped = temp.groupby("period", sort=True)
    if semantics == "sum":
        result = grouped["value"].sum(min_count=1)
    elif semantics == "min":
        result = grouped["value"].min()
    elif semantics == "max":
        result = grouped["value"].max()
    elif semantics == "circular mean":
        result = grouped.apply(lambda g: _weighted_circular(g["value"], g["weight"]))
    else:
        def weighted(g: pd.DataFrame) -> float:
            valid = g["value"].notna() & g["weight"].notna() & g["weight"].gt(0)
            return float("nan") if not bool(valid.any()) else float(np.average(g.loc[valid, "value"], weights=g.loc[valid, "weight"]))
        result = grouped.apply(weighted)
    out = pd.Series(result, dtype=float).dropna()
    out.index = pd.DatetimeIndex(out.index, name="Period")
    out.name = str(column)
    return out


def _calendar_slot(index: pd.DatetimeIndex, aggregation: str) -> pd.Index:
    if aggregation == "Monthly":
        return pd.Index(index.month.astype(int), name="Month")
    if aggregation == "Seasonal":
        return pd.CategoricalIndex([season_name(int(m)) for m in index.month], categories=list(SEASON_ORDER), ordered=True, name="Season")
    return pd.Index(["Annual"] * len(index), name="Period")


def monthly_aggregate_summary(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
    values = monthly_period_values(df, column, aggregation)
    if time_basis(df) == CALENDAR_PROFILE:
        temp = pd.DataFrame({"value": values.to_numpy(), "slot": _calendar_slot(pd.DatetimeIndex(values.index), aggregation)})
        grouped = temp.groupby("slot", observed=False, sort=True)["value"]
        out = grouped.agg(mean="mean", min="min", max="max", median="median")
        out["p05"], out["p95"] = grouped.quantile(0.05), grouped.quantile(0.95)
        out = out.dropna(how="all")
    else:
        out = pd.DataFrame(index=values.index)
        for name in ("mean", "min", "max", "median", "p05", "p95"):
            out[name] = values.to_numpy()
    out.attrs.update(dict(df.attrs)); out.attrs["aggregation"] = aggregation
    return out


def monthly_aggregate_sum(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
    values = monthly_period_values(df, column, aggregation)
    out = pd.DataFrame({name: values for name in ("sum", "mean", "min", "max")})
    out.attrs.update(dict(df.attrs)); out.attrs["aggregation"] = aggregation
    return out


def _monthly_overlay_table(df: pd.DataFrame, column: str, resolution: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    values = monthly_period_values(df, column, resolution)
    frame = values.rename("value").to_frame(); frame["interval_start"] = frame.index
    if resolution == "Monthly":
        frame["interval_end"] = [pd.Timestamp(ts) + pd.offsets.MonthBegin(1) for ts in frame.index]
    elif resolution == "Seasonal":
        frame["interval_end"] = [pd.Timestamp(ts) + pd.DateOffset(months=3) for ts in frame.index]
    else:
        frame["interval_end"] = [pd.Timestamp(ts) + pd.offsets.YearBegin(1) for ts in frame.index]
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    frame = frame.loc[(frame["interval_end"] > start) & (frame["interval_start"] < end)].copy()
    frame["plot_start"] = frame["interval_start"].where(frame["interval_start"] >= start, start)
    frame["plot_end"] = frame["interval_end"].where(frame["interval_end"] <= end, end)
    frame["resolution"], frame["aggregation"] = resolution, _monthly_semantics(column)
    return frame


def _calendar_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out, attrs = frame.copy(), dict(frame.attrs); idx = pd.DatetimeIndex(out.index)
    out["year"], out["month_index"], out["month_name"] = idx.year, idx.month, idx.month_name().str.slice(stop=3)
    out["day_of_year"], out["week_of_year"], out["hour_of_day"] = idx.dayofyear, idx.isocalendar().week.astype(int), idx.hour
    out["season"] = [season_name(int(m)) for m in idx.month]; out.attrs.update(attrs)
    return out


def monthly_psychrometric_frame(dataset: Any, frame: pd.DataFrame) -> pd.DataFrame:
    out = _calendar_columns(frame)
    if not (_numeric(out, "dry_bulb_temperature_c") and _numeric(out, "relative_humidity_pct")):
        return out
    fallback = pressure_from_altitude_m(float(getattr(dataset.location, "elevation_m", 0.0) or 0.0))
    out = add_psychrometric_properties(out, fallback_pressure_pa=fallback)
    out.attrs.update({
        "canonical_monthly_psychrometric_fallback_pressure_pa": float(fallback),
        "canonical_monthly_psychrometric_semantics": MONTHLY_REPRESENTATIVE_STATE_NOTE,
        "canonical_native_resolution": "monthly", "canonical_analysis_resolution": "monthly",
    })
    return out


def monthly_psychrometric_profile(df: pd.DataFrame, fallback_pressure_pa: float) -> pd.DataFrame:
    if not all(_numeric(df, c) for c in ("dry_bulb_temperature_c", "relative_humidity_pct")):
        return pd.DataFrame()
    idx = pd.DatetimeIndex(df.index); work = pd.DataFrame(index=df.index)
    work["month_index"] = idx.month
    for c in ("dry_bulb_temperature_c", "relative_humidity_pct", "atmospheric_station_pressure_pa"):
        if c in df.columns: work[c] = pd.to_numeric(df[c], errors="coerce")
    work = work.loc[work["dry_bulb_temperature_c"].notna() & work["relative_humidity_pct"].notna()].copy()
    if work.empty: return pd.DataFrame()
    cols = [c for c in ("dry_bulb_temperature_c", "relative_humidity_pct", "atmospheric_station_pressure_pa") if c in work.columns]
    profile = work.groupby("month_index", sort=True)[cols].mean()
    profile.index = pd.DatetimeIndex([pd.Timestamp(2000, int(m), 1) for m in profile.index], name="timestamp")
    profile["month_index"], profile["month_name"] = profile.index.month, profile.index.month_name().str.slice(stop=3)
    profile = add_psychrometric_properties(profile, fallback_pressure_pa=float(fallback_pressure_pa))
    profile.attrs.update(dict(df.attrs)); profile.attrs["canonical_monthly_psychrometric_semantics"] = MONTHLY_REPRESENTATIVE_STATE_NOTE
    return profile


def _threshold_label(label: str, frame: pd.DataFrame) -> bool:
    provider = str(frame.attrs.get("geosphere_monthly_label_to_provider", {}).get(label, ""))
    descriptor = frame.attrs.get("geosphere_monthly_parameter_descriptors", {}).get(provider)
    text = f"{provider} {label}".lower()
    return str(getattr(descriptor, "statistic", "")) == "Monthly count" or any(t in text for t in ("frost", "eis", "ice", "sommer", "summer", "trop", "hot day"))


def _ensure_label(groups: dict[str, list[str]], page: str, label: str, legacy: Any, frame: pd.DataFrame) -> None:
    if label in legacy.VARIABLES and _numeric(frame, legacy.VARIABLES[label][0]) and label not in groups.setdefault(page, []):
        groups[page].append(label)


def _render_monthly_generic(legacy: Any, df: pd.DataFrame, labels: list[str], title: str) -> None:
    if not labels: legacy.st.info("No variables for this analysis are available in the active monthly dataset."); return
    st, real_selectbox = legacy.st, legacy.st.selectbox; selected = {"column": None}
    def selectbox(label: str, options: Iterable[Any], *args: Any, **kwargs: Any):
        values = list(options)
        if label == "Variable":
            value = real_selectbox(label, values, *args, **kwargs); selected["column"] = legacy.VARIABLES.get(value, (None,))[0]; return value
        if label == "Chart type": values = [v for v in values if v in monthly_ui.MONTHLY_ALLOWED_GENERIC_CHART_TYPES]
        elif label == "Aggregation":
            semantics = _monthly_semantics(selected["column"]) if selected["column"] else None
            values = ["Monthly"] if semantics is None else ["Monthly", "Seasonal", "Annual"]
            if semantics is None: kwargs["help"] = "No normalized seasonal/annual semantics are known for this provider statistic."
        elif label == "Heat-map aggregation": values, kwargs["disabled"] = ["Month"], True
        elif label == "Compare across": values, kwargs["disabled"] = ["Year"], True
        kwargs["index"] = min(int(kwargs.get("index", 0)), max(len(values)-1, 0)); return real_selectbox(label, values, *args, **kwargs)
    st.selectbox = selectbox
    try:
        legacy.render_generic_variable_page(df, labels, labels[0], title, monthly_ui._monthly_interpretation, temperature_thresholds=(18.0, 26.0) if title.startswith("Temperature") else None)
        st.caption("Monthly preserves published values. Seasonal/Annual use quantity-aware semantics: day-weighted means, sums for totals/counts, extrema for extrema, circular means for directions.")
    finally: st.selectbox = real_selectbox


def _render_monthly_psychrometric(legacy: Any, df: pd.DataFrame) -> None:
    st = legacy.st
    p = pd.to_numeric(df.get("atmospheric_station_pressure_pa"), errors="coerce").dropna() if "atmospheric_station_pressure_pa" in df.columns else pd.Series(dtype=float)
    if not p.empty: reference, origin = float(p.mean()), "mean published station pressure"
    else:
        reference = float(df.attrs.get("canonical_monthly_psychrometric_fallback_pressure_pa", 101325.0)); origin = "altitude-derived fallback" if "canonical_monthly_psychrometric_fallback_pressure_pa" in df.attrs else "standard-atmosphere fallback"
    profile = monthly_psychrometric_profile(df, reference)
    if profile.empty: st.info("Monthly psychrometric points require monthly-mean dry-bulb temperature and relative humidity."); return
    display = profile.copy(); display["atmospheric_station_pressure_pa"] = reference
    display = add_psychrometric_properties(display, fallback_pressure_pa=reference)
    display["month_index"], display["month_name"] = display.index.month, display.index.month_name().str.slice(stop=3)
    axes = st.radio("Psychrometric axes", ["T-d", "i-d"], horizontal=True, key="monthly_psych_axes")
    givoni = st.checkbox("Show Givoni-Milne bioclimatic overlay", True, key="monthly_psych_givoni")
    fig = legacy.psychrometric_chart(display, chart_type=axes, pressure_pa=reference, show_rh_curves=True, show_comfort_zone=givoni, data_mode="Monthly points", selected_months=list(range(1, 13)), color_mode="Month")
    legacy.render_plot(fig, f"Up to 12 representative calendar-month states at one common pressure ({reference:,.0f} Pa; {origin}). {MONTHLY_REPRESENTATIVE_STATE_NOTE}")


def _render_monthly_temperature(legacy: Any, df: pd.DataFrame, labels: list[str], title: str) -> None:
    st = legacy.st; thresholds = [l for l in labels if _threshold_label(l, df)]
    ground = [l for l in labels if l in legacy.VARIABLES and legacy.VARIABLES[l][0] in GROUND_COLUMNS]
    explorer = [l for l in labels if l not in thresholds and l not in ground]
    if _numeric(df, "dew_point_temperature_c") and "Dew-point temperature" not in explorer: explorer.append("Dew-point temperature")
    options = (["Temperature variable explorer"] if explorer else []) + (["Ground temperature"] if ground else []) + (["Threshold conditions"] if thresholds else [])
    if not options: st.info("No monthly temperature variables are available."); return
    choice = st.selectbox("Analysis type", options, key="monthly_temperature_analysis_type")
    if choice == "Ground temperature": legacy.render_ground_temperature_page(df, source_label="GeoSphere monthly measured", native_df=df)
    elif choice == "Threshold conditions":
        st.caption("Provider-published monthly event/count statistics; they are not reconstructed from monthly mean temperature."); _render_monthly_generic(legacy, df, thresholds, "Temperature threshold conditions")
    else: _render_monthly_generic(legacy, df, explorer, title)


def _render_monthly_humidity(legacy: Any, df: pd.DataFrame, labels: list[str], title: str) -> None:
    st = legacy.st; explorer = [l for l in labels if l != "Dew-point temperature"]
    for label in ("Relative humidity", "Humidity ratio", "Moist-air enthalpy", "Wet-bulb temperature", "Specific volume", "Moist-air density", "Station pressure"):
        if label in legacy.VARIABLES and _numeric(df, legacy.VARIABLES[label][0]) and label not in explorer: explorer.append(label)
    options = ["Humidity variable explorer"] + (["Psychrometric chart"] if _numeric(df, "dry_bulb_temperature_c") and _numeric(df, "relative_humidity_pct") else [])
    choice = st.selectbox("Analysis type", options, key="monthly_humidity_analysis_type")
    if choice == "Psychrometric chart": st.caption(MONTHLY_REPRESENTATIVE_STATE_NOTE); _render_monthly_psychrometric(legacy, df)
    else: _render_monthly_generic(legacy, df, explorer, title)


def _install_monthly(proxy: Any, parity: Any) -> None:
    if "tp_mittel" in monthly_cleanup._KNOWN_MONTHLY_FIELDS:
        label, _, semantics, recommended = monthly_cleanup._KNOWN_MONTHLY_FIELDS["tp_mittel"]
        monthly_cleanup._KNOWN_MONTHLY_FIELDS["tp_mittel"] = (label, "Temperature", semantics, recommended)
    previous_frame, previous_registry = monthly_ui.monthly_analysis_frame, monthly_ui.monthly_variable_registry
    monthly_ui.monthly_analysis_frame = lambda dataset: monthly_psychrometric_frame(dataset, previous_frame(dataset))
    def registry(legacy: Any, dataset: Any, frame: pd.DataFrame):
        groups, mapping = previous_registry(legacy, dataset, frame); groups = {k:list(v) for k,v in groups.items()}
        groups["Humidity and Psychrometrics"] = [l for l in groups.get("Humidity and Psychrometrics", []) if l != "Dew-point temperature"]
        _ensure_label(groups, "Temperature", "Dew-point temperature", legacy, frame)
        for label in ("Relative humidity", "Humidity ratio", "Moist-air enthalpy", "Wet-bulb temperature", "Specific volume", "Moist-air density", "Station pressure"):
            _ensure_label(groups, "Humidity and Psychrometrics", label, legacy, frame)
        return groups, mapping
    monthly_ui.monthly_variable_registry = registry
    monthly_ui.MONTHLY_ALLOWED_AGGREGATIONS = monthly_cleanup.MONTHLY_GENERIC_AGGREGATIONS = ("Monthly", "Seasonal", "Annual")
    monthly_cleanup.MONTHLY_OVERLAY_RESOLUTIONS = ("Monthly", "Seasonal", "Annual")

    old_summary, old_sum = agg.aggregate_summary, agg.aggregate_sum
    agg.aggregate_summary = lambda df,c,a: monthly_aggregate_summary(df,c,a) if str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly" and a in {"Monthly","Seasonal","Annual"} else old_summary(df,c,a)
    agg.aggregate_sum = lambda df,c,a: monthly_aggregate_sum(df,c,a) if str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly" and a in {"Monthly","Seasonal","Annual"} else old_sum(df,c,a)
    charts.aggregate_summary, charts.aggregate_sum = agg.aggregate_summary, agg.aggregate_sum
    old_semantics = agg.aggregation_semantics_for
    agg.aggregation_semantics_for = lambda c: monthly_cleanup.monthly_semantics_from_column(str(c)) or old_semantics(c)
    old_ts = timeseries.aggregate_series
    timeseries.aggregate_series = lambda df,c,r,s,e: _monthly_overlay_table(df,c,r,s,e) if str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly" and r in {"Monthly","Seasonal","Annual"} else old_ts(df,c,r,s,e)

    def render_generic(legacy: Any, df: pd.DataFrame, labels: list[str], title: str):
        if title.startswith("Temperature"): _render_monthly_temperature(legacy, df, labels, title)
        elif title.startswith("Humidity"): _render_monthly_humidity(legacy, df, labels, title)
        else: _render_monthly_generic(legacy, df, labels, title)
    monthly_ui._render_monthly_generic = render_generic
    old_renderer = monthly_ui.render_monthly_canonical_analysis
    def renderer(legacy: Any, dataset: Any):
        st, real = legacy.st, legacy.st.selectbox
        def selectbox(label: str, options: Iterable[Any], *args: Any, **kwargs: Any):
            values=list(options); key=str(kwargs.get("key") or "")
            if label=="Analysis type" and kwargs.get("disabled") and key.startswith("monthly_locked_analysis_"): return values[0] if values else None
            return real(label, values, *args, **kwargs)
        st.selectbox=selectbox
        try: old_renderer(legacy,dataset)
        finally: st.selectbox=real
    monthly_ui.render_monthly_canonical_analysis = renderer


def _install_shared_ui(proxy: Any, parity: Any) -> None:
    st, old_temp = parity.st, proxy.render_temperature
    old_humidity_base = getattr(proxy, "_source_parity_original_humidity", proxy.render_humidity)
    def temperature(df: pd.DataFrame, *args: Any, **kwargs: Any):
        has_mean = _numeric(df,"dry_bulb_temperature_c"); has_partial = any(_numeric(df,c) for c in ("dry_bulb_temperature_min_c","dry_bulb_temperature_max_c","dew_point_temperature_c")); has_ground=any(_numeric(df,c) for c in GROUND_COLUMNS)
        if not has_mean and has_partial:
            st.header("Temperature and extremes"); labels=[l for l in ("Dry-bulb temperature minimum","Dry-bulb temperature maximum","Dew-point temperature") if l in proxy.VARIABLES and _numeric(df,proxy.VARIABLES[l][0])]
            options=(["Temperature variable explorer"] if labels else [])+(["Ground temperature"] if has_ground else []); choice=st.selectbox("Analysis type",options,key="temperature_partial_analysis_type")
            if choice=="Ground temperature": proxy.render_ground_temperature_page(df,source_label=kwargs.get("ground_source_label") or "Measured",native_df=kwargs.get("ground_native_df"))
            else: proxy.render_generic_variable_page(df,labels,labels[0],"Temperature",None,temperature_thresholds=(18.0,26.0))
            return
        real_select, real_slider = st.selectbox, st.slider; state={"analysis":None}
        def selectbox(label: str, options: Iterable[Any], *a: Any, **k: Any):
            v=real_select(label,options,*a,**k); state["analysis"]=v if label=="Analysis type" else state["analysis"]; return v
        def slider(label: str,*a: Any,**k: Any):
            if state["analysis"]=="Temperature variable explorer" and label in {"Heating threshold [°C]","Cooling threshold [°C]"}: return 18.0 if label.startswith("Heating") else 26.0
            return real_slider(label,*a,**k)
        st.selectbox,st.slider=selectbox,slider
        try: old_temp(df,*args,**kwargs)
        finally: st.selectbox,st.slider=real_select,real_slider
    proxy.render_temperature=temperature

    def humidity_base(df: pd.DataFrame, pressure_pa: float, *args: Any, **kwargs: Any):
        full=_numeric(df,"dry_bulb_temperature_c") and _numeric(df,"relative_humidity_pct"); real_select,real_generic=st.selectbox,proxy.render_generic_variable_page
        def selectbox(label: str, options: Iterable[Any], *a: Any, **k: Any):
            values=list(options)
            if label=="Analysis type" and not full: values=["Humidity variable explorer"]; k["index"]=0
            return real_select(label,values,*a,**k)
        def generic(data: pd.DataFrame, labels: list[str], default: str, title: str, *a: Any, **k: Any):
            labels=list(labels)
            if title=="Humidity":
                labels=[l for l in labels if l!="Dew-point temperature"]
                if _numeric(data,"atmospheric_station_pressure_pa") and "Station pressure" not in labels: labels.append("Station pressure")
                if default not in labels and labels: default=labels[0]
            return real_generic(data,labels,default,title,*a,**k)
        st.selectbox,proxy.render_generic_variable_page=selectbox,generic
        try: old_humidity_base(df,pressure_pa,*args,**kwargs)
        finally: st.selectbox,proxy.render_generic_variable_page=real_select,real_generic
    if hasattr(proxy,"_source_parity_original_humidity"): proxy._source_parity_original_humidity=humidity_base
    else: proxy.render_humidity=humidity_base

    old_pages=parity.available_historical_pages
    def pages(df: pd.DataFrame) -> tuple[str,...]:
        current=list(old_pages(df))
        if _numeric(df,"dew_point_temperature_c") and "Temperature" not in current: current.insert(current.index("Overview")+1 if "Overview" in current else 2,"Temperature")
        humid=any(_numeric(df,c) for c in ("relative_humidity_pct","humidity_ratio_g_kg","moist_air_enthalpy_kj_kg","wet_bulb_temperature_c","specific_volume_m3_kg","moist_air_density_kg_m3","atmospheric_station_pressure_pa"))
        if humid and "Humidity and Psychrometrics" not in current: current.insert(current.index("Temperature")+1 if "Temperature" in current else min(2,len(current)),"Humidity and Psychrometrics")
        return tuple(dict.fromkeys(current))
    parity.available_historical_pages=pages


def _install_native_secondary(parity: Any) -> None:
    unrestricted=getattr(parity,"_source_parity_unrestricted_native_analysis",None)
    if unrestricted is None: return
    hourly,st=parity.prepare_historical_analysis_frame,parity.st
    parity.prepare_historical_native_analysis_frame=lambda dataset,**kwargs: unrestricted(dataset,**kwargs) if str(st.session_state.get("climate_analyzer_navigation","")) in {"Time Series and Overlay","Precipitation and Snow","Temperature"} else hourly(dataset,**kwargs)


def _install_overview(parity: Any) -> None:
    current,st=parity._render_historical_overview_enhanced,parity.st
    def render(legacy: Any, original: Callable, dataset: Any, df: pd.DataFrame, coverage_df: pd.DataFrame|None=None):
        susceptible=pd.DatetimeIndex(df.index).tz is not None and time_basis(df)==CHRONOLOGICAL and is_multiyear(df)
        if not susceptible: return current(legacy,original,dataset,df,coverage_df)
        original(dataset,df,coverage_df); cols=[c for c in dataset.available_canonical_variables if parity._numeric(df,c)]
        if not cols: return
        st.subheader("Calculated climate statistics"); st.caption("Source-neutral statistics below are calculated from the canonical hourly analysis frame and respect the active Data filter.")
        labels={v[0]:l for l,v in legacy.VARIABLES.items()}; selectable=[c for c in cols if c in labels]
        if selectable:
            column=st.selectbox("Overview statistic variable",selectable,format_func=lambda v:labels.get(v,v),key="historical_overview_stat_variable"); numeric=pd.to_numeric(df[column],errors="coerce"); key=pd.Series(pd.DatetimeIndex(df.index).month,index=df.index,dtype="int64"); sem=parity.aggregation_semantics_for(column)
            monthly=numeric.groupby(key).sum(min_count=1) if sem=="sum" else numeric.groupby(key).min() if sem=="min" else numeric.groupby(key).max() if sem=="max" else numeric.groupby(key).mean()
            table=monthly.reindex(pd.Index(range(1,13),dtype="int64")).rename_axis("month").reset_index(name="value"); fig=parity.px.bar(table,x="month",y="value",title=f"Monthly {labels.get(column,column)}"); fig.update_layout(template="plotly_white",xaxis_title="Month",yaxis_title=parity.CANONICAL_VARIABLES[column].unit if column in parity.CANONICAL_VARIABLES else ""); legacy.render_plot(fig,f"Monthly source-neutral {sem} aggregation for {labels.get(column,column)}.")
        if parity._numeric(df,"dry_bulb_temperature_c"):
            daily=longterm.chronological_aggregate_summary(df,"dry_bulb_temperature_c","Daily")[["mean","min","max"]]; c1,c2=st.columns(2); c1.markdown("**Hottest days**"); c1.dataframe(daily.sort_values("max",ascending=False).head(10),use_container_width=True); c2.markdown("**Coldest days**"); c2.dataframe(daily.sort_values("min").head(10),use_container_width=True)
    parity._render_historical_overview_enhanced=render


def _install_guidance(parity: Any) -> None:
    st,previous=parity.st,parity._render_geosphere_resource_selector
    def selector(legacy: Any, original: Callable):
        real_info,real_caption,real_write,real_expander,real_radio,real_editor=st.info,st.caption,st.write,st.expander,st.radio,st.data_editor
        seen_info:set[str]=set(); seen_caption:set[str]=set(); monthly_context={"shown":False}; view={"value":"Core variables"}
        def info(body: Any,*a: Any,**k: Any):
            text=str(body)
            if text==MONTHLY_OFFICIAL_CONTEXT_EN.strip(): return None
            if text.startswith("Official GeoSphere Austria availability context"):
                if text in seen_info:return None
                seen_info.add(text)
            return real_info(body,*a,**k)
        def caption(body: Any,*a: Any,**k: Any):
            text=str(body)
            if text.startswith("Official source: GeoSphere Austria Station Data-v2 (1 m)"): return None
            if text.startswith("Authoritative source: GeoSphere Austria Stationsdaten-v2 (1 h)"):
                if text in seen_caption:return None
                seen_caption.add(text)
            return real_caption(body,*a,**k)
        def write(body: Any,*a: Any,**k: Any):
            return None if str(st.session_state.get("geosphere_resource_id",""))==MONTHLY_RESOURCE_ID and str(body).strip()==MONTHLY_OFFICIAL_CONTEXT_EN.strip() else real_write(body,*a,**k)
        def expander(label: str,*a: Any,**k: Any):
            return nullcontext() if str(st.session_state.get("geosphere_resource_id",""))==MONTHLY_RESOURCE_ID and label=="About this GeoSphere monthly dataset" else real_expander(label,*a,**k)
        def radio(label: str,options: Iterable[Any],*a: Any,**k: Any):
            values=list(options)
            if label=="Parameter catalogue" and values==["Recommended","All parameters"]:
                selected=real_radio("Parameter set",["Core variables","Core + additional statistics","All provider parameters"],0,horizontal=True,key="geosphere_monthly_parameter_catalogue_v2",help="Core variables are canonical/building-climate quantities. Additional statistics are provider-published monthly counts/extrema/indicators. All also shows fields without normalized seasonal/annual semantics."); view["value"]=str(selected); return "All parameters"
            return real_radio(label,values,*a,**k)
        def editor(data: Any,*a: Any,**k: Any):
            if str(st.session_state.get("geosphere_resource_id",""))==MONTHLY_RESOURCE_ID and isinstance(data,pd.DataFrame) and {"Provider","Measured variable"}.issubset(data.columns):
                if not monthly_context["shown"]:
                    with real_expander("About this GeoSphere monthly dataset",expanded=False): real_write(MONTHLY_OFFICIAL_CONTEXT_EN); real_caption(f"Official source: GeoSphere Austria Station Data-v2 (1 m) · {MONTHLY_DOI} · {MONTHLY_DATASET_PAGE}")
                    monthly_context["shown"]=True
                out=data.copy(); roles=[]
                for _,row in out.iterrows():
                    provider=str(row.get("Provider","") or ""); name=str(row.get("Original GeoSphere name",row.get("Measured variable",provider)) or provider); descriptor=monthly_cleanup._metadata_descriptor(parity,provider,name,str(row.get("Unit","") or "")); roles.append(monthly_catalogue_role(descriptor))
                out["Role"]=roles; order={"Core variable":0,"Additional statistic":1,"Other provider parameter":2}; out["_role"]=out["Role"].map(order).fillna(9); out=out.sort_values(["_role","Category","Measured variable"],kind="stable").drop(columns=["_role"])
                if view["value"]=="Core variables": out=out.loc[out["Role"]=="Core variable"].copy()
                elif view["value"]=="Core + additional statistics": out=out.loc[out["Role"].isin(["Core variable","Additional statistic"])].copy()
                config=dict(k.get("column_config") or {}); config["Role"]=st.column_config.TextColumn("Role",width="medium")
                if view["value"]!="All provider parameters": config["Provider"]=None; config["Original GeoSphere name"]=None
                k["column_config"]=config; disabled=list(k.get("disabled") or []); k["disabled"]=disabled+["Role"] if "Role" not in disabled else disabled
                return real_editor(out,*a,**k)
            return real_editor(data,*a,**k)
        st.info,st.caption,st.write,st.expander,st.radio,st.data_editor=info,caption,write,expander,radio,editor
        try: previous(legacy,original)
        finally: st.info,st.caption,st.write,st.expander,st.radio,st.data_editor=real_info,real_caption,real_write,real_expander,real_radio,real_editor
    parity._render_geosphere_resource_selector=selector


def install_contract_closure(proxy: Any, parity: Any) -> None:
    if bool(getattr(proxy,"_CANONICAL_CONTRACT_CLOSURE_INSTALLED",False)): return
    _install_shared_ui(proxy,parity); _install_native_secondary(parity); _install_overview(parity); _install_monthly(proxy,parity); _install_guidance(parity)
    proxy._CANONICAL_CONTRACT_CLOSURE_INSTALLED=True
