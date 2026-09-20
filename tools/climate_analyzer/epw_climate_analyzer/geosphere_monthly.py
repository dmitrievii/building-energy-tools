"""Native-monthly GeoSphere Austria integration for ``klima-v2-1m``.

The monthly climate resource is intentionally *not* coerced into the canonical
hourly engine.  It contains provider-derived monthly means, absolute extrema,
monthly sums, event-day counts and other climatological statistics whose
semantics would be damaged by pretending that every row is an hourly state.

The transport remains strict and source-attributed:
* selectable physical parameters come from the live GeoSphere metadata;
* quality flags remain opt-in;
* requests are planned on calendar months rather than fixed 30-day intervals;
* only completely empty outer rows are trimmed; one early valid variable keeps
  the corresponding month even when another selected variable starts later;
* the active dataset keeps provider parameter names and units so the full
  monthly vocabulary remains available to the dedicated monthly explorer.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode

import pandas as pd

from . import geosphere
from .climate_model import (
    CanonicalClimateDataset,
    ClimateLocation,
    ClimateProvenance,
    ClimateTemporalMetadata,
    build_canonical_dataset,
)


MONTHLY_RESOURCE_ID = "klima-v2-1m"
MONTHLY_NOMINAL_INTERVAL_MINUTES = 30 * 24 * 60
MONTHLY_DOI = "https://doi.org/10.60669/923n-p390"
MONTHLY_DATASET_PAGE = "https://data.hub.geosphere.at/en/dataset/klima-v2-1m"
MONTH_LABELS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Faithful English summary of the official GeoSphere Austria dataset description.
# Keep this as a paraphrase with a direct source link rather than duplicating the
# complete portal text in the application.
MONTHLY_OFFICIAL_CONTEXT_EN = (
    "GeoSphere Austria documents this resource as a monthly climatological station dataset with some records reaching "
    "back into the 18th century; temperature observations from Kremsmünster are given as an example from 1767. Monthly "
    "values include means at the historical climate-observation times as well as, depending on the parameter, whole-month "
    "means, absolute minima/maxima, monthly totals and statistical counts of meteorological phenomena. The observation "
    "times changed historically (7/14/21 MOZ until 1971; 7/14/19 MOZ from 1971 to 2003; 7/14/19 MEZ since 2003). Long "
    "manual records and modern automatic stations coexist, so availability is parameter- and station-specific. Quality "
    "status is published in matching *_flag fields. The archived dataset is refreshed every 10 minutes and retrospective "
    "changes may occur after quality verification."
)

MONTHLY_TEMPERATURE_COLORSCALE = [
    [0.00, "#172554"],
    [0.18, "#1d4ed8"],
    [0.36, "#60a5fa"],
    [0.52, "#22c55e"],
    [0.68, "#fde047"],
    [0.84, "#f97316"],
    [1.00, "#b91c1c"],
]


def ensure_monthly_resource_registered() -> None:
    """Register the monthly resource without forcing it into canonical field specs."""
    if MONTHLY_RESOURCE_ID in geosphere.GEOSPHERE_RESOURCES:
        return
    geosphere.GEOSPHERE_RESOURCES[MONTHLY_RESOURCE_ID] = geosphere.GeoSphereResourceSpec(
        resource_id=MONTHLY_RESOURCE_ID,
        label="GeoSphere climate station data — 1 month (long-term climatology)",
        # The base dataclass still requires an integer cadence.  The monthly
        # engine never uses this value for stepping; all planning below is by
        # calendar month.  The nominal value exists only for shared provenance.
        native_interval_minutes=MONTHLY_NOMINAL_INTERVAL_MINUTES,
        doi=MONTHLY_DOI,
        dataset_page=MONTHLY_DATASET_PAGE,
        field_specs=(),
        interval_semantics="provider-derived monthly climatological statistic",
    )


def monthly_parameter_mapping(metadata: Mapping[str, Any]) -> dict[str, geosphere.ProviderFieldSpec]:
    """Expose every live numeric/coded physical monthly parameter except flags.

    ``canonical_name`` deliberately equals the provider name.  These proxy specs
    exist only so the mature station-selection table can be reused; no claim is
    made that a provider monthly statistic is an hourly canonical variable.
    """
    parameters = geosphere.parse_parameters(metadata)
    result: dict[str, geosphere.ProviderFieldSpec] = {}
    for name, parameter in parameters.items():
        if str(name).endswith("_flag"):
            continue
        unit = str(parameter.unit or "").strip()
        result[name] = geosphere.ProviderFieldSpec(
            provider_name=name,
            canonical_name=name,
            expected_units=(unit,),
            scale=1.0,
            description=parameter.long_name or parameter.description or name,
            interval_semantics="provider-defined monthly statistic",
        )
    if not result:
        raise ValueError("GeoSphere monthly metadata expose no physical parameters.")
    return result


def monthly_metadata_bundle(metadata: Mapping[str, Any]) -> tuple:
    """Return the bundle shape expected by the mature GeoSphere station UI."""
    supported = monthly_parameter_mapping(metadata)
    stations = geosphere.parse_stations(metadata)
    return (
        dict(metadata),
        supported,
        stations,
        geosphere.station_catalog(metadata),
        {},  # monthly metadata do not provide reliable per-parameter station validity windows
        geosphere.parse_parameters(metadata),
    )


def _month_ordinal(value: pd.Timestamp) -> int:
    stamp = pd.Timestamp(value)
    return int(stamp.year) * 12 + int(stamp.month) - 1


def month_count(start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Return inclusive calendar-month count for an arbitrary timestamp range."""
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if end_ts < start_ts:
        raise ValueError("GeoSphere monthly request end must not be earlier than start.")
    return _month_ordinal(end_ts) - _month_ordinal(start_ts) + 1


def _month_start(value: pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    tz = stamp.tz
    return pd.Timestamp(year=int(stamp.year), month=int(stamp.month), day=1, tz=tz)


def _add_months(value: pd.Timestamp, months: int) -> pd.Timestamp:
    start = _month_start(value)
    ordinal = _month_ordinal(start) + int(months)
    year, month0 = divmod(ordinal, 12)
    return pd.Timestamp(year=year, month=month0 + 1, day=1, tz=start.tz)


def _format_utc_query_time(value: pd.Timestamp) -> str:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp.strftime("%Y-%m-%dT%H:%M")


def estimate_monthly_datapoints(
    start: pd.Timestamp,
    end: pd.Timestamp,
    parameter_count: int,
    station_count: int = 1,
) -> int:
    if int(parameter_count) <= 0 or int(station_count) <= 0:
        raise ValueError("GeoSphere monthly requests require at least one parameter and one station.")
    return month_count(pd.Timestamp(start), pd.Timestamp(end)) * int(parameter_count) * int(station_count)


def _validate_monthly_parameter_names(
    metadata: Mapping[str, Any], provider_parameters: Iterable[str]
) -> tuple[str, ...]:
    available = geosphere.parse_parameters(metadata)
    parameters = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))
    if not parameters:
        raise ValueError("At least one GeoSphere monthly parameter is required.")
    unknown = sorted(name for name in parameters if name not in available)
    if unknown:
        raise ValueError("GeoSphere monthly metadata do not expose: " + ", ".join(unknown))
    return parameters


def selected_monthly_query_parameters(
    metadata: Mapping[str, Any],
    provider_parameters: Iterable[str],
    *,
    selected_flag_names: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return physical fields plus explicitly selected matching quality flags."""
    physical = _validate_monthly_parameter_names(metadata, provider_parameters)
    available = geosphere.parse_parameters(metadata)
    selected_flags = {str(value).strip() for value in selected_flag_names if str(value).strip()}
    flags: list[str] = []
    for name in physical:
        flag = f"{name}_flag"
        if flag in selected_flags and flag in available:
            flag_meta = available[flag]
            if str(flag_meta.unit).strip().lower() != "code":
                raise ValueError(f"GeoSphere monthly quality flag '{flag}' no longer has unit 'code'.")
            flags.append(flag)
    return physical + tuple(flags)


def plan_monthly_queries(
    station_id: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    provider_parameters: Iterable[str],
    *,
    max_datapoints: int = geosphere.DEFAULT_BATCH_DATAPOINTS,
) -> list[dict[str, str]]:
    """Split one monthly request on calendar-month boundaries."""
    station = str(station_id).strip()
    if not station:
        raise ValueError("GeoSphere station_id must not be empty.")
    parameters = tuple(dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()))
    if not parameters:
        raise ValueError("At least one GeoSphere monthly parameter is required.")
    if int(max_datapoints) <= 0 or int(max_datapoints) > geosphere.MAX_REQUEST_DATAPOINTS:
        raise ValueError("Invalid GeoSphere monthly batch datapoint limit.")
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if end_ts < start_ts:
        raise ValueError("GeoSphere monthly request end must not be earlier than start.")

    months_per_batch = int(max_datapoints) // len(parameters)
    if months_per_batch < 1:
        raise ValueError("GeoSphere monthly batch datapoint limit is too small for the selected parameters.")

    first_month = _month_start(start_ts)
    last_ordinal = _month_ordinal(end_ts)
    cursor = first_month
    queries: list[dict[str, str]] = []
    while _month_ordinal(cursor) <= last_ordinal:
        remaining = last_ordinal - _month_ordinal(cursor) + 1
        span = min(months_per_batch, remaining)
        next_start = _add_months(cursor, span)
        batch_end = min(end_ts, next_start - pd.Timedelta(minutes=1))
        query = {
            "parameters": ",".join(parameters),
            "station_ids": station,
            "start": _format_utc_query_time(cursor),
            "end": _format_utc_query_time(batch_end),
        }
        if estimate_monthly_datapoints(cursor, batch_end, len(parameters), 1) > int(max_datapoints):
            raise RuntimeError("Internal GeoSphere monthly planner exceeded its datapoint limit.")
        queries.append(query)
        cursor = next_start
    return queries


def _emit_progress(
    callback: Callable[[Mapping[str, object]], None] | None,
    *,
    event: str,
    completed: int,
    total: int,
    batch_number: int,
    query: Mapping[str, str],
    attempt: int | None = None,
) -> None:
    if callback is None:
        return
    payload: dict[str, object] = {
        "event": event,
        "completed_batches": int(completed),
        "total_batches": int(total),
        "batch_number": int(batch_number),
        "start": str(query.get("start", "")),
        "end": str(query.get("end", "")),
    }
    if attempt is not None:
        payload["attempt"] = int(attempt)
    try:
        callback(payload)
    except Exception:
        pass


def fetch_monthly_provider_frame(
    *,
    station_id: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    provider_parameters: Iterable[str],
    metadata: Mapping[str, Any],
    timeout_s: int = geosphere.DEFAULT_TIMEOUT_SECONDS,
    progress_callback: Callable[[Mapping[str, object]], None] | None = None,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Fetch provider-native monthly rows with bounded calendar-month batches."""
    parameters = _validate_monthly_parameter_names(metadata, provider_parameters)
    queries = plan_monthly_queries(station_id, start, end, parameters)
    frames: list[pd.DataFrame] = []
    references: list[str] = []
    endpoint = geosphere.resource_spec(MONTHLY_RESOURCE_ID).endpoint
    total = len(queries)

    for batch_number, query in enumerate(queries, start=1):
        _emit_progress(progress_callback, event="batch_start", completed=batch_number - 1, total=total, batch_number=batch_number, query=query)
        payload = None
        last_error: BaseException | None = None
        for attempt in range(1, geosphere.MAX_TRANSIENT_ATTEMPTS + 1):
            try:
                payload = geosphere._bounded_get_json(endpoint, params=query, timeout_s=timeout_s)
                break
            except Exception as exc:  # provider/network boundary
                last_error = exc
                if not geosphere._is_transient_provider_error(exc) or attempt >= geosphere.MAX_TRANSIENT_ATTEMPTS:
                    raise
                _emit_progress(progress_callback, event="retry", completed=batch_number - 1, total=total, batch_number=batch_number, query=query, attempt=attempt + 1)
                time.sleep(geosphere.RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
        if payload is None:
            raise RuntimeError("GeoSphere monthly provider request failed.") from last_error
        frames.append(geosphere.parse_station_data_response(payload, station_id, parameters))
        references.append(f"{endpoint}?{urlencode(query)}")
        _emit_progress(progress_callback, event="batch_complete", completed=batch_number, total=total, batch_number=batch_number, query=query)

    combined = pd.concat(frames, axis=0).sort_index(kind="mergesort")
    if combined.empty:
        raise ValueError("GeoSphere monthly resource returned no timestamps for the selected interval.")
    if combined.index.has_duplicates:
        raise ValueError("GeoSphere monthly batched response contains duplicate timestamps.")
    _emit_progress(progress_callback, event="load_complete", completed=total, total=total, batch_number=total, query=queries[-1])
    return combined, tuple(references)


def _monthly_quality_attrs(metadata: Mapping[str, Any], physical_parameters: Iterable[str]) -> tuple[dict, dict]:
    codebooks: dict[str, dict[int, str]] = {}
    labels: dict[str, str] = {}
    parsed = geosphere.parse_parameters(metadata)
    for provider in physical_parameters:
        codebook = geosphere.quality_flag_codebook(metadata, provider)
        if codebook:
            codebooks[str(provider)] = codebook
            flag = parsed.get(f"{provider}_flag")
            labels[str(provider)] = flag.long_name if flag else str(provider)
    return codebooks, labels


def trim_monthly_empty_edges(data: pd.DataFrame, physical_parameters: Iterable[str]) -> pd.DataFrame:
    """Trim only outer months where every selected physical parameter is null."""
    columns = [name for name in physical_parameters if name in data.columns]
    if not columns:
        return data
    observed = data[columns].notna().any(axis=1)
    if not bool(observed.any()):
        raise ValueError("GeoSphere returned no numeric monthly observations for the selected physical parameters.")
    positions = observed.to_numpy().nonzero()[0]
    first, last = int(positions[0]), int(positions[-1])
    attrs = dict(data.attrs)
    out = data.iloc[first : last + 1].copy()
    out.attrs.update(attrs)
    out.attrs["canonical_measured_envelope_start"] = pd.Timestamp(out.index.min()).isoformat()
    out.attrs["canonical_measured_envelope_end"] = pd.Timestamp(out.index.max()).isoformat()
    out.attrs["canonical_trimmed_empty_edge_rows"] = int(first + (len(data) - last - 1))
    return out


def build_monthly_dataset(
    *,
    station: geosphere.GeoSphereStation,
    provider_frame: pd.DataFrame,
    metadata: Mapping[str, Any],
    physical_parameters: Iterable[str],
    request_references: Iterable[str] = (),
    requested_start: pd.Timestamp | None = None,
    requested_end: pd.Timestamp | None = None,
) -> CanonicalClimateDataset:
    """Build an active provider-native monthly dataset without semantic coercion."""
    physical = tuple(dict.fromkeys(str(value) for value in physical_parameters))
    parsed = geosphere.parse_parameters(metadata)
    frame = pd.DataFrame(index=provider_frame.index.copy())
    for name in physical:
        if name in provider_frame.columns:
            frame[name] = pd.to_numeric(provider_frame[name], errors="coerce")
        flag = f"{name}_flag"
        if flag in provider_frame.columns:
            frame[geosphere.quality_flag_column(name)] = pd.to_numeric(provider_frame[flag], errors="coerce")

    parameter_meta = {
        name: {
            "long_name": parsed[name].long_name if name in parsed else name,
            "unit": parsed[name].unit if name in parsed else "",
            "description": parsed[name].description if name in parsed else "",
        }
        for name in physical
    }
    codebooks, flag_labels = _monthly_quality_attrs(metadata, physical)
    frame.attrs.update(
        {
            "geosphere_resource_id": MONTHLY_RESOURCE_ID,
            "geosphere_temporal_resolution": "monthly",
            "geosphere_selected_physical_parameters": physical,
            "geosphere_parameter_metadata": parameter_meta,
            geosphere.QUALITY_CODEBOOK_ATTR: codebooks,
            geosphere.QUALITY_LABEL_ATTR: flag_labels,
            "canonical_frame_role": "native-monthly",
            "canonical_native_resolution": "monthly",
            "canonical_analysis_resolution": "monthly",
        }
    )
    if requested_start is not None:
        frame.attrs["canonical_requested_start"] = pd.Timestamp(requested_start).isoformat()
    if requested_end is not None:
        frame.attrs["canonical_requested_end"] = pd.Timestamp(requested_end).isoformat()
    frame = trim_monthly_empty_edges(frame, physical)

    years = tuple(sorted({int(value) for value in pd.DatetimeIndex(frame.index).year}))
    temporal = ClimateTemporalMetadata(
        native_interval_minutes=MONTHLY_NOMINAL_INTERVAL_MINUTES,
        calendar_mode="historical",
        timezone_name="UTC",
        interval_semantics="unknown",
        source_years=years,
    )
    location = ClimateLocation(
        latitude=station.latitude,
        longitude=station.longitude,
        elevation_m=station.elevation_m,
        city=station.name,
        state=station.state,
        country="Austria",
        station_id=station.station_id,
    )
    references = tuple(str(value) for value in request_references if str(value).strip())
    provenance = ClimateProvenance(
        provider="GeoSphere Austria",
        dataset="klima-v2-1m — quality-checked monthly station data for Austria",
        source_format="Dataset API JSON",
        source_name=f"GeoSphere station {station.station_id} ({station.name})",
        source_reference="\n".join(references) if references else MONTHLY_DATASET_PAGE,
        provider_station_id=station.station_id,
        retrieval_time_utc=datetime.now(timezone.utc).isoformat(),
        notes=(
            f"License: CC BY 4.0 ({geosphere.GEOSPHERE_LICENSE})",
            f"Dataset DOI: {MONTHLY_DOI}",
            "Monthly provider statistics are retained in their native published semantics; they are not upsampled to hourly data.",
            "Parameter availability is station- and parameter-specific; station validity is not treated as per-variable coverage.",
        ),
    )
    return build_canonical_dataset(
        climate_id=f"geosphere:{MONTHLY_RESOURCE_ID}:{station.station_id}",
        display_name=f"{station.name} — GeoSphere monthly",
        data=frame,
        location=location,
        temporal=temporal,
        provenance=provenance,
    )


def fetch_monthly_dataset(
    *,
    station: geosphere.GeoSphereStation,
    start: pd.Timestamp,
    end: pd.Timestamp,
    metadata: Mapping[str, Any],
    provider_parameters: Iterable[str],
    selected_flag_names: Iterable[str] = (),
    timeout_s: int = geosphere.DEFAULT_TIMEOUT_SECONDS,
    progress_callback: Callable[[Mapping[str, object]], None] | None = None,
) -> CanonicalClimateDataset:
    physical = _validate_monthly_parameter_names(metadata, provider_parameters)
    query_parameters = selected_monthly_query_parameters(
        metadata,
        physical,
        selected_flag_names=selected_flag_names,
    )
    provider_frame, references = fetch_monthly_provider_frame(
        station_id=station.station_id,
        start=start,
        end=end,
        provider_parameters=query_parameters,
        metadata=metadata,
        timeout_s=timeout_s,
        progress_callback=progress_callback,
    )
    return build_monthly_dataset(
        station=station,
        provider_frame=provider_frame,
        metadata=metadata,
        physical_parameters=physical,
        request_references=references,
        requested_start=start,
        requested_end=end,
    )


def monthly_coverage_table(data: pd.DataFrame) -> pd.DataFrame:
    """Return independent per-variable real coverage; one field never masks another."""
    metadata = data.attrs.get("geosphere_parameter_metadata", {})
    physical = data.attrs.get("geosphere_selected_physical_parameters", ())
    rows: list[dict[str, object]] = []
    total = max(1, len(data))
    for name in physical:
        if name not in data.columns:
            continue
        numeric = pd.to_numeric(data[name], errors="coerce")
        valid = numeric.notna()
        info = metadata.get(name, {}) if isinstance(metadata, Mapping) else {}
        rows.append(
            {
                "Variable": info.get("long_name") or name,
                "Provider": name,
                "Unit": info.get("unit") or "",
                "First available": pd.Timestamp(data.index[valid][0]).strftime("%Y-%m") if bool(valid.any()) else "",
                "Last available": pd.Timestamp(data.index[valid][-1]).strftime("%Y-%m") if bool(valid.any()) else "",
                "Available months": int(valid.sum()),
                "Rows": int(len(data)),
                "Coverage [%]": round(float(valid.sum()) / total * 100.0, 1),
            }
        )
    return pd.DataFrame(rows)


def _is_temperature_parameter(name: str, unit: str) -> bool:
    normalized = str(unit).strip().lower().replace("℃", "°c")
    if normalized in {"°c", "c", "degc"}:
        return True
    return str(name).startswith(("tl", "tb", "ts", "tp_", "gras", "bet"))


def render_monthly_analysis(legacy: Any, dataset: CanonicalClimateDataset) -> None:
    """Render analyses that are semantically valid for native monthly statistics."""
    import plotly.express as px
    import plotly.graph_objects as go

    st = legacy.st
    pages = ("Overview", "Monthly Explorer", "Coverage & Quality", "Climate File Source")
    if legacy.NAVIGATION_KEY not in st.session_state or st.session_state[legacy.NAVIGATION_KEY] not in pages:
        st.session_state[legacy.NAVIGATION_KEY] = "Overview"

    st.sidebar.markdown("### Explore")
    page = st.sidebar.radio(
        "Analysis section",
        pages,
        key=legacy.NAVIGATION_KEY,
        label_visibility="collapsed",
    )
    if page == "Climate File Source":
        legacy.render_climate_file_source()
        return

    data = dataset.data.copy()
    attrs = dict(dataset.data.attrs)
    data.attrs.update(attrs)
    index = pd.DatetimeIndex(data.index)
    years = sorted({int(value) for value in index.year})
    if len(years) > 1:
        year_range = st.sidebar.slider(
            "Years",
            min_value=int(years[0]),
            max_value=int(years[-1]),
            value=(int(years[0]), int(years[-1])),
            key="monthly_year_range",
        )
        data = data.loc[(index.year >= int(year_range[0])) & (index.year <= int(year_range[1]))].copy()
        data.attrs.update(attrs)
    selected_month_labels = st.sidebar.multiselect(
        "Months",
        list(MONTH_LABELS),
        default=list(MONTH_LABELS),
        key="monthly_month_filter",
    )
    selected_months = {MONTH_LABELS.index(value) + 1 for value in selected_month_labels}
    if selected_months:
        data = data.loc[pd.DatetimeIndex(data.index).month.isin(selected_months)].copy()
        data.attrs.update(attrs)
    if data.empty:
        st.warning("The monthly filters remove all loaded rows.")
        return

    st.session_state["_active_filtered_export_df"] = data
    st.sidebar.markdown("### Current climate")
    st.sidebar.write(f"**{dataset.location.city}, {dataset.location.country}**")
    st.sidebar.caption("GeoSphere Austria · native monthly climatological statistics")
    st.sidebar.write(f"Monthly rows in current view: {len(data):,}")
    with st.sidebar.expander("Data provenance", expanded=False):
        st.caption(dataset.provenance.dataset)
        st.caption(f"Dataset DOI: {MONTHLY_DOI}")
        st.caption("Native resolution: monthly · timezone UTC")
        st.caption("No hourly interpolation or canonical-hourly normalization is applied.")

    physical = tuple(name for name in attrs.get("geosphere_selected_physical_parameters", ()) if name in data.columns)
    metadata = attrs.get("geosphere_parameter_metadata", {})

    def label(name: str) -> str:
        info = metadata.get(name, {}) if isinstance(metadata, Mapping) else {}
        long_name = str(info.get("long_name") or name)
        unit = str(info.get("unit") or "")
        return f"{long_name} [{unit}] — {name}" if unit else f"{long_name} — {name}"

    if page == "Overview":
        st.header("GeoSphere monthly climate")
        st.info(MONTHLY_OFFICIAL_CONTEXT_EN)
        st.caption(f"Official source: GeoSphere Austria Station Data-v2 (1 m) · {MONTHLY_DOI} · {MONTHLY_DATASET_PAGE}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("First loaded month", pd.Timestamp(data.index.min()).strftime("%Y-%m"))
        c2.metric("Last loaded month", pd.Timestamp(data.index.max()).strftime("%Y-%m"))
        c3.metric("Loaded monthly rows", f"{len(data):,}")
        c4.metric("Selected physical fields", len(physical))
        st.subheader("Actual per-variable coverage")
        st.caption(
            "Coverage is calculated independently for each loaded parameter. An early valid sunshine series therefore remains visible even if temperature begins later."
        )
        st.dataframe(monthly_coverage_table(data), hide_index=True, use_container_width=True)
        return

    if page == "Coverage & Quality":
        st.header("Monthly coverage and quality")
        coverage = monthly_coverage_table(data)
        st.dataframe(coverage, hide_index=True, use_container_width=True)
        rows = []
        for name in physical:
            info = metadata.get(name, {}) if isinstance(metadata, Mapping) else {}
            rows.append(
                {
                    "Provider": name,
                    "Variable": info.get("long_name") or name,
                    "Unit": info.get("unit") or "",
                    "Description": info.get("description") or "",
                }
            )
        st.subheader("Loaded parameter metadata")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        flag_columns = [column for column in data.columns if str(column).startswith(geosphere.QUALITY_FLAG_COLUMN_PREFIX)]
        if not flag_columns:
            st.info("No quality flags were loaded. Flag transfer is opt-in in the source table.")
            return
        codebooks = attrs.get(geosphere.QUALITY_CODEBOOK_ATTR, {})
        st.subheader("Loaded quality flags")
        quality_rows: list[dict[str, object]] = []
        for column in flag_columns:
            provider = str(column).removeprefix(geosphere.QUALITY_FLAG_COLUMN_PREFIX)
            values = pd.to_numeric(data[column], errors="coerce")
            counts = values.value_counts(dropna=False)
            codebook = codebooks.get(provider, {}) if isinstance(codebooks, Mapping) else {}
            for code, count in counts.items():
                if pd.isna(code):
                    code_label = "missing"
                else:
                    code_int = int(code)
                    code_label = str(codebook.get(code_int, code_int)) if isinstance(codebook, Mapping) else str(code_int)
                quality_rows.append({"Provider": provider, "Quality state": code_label, "Months": int(count)})
        st.dataframe(pd.DataFrame(quality_rows), hide_index=True, use_container_width=True)
        return

    st.header("Monthly variable explorer")
    if not physical:
        st.info("No physical monthly parameters are loaded.")
        return
    variable = st.selectbox("Variable", list(physical), format_func=label, key="monthly_explorer_variable")
    info = metadata.get(variable, {}) if isinstance(metadata, Mapping) else {}
    unit = str(info.get("unit") or "")
    values = pd.to_numeric(data[variable], errors="coerce")
    valid = values.notna()
    if not bool(valid.any()):
        st.info("The selected parameter has no numeric observations in the active monthly filter.")
        return
    chart_type = st.radio(
        "Chart type",
        ["Time series", "Calendar-month profile", "Year × month heat map", "Distribution"],
        horizontal=True,
        key="monthly_explorer_chart",
    )

    if chart_type == "Time series":
        fig = go.Figure(
            go.Scatter(
                x=data.index,
                y=values,
                mode="lines+markers",
                name=label(variable),
                hovertemplate="%{x|%Y-%m}<br>%{y:.3g} " + unit + "<extra></extra>",
            )
        )
        fig.update_layout(template="plotly_white", title=label(variable), xaxis_title="Month", yaxis_title=unit or variable)
        legacy.render_plot(fig, "Native monthly values from GeoSphere Austria; no temporal interpolation is applied.")
        return

    temp = pd.DataFrame({"value": values.to_numpy()}, index=data.index)
    temp["year"] = pd.DatetimeIndex(temp.index).year.astype(int)
    temp["month"] = pd.DatetimeIndex(temp.index).month.astype(int)
    temp = temp.dropna(subset=["value"])

    if chart_type == "Calendar-month profile":
        grouped = temp.groupby("month")["value"]
        summary = grouped.agg(mean="mean", min="min", max="max").reindex(range(1, 13))
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=list(MONTH_LABELS), y=summary["max"], mode="lines+markers", name="Maximum"))
        fig.add_trace(go.Scatter(x=list(MONTH_LABELS), y=summary["min"], mode="lines+markers", name="Minimum", fill="tonexty"))
        fig.add_trace(go.Scatter(x=list(MONTH_LABELS), y=summary["mean"], mode="lines+markers", name="Mean"))
        fig.update_layout(template="plotly_white", title=f"Calendar-month profile · {label(variable)}", xaxis_title="Calendar month", yaxis_title=unit or variable)
        legacy.render_plot(fig, "Each calendar month summarizes the loaded real monthly provider values across the selected years.")
        return

    if chart_type == "Year × month heat map":
        matrix = temp.pivot_table(index="year", columns="month", values="value", aggfunc="mean").reindex(columns=range(1, 13))
        colorscale = MONTHLY_TEMPERATURE_COLORSCALE if _is_temperature_parameter(variable, unit) else "Viridis"
        fig = px.imshow(
            matrix,
            aspect="auto",
            color_continuous_scale=colorscale,
            labels={"x": "Month", "y": "Year", "color": unit or variable},
            title=f"Year × month · {label(variable)}",
        )
        fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=list(MONTH_LABELS))
        years_present = [int(value) for value in matrix.index]
        fig.update_yaxes(tickmode="array", tickvals=years_present, ticktext=[str(value) for value in years_present])
        fig.update_layout(template="plotly_white")
        legacy.render_plot(fig, "One cell is one published monthly statistic for the selected parameter and source year/month.")
        return

    plot = pd.DataFrame({"value": values[valid].to_numpy()})
    fig = px.histogram(plot, x="value", nbins=min(60, max(10, int(math.sqrt(len(plot)) * 2))), title=f"Distribution · {label(variable)}")
    fig.update_layout(template="plotly_white", xaxis_title=unit or variable, yaxis_title="Months")
    legacy.render_plot(fig, "Distribution of the loaded monthly provider statistics; each non-missing month contributes one observation.")
