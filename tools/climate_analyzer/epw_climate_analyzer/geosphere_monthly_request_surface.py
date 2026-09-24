"""Fragment-isolated request surface for GeoSphere native-monthly data.

The mature station browser/map remains the authoritative station-selection UI.
Once that browser reaches the first request date widget, this module terminates
only the legacy request tail and renders one monthly request fragment containing
Parameter set, dates, measured variables and the explicit Load action.

The boundary is intentionally monthly-only. 10-minute and hourly resources keep
the already validated mature request path while the higher-cost native-monthly
route is migrated without fragmenting station search/map state.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha1
from typing import Any, Callable

import pandas as pd
from streamlit.delta_generator import DeltaGenerator

from .geosphere_monthly import (
    MONTHLY_DATASET_PAGE,
    MONTHLY_DOI,
    MONTHLY_OFFICIAL_CONTEXT_EN,
    MONTHLY_RESOURCE_ID,
)
from .geosphere_request_form import GeoSphereRequestForm
from .source_parity_longterm_hotfix import QUALITY_FLAG_SELECTION_KEY
from .source_parity_monthly_selection_state import (
    _FLAG_STATE_KEY,
    _LAST_VIEW_KEY,
    _PARAMETER_SET_EPOCH_KEY,
    _PARAMETER_SET_KEY,
    _PARAMETER_SET_RESET_PENDING_KEY,
    _SELECTION_STATE_KEY,
    _editor_key,
    _parameter_set_epoch,
    _provider_state,
    _visible_catalogue,
    reset_monthly_parameter_set_state,
)

_START_KEY = "geosphere_start_date"
_END_KEY = "geosphere_end_date"
_STATION_KEY = "geosphere_selected_station_id"
_LOAD_LABEL = "Load measured GeoSphere interval"
_EMPTY_WARNING = "Select at least one measured GeoSphere variable to load."
_FORM_CAPTION = "Variable choices are staged locally. Checking or unchecking rows does not reload this page and does not request GeoSphere data."
_PARAMETER_SET_OPTIONS = (
    "Core variables",
    "Core + additional statistics",
    "All provider parameters",
)
_PARAMETER_SET_HELP = (
    "Core variables are canonical/building-climate quantities. Additional statistics are provider-published monthly "
    "counts, extrema and indicators. All provider parameters also shows fields without normalized Seasonal/Annual "
    "semantics. Changing Parameter set clears the current Load and quality-flag selections."
)


class _MonthlyRequestBoundary(RuntimeError):
    """Internal control-flow sentinel raised after the station browser is rendered."""


def _as_date(value: object) -> date | None:
    try:
        stamp = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(stamp):
        return None
    return stamp.date()


def _clamp(value: date | None, low: date, high: date, fallback: date) -> date:
    current = value or fallback
    if current < low:
        return low
    if current > high:
        return high
    return current


def _filtered_station_ids(catalog: Any, stations: Any, st: Any) -> tuple[str, ...]:
    """Reproduce the mature browser's visible station order for fallback selection.

    The mature source shell displays ``option_ids[0]`` as the selected station on
    a fresh session but historically did not persist that default into
    ``geosphere_selected_station_id``.  The monthly request fragment is rendered
    after that browser and needs the same effective station.  Reconstruct only
    this fallback path from the already-cached metadata; explicit map/list
    selections continue to own the committed station key.
    """
    if not isinstance(catalog, pd.DataFrame) or catalog.empty or "station_id" not in catalog.columns:
        return ()

    filtered = catalog.copy()
    search = str(st.session_state.get("geosphere_station_search", "") or "").strip()
    if search:
        needle = search.lower()
        masks = [filtered["station_id"].astype(str).str.lower().str.contains(needle, regex=False)]
        for column in ("name", "state"):
            if column in filtered.columns:
                masks.append(filtered[column].astype(str).str.lower().str.contains(needle, regex=False))
        mask = masks[0]
        for extra in masks[1:]:
            mask = mask | extra
        filtered = filtered.loc[mask]

    raw_states = st.session_state.get("geosphere_station_states", ())
    if isinstance(raw_states, (list, tuple, set)):
        selected_states = {str(value) for value in raw_states if str(value).strip()}
    else:
        selected_states = set()
    if selected_states and "state" in filtered.columns:
        filtered = filtered.loc[filtered["state"].astype(str).isin(selected_states)]

    station_ids = {str(item.station_id) for item in stations}
    return tuple(
        str(value)
        for value in filtered["station_id"].tolist()
        if str(value) in station_ids
    )


def _station_and_bundle(legacy: Any, st: Any):
    # The mature station browser has already requested this metadata earlier in
    # the same rerun.  Calling its cached accessor here therefore performs no
    # measurement request and lets us reconcile the browser's displayed default
    # station when the legacy key has not yet been persisted.
    metadata, supported, stations, catalog, capability_index, parameter_metadata = legacy.cached_geosphere_metadata_bundle()
    station_id = str(st.session_state.get(_STATION_KEY, "") or "")
    station_by_id = {str(item.station_id): item for item in stations}

    if station_id not in station_by_id:
        option_ids = _filtered_station_ids(catalog, stations, st)
        if not option_ids:
            return None
        station_id = option_ids[0]
        # This is the same station that the mature browser already displays as
        # selected. Persisting it closes the state gap without changing the
        # semantics of an explicit manual/map selection.
        st.session_state[_STATION_KEY] = station_id

    station = station_by_id.get(station_id)
    if station is None:
        return None
    return metadata, supported, station, capability_index, parameter_metadata


def _date_bounds(station: Any) -> tuple[date, date, date, date]:
    today = pd.Timestamp.now(tz="UTC").date()
    parsed_from = pd.to_datetime(getattr(station, "valid_from", None), errors="coerce")
    parsed_to = pd.to_datetime(getattr(station, "valid_to", None), errors="coerce")
    minimum = parsed_from.date() if pd.notna(parsed_from) else pd.Timestamp("1760-01-01").date()
    provider_max = parsed_to.date() if pd.notna(parsed_to) else today
    maximum = min(provider_max, today)
    if maximum < minimum:
        raise ValueError("The station validity interval does not overlap the available historical date range.")
    default_end = maximum
    default_start = max(minimum, (pd.Timestamp(default_end) - pd.DateOffset(years=5)).date())
    return minimum, maximum, default_start, default_end


def _base_variable_table(
    supported: dict[str, Any],
    capability_index: dict[str, Any],
    parameter_metadata: dict[str, Any],
    station_id: str,
) -> pd.DataFrame:
    station_capabilities = capability_index.get(station_id, {}) if isinstance(capability_index, dict) else {}
    rows: list[dict[str, object]] = []
    for name, spec in supported.items():
        if station_capabilities.get(name, "resource-supported") == "station-unavailable":
            continue
        parameter = parameter_metadata.get(name)
        rows.append(
            {
                "Selected": False,
                "Quality flag": False,
                "Measured variable": (
                    parameter.long_name
                    if parameter is not None and getattr(parameter, "long_name", None)
                    else getattr(spec, "description", None) or getattr(spec, "canonical_name", name)
                ),
                "Provider": str(name),
                "Unit": getattr(parameter, "unit", "") if parameter is not None else "",
                "Availability": (
                    "Station-confirmed"
                    if station_capabilities.get(name) == "station-confirmed"
                    else "Resource-supported"
                ),
                "Canonical field": getattr(spec, "canonical_name", name),
            }
        )
    return pd.DataFrame(rows)


def _selected_payload(edited: pd.DataFrame) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not isinstance(edited, pd.DataFrame) or not {"Selected", "Provider"}.issubset(edited.columns):
        return (), ()
    selected_mask = edited["Selected"].fillna(False).astype(bool)
    providers = tuple(
        dict.fromkeys(edited.loc[selected_mask, "Provider"].fillna("").astype(str).tolist())
    )
    flags: tuple[str, ...] = ()
    if "Quality flag" in edited.columns:
        flag_mask = selected_mask & edited["Quality flag"].fillna(False).astype(bool)
        flags = tuple(
            dict.fromkeys(
                f"{name}_flag"
                for name in edited.loc[flag_mask, "Provider"].fillna("").astype(str).tolist()
                if str(name).strip()
            )
        )
    return providers, flags


def _persist_provider_state(st: Any, edited: pd.DataFrame) -> tuple[tuple[str, ...], tuple[str, ...]]:
    providers, flags = _selected_payload(edited)
    selected_set = set(providers)
    flag_set = {value.removesuffix("_flag") for value in flags}
    all_providers = edited["Provider"].fillna("").astype(str).tolist() if "Provider" in edited.columns else []
    st.session_state[_SELECTION_STATE_KEY] = {
        provider: provider in selected_set for provider in all_providers if provider
    }
    st.session_state[_FLAG_STATE_KEY] = {
        provider: provider in flag_set for provider in all_providers if provider
    }
    st.session_state[QUALITY_FLAG_SELECTION_KEY] = {
        "resource_id": MONTHLY_RESOURCE_ID,
        "flags": flags,
    }
    return providers, flags


def install_monthly_request_surface(parity: Any) -> None:
    """Stop the monthly legacy tail at its first date widget and render a fragment."""
    previous = parity._render_geosphere_resource_selector
    st = parity.st
    fragment_factory = getattr(st, "fragment", None)

    def render_surface(legacy: Any) -> None:
        bundle = _station_and_bundle(legacy, st)
        if bundle is None:
            return
        metadata, supported, station, capability_index, parameter_metadata = bundle
        station_id = str(station.station_id)
        minimum, maximum, default_start, default_end = _date_bounds(station)
        request_form = GeoSphereRequestForm(st)

        current_view = str(st.session_state.get(_PARAMETER_SET_KEY, "Core variables"))
        if current_view not in _PARAMETER_SET_OPTIONS:
            current_view = "Core variables"
            st.session_state[_PARAMETER_SET_KEY] = current_view

        chosen_view = st.radio(
            "Parameter set",
            list(_PARAMETER_SET_OPTIONS),
            index=list(_PARAMETER_SET_OPTIONS).index(current_view),
            horizontal=True,
            key=_PARAMETER_SET_KEY,
            help=_PARAMETER_SET_HELP,
            on_change=lambda: reset_monthly_parameter_set_state(st),
        )
        chosen_view = str(chosen_view)
        st.session_state[_LAST_VIEW_KEY] = chosen_view

        base = _base_variable_table(supported, capability_index, parameter_metadata, station_id)
        if base.empty:
            st.warning("No supported GeoSphere variables are selectable for this station according to metadata.")
            return

        visible = _visible_catalogue(parity, base, chosen_view).reset_index(drop=True)
        if visible.empty:
            st.warning(
                f"No GeoSphere monthly parameters match the current `{chosen_view}` catalogue view. "
                "Choose `All provider parameters` to inspect the live provider catalogue."
            )
            return
        providers = visible["Provider"].fillna("").astype(str).tolist()
        selection_state = _provider_state(st, _SELECTION_STATE_KEY, visible, "Selected", default=False)
        flag_state = _provider_state(st, _FLAG_STATE_KEY, visible, "Quality flag", default=False)
        visible["Selected"] = [bool(selection_state.get(name, False)) for name in providers]
        visible["Quality flag"] = [bool(flag_state.get(name, False)) for name in providers]

        epoch = _parameter_set_epoch(st)
        editor_key = _editor_key(chosen_view, providers, epoch=epoch)
        form_signature = sha1(f"{MONTHLY_RESOURCE_ID}\0{station_id}\0{epoch}".encode("utf-8")).hexdigest()[:12]
        form_key = f"geosphere_monthly_request_form::{form_signature}"

        with st.expander("About this GeoSphere monthly dataset", expanded=False):
            st.write(MONTHLY_OFFICIAL_CONTEXT_EN)
            st.caption(
                f"Official source: GeoSphere Austria Station Data-v2 (1 m) · {MONTHLY_DOI} · {MONTHLY_DATASET_PAGE}"
            )

        start_existing = _clamp(_as_date(st.session_state.get(_START_KEY)), minimum, maximum, default_start)
        end_existing = _clamp(_as_date(st.session_state.get(_END_KEY)), minimum, maximum, default_end)
        if end_existing < start_existing:
            start_existing, end_existing = default_start, default_end

        with st.form(form_key, clear_on_submit=False):
            c1, c2 = st.columns(2)
            start_date = c1.date_input(
                "From date (UTC)", value=start_existing, min_value=minimum, max_value=maximum, key=_START_KEY
            )
            end_date = c2.date_input(
                "Through date (UTC)", value=end_existing, min_value=minimum, max_value=maximum, key=_END_KEY
            )
            st.markdown("#### Measured variables to load")
            st.caption(
                "Select the measured GeoSphere fields required for this load. Analysis pages are enabled only when the "
                "returned interval contains actual numeric observations."
            )

            config: dict[str, Any] = {
                "Selected": st.column_config.CheckboxColumn("Load", width="small"),
                "Quality flag": st.column_config.CheckboxColumn(
                    "Flag",
                    width="small",
                    help="Load the matching GeoSphere provider quality flag. Off by default.",
                ),
                "Measured variable": st.column_config.TextColumn("Variable", width="large"),
                "Unit": st.column_config.TextColumn("Unit", width="small"),
                "Availability": st.column_config.TextColumn("Metadata availability", width="medium"),
                "Category": st.column_config.TextColumn("Category", width="medium"),
                "Statistic": st.column_config.TextColumn("Statistic", width="medium"),
                "Notes": st.column_config.TextColumn("Interpretation", width="large"),
                "Role": st.column_config.TextColumn("Role", width="medium"),
                "Canonical field": None,
            }
            if chosen_view != "All provider parameters":
                config["Provider"] = None
                config["Original GeoSphere name"] = None
            else:
                config["Original GeoSphere name"] = st.column_config.TextColumn(
                    "Original GeoSphere name", width="large"
                )

            disabled = [
                "Measured variable",
                "Provider",
                "Unit",
                "Availability",
                "Canonical field",
                "Category",
                "Statistic",
                "Notes",
                "Role",
                "Original GeoSphere name",
            ]
            edited = st.data_editor(
                visible,
                hide_index=True,
                use_container_width=True,
                num_rows="fixed",
                disabled=disabled,
                column_config=config,
                key=editor_key,
            )
            st.caption(_FORM_CAPTION)
            st.caption(
                "Quality flags are optional and disabled by default. Station validity is station metadata, not "
                "per-variable coverage."
            )
            submitted = st.form_submit_button(
                _LOAD_LABEL,
                type="primary",
                help="Submit the current dates and variable selection and start the provider request.",
            )

        pending = st.session_state.get(_PARAMETER_SET_RESET_PENDING_KEY)
        if pending is not None:
            try:
                if int(pending) == int(epoch):
                    st.session_state.pop(_PARAMETER_SET_RESET_PENDING_KEY, None)
            except (TypeError, ValueError):
                st.session_state.pop(_PARAMETER_SET_RESET_PENDING_KEY, None)

        st.caption(f"Source: GeoSphere Austria `{MONTHLY_RESOURCE_ID}` · CC BY 4.0 · DOI {MONTHLY_DOI}")
        if not submitted:
            return

        providers_selected, _flags = _persist_provider_state(st, edited)
        request_form.capture_date(_START_KEY, start_date)
        request_form.capture_date(_END_KEY, end_date)
        request_form.capture_editor(edited)

        if not providers_selected:
            st.warning(_EMPTY_WARNING)
            return
        if end_date < start_date:
            st.error("GeoSphere end date must not be earlier than start date.")
            return

        committed = request_form.commit()
        if not committed.is_loadable:
            st.error("The GeoSphere request is incomplete and cannot be loaded.")
            return

        start_ts = pd.Timestamp(start_date, tz="UTC")
        end_ts = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(hours=23, minutes=59)
        query_parameters = legacy.provider_parameters_with_quality_flags(metadata, providers_selected)
        estimated = legacy.estimate_geosphere_datapoints(start_ts, end_ts, len(query_parameters), 1)
        batches = legacy.plan_geosphere_queries(station_id, start_ts, end_ts, query_parameters)
        selected_months = (int(end_date.year) - int(start_date.year)) * 12 + int(end_date.month) - int(start_date.month) + 1
        st.caption(
            f"Requested interval: {selected_months} calendar month(s), {len(providers_selected)} selected measured "
            f"variables plus {len(query_parameters) - len(providers_selected)} matching quality flag(s). "
            f"Estimated provider datapoints: {estimated:,}; bounded API batches: {len(batches)}."
        )

        progress_state = {"completed": 0, "total": max(1, len(batches))}
        progress_bar = st.progress(0.0, text=f"GeoSphere load — 0/{len(batches)} planned batch(es) complete")

        def update_progress(event: Any) -> None:
            total = max(1, int(event.get("total_batches", len(batches))))
            completed = min(total, max(0, int(event.get("completed_batches", 0))))
            progress_state["completed"] = completed
            progress_state["total"] = total
            progress_bar.progress(
                completed / total,
                text=f"GeoSphere load — {completed}/{total} planned batch(es) complete",
            )

        try:
            dataset = legacy.fetch_geosphere_station_dataset(
                station=station,
                start=start_ts,
                end=end_ts,
                metadata=metadata,
                canonical_variables=providers_selected,
                progress_callback=update_progress,
            )
            progress_bar.progress(
                1.0,
                text=f"GeoSphere load complete — {len(batches)}/{len(batches)} planned batch(es)",
            )
            legacy.set_active_canonical_climate(dataset)
            st.rerun()
        except Exception as exc:
            total = max(1, int(progress_state["total"]))
            completed = min(total, max(0, int(progress_state["completed"])))
            progress_bar.progress(
                completed / total,
                text=f"GeoSphere load stopped — {completed}/{total} planned batch(es) complete",
            )
            st.error(f"GeoSphere station-data load failed: {exc}")

    fragment_surface = fragment_factory(render_surface) if callable(fragment_factory) else render_surface

    def selector(legacy: Any, original: Callable) -> Any:
        real_date_input = DeltaGenerator.date_input
        boundary_reached = {"value": False}

        def date_input(self: DeltaGenerator, label: str, *args: Any, **kwargs: Any):
            key = str(kwargs.get("key") or "")
            if (
                str(st.session_state.get("geosphere_resource_id", "")) == MONTHLY_RESOURCE_ID
                and key == _START_KEY
            ):
                boundary_reached["value"] = True
                raise _MonthlyRequestBoundary()
            return real_date_input(self, label, *args, **kwargs)

        DeltaGenerator.date_input = date_input
        try:
            return previous(legacy, original)
        except _MonthlyRequestBoundary:
            pass
        finally:
            DeltaGenerator.date_input = real_date_input

        if boundary_reached["value"]:
            return fragment_surface(legacy)
        return None

    parity._render_geosphere_resource_selector = selector
