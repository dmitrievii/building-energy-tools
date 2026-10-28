"""Shared IGE request/result contracts and research climate assembly.

The historical route produces a grid background. The future route is a
reference-normalized monthly research morph, not a qualified local forecast.
"""

from .contracts import ClimateResult, FieldDefinition, FutureRequest, HistoricalRequest
from .historical import run_historical
from .future import run_future

__all__ = ["ClimateResult", "FieldDefinition", "FutureRequest", "HistoricalRequest", "run_historical", "run_future"]
