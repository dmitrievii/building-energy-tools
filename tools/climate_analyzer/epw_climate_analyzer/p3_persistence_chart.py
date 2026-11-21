"""Common monthly persistence chart for interactive and Atlas output."""
from __future__ import annotations
import plotly.graph_objects as go
from .calendar_heatmap_axes import apply_monthly_axes,set_period_axis_scope

def persistence_figure(counts,title,*,night=False):
    unit="nights" if night else "days"
    fig=go.Figure()
    for name,colour in (("Meets minimum","#21866B"),("Below minimum","#B8C0C6")):
        fig.add_bar(x=counts.index,y=counts[name],name=name,marker_color=colour,
                    hovertemplate="%{x|%b %Y}<br>"+name+": %{y:.0f} "+unit+"<extra></extra>")
    fig.add_scatter(x=counts.index,y=counts["Observed days"],name="Observed "+unit,
                    mode="lines+markers",line=dict(color="#334155",width=2),
                    marker=dict(size=6),connectgaps=False,
                    hovertemplate="%{x|%b %Y}<br>Observed "+unit+": %{y:.0f}<extra></extra>")
    fig.update_layout(template="plotly_white",title=title,barmode="stack",
                      xaxis_title="Month",yaxis_title=unit.capitalize(),
                      legend=dict(orientation="h",x=0,y=-.22),
                      margin=dict(b=85))
    fig.update_yaxes(rangemode="tozero")
    set_period_axis_scope(fig,counts,aggregation="Monthly")
    return apply_monthly_axes(fig)
