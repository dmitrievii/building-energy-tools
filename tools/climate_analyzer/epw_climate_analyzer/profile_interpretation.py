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
