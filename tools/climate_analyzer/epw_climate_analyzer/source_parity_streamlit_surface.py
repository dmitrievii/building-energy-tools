"""Pristine Streamlit callable surface for rerun-safe source-parity wrappers.

Streamlit reruns the application script while the imported ``streamlit`` module
and ``DeltaGenerator`` class remain alive in the Python process.  The source-
parity compatibility stack temporarily replaces a small set of Streamlit
callables while rendering the GeoSphere selector.  A widget-triggered rerun can
interrupt that call stack before every nested ``finally`` has restored its
callable, leaving an old wrapper as the next run's apparent "real" function.

This module is deliberately *not* reloaded by ``source_parity_runtime``.  On its
first import in a clean process it captures the genuine Streamlit callables; at
the beginning of every later application rerun it restores those exact objects
before any source-parity layer is composed again.
"""
from __future__ import annotations

from typing import Any

import streamlit as st
from streamlit.delta_generator import DeltaGenerator


_STREAMLIT_NAMES = (
    "data_editor",
    "dataframe",
    "date_input",
    "selectbox",
    "radio",
    "slider",
    "button",
    "form_submit_button",
    "warning",
    "caption",
    "info",
    "write",
    "expander",
)

_PRISTINE_STREAMLIT: dict[str, Any] = {
    name: getattr(st, name) for name in _STREAMLIT_NAMES
}
_PRISTINE_DG_DATE_INPUT = DeltaGenerator.date_input


def restore_streamlit_surface() -> None:
    """Restore Streamlit functions that source-parity renders patch temporarily."""
    for name, function in _PRISTINE_STREAMLIT.items():
        setattr(st, name, function)
    DeltaGenerator.date_input = _PRISTINE_DG_DATE_INPUT


def pristine_streamlit_callable(name: str) -> Any:
    """Return a captured pristine callable for focused regression tests."""
    return _PRISTINE_STREAMLIT[name]


def pristine_delta_generator_date_input() -> Any:
    """Return the captured pristine ``DeltaGenerator.date_input`` method."""
    return _PRISTINE_DG_DATE_INPUT
