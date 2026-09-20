"""Small fail-closed guard for provider-defined native-monthly statistics."""
from __future__ import annotations

import pandas as pd

from . import source_parity_contract_closure as contract


def install_contract_guards() -> None:
    """Keep unknown provider statistics usable monthly, but never infer coarser semantics."""
    original = contract.monthly_period_values

    def monthly_period_values(df: pd.DataFrame, column: str, aggregation: str) -> pd.Series:
        if aggregation == "Monthly" and contract._monthly_semantics(column) is None:
            if column not in df.columns:
                raise KeyError(column)
            index = contract._period_keys(pd.DatetimeIndex(df.index), "Monthly")
            values = pd.to_numeric(df[column], errors="coerce")
            out = pd.Series(values.to_numpy(dtype=float), index=index, name=str(column)).dropna()
            if out.index.has_duplicates:
                raise ValueError(f"Native monthly provider field {column} contains duplicate calendar-month records.")
            return out
        return original(df, column, aggregation)

    contract.monthly_period_values = monthly_period_values
