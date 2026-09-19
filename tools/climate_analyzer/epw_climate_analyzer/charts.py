"""Plotly chart factory functions for EPW climate analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
import psychrolib

from .aggregations import (
    HEATMAP_COMPARE_HOUR,
    aggregate_summary,
    aggregate_sum,
    duration_curve,
    monthly_box_data,
    native_interval_hours,
    temporal_heatmap_matrix,
)
from .temporal_filtering import CALENDAR_PROFILE, CHRONOLOGICAL, display_period_labels, is_multiyear, time_basis
from .psychrometrics import DEFAULT_PRESSURE_PA, psychrometric_rh_curves
from .psychrometric_distribution import add_climate_zone_traces, psychrometric_axis_ranges
from .chart_theme import (
    BINARY_SUITABILITY_COLORSCALE,
    CLIMATE_COLORS,
    PSYCHROMETRIC_TILE_COLORSCALE,
    DEFAULT_METRIC_COLOR,
    WIND_SPEED_COLOR_MAP,
    WIND_SPEED_LABELS,
    metric_band_colors,
    metric_color,
    metric_colorscale,
    rgba,
    semantic_color_from_text,
)

psychrolib.SetUnitSystem(psychrolib.SI)


# Increment whenever app.py starts passing a psychrometric_chart call contract
# that an older in-process charts module cannot accept. Streamlit can rerun a
# freshly updated app.py while Python still retains imported package modules in
# sys.modules; the app uses this marker to detect and reload that stale module.
PSYCHROMETRIC_CHART_API_VERSION = 2

PLOT_TEMPLATE = "plotly_white"
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TEMPERATURE_COMFORT_COLORSCALE = [
    [0.00, "#1d4ed8"],
    [0.32, "#3b82f6"],
    [0.45, "#22c55e"],
    [0.55, "#22c55e"],
    [0.70, "#f97316"],
    [1.00, "#dc2626"],
]

# NOTE: The remainder of this file is intentionally unchanged by this hotfix.
