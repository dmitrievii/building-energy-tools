"""Shared IGE request/result contracts and research climate assembly.

The historical entry point produces a grid background, not a qualified local
station reconstruction. FutureRequest is a contract, not an implemented solver.
"""

from .contracts import ClimateResult, FieldDefinition, FutureRequest, HistoricalRequest
from .historical import run_historical

__all__ = ["ClimateResult", "FieldDefinition", "FutureRequest", "HistoricalRequest", "run_historical"]
