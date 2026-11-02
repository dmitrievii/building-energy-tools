"""Presentation and charting; physics/aggregation lives only in bundle.py."""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

PLOT_TEMPLATE = 'plotly_white'
COLORS = ['#D55E00', '#0072B2', '#009E73', '#7C3AED', '#E69F00', '#64748B', '#CC79A7', '#0E7490']


@dataclass(frozen=True)
class ChartSettings:
    width: int = 1250
    height: int = 600
    font_size: int = 15
    legend: str = 'Top'
    line_width: int = 2
    title: str = ''


def apply_presentation(fig: go.Figure, settings: ChartSettings, ylabel: str) -> go.Figure:
    legend = dict(orientation='h', yanchor='bottom', y=1.03, xanchor='left', x=0) if settings.legend == 'Top' else dict(orientation='v', y=1.0, x=1.03)
    fig.update_layout(
        template=PLOT_TEMPLATE, width=settings.width, height=settings.height,
        font=dict(size=settings.font_size, family='Arial, sans-serif', color='#273244'),
        title=dict(text=settings.title, font=dict(size=settings.font_size + 3)),
        xaxis=dict(title='Reference calendar (not weather/project year)', showgrid=True, tickfont=dict(size=settings.font_size)),
        yaxis=dict(title=ylabel, showgrid=True, tickfont=dict(size=settings.font_size)),
        legend=legend, margin=dict(l=85, r=45 if settings.legend == 'Top' else 160, t=110, b=75),
        hovermode='x unified', paper_bgcolor='#FFFFFF', plot_bgcolor='#FFFFFF',
    )
    return fig


def timeline_chart(data: pd.DataFrame, *, unit: str, settings: ChartSettings,
                   chart_type: str = 'Line') -> go.Figure:
    fig = go.Figure()
    if data.empty:
        return apply_presentation(fig, settings, unit)
    for idx, (key, group) in enumerate(data.groupby('series', sort=True)):
        color = COLORS[idx % len(COLORS)]
        if chart_type == 'Bar':
            fig.add_trace(go.Bar(x=group.time, y=group.value, name=str(key), marker_color=color))
        else:
            fig.add_trace(go.Scatter(x=group.time, y=group.value, name=str(key),
                                     mode='lines', line=dict(width=settings.line_width, color=color),
                                     connectgaps=False))
    apply_presentation(fig, settings, unit)
    fig.update_layout(barmode='group')
    return fig


def duration_chart(data: pd.DataFrame, *, unit: str, settings: ChartSettings) -> go.Figure:
    fig = go.Figure()
    for idx, (key, group) in enumerate(data.groupby('series', sort=True)):
        ranked = group.value.dropna().sort_values(ascending=False).to_numpy()
        if len(ranked):
            fig.add_trace(go.Scatter(x=100.0 * (pd.RangeIndex(1,len(ranked)+1).to_numpy()/len(ranked)),
                                     y=ranked, name=str(key), mode='lines',
                                     line=dict(width=settings.line_width, color=COLORS[idx % len(COLORS)])))
    apply_presentation(fig, settings, unit)
    fig.update_xaxes(title='Exceeded fraction of selected intervals (%)')
    fig.update_layout(hovermode='closest')
    return fig


def calendar_heatmap(hourly: pd.DataFrame, *, settings: ChartSettings, unit: str) -> go.Figure:
    if hourly.empty or hourly.series.nunique() != 1:
        raise ValueError('Hourly calendar heatmap requires exactly one series.')
    daily = hourly.copy()
    daily['day'] = daily.time.dt.dayofyear
    daily['hour'] = daily.time.dt.hour
    matrix = daily.pivot_table(index='hour', columns='day', values='value', aggfunc='mean')
    fig = go.Figure(go.Heatmap(z=matrix.to_numpy(), x=matrix.columns, y=matrix.index,
                               colorscale='RdYlBu_r', colorbar=dict(title=unit, tickfont=dict(size=settings.font_size))))
    apply_presentation(fig, settings, unit)
    fig.update_xaxes(title='Day of reference year')
    fig.update_yaxes(title='Hour of day', autorange='reversed')
    return fig


def monthly_metrics_figure(df: pd.DataFrame, *, settings: ChartSettings, unit: str) -> go.Figure:
    fig = go.Figure()
    for idx, (key, g) in enumerate(df.groupby('series', sort=True)):
        fig.add_trace(go.Bar(x=g.month, y=g.value, name=str(key), marker_color=COLORS[idx % len(COLORS)]))
    apply_presentation(fig, settings, unit)
    fig.update_xaxes(title='Month', tickmode='linear', dtick=1, range=[0.5,12.5])
    fig.update_layout(barmode='group')
    return fig


def plotly_configuration(settings: ChartSettings) -> dict:
    return {
        'displaylogo': False,
        'responsive': False,
        'scrollZoom': True,
        'toImageButtonOptions': {
            'format': 'svg', 'filename': 'EPB_Results_Chart',
            'height': settings.height, 'width': settings.width,
            'scale': 1,
        },
        'modeBarButtonsToAdd': ['drawline', 'eraseshape'],
    }
