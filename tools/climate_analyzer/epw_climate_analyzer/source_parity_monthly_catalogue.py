"""Human-readable catalogue adapter for GeoSphere native-monthly parameters.

Kept separate from the source selector so provider metadata can remain live while
UI labels/statistics are deterministic and testable.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from . import source_parity_monthly_cleanup as cleanup


def decorate_monthly_parameter_table(parity: Any, data: pd.DataFrame) -> pd.DataFrame:
    """Add category/statistic guidance without losing provider selection keys."""
    out = data.copy()
    descriptors = []
    for _, row in out.iterrows():
        provider = str(row.get("Provider", "") or "")
        name = str(row.get("Measured variable", "") or provider)
        unit = str(row.get("Unit", "") or "")
        descriptors.append(cleanup._metadata_descriptor(parity, provider, name, unit))

    out["Category"] = [item.category for item in descriptors]
    out["Statistic"] = [item.statistic for item in descriptors]
    out["Notes"] = [item.note for item in descriptors]
    out["_recommended"] = [item.recommended for item in descriptors]
    out["Original GeoSphere name"] = out["Measured variable"].astype(str)
    out["Measured variable"] = [item.label for item in descriptors]
    return out


def install_monthly_catalogue_adapter() -> None:
    """Bind the stable catalogue decorator into the monthly cleanup layer."""
    cleanup._decorate_parameter_table = decorate_monthly_parameter_table
