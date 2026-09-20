"""Final fail-closed native-monthly aggregation guard.

This module is installed after the composed runtime stack.  It keeps provider-
defined monthly fields usable at their published cadence, refuses to invent
Seasonal/Annual semantics for unknown statistics, and provides warning-free
vectorized aggregation for known monthly quantities.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import source_parity_contract_closure as contract


def _known_monthly_period_values(
    df: pd.DataFrame,
    column: str,
    aggregation: str,
    semantics: str,
) -> pd.Series:
    if column not in df.columns:
        raise KeyError(column)
    if aggregation not in {"Monthly", "Seasonal", "Annual"}:
        raise ValueError(f"Unsupported native-monthly aggregation: {aggregation}")

    index = pd.DatetimeIndex(df.index)
    values = pd.to_numeric(df[column], errors="coerce").astype(float)
    periods = pd.Series(
        contract._period_keys(index, aggregation).to_numpy(),
        index=df.index,
        name="period",
    )
    weights = pd.Series(index.days_in_month.astype(float), index=df.index, name="weight")
    work = pd.DataFrame(
        {
            "value": values.to_numpy(dtype=float),
            "period": periods.to_numpy(),
            "weight": weights.to_numpy(dtype=float),
        },
        index=df.index,
    )
    valid = work["value"].notna() & work["weight"].notna() & work["weight"].gt(0)

    if semantics == "sum":
        result = work.groupby("period", sort=True)["value"].sum(min_count=1)
    elif semantics == "min":
        result = work.groupby("period", sort=True)["value"].min()
    elif semantics == "max":
        result = work.groupby("period", sort=True)["value"].max()
    elif semantics == "circular mean":
        radians = np.deg2rad(np.mod(work["value"], 360.0))
        sin_weighted = (np.sin(radians) * work["weight"]).where(valid)
        cos_weighted = (np.cos(radians) * work["weight"]).where(valid)
        grouped_sin = sin_weighted.groupby(work["period"], sort=True).sum(min_count=1)
        grouped_cos = cos_weighted.groupby(work["period"], sort=True).sum(min_count=1)
        result = np.mod(np.rad2deg(np.arctan2(grouped_sin, grouped_cos)), 360.0)
        result = pd.Series(result, index=grouped_sin.index, dtype=float)
    else:
        weighted_value = (work["value"] * work["weight"]).where(valid)
        valid_weight = work["weight"].where(valid)
        numerator = weighted_value.groupby(work["period"], sort=True).sum(min_count=1)
        denominator = valid_weight.groupby(work["period"], sort=True).sum(min_count=1)
        result = numerator / denominator.replace(0.0, np.nan)

    out = pd.Series(result, dtype=float).dropna()
    out.index = pd.DatetimeIndex(out.index, name="Period")
    out.name = str(column)
    return out


def install_contract_guards() -> None:
    """Install the final native-monthly semantics contract exactly once per stack.

    The idempotency marker belongs to the wrapper function rather than the
    module namespace. ``importlib.reload`` re-executes function definitions but
    retains unrelated dynamic module attributes; a module-level installed flag
    can therefore survive a Streamlit rerun after the wrapped function itself
    has been replaced. A function-local marker cannot become stale that way.
    """
    current = contract.monthly_period_values
    if bool(getattr(current, "_MONTHLY_CONTRACT_GUARDED", False)):
        return

    def monthly_period_values(df: pd.DataFrame, column: str, aggregation: str) -> pd.Series:
        semantics = contract._monthly_semantics(column)
        if semantics is None:
            if aggregation != "Monthly":
                raise ValueError(f"No safe seasonal/annual semantics are known for {column}.")
            if column not in df.columns:
                raise KeyError(column)
            index = contract._period_keys(pd.DatetimeIndex(df.index), "Monthly")
            values = pd.to_numeric(df[column], errors="coerce")
            out = pd.Series(values.to_numpy(dtype=float), index=index, name=str(column)).dropna()
            if out.index.has_duplicates:
                raise ValueError(
                    f"Native monthly provider field {column} contains duplicate calendar-month records."
                )
            return out
        return _known_monthly_period_values(df, column, aggregation, semantics)

    monthly_period_values._MONTHLY_CONTRACT_GUARDED = True
    contract.monthly_period_values = monthly_period_values
