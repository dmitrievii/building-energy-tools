"""Runtime binding for the native ``klima-v2-1m`` GeoSphere resource."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

import pandas as pd

from . import geosphere
from .geosphere_monthly import (
    MONTHLY_DATASET_PAGE,
    MONTHLY_DOI,
    MONTHLY_NOMINAL_INTERVAL_MINUTES,
    MONTHLY_OFFICIAL_CONTEXT_EN,
    MONTHLY_RESOURCE_ID,
    ensure_monthly_resource_registered,
    estimate_monthly_datapoints,
    fetch_monthly_dataset,
    monthly_metadata_bundle,
    monthly_parameter_mapping,
    plan_monthly_queries,
    render_monthly_analysis,
    selected_monthly_query_parameters,
)
from .source_parity_longterm_hotfix import QUALITY_FLAG_SELECTION_KEY


def _selected_flag_names(st: Any) -> tuple[str, ...]:
    state = st.session_state.get(QUALITY_FLAG_SELECTION_KEY, {})
    if not isinstance(state, Mapping) or str(state.get("resource_id", "")) != MONTHLY_RESOURCE_ID:
        return ()
    values = state.get("flags", ())
    if not isinstance(values, (tuple, list, set)):
        return ()
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def install_monthly_resource(proxy: Any, parity: Any) -> None:
    """Add the monthly resource while preserving the stable source-selection shell."""
    if bool(getattr(proxy, "_GEOSPHERE_MONTHLY_RESOURCE_INSTALLED", False)):
        return

    ensure_monthly_resource_registered()
    st = parity.st

    original_cached_bundle = parity._cached_geosphere_resource_bundle
    original_supported_mapping = parity.supported_parameter_mapping
    original_provider_parameters = parity.provider_parameters_with_quality_flags
    original_estimate = parity.estimate_request_datapoints
    original_plan = parity.plan_data_queries
    original_fetch_dataset = parity.fetch_station_dataset

    @st.cache_data(show_spinner=False, ttl=18 * 60 * 60, max_entries=2)
    def cached_monthly_bundle() -> tuple:
        metadata = parity.fetch_metadata(resource_id=MONTHLY_RESOURCE_ID)
        return monthly_metadata_bundle(metadata)

    def cached_bundle(resource_id: str) -> tuple:
        if str(resource_id) == MONTHLY_RESOURCE_ID:
            return cached_monthly_bundle()
        return original_cached_bundle(resource_id)

    def supported_mapping(metadata: Mapping[str, Any], *, resource_id: str = geosphere.GEOSPHERE_RESOURCE_ID):
        if str(resource_id) == MONTHLY_RESOURCE_ID:
            return monthly_parameter_mapping(metadata)
        return original_supported_mapping(metadata, resource_id=resource_id)

    def provider_parameters(
        metadata: Mapping[str, Any],
        provider_parameters: Iterable[str],
        *,
        resource_id: str = geosphere.GEOSPHERE_RESOURCE_ID,
    ) -> tuple[str, ...]:
        if str(resource_id) == MONTHLY_RESOURCE_ID:
            return selected_monthly_query_parameters(
                metadata,
                provider_parameters,
                selected_flag_names=_selected_flag_names(st),
            )
        return original_provider_parameters(metadata, provider_parameters, resource_id=resource_id)

    def estimate(
        start: pd.Timestamp,
        end: pd.Timestamp,
        parameter_count: int,
        station_count: int = 1,
        *,
        resource_id: str = geosphere.GEOSPHERE_RESOURCE_ID,
    ) -> int:
        if str(resource_id) == MONTHLY_RESOURCE_ID:
            return estimate_monthly_datapoints(start, end, parameter_count, station_count)
        return original_estimate(start, end, parameter_count, station_count, resource_id=resource_id)

    def plan(
        station_id: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        provider_parameters: Iterable[str],
        *,
        max_datapoints: int = geosphere.DEFAULT_BATCH_DATAPOINTS,
        resource_id: str = geosphere.GEOSPHERE_RESOURCE_ID,
    ) -> list[dict[str, str]]:
        if str(resource_id) == MONTHLY_RESOURCE_ID:
            return plan_monthly_queries(
                station_id,
                start,
                end,
                provider_parameters,
                max_datapoints=max_datapoints,
            )
        return original_plan(
            station_id,
            start,
            end,
            provider_parameters,
            max_datapoints=max_datapoints,
            resource_id=resource_id,
        )

    def fetch_dataset(*, resource_id: str = geosphere.GEOSPHERE_RESOURCE_ID, **kwargs: Any):
        if str(resource_id) != MONTHLY_RESOURCE_ID:
            return original_fetch_dataset(resource_id=resource_id, **kwargs)
        metadata = kwargs.get("metadata")
        if not isinstance(metadata, Mapping):
            metadata = cached_monthly_bundle()[0]
        selected = kwargs.get("canonical_variables")
        if selected is None:
            raise ValueError("The monthly resource requires an explicit measured-parameter selection.")
        return fetch_monthly_dataset(
            station=kwargs["station"],
            start=kwargs["start"],
            end=kwargs["end"],
            metadata=metadata,
            provider_parameters=selected,
            selected_flag_names=_selected_flag_names(st),
            timeout_s=int(kwargs.get("timeout_s", geosphere.DEFAULT_TIMEOUT_SECONDS)),
            progress_callback=kwargs.get("progress_callback"),
        )

    parity._cached_geosphere_resource_bundle = cached_bundle
    parity.supported_parameter_mapping = supported_mapping
    parity.provider_parameters_with_quality_flags = provider_parameters
    parity.estimate_request_datapoints = estimate
    parity.plan_data_queries = plan
    parity.fetch_station_dataset = fetch_dataset

    # The app's dependency shim imports these geosphere helpers by name.  The
    # source-parity selector replaces the shim callables per selected resource,
    # so no module-scope dependency expansion is required here.

    previous_selector = parity._render_geosphere_resource_selector

    def selector_with_monthly_context(legacy: Any, original: Callable) -> None:
        real_selectbox = st.selectbox
        real_caption = st.caption
        real_info = st.info
        real_dataframe = st.dataframe
        real_data_editor = st.data_editor

        def selectbox(label: str, options: Any, *args: Any, **kwargs: Any):
            if label == "GeoSphere dataset":
                kwargs["help"] = (
                    "10-minute data are intended for recent event/detail analysis. The 1-hour resource provides long-term "
                    "hourly observations. The 1-month resource is a separate, richer climatological dataset containing native "
                    "monthly means, extrema, totals and event statistics; it is analysed at monthly resolution and is never upsampled to hours."
                )
            return real_selectbox(label, options, *args, **kwargs)

        def caption(body: Any, *args: Any, **kwargs: Any):
            text = body
            if str(st.session_state.get("geosphere_resource_id", "")) == MONTHLY_RESOURCE_ID and isinstance(text, str):
                if text.startswith("Selected resource:"):
                    text = f"Selected resource: `{MONTHLY_RESOURCE_ID}` · native cadence monthly · {MONTHLY_DOI}"
                text = text.replace("`klima-v2-10min`", f"`{MONTHLY_RESOURCE_ID}`")
                text = text.replace("10.60669/8fya-7x87", "10.60669/923n-p390")
                text = text.replace("10.60669/9bdm-yq93", "10.60669/923n-p390")
                text = text.replace("10-minute source data", "monthly source data")
                text = text.replace("hourly source data", "monthly source data")
                text = text.replace("10-minute source", "monthly source")
                text = text.replace("hourly source", "monthly source")
            return real_caption(text, *args, **kwargs)

        def info(body: Any, *args: Any, **kwargs: Any):
            if (
                str(st.session_state.get("geosphere_resource_id", "")) == MONTHLY_RESOURCE_ID
                and isinstance(body, str)
                and body.startswith("Air temperature is not selected.")
            ):
                # The mature hourly shell checks for provider field `tl`; the
                # monthly resource uses `tl_mittel` and many related statistics.
                return None
            return real_info(body, *args, **kwargs)

        def dataframe(data: Any = None, *args: Any, **kwargs: Any):
            result = real_dataframe(data, *args, **kwargs)
            if (
                str(st.session_state.get("geosphere_resource_id", "")) == MONTHLY_RESOURCE_ID
                and isinstance(data, pd.DataFrame)
                and {"Field", "Value"}.issubset(data.columns)
                and bool(data["Field"].astype(str).eq("Station metadata validity").any())
            ):
                st.info(MONTHLY_OFFICIAL_CONTEXT_EN)
                real_caption(
                    f"Official source: GeoSphere Austria Station Data-v2 (1 m) · {MONTHLY_DOI} · {MONTHLY_DATASET_PAGE}"
                )
            return result

        def data_editor(data: Any, *args: Any, **kwargs: Any):
            if (
                str(st.session_state.get("geosphere_resource_id", "")) == MONTHLY_RESOURCE_ID
                and isinstance(data, pd.DataFrame)
                and {"Provider", "Canonical field"}.issubset(data.columns)
            ):
                column_config = dict(kwargs.get("column_config") or {})
                column_config["Canonical field"] = st.column_config.TextColumn(
                    "Monthly field",
                    width="large",
                    help="Native GeoSphere monthly provider parameter. It is not coerced into an hourly canonical variable.",
                )
                kwargs["column_config"] = column_config
            return real_data_editor(data, *args, **kwargs)

        st.selectbox = selectbox
        st.caption = caption
        st.info = info
        st.dataframe = dataframe
        st.data_editor = data_editor
        try:
            previous_selector(legacy, original)
        finally:
            st.selectbox = real_selectbox
            st.caption = real_caption
            st.info = real_info
            st.dataframe = real_dataframe
            st.data_editor = real_data_editor

    parity._render_geosphere_resource_selector = selector_with_monthly_context

    # Keep marker provenance truthful when the shared GeoSphere map is reused.
    if hasattr(proxy, "station_marker_payload"):
        original_marker_payload = proxy.station_marker_payload

        def marker_payload(data: pd.DataFrame, *args: Any, **kwargs: Any):
            if str(st.session_state.get("geosphere_resource_id", "")) == MONTHLY_RESOURCE_ID and isinstance(data, pd.DataFrame):
                display = data.copy()
                if "dataset" in display.columns:
                    display["dataset"] = f"GeoSphere {MONTHLY_RESOURCE_ID}"
                return original_marker_payload(display, *args, **kwargs)
            return original_marker_payload(data, *args, **kwargs)

        proxy.station_marker_payload = marker_payload

    previous_analysis = proxy.render_canonical_climate_analysis

    def render_active_dataset(dataset: Any) -> None:
        resource_id = str(getattr(dataset, "data", pd.DataFrame()).attrs.get("geosphere_resource_id", ""))
        if resource_id == MONTHLY_RESOURCE_ID:
            render_monthly_analysis(proxy, dataset)
            return
        previous_analysis(dataset)

    proxy.render_canonical_climate_analysis = render_active_dataset
    proxy._GEOSPHERE_MONTHLY_RESOURCE_INSTALLED = True
