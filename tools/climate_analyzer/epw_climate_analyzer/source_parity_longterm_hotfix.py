"""Focused production hotfixes for long-term GeoSphere analysis.

This module is installed only by the mature Climate Analyzer runtime.  It keeps
provider transport, canonical physics and the stable UI shell separate while
closing four production defects exposed by multi-decade ``klima-v2-1h`` use:

* local-civil calendar aggregation must not rely on timezone-aware pandas
  ``resample`` bins across DST transitions;
* GeoSphere quality flags are optional transfer columns and are off by default;
* leading/trailing timestamps with no selected measured observations are not
  retained in the active canonical dataset;
* heat maps scale their hour axis to the actually populated hours instead of
  forcing a 0..23 canvas around a single filtered hour.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Iterable, Mapping

import pandas as pd


QUALITY_FLAG_SELECTION_KEY = "_geosphere_selected_quality_flags"
QUALITY_FLAG_COLUMN_LABEL = "Quality flag"


def chronological_period_key(index: pd.DatetimeIndex, aggregation: str) -> pd.DatetimeIndex:
    """Return DST-independent local-calendar period starts.

    The input index already represents the selected analysis clock.  Calendar
    periods are labels rather than physical instants, so timezone information is
    intentionally removed *after* the clock conversion and before grouping.
    Both physical records of an autumn repeated hour therefore contribute to the
    same local calendar day/month without any relocalization step.
    """
    idx = pd.DatetimeIndex(index)
    wall = idx.tz_localize(None) if idx.tz is not None else idx
    if aggregation == "Daily":
        key = wall.normalize()
    elif aggregation == "Weekly":
        key = wall.to_period("W-SUN").start_time
    elif aggregation == "Monthly":
        key = wall.to_period("M").start_time
    elif aggregation == "Annual":
        key = wall.to_period("Y").start_time
    else:
        raise ValueError(f"Unsupported chronological calendar aggregation: {aggregation}")
    return pd.DatetimeIndex(key, name="Period")


def chronological_aggregate_summary(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
    """Aggregate an intensive/state variable by local calendar labels."""
    values = pd.to_numeric(df[column], errors="coerce")
    key = chronological_period_key(pd.DatetimeIndex(df.index), aggregation)
    temp = pd.DataFrame({"_value": values.to_numpy(), "_period": key.to_numpy()})
    grouped = temp.groupby("_period", sort=True)["_value"]
    out = grouped.agg(mean="mean", min="min", max="max", median="median")
    out["p05"] = grouped.quantile(0.05)
    out["p95"] = grouped.quantile(0.95)
    out = out.dropna(how="all")
    out.index = pd.DatetimeIndex(out.index, name="Period")
    return out


def chronological_period_total(values: pd.Series, df: pd.DataFrame, aggregation: str) -> pd.Series:
    """Aggregate an extensive quantity by local calendar labels."""
    numeric = pd.to_numeric(values, errors="coerce")
    key = chronological_period_key(pd.DatetimeIndex(df.index), aggregation)
    temp = pd.DataFrame({"_value": numeric.to_numpy(), "_period": key.to_numpy()})
    result = temp.groupby("_period", sort=True)["_value"].sum(min_count=1).dropna()
    result.index = pd.DatetimeIndex(result.index, name="Period")
    return result


def chronological_aggregate_sum(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
    """Return period sum plus raw-interval descriptive statistics."""
    values = pd.to_numeric(df[column], errors="coerce")
    key = chronological_period_key(pd.DatetimeIndex(df.index), aggregation)
    temp = pd.DataFrame({"_value": values.to_numpy(), "_period": key.to_numpy()})
    grouped = temp.groupby("_period", sort=True)["_value"]
    out = pd.DataFrame(
        {
            "sum": grouped.sum(min_count=1),
            "mean": grouped.mean(),
            "min": grouped.min(),
            "max": grouped.max(),
        }
    ).dropna(how="all")
    out.index = pd.DatetimeIndex(out.index, name="Period")
    return out


def trim_empty_measured_edges(dataset: Any) -> Any:
    """Trim only all-empty leading/trailing rows from a canonical dataset.

    Interior all-missing periods remain untouched so genuine provider gaps stay
    visible to Data Quality.  The requested interval is retained in attrs while
    the active DataFrame starts/ends at the first/last selected measured value.
    """
    data = dataset.data
    measured_columns = [column for column in dataset.available_canonical_variables if column in data.columns]
    if not measured_columns:
        return dataset
    observed = data[measured_columns].notna().any(axis=1)
    if not bool(observed.any()):
        raise ValueError(
            "GeoSphere returned no numeric observations for the selected measured variables in the requested interval."
        )
    positions = observed.to_numpy().nonzero()[0]
    first = int(positions[0])
    last = int(positions[-1])
    if first == 0 and last == len(data) - 1:
        attrs = dict(data.attrs)
        attrs["canonical_measured_envelope_start"] = pd.Timestamp(data.index[first]).isoformat()
        attrs["canonical_measured_envelope_end"] = pd.Timestamp(data.index[last]).isoformat()
        attrs["canonical_trimmed_empty_edge_rows"] = 0
        data.attrs.update(attrs)
        return dataset

    attrs = dict(data.attrs)
    trimmed = data.iloc[first : last + 1].copy()
    trimmed.attrs.update(attrs)
    trimmed.attrs["canonical_measured_envelope_start"] = pd.Timestamp(trimmed.index.min()).isoformat()
    trimmed.attrs["canonical_measured_envelope_end"] = pd.Timestamp(trimmed.index.max()).isoformat()
    trimmed.attrs["canonical_trimmed_empty_edge_rows"] = int(first + (len(data) - last - 1))
    return replace(dataset, data=trimmed)


def populated_hour_axis_range(df: pd.DataFrame, column: str) -> list[float] | None:
    """Return a reversed Plotly hour-axis range around populated heat-map rows."""
    if column not in df.columns:
        return None
    valid = pd.to_numeric(df[column], errors="coerce").notna()
    if not bool(valid.any()):
        return None
    if "hour_of_day" in df.columns:
        hours = pd.to_numeric(df.loc[valid, "hour_of_day"], errors="coerce").dropna()
    else:
        hours = pd.Series(pd.DatetimeIndex(df.index[valid]).hour, dtype=float)
    hours = hours[(hours >= 0) & (hours <= 23)]
    if hours.empty:
        return None
    lo = float(hours.min())
    hi = float(hours.max())
    return [hi + 0.5, lo - 0.5]


def _selected_flag_names_from_state(st: Any, resource_id: str) -> tuple[str, ...]:
    state = st.session_state.get(QUALITY_FLAG_SELECTION_KEY, {})
    if not isinstance(state, Mapping) or str(state.get("resource_id", "")) != str(resource_id):
        return ()
    values = state.get("flags", ())
    if not isinstance(values, (tuple, list, set)):
        return ()
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def install_longterm_hourly_hotfix(proxy: Any, parity: Any) -> None:
    """Install the long-term GeoSphere fixes into the already mature runtime."""
    if bool(getattr(proxy, "_LONGTERM_GEOSPHERE_HOTFIX_INSTALLED", False)):
        return

    from . import aggregations as agg
    from . import charts
    from . import geosphere
    from .temporal_filtering import CALENDAR_PROFILE, CHRONOLOGICAL, is_multiyear, time_basis

    st = parity.st

    # ------------------------------------------------------------------
    # 1. DST-safe calendar aggregation.
    # ------------------------------------------------------------------
    original_summary = agg.aggregate_summary
    original_period_total = agg.period_total_series
    original_aggregate_sum = agg.aggregate_sum

    def aggregate_summary_safe(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
        if time_basis(df) == CALENDAR_PROFILE or aggregation in {"Hourly", "Seasonal"}:
            return original_summary(df, column, aggregation)
        out = chronological_aggregate_summary(df, column, aggregation)
        return agg._attach_temporal_attrs(out, df, aggregation)

    def period_total_safe(values: pd.Series, df: pd.DataFrame, aggregation: str) -> pd.Series:
        if time_basis(df) == CALENDAR_PROFILE or aggregation in {"Hourly", "Seasonal"}:
            return original_period_total(values, df, aggregation)
        return chronological_period_total(values, df, aggregation)

    def aggregate_sum_safe(df: pd.DataFrame, column: str, aggregation: str) -> pd.DataFrame:
        if time_basis(df) == CALENDAR_PROFILE or aggregation in {"Hourly", "Seasonal"}:
            return original_aggregate_sum(df, column, aggregation)
        out = chronological_aggregate_sum(df, column, aggregation)
        return agg._attach_temporal_attrs(out, df, aggregation)

    agg.aggregate_summary = aggregate_summary_safe
    agg.period_total_series = period_total_safe
    agg.aggregate_sum = aggregate_sum_safe
    # charts imported these helpers by name; update those module globals too.
    charts.aggregate_summary = aggregate_summary_safe
    charts.aggregate_sum = aggregate_sum_safe

    # ------------------------------------------------------------------
    # 2. Heat-map axis behavior for filtered/multi-decade data.
    # ------------------------------------------------------------------
    original_temporal_heatmap_chart = charts.temporal_heatmap_chart

    def temporal_heatmap_chart_safe(
        df: pd.DataFrame,
        column: str,
        row_group: str,
        compare_across: str,
        statistic: str,
        title: str,
        unit: str,
        temperature_thresholds: tuple[float, float] | None = None,
    ):
        fig = original_temporal_heatmap_chart(
            df,
            column,
            row_group,
            compare_across,
            statistic,
            title,
            unit,
            temperature_thresholds=temperature_thresholds,
        )
        if compare_across == agg.HEATMAP_COMPARE_HOUR:
            axis_range = populated_hour_axis_range(df, column)
            if axis_range is not None:
                fig.update_yaxes(range=axis_range, autorange=False)
        if time_basis(df) == CHRONOLOGICAL and is_multiyear(df):
            group = str(row_group).strip().lower()
            if group == "day":
                fig.update_xaxes(title_text="Date")
            elif group == "week":
                fig.update_xaxes(title_text="Week")
            elif group == "month":
                fig.update_xaxes(title_text="Month")
        return fig

    charts.temporal_heatmap_chart = temporal_heatmap_chart_safe
    # render_generic_variable_page resolves this symbol from app globals.
    if hasattr(proxy, "temporal_heatmap_chart"):
        proxy.temporal_heatmap_chart = temporal_heatmap_chart_safe

    # ------------------------------------------------------------------
    # 3. Optional quality flags in the existing measured-variable table.
    # ------------------------------------------------------------------
    original_provider_with_flags = geosphere.provider_parameters_with_quality_flags
    original_resource_selector = parity._render_geosphere_resource_selector

    def selected_query_parameters(
        metadata: Mapping[str, Any],
        provider_parameters: Iterable[str],
        *,
        resource_id: str = geosphere.GEOSPHERE_RESOURCE_ID,
    ) -> tuple[str, ...]:
        physical = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))
        # Let the original strict contract validate physical fields and discover
        # which matching flags actually exist in live metadata.
        complete = original_provider_with_flags(metadata, physical, resource_id=resource_id)
        available_flags = {name for name in complete if name not in physical}
        selected_flags = _selected_flag_names_from_state(st, resource_id)
        chosen = tuple(
            flag
            for flag in selected_flags
            if flag in available_flags and flag.removesuffix("_flag") in physical
        )
        return physical + chosen

    # fetch_station_dataset resolves this helper from geosphere module globals,
    # so the actual provider transfer now matches the UI estimate exactly.
    geosphere.provider_parameters_with_quality_flags = selected_query_parameters
    parity.provider_parameters_with_quality_flags = selected_query_parameters

    def resource_selector_with_flag_column(legacy: Any, original: Callable) -> None:
        real_data_editor = parity.st.data_editor

        def data_editor_with_flag(data: Any, *args: Any, **kwargs: Any):
            if kwargs.get("key") != "geosphere_variable_editor" or not isinstance(data, pd.DataFrame):
                return real_data_editor(data, *args, **kwargs)

            enhanced = data.copy()
            if QUALITY_FLAG_COLUMN_LABEL not in enhanced.columns:
                insert_at = 1 if "Selected" in enhanced.columns else len(enhanced.columns)
                enhanced.insert(insert_at, QUALITY_FLAG_COLUMN_LABEL, False)

            column_config = dict(kwargs.get("column_config") or {})
            column_config[QUALITY_FLAG_COLUMN_LABEL] = st.column_config.CheckboxColumn(
                "Flag",
                width="small",
                help="Load the matching GeoSphere provider quality flag. Off by default to avoid doubling transfer size.",
            )
            kwargs["column_config"] = column_config
            disabled = list(kwargs.get("disabled") or [])
            kwargs["disabled"] = [name for name in disabled if name != QUALITY_FLAG_COLUMN_LABEL]
            edited = real_data_editor(enhanced, *args, **kwargs)

            resource_id = str(st.session_state.get("geosphere_resource_id", geosphere.GEOSPHERE_RESOURCE_ID))
            if isinstance(edited, pd.DataFrame) and {"Selected", "Provider", QUALITY_FLAG_COLUMN_LABEL}.issubset(edited.columns):
                mask = (
                    edited["Selected"].fillna(False).astype(bool)
                    & edited[QUALITY_FLAG_COLUMN_LABEL].fillna(False).astype(bool)
                )
                selected_flags = tuple(
                    f"{name}_flag"
                    for name in edited.loc[mask, "Provider"].astype(str).tolist()
                )
            else:
                selected_flags = ()
            st.session_state[QUALITY_FLAG_SELECTION_KEY] = {
                "resource_id": resource_id,
                "flags": selected_flags,
            }
            st.caption(
                "Quality flags are optional and disabled by default. Station validity is station metadata, not per-variable coverage; "
                "after loading, empty leading/trailing timestamps are trimmed to the actual measured envelope of the selected variables."
            )
            return edited

        parity.st.data_editor = data_editor_with_flag
        try:
            original_resource_selector(legacy, original)
        finally:
            parity.st.data_editor = real_data_editor

    parity._render_geosphere_resource_selector = resource_selector_with_flag_column

    # ------------------------------------------------------------------
    # 4. Drop completely empty outer timestamp tails after provider load.
    # ------------------------------------------------------------------
    original_parity_fetch = parity.fetch_station_dataset

    def fetch_station_dataset_trimmed(*args: Any, **kwargs: Any):
        dataset = original_parity_fetch(*args, **kwargs)
        return trim_empty_measured_edges(dataset)

    parity.fetch_station_dataset = fetch_station_dataset_trimmed

    # Overview contained one direct daily ``resample`` outside the shared
    # aggregation engine. Replace only the enhanced wrapper with the same local-
    # calendar grouping contract so Overview is covered by this hotfix too.
    original_overview_enhanced = parity._render_historical_overview_enhanced

    def overview_enhanced_safe(
        legacy: Any,
        original: Callable,
        dataset: Any,
        df: pd.DataFrame,
        coverage_df: pd.DataFrame | None = None,
    ) -> None:
        # Run the existing function for UTC/fixed-offset and calendar-profile
        # cases. Local-civil multi-year data are the only path susceptible to the
        # direct pandas daily resample in that wrapper.
        idx = pd.DatetimeIndex(df.index)
        susceptible = idx.tz is not None and time_basis(df) == CHRONOLOGICAL and is_multiyear(df)
        if not susceptible:
            original_overview_enhanced(legacy, original, dataset, df, coverage_df)
            return

        original(dataset, df, coverage_df)
        canonical_columns = [column for column in dataset.available_canonical_variables if parity._numeric(df, column)]
        if not canonical_columns:
            return
        st.subheader("Calculated climate statistics")
        st.caption("Source-neutral statistics below are calculated from the canonical hourly analysis frame and respect the active Data filter.")
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
            table = monthly.reindex(range(1, 13)).rename("value").reset_index(names="month")
            fig = parity.px.bar(table, x="month", y="value", title=f"Monthly {labels.get(column, column)}")
            fig.update_layout(template="plotly_white", xaxis_title="Month", yaxis_title=parity.CANONICAL_VARIABLES[column].unit)
            legacy.render_plot(fig, f"Monthly source-neutral {semantics} aggregation for {labels.get(column, column)}.")
        if parity._numeric(df, "dry_bulb_temperature_c"):
            daily = aggregate_summary_safe(df, "dry_bulb_temperature_c", "Daily")[["mean", "min", "max"]]
            c1, c2 = st.columns(2)
            c1.markdown("**Hottest days**")
            c1.dataframe(daily.sort_values("max", ascending=False).head(10), use_container_width=True)
            c2.markdown("**Coldest days**")
            c2.dataframe(daily.sort_values("min").head(10), use_container_width=True)

    parity._render_historical_overview_enhanced = overview_enhanced_safe

    proxy._LONGTERM_GEOSPHERE_HOTFIX_INSTALLED = True
