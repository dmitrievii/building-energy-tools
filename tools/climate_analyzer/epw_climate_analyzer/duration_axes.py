"""Explicit duration-axis endpoints and readable round-number ticks.

Labels are data-derived. A small display-only right-hand gutter prevents Plotly
from dropping or clipping the last tick at the Cartesian boundary, including
when the shared presentation font is increased. No extrapolated data or
additional duration observations are introduced.
"""
from __future__ import annotations

import math


def physical_hour_ticks(endpoint: float) -> list[float]:
    """Use round 1/2/5-decade steps plus the exact observed duration."""
    if not math.isfinite(endpoint) or endpoint <= 0:
        return []
    target = endpoint / 8.
    decade = 10. ** math.floor(math.log10(target))
    step = min((decade, 2*decade, 5*decade, 10*decade),
               key=lambda candidate: abs(math.log(candidate / target)))
    ticks = [round(i*step, 10) for i in range(int(math.floor(endpoint/step))+1)]
    # Avoid a near-duplicate at the right boundary. Keep 8000 for both
    # 8760 and 8784 and use just one label when the total is a round number.
    if ticks and math.isclose(ticks[-1],endpoint,rel_tol=1e-12,abs_tol=1e-10):
        ticks[-1] = endpoint
    else:
        if len(ticks)>1 and endpoint-ticks[-1] < .33*step:
            ticks.pop()
        ticks.append(endpoint)
    return ticks


def apply_duration_axis(fig,endpoint: float,*,percentage: bool=False):
    if not math.isfinite(endpoint) or endpoint<=0:
        return fig
    ticks=[0,20,40,60,80,100] if percentage else physical_hour_ticks(endpoint)
    labels=[f"{v:g}%" if percentage else f"{v:g}" for v in ticks]
    # A 1.5% gutter is visual whitespace only; the last labelled tick is
    # exactly the physical endpoint, with no ticks or samples beyond it.
    upper=endpoint*1.015
    fig.update_xaxes(range=[0,upper],tickmode="array",tickvals=ticks,
                     ticktext=labels,ticksuffix="",ticklabeloverflow="allow",
                     automargin=True,
                     autorangeoptions=dict(minallowed=0,maxallowed=upper))
    fig.update_layout(margin=dict(r=max(85,int(fig.layout.margin.r or 0))))
    return fig
