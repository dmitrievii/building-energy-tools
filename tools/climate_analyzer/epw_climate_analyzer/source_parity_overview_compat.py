"""Compatibility closure for the enhanced historical Overview renderer.

Pandas Series.reset_index accepts ``name=`` (singular), while DataFrame.reset_index
accepts ``names=``. The legacy enhanced Overview used the DataFrame spelling on a
Series and therefore failed only when the browser smoke reached that page.
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st

from . import aggregations as agg


def install_overview_pandas_compat(parity: Any) -> None:
    """Replace only the enhanced Overview renderer with the pandas-safe form."""

    def render(
        legacy: Any,
        original: Callable,
        dataset: Any,
        df: pd.DataFrame,
        coverage_df: pd.DataFrame | None = None,
    ) -> None:
        original(dataset, df, coverage_df)
        canonical_columns = [
            column for column in dataset.available_canonical_variables
            if parity._numeric(df, column)
        ]
        if not canonical_columns:
            return

        st.subheader("Calculated climate statistics")
        st.caption(
            "Source-neutral statistics below are calculated from the canonical hourly analysis frame "
            "and respect the active Data filter."
        )
        labels = {value[0]: label for label, value in legacy.VARIABLES.items()}
        selectable = [column for column in canonical_columns if column in labels]
        if selectable:
            column = st.selectbox(
                "Overview statistic variable",
                selectable,
                format_func=lambda value: labels.get(value, value),
                key="historical_overview_stat_variable",
            )
            semantics = parity.aggregation_semantics_for(column)
            numeric = pd.to_numeric(df[column], errors="coerce")
            if semantics == "sum":
                monthly = numeric.groupby(df["month_index"]).sum(min_count=1)
            elif semantics == "min":
                monthly = numeric.groupby(df["month_index"]).min()
            elif semantics == "max":
                monthly = numeric.groupby(df["month_index"]).max()
            else:
                monthly = numeric.groupby(df["month_index"]).mean()

            # Series.reset_index uses `name`, not DataFrame.reset_index `names`.
            table = monthly.reindex(range(1, 13)).rename("value").rename_axis("month").reset_index()
            fig = parity.px.bar(
                table,
                x="month",
                y="value",
                title=f"Monthly {labels.get(column, column)}",
            )
            fig.update_layout(
                template="plotly_white",
                xaxis_title="Month",
                yaxis_title=parity.CANONICAL_VARIABLES[column].unit,
            )
            legacy.render_plot(
                fig,
                f"Monthly source-neutral {semantics} aggregation for {labels.get(column, column)}.",
            )

        if parity._numeric(df, "dry_bulb_temperature_c"):
            # install_longterm_hourly_hotfix has already replaced this module-level
            # callable with its DST-safe implementation before this renderer is
            # installed. Keeping the module reference also makes runtime reloads
            # safe: there is no import of a function that exists only as a local
            # closure inside the hotfix installer.
            daily = agg.aggregate_summary(df, "dry_bulb_temperature_c", "Daily")[["mean", "min", "max"]]
            c1, c2 = st.columns(2)
            c1.markdown("**Hottest days**")
            c1.dataframe(daily.sort_values("max", ascending=False).head(10), use_container_width=True)
            c2.markdown("**Coldest days**")
            c2.dataframe(daily.sort_values("min").head(10), use_container_width=True)

    parity._render_historical_overview_enhanced = render
