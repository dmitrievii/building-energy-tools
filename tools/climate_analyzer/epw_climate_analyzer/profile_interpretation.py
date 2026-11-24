"""One scientific interpretation adapter for all ordinary climate profile routes.

The interactive explorer, generated standard report and comprehensive atlas
call the same statistic-sensitive interpretation function. Route identifiers
and interface wording never change the inferred physical quantity.
"""
from __future__ import annotations

def canonical_profile_kind(kind, title="", args=()):
    """Map chart representations to the same scientific interpretation kind."""
    route=str(kind or "").strip().lower()
    if route not in ("time_series","time series / profile","profile","percentile","native"):
        return route
    if route=="native":return "native"
    description=(str(title or "")+" "+" ".join(map(str,args or ()))).lower()
    if "observed values" in description or "native observations" in description:
        return "time_series"
    if "p05" in description and "p95" in description:
        return "percentile"
    if route=="percentile":return "percentile"
    if route in ("time_series","time series / profile"):return "profile"
    return route

PROFILE_KINDS=frozenset(("native","time_series","time series / profile","profile","percentile"))

# Quantity taxonomy is shared with live chart dispatch. The same quantity
# receives one scientific interpretation regardless of its navigation tab.
MOIST_AIR_QUANTITIES=frozenset((
    "dew_point_temperature_c","wet_bulb_temperature_c",
    "relative_humidity_pct","humidity_ratio_g_kg",
    "moist_air_enthalpy_kj_kg","specific_volume_m3_kg",
    "moist_air_density_kg_m3","atmospheric_station_pressure_pa",
))


def profile_interpretation(
    df,fig,kind,*,domain,column,title="",args=(),thresholds=(18.,26.),
    latitude=None,plane="reference vertical south-facing plane",
):
    """Interpret an actual profile figure consistently in all delivery formats.

    All time/percentile conclusions refer to the provided plotted figure and
    its source weather observations. Chart construction is unchanged.
    """
    route=str(kind or "").lower()
    if route not in PROFILE_KINDS:
        raise ValueError("A statistical climate profile is required.")
    actual_title=str(title or getattr(getattr(getattr(fig,"layout",None),"title",None),"text","") or "")
    canonical=canonical_profile_kind(kind,actual_title,args)
    name=quantity_domain(column,domain).lower()
    # Dispatch by physical quantity BEFORE page domain. Dew point and wet bulb
    # also appear in Temperature explorer, while the same graph is catalogued
    # under Humidity and Psychrometrics in Atlas/report. Domain-first dispatch
    # previously produced two different interpretations for identical figures.
    if column in MOIST_AIR_QUANTITIES:
        from .humidity_findings import humidity_figure_interpretation
        return humidity_figure_interpretation(
            df,fig,canonical,column=column,title=actual_title,args=args)
    if name.startswith("temperature"):
        from .temperature_findings import temperature_figure_interpretation
        return temperature_figure_interpretation(
            df,fig,canonical,column=column,title=actual_title,thresholds=thresholds)
    if name.startswith("humidity"):
        from .humidity_findings import humidity_figure_interpretation
        return humidity_figure_interpretation(
            df,fig,canonical,column=column,title=actual_title,args=args)
    if name.startswith("wind"):
        from .wind_findings import wind_figure_interpretation
        return wind_figure_interpretation(
            df,fig,canonical,column=column,title=actual_title,args=args)
    if name.startswith("solar"):
        from .solar_findings import solar_figure_interpretation
        return solar_figure_interpretation(
            df,fig,canonical,column=column,title=actual_title,args=args,plane=plane)
    if name.startswith("sky") or name.startswith("illuminance"):
        from .sky_findings import sky_figure_interpretation
        return sky_figure_interpretation(
            df,fig,canonical,column=column,title=actual_title,args=args,latitude=latitude)
    if name.startswith("precipitation") or name.startswith("snow"):
        from .precipitation_findings import precipitation_figure_interpretation
        return precipitation_figure_interpretation(
            df,fig,canonical,column=column,title=actual_title,args=args)
    # Generic explorers (e.g. Atmospheric context) route by the selected
    # physical quantity rather than the page heading. Keep all existing chart
    # pages functional when they use the same generic explorer component.
    if column in MOIST_AIR_QUANTITIES:
        from .humidity_findings import humidity_figure_interpretation
        return humidity_figure_interpretation(
            df,fig,canonical,column=column,title=actual_title,args=args)
    if "temperature" in column:
        from .temperature_findings import temperature_figure_interpretation
        return temperature_figure_interpretation(
            df,fig,canonical,column=column,title=actual_title,thresholds=thresholds)
    from .interpretations import variable_interpretation
    return variable_interpretation(
        df,column,actual_title or column,"")


def profile_band(fig,kind="",title=""):
    """Identify the statistical envelope from the traces actually rendered.

    A standard-report title need not contain 'min–mean–max', while the plotted
    Minimum and Maximum traces have exactly the same meaning as on the website.
    """
    names=[str(getattr(t,"name","") or "").lower() for t in getattr(fig,"data",())]
    p05=any("p05" in n for n in names)
    p95=any("p95" in n for n in names)
    if p05 and p95:return "percentile"
    minimum=any(n in ("min","minimum") for n in names)
    maximum=any(n in ("max","maximum") for n in names)
    if minimum and maximum:return "minmax"
    if len(names)==1 and names[0] in ("mean","median","observed values"):
        return ""
    label=str(title or "").lower()
    if "p05" in label and "p95" in label:return "percentile"
    if ("min–mean–max" in label or "min-mean-max" in label):return "minmax"
    return "percentile" if kind=="percentile" else ""


def profile_centre(fig,kind="",title=""):
    """Select the central statistic represented by a figure's actual traces."""
    names=[str(getattr(t,"name","") or "").lower() for t in getattr(fig,"data",())]
    if any(n=="median" for n in names):return "median"
    if any(n=="mean" for n in names):return "mean"
    if profile_band(fig,kind,title)=="percentile":return "median"
    label=str(title or "").lower()
    return "median" if "median" in label or kind=="percentile" else "mean"


# R2.8: one entrypoint for all ordinary variable representations.
GENERIC_KINDS=frozenset(("native","time_series","time series / profile","profile",
    "percentile","heatmap","duration","histogram","box","violin","diurnal",
    "occurrence","amplitude"))
_KIND_ALIASES={"heat map":"heatmap","duration curve":"duration",
    "monthly boxplot":"box","monthly violin plot":"violin",
    "typical daily profile":"diurnal","monthly occurrence classes":"occurrence"}


def quantity_domain(column,domain=""):
    """Use the physical registry, with a domain fallback for uncatalogued fields."""
    if column in MOIST_AIR_QUANTITIES:return "Humidity and Psychrometrics"
    # Imported lazily because the atlas registry also imports the report module.
    from .p66_catalogue import VARIABLE_GROUPS
    for family,variables in VARIABLE_GROUPS.items():
        if any(c==column for c,_,_ in variables):return family
    if "temperature" in str(column):return "Temperature"
    return str(domain or "")


def generic_figure_interpretation(df,fig,kind,*,domain,column,title="",args=(),
                                  thresholds=(18.,26.),latitude=None,plane=None):
    """Shared website/standard/atlas interpreter for a variable representation.

    The caller supplies the actual plotted scope (wet-only and selected months
    included) and semantic chart arguments, never navigation-specific prose.
    """
    route=str(kind).strip().lower()
    route=_KIND_ALIASES.get(route,route)
    if route not in GENERIC_KINDS:
        raise ValueError("Unsupported generic variable representation: "+route)
    family=quantity_domain(column,domain)
    plane=plane or df.attrs.get("r24_solar_plane","reference vertical south-facing plane")
    actual_title=str(title or getattr(getattr(fig.layout,"title",None),"text","") or "")
    args=tuple(args or ())
    if route in PROFILE_KINDS:
        return profile_interpretation(df,fig,route,domain=family,column=column,
            title=actual_title,args=args,thresholds=thresholds,latitude=latitude,plane=plane)
    from .p66_catalogue import LABELS,UNITS
    label=LABELS.get(column,column.replace("_"," "))
    # Non-profile titles are presentation labels; construct the same semantic
    # description from controls rather than infer science from a page heading.
    semantic_title=label+" · "+route+" · "+" · ".join(map(str,args))
    if not args:semantic_title=actual_title
    if route=="diurnal":
        # Use the centre curves actually drawn by diurnal_figure. They contain
        # complete clock-hour aggregates (including extensive interval sums).
        import numpy as np
        points=[]
        for trace in fig.data:
            if getattr(trace,"customdata",None) is None:continue
            y=np.asarray(trace.y,dtype=float)
            x=list(trace.x)
            month=str(getattr(trace,"name","") or "")
            points.extend((float(v),month,x[i]) for i,v in enumerate(y)
                          if i<len(x) and np.isfinite(v))
        if points:
            low=min(points,key=lambda p:p[0]);high=max(points,key=lambda p:p[0])
            centre=str(args[1]).lower() if len(args)>1 else "mean"
            unit=UNITS.get(column,str(fig.layout.yaxis.title.text or ""))
            return (f"The plotted month–hour {centre} of {label.lower()} is lowest in "
                    f"{low[1]} at {int(low[2]):02d}:00 ({low[0]:,.1f} {unit}) and highest in "
                    f"{high[1]} at {int(high[2]):02d}:00 ({high[0]:,.1f} {unit}). "
                    "Equivalent calendar-month clock hours pool complete source hours; "
                    "the daily contrast identifies the timing and magnitude of recurring conditions."
                    +(" "+_quantity_physics(df,column) if family.startswith("Humidity") else ""))
    if route=="amplitude":
        import numpy as np
        from .period_display import format_plotted_time
        values=[]
        for trace in fig.data:
            if getattr(trace,"y",None) is None:continue
            x=list(trace.x)
            values.extend((float(v),x[i]) for i,v in enumerate(np.asarray(trace.y,dtype=float))
                          if i<len(x) and np.isfinite(v))
        if values:
            high=max(values,key=lambda p:p[0])
            period=str(args[0]).lower() if args else "selected-period"
            when=format_plotted_time(high[1],df,title=semantic_title)
            mean=float(np.mean([v for v,_ in values]))
            return (f"The mean plotted {period} {label.lower()} amplitude is {mean:,.1f} K; "
                    f"maximum {high[0]:,.1f} K at {when}. "
                    "Amplitude equals the observed within-period maximum minus minimum. "
                    "At least two valid observations define a period range."
                    +(" "+_quantity_physics(df,column) if family.startswith("Humidity") else ""))
    if family.startswith("Temperature"):
        from .temperature_findings import temperature_figure_interpretation
        note=temperature_figure_interpretation(df,fig,route,column=column,
            title=semantic_title,thresholds=thresholds)
    elif family.startswith("Humidity"):
        from .humidity_findings import humidity_figure_interpretation
        note=humidity_figure_interpretation(df,fig,route,column=column,title=semantic_title,args=args)
    elif family.startswith("Wind"):
        from .wind_findings import wind_figure_interpretation
        note=wind_figure_interpretation(df,fig,route,column=column,title=semantic_title,args=args)
    elif family.startswith("Solar"):
        from .solar_findings import solar_figure_interpretation
        note=solar_figure_interpretation(df,fig,route,column=column,title=semantic_title,args=args,plane=plane)
    elif family.startswith(("Sky","Illuminance")):
        from .sky_findings import sky_figure_interpretation
        note=sky_figure_interpretation(df,fig,route,column=column,title=semantic_title,args=args,latitude=latitude)
    elif family.startswith(("Precipitation","Snow")):
        from .precipitation_findings import precipitation_figure_interpretation
        note=precipitation_figure_interpretation(df,fig,route,column=column,title=semantic_title,args=args)
    else:
        from .interpretations import variable_interpretation
        note=variable_interpretation(df,column,label.lower(),UNITS.get(column,""))
    if route=="heatmap" and len(args)>=3:
        from .aggregations import heatmap_has_single_observation_cells
        if heatmap_has_single_observation_cells(df,args[0],args[1]):
            note+=" Each occupied calendar cell represents its corresponding source observation."
        else:note+=f" Cell statistic: {args[2]}; comparison: {args[1]}."
    if route in ("duration","histogram","box","violin") and args and args[0]=="wet":
        note+=" The distribution contains positive precipitation intervals."
    if route=="occurrence" and column=="diffuse_radiation_fraction_pct" and args and args[0]=="Days":
        note+=" Complete days with positive GHI and complete coincident daylight DHI define the daily fraction statistic."
    return note.strip()


def _quantity_physics(df,column):
    from .humidity_findings import _physical_context
    return _physical_context(df,column)
