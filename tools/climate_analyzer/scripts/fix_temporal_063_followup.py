"""Focused follow-up patch for Climate Analyzer 0.6.3 temporal semantics.

Temporary branch-only helper. Removed before merge.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise RuntimeError(f"{label}: source anchor not found")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_app() -> None:
    path = ROOT / "app.py"
    old = '''    if page == "Time Series and Overlay":
        # This page owns an exact date/hour/minute viewport. Applying the global
        # month/hour sidebar filter as well would create two conflicting time
        # filters, so it starts from the complete loaded source calendar.
        filtered_df = full_df
        st.session_state["_active_filtered_export_df"] = full_df
    else:
        filtered_df = sidebar_filters(full_df)
        if filtered_df.empty:
            st.warning("The current filters remove all data. Adjust the month or hour filter.")
            return
'''
    new = '''    filtered_df = sidebar_filters(full_df)
    if filtered_df.empty:
        st.warning("The current filters remove all data. Adjust the date, month or hour filter.")
        return
'''
    replace_exact(path, old, new, "EPW global-filter bypass")

    old = '''    elif page == "Time Series and Overlay":
        render_time_series_overlay(full_df)
    elif page == "Natural Ventilation":
'''
    new = '''    elif page == "Time Series and Overlay":
        render_time_series_overlay(filtered_df)
    elif page == "Natural Ventilation":
'''
    replace_exact(path, old, new, "EPW overlay input")

    old = '''    else:
        render_data_quality(epw, full_df, issues)


if __name__ == "__main__":
'''
    new = '''    else:
        render_data_quality(epw, filtered_df, issues)


if __name__ == "__main__":
'''
    replace_exact(path, old, new, "EPW data-quality input")


def patch_aggregations() -> None:
    path = ROOT / "epw_climate_analyzer" / "aggregations.py"
    old = '''        frame = pd.DataFrame({"season": df.get("season"), "_value": numeric}, index=df.index)
        return frame.groupby("season", observed=False)["_value"].sum(min_count=1).reindex(list(SEASON_ORDER)).dropna()
'''
    new = '''        if "season" in df.columns:
            season_values = df["season"]
        else:
            season_values = pd.Categorical(
                [season_name(month) for month in pd.DatetimeIndex(df.index).month],
                categories=list(SEASON_ORDER),
                ordered=True,
            )
        frame = pd.DataFrame({"season": season_values, "_value": numeric.to_numpy()}, index=df.index)
        return frame.groupby("season", observed=False)["_value"].sum(min_count=1).reindex(list(SEASON_ORDER)).dropna()
'''
    replace_exact(path, old, new, "seasonal period totals without season column")

    old = '''    if aggregation == "Seasonal" and not is_multiyear(df):
        grouped = df.groupby("season", observed=False)[column]
        out = grouped.agg(sum="sum", mean="mean", min="min", max="max").reindex(list(SEASON_ORDER)).dropna(how="all")
        return _attach_temporal_attrs(out, df, aggregation)
'''
    new = '''    if aggregation == "Seasonal" and not is_multiyear(df):
        if "season" in df.columns:
            season_values = df["season"]
        else:
            season_values = pd.Categorical(
                [season_name(month) for month in pd.DatetimeIndex(df.index).month],
                categories=list(SEASON_ORDER),
                ordered=True,
            )
        temp = pd.DataFrame({"season": season_values, "_value": values.to_numpy()}, index=df.index)
        grouped = temp.groupby("season", observed=False)["_value"]
        out = grouped.agg(sum="sum", mean="mean", min="min", max="max").reindex(list(SEASON_ORDER)).dropna(how="all")
        return _attach_temporal_attrs(out, df, aggregation)
'''
    replace_exact(path, old, new, "seasonal extensive summary without season column")

    old_import = '''    is_multiyear,
    time_basis,
)
'''
    new_import = '''    is_multiyear,
    season_name,
    time_basis,
)
'''
    replace_exact(path, old_import, new_import, "season_name import")


def main() -> None:
    patch_app()
    patch_aggregations()


if __name__ == "__main__":
    main()
