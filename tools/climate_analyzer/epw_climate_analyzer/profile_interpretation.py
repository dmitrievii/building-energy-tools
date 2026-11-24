"""One scientific interpretation adapter for all ordinary climate profile routes.

The interactive explorer, generated standard report and comprehensive atlas
call the same statistic-sensitive interpretation function. Route identifiers
and interface wording never change the inferred physical quantity.
"""
from __future__ import annotations

from .period_display import canonical_profile_kind

PROFILE_KINDS=frozenset(("native","time_series","time series / profile","profile","percentile"))


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
    name=str(domain or "").lower()
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
    raise ValueError(f"No profile interpretation route for domain {domain!r}.")


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
