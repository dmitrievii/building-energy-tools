"""Memory-safe runtime contract for EPW multi-climate comparison.

Streamlit executes every ``st.tabs`` body on each rerun, even when the tab is
not visible. The mature comparison page historically rendered nine analysis
families at once and also loaded the full Climate.OneBuilding station catalogue
inside a collapsed expander. Both behaviours scale poorly on Community Cloud.

This hotfix keeps the established comparison calculations unchanged while
making the expensive surfaces explicit: one comparison family is rendered per
rerun, and the station catalogue is loaded only after the user enables that
browser.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


COMPARISON_SECTIONS = (
    "Summary",
    "Temperature",
    "Humidity / Psychrometrics",
    "Solar",
    "Wind",
    "Natural ventilation",
    "Passive / HVAC",
    "Difference to reference",
    "Data quality",
)

_ALL_MONTHS = frozenset(range(1, 13))
_ALL_HOURS = frozenset(range(24))


def _safe_epw_file_eq(self: Any, other: object) -> bool | NotImplemented:
    """Compare EPW identity metadata without evaluating a pandas DataFrame."""
    if other.__class__ is not self.__class__:
        return NotImplemented
    other_epw = other
    return (
        self.location,
        self.header_lines,
        self.name,
    ) == (
        other_epw.location,
        other_epw.header_lines,
        other_epw.name,
    )


def _safe_climate_dataset_eq(self: Any, other: object) -> bool | NotImplemented:
    """Compare comparison-dataset identity without evaluating payload frames."""
    if other.__class__ is not self.__class__:
        return NotImplemented
    other_climate = other
    return (
        self.climate_id,
        self.display_name,
        self.source,
    ) == (
        other_climate.climate_id,
        other_climate.display_name,
        other_climate.source,
    )


def _install_safe_dataclass_equality(legacy: Any) -> None:
    """Make pandas-bearing EPW comparison value objects safe for ``!=``.

    Streamlit's widget-state change detector performs ``new_value != old_value``.
    The generated dataclass equality for ``EpwFile`` and ``ClimateDataset`` used
    to traverse pandas DataFrames, which can raise ``ValueError`` because a
    DataFrame has no single truth value.
    """
    from .epw_parser import EpwFile

    if not getattr(EpwFile, "_comparison_safe_eq_installed", False):
        EpwFile.__eq__ = _safe_epw_file_eq
        EpwFile._comparison_safe_eq_installed = True

    climate_dataset = getattr(legacy, "ClimateDataset", None)
    if climate_dataset is not None and not getattr(
        climate_dataset, "_comparison_safe_eq_installed", False
    ):
        climate_dataset.__eq__ = _safe_climate_dataset_eq
        climate_dataset._comparison_safe_eq_installed = True


def _filter_comparison_climates(
    legacy: Any,
    climates: list[Any],
    months: list[int],
    hours: list[int],
) -> list[Any]:
    """Avoid cloning every climate when the default full-period filter is active."""
    if frozenset(months) == _ALL_MONTHS and frozenset(hours) == _ALL_HOURS:
        return climates
    return legacy.filter_comparison_climates(climates, months=months, hours=hours)


def _render_comparison_basket_manager(legacy: Any, active_file: Any | None) -> None:
    """Render the comparison basket without eagerly loading the 98k-row catalogue."""
    st.subheader("Comparison basket")
    st.caption(
        "Add two or more EPW climates. All comparison metrics are calculated "
        "from EPW hourly data only."
    )

    col_a, col_b, col_c = st.columns([1, 1, 1])
    with col_a:
        if active_file is not None and st.button(
            "Add active climate to comparison", type="secondary"
        ):
            legacy.add_to_comparison_basket(
                active_file.name,
                active_file.payload,
                active_file.source,
                active_file.name,
            )
            st.rerun()
    with col_b:
        if st.button("Clear comparison basket", type="secondary"):
            legacy.clear_comparison_basket()
            st.rerun()
    with col_c:
        st.write(f"Selected climates: **{len(legacy.get_comparison_payloads())}**")

    uploaded = st.file_uploader(
        "Add local EPW files to comparison",
        type=["epw"],
        accept_multiple_files=True,
        key="comparison_local_epw_upload",
    )
    if uploaded and st.button("Add uploaded EPW files", type="primary"):
        for file in uploaded:
            legacy.add_to_comparison_basket(
                file.name,
                file.getvalue(),
                "Local comparison upload | user-provided EPW | transient session",
                file.name,
            )
        st.rerun()

    enable_station_browser = st.checkbox(
        "Enable Climate.OneBuilding station browser",
        value=False,
        key="comparison_enable_station_browser",
        help=(
            "The full station catalogue is intentionally not loaded until this "
            "browser is enabled, which keeps EPW comparison memory bounded."
        ),
    )
    if enable_station_browser:
        from .catalog_runtime import catalog_runtime_summary, station_provenance_text
        from .climate_sources import download_station_epw, filter_station_catalog

        with st.expander(
            "Add Climate.OneBuilding station to comparison", expanded=True
        ):
            try:
                catalog = legacy.cached_station_catalog()
            except Exception as exc:
                st.error(
                    "The versioned station catalog failed integrity/provenance "
                    f"validation: {exc}"
                )
                catalog = None

            if catalog is None or catalog.empty:
                st.warning(
                    "No reviewed Climate.OneBuilding station catalog is available "
                    "in this release."
                )
            else:
                st.caption(catalog_runtime_summary(catalog))
                c1, c2, c3 = st.columns([2, 1, 1])
                search_text = c1.text_input(
                    "Station search", value="", key="comparison_station_search"
                )
                countries = sorted(
                    value
                    for value in catalog["country"].dropna().unique().tolist()
                    if str(value).strip()
                )
                datasets = sorted(
                    value
                    for value in catalog["dataset"].dropna().unique().tolist()
                    if str(value).strip()
                )
                selected_countries = c2.multiselect(
                    "Station countries",
                    countries,
                    default=[],
                    key="comparison_station_countries",
                )
                selected_datasets = c3.multiselect(
                    "Station datasets",
                    datasets,
                    default=[],
                    key="comparison_station_datasets",
                )
                filtered_catalog = filter_station_catalog(
                    catalog,
                    search_text=search_text,
                    countries=selected_countries if selected_countries else None,
                    datasets=selected_datasets if selected_datasets else None,
                )
                st.caption(f"Matching stations: {len(filtered_catalog):,}")
                if not filtered_catalog.empty:
                    station_options = legacy.station_options_from_catalog(
                        filtered_catalog, limit=10000
                    )
                    label = st.selectbox(
                        "Station",
                        list(station_options.keys()),
                        key="comparison_station_select",
                    )
                    selected = filtered_catalog[
                        filtered_catalog["station_id"] == station_options[label]
                    ].iloc[0]
                    if st.button(
                        "Download and add selected station", type="primary"
                    ):
                        try:
                            with st.spinner(
                                "Downloading and extracting station EPW..."
                            ):
                                result = download_station_epw(selected)
                            display = (
                                f"{selected.get('name', result.file_name)} — "
                                f"{selected.get('country', '')}"
                            )
                            source_text = station_provenance_text(
                                selected,
                                final_download_url=result.source_url,
                                archive_name=result.extracted_from,
                            )
                            legacy.add_to_comparison_basket(
                                result.file_name,
                                result.payload,
                                source_text,
                                display,
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Station download failed: {exc}")

    payloads = legacy.get_comparison_payloads()
    if payloads:
        st.markdown("#### Basket contents")
        for item in payloads:
            cols = st.columns([3, 4, 1])
            current_name = str(
                item.get("display_name", item.get("name", "Climate"))
            )
            new_name = cols[0].text_input(
                "Display name",
                value=current_name,
                key=f"rename_{item['climate_id']}",
            )
            item["display_name"] = new_name
            cols[1].caption(
                f"File: `{item.get('name')}`  \nSource: {item.get('source', '')}"
            )
            if cols[2].button("Remove", key=f"remove_{item['climate_id']}"):
                legacy.remove_from_comparison_basket(str(item["climate_id"]))
                st.rerun()
        legacy.save_comparison_payloads(payloads)


def _render_compare_climates(
    legacy: Any,
    active_file: Any | None,
    pressure_mode: str,
    custom_pressure_pa: float | None,
    active_pressure: float,
) -> None:
    """Render only the selected comparison family on the current rerun."""
    del active_pressure  # Retained in the public renderer contract.

    _install_safe_dataclass_equality(legacy)

    st.header("Compare climates")
    st.write(
        "Compare several EPW climates with overlay, small-multiple, ranked and "
        "difference-to-reference modes. All calculations use only EPW hourly "
        "data and EPW-derived indicators."
    )
    _render_comparison_basket_manager(legacy, active_file)

    payloads = legacy.get_comparison_payloads()
    if len(payloads) < 2:
        st.warning("Add at least two EPW climates to enable comparison charts.")
        return

    climates = legacy.load_comparison_datasets(
        payloads, pressure_mode, custom_pressure_pa
    )
    if len(climates) < 2:
        st.warning("At least two valid climates are required after loading.")
        return

    reference_name, display_mode, months, hours = legacy.comparison_controls(
        climates
    )
    climates = _filter_comparison_climates(
        legacy, climates, months=months, hours=hours
    )
    if any(climate.data.empty for climate in climates):
        st.warning(
            "The current comparison filters remove all data for at least one "
            "climate. Adjust the month or hour filter."
        )
        return

    section = st.selectbox(
        "Comparison section",
        COMPARISON_SECTIONS,
        index=0,
        key="comparison_analysis_section",
        help=(
            "Only the selected comparison family is calculated on this rerun. "
            "This avoids retaining nine chart families in memory simultaneously."
        ),
    )

    if section == "Summary":
        legacy.render_compare_summary(climates, reference_name)
    elif section == "Temperature":
        legacy.render_compare_temperature(climates, reference_name, display_mode)
    elif section == "Humidity / Psychrometrics":
        legacy.render_compare_humidity(climates, reference_name, display_mode)
    elif section == "Solar":
        legacy.render_compare_solar(climates, reference_name, display_mode)
    elif section == "Wind":
        legacy.render_compare_wind(climates, reference_name, display_mode)
    elif section == "Natural ventilation":
        legacy.render_compare_natural_ventilation(
            climates, reference_name, display_mode
        )
    elif section == "Passive / HVAC":
        legacy.render_compare_passive_hvac(
            climates, reference_name, display_mode
        )
    elif section == "Difference to reference":
        legacy.render_compare_difference(climates, reference_name)
    else:
        legacy.render_compare_data_quality(climates, reference_name)


def install_comparison_memory_hotfix(legacy: Any) -> None:
    """Install bounded-memory EPW comparison rendering into the app namespace."""
    _install_safe_dataclass_equality(legacy)

    if not hasattr(legacy, "_comparison_original_basket_manager"):
        legacy._comparison_original_basket_manager = (
            legacy.render_comparison_basket_manager
        )
    legacy.render_comparison_basket_manager = (
        lambda active_file: _render_comparison_basket_manager(
            legacy, active_file
        )
    )

    if not hasattr(legacy, "_comparison_original_renderer"):
        legacy._comparison_original_renderer = legacy.render_compare_climates
    legacy.render_compare_climates = (
        lambda active_file, pressure_mode, custom_pressure_pa, active_pressure:
        _render_compare_climates(
            legacy,
            active_file,
            pressure_mode,
            custom_pressure_pa,
            active_pressure,
        )
    )
