"""Follow-up runtime closure for long-term GeoSphere UX and heat-map semantics.

This module is deliberately narrow.  It is installed after the existing source-
parity and long-term patches and addresses production findings that are easiest
to close without editing the mature Streamlit shell directly:

* measured variables and provider quality flags start unchecked;
* the selected-variable state is retained for availability guidance;
* hourly heat-map coordinates are always derived from the active DatetimeIndex,
  never from a potentially stale helper column;
* interannual ``Compare across = Year`` is exposed in chronological mode too;
* dry-bulb temperature heat maps use a continuous cold/neutral/hot gradient;
* the published GeoSphere hourly-data history is shown next to station metadata;
* a non-blocking warning is shown when a selected early period predates the
  documented broad availability of temperature/humidity/precipitation.

The official 1-hour dataset description is paraphrased rather than embedded as a
large verbatim block.  The UI links to the authoritative GeoSphere page and DOI.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


VARIABLE_SELECTION_KEY = "_geosphere_selected_measured_variables"
VARIABLE_EDITOR_KEY_PREFIX = "geosphere_variable_editor_v2"

OFFICIAL_HOURLY_DATASET_PAGE = "https://data.hub.geosphere.at/en/dataset/klima-v2-1h"
OFFICIAL_HOURLY_DOI = "https://doi.org/10.60669/9bdm-yq93"

# GeoSphere's published dataset-level history says that the oldest observations
# are Vienna sunshine-duration records from 1880, while hourly air temperature,
# humidity and precipitation are present for a few stations from 1941.  These
# are broad dataset milestones, NOT station-specific validity dates.
DOCUMENTED_HOURLY_BROAD_START: dict[str, date] = {
    "sunshine_duration_s": date(1880, 4, 1),
    "dry_bulb_temperature_c": date(1941, 1, 1),
    "dry_bulb_temperature_min_c": date(1941, 1, 1),
    "dry_bulb_temperature_max_c": date(1941, 1, 1),
    "relative_humidity_pct": date(1941, 1, 1),
    "liquid_precipitation_depth_mm": date(1941, 1, 1),
    "precipitation_duration_min": date(1941, 1, 1),
}


def empty_measured_variable_table(data: pd.DataFrame) -> pd.DataFrame:
    """Return the variable editor source table with every load checkbox off."""
    out = data.copy()
    if "Selected" in out.columns:
        out["Selected"] = False
    return out


def selected_variable_state(
    edited: pd.DataFrame,
    *,
    resource_id: str,
    station_id: str,
) -> dict[str, object]:
    """Return compact provider/canonical selection state for later UI guidance."""
    if not isinstance(edited, pd.DataFrame) or "Selected" not in edited.columns:
        providers: tuple[str, ...] = ()
        canonicals: tuple[str, ...] = ()
    else:
        mask = edited["Selected"].fillna(False).astype(bool)
        providers = tuple(
            dict.fromkeys(
                edited.loc[mask, "Provider"].astype(str).tolist()
                if "Provider" in edited.columns
                else ()
            )
        )
        canonicals = tuple(
            dict.fromkeys(
                edited.loc[mask, "Canonical field"].astype(str).tolist()
                if "Canonical field" in edited.columns
                else ()
            )
        )
    return {
        "resource_id": str(resource_id),
        "station_id": str(station_id),
        "providers": providers,
        "canonicals": canonicals,
    }


def selected_canonical_variables(state: object, resource_id: str, station_id: str) -> tuple[str, ...]:
    """Read selection state only when it belongs to the current resource/station."""
    if not isinstance(state, Mapping):
        return ()
    if str(state.get("resource_id", "")) != str(resource_id):
        return ()
    if str(state.get("station_id", "")) != str(station_id):
        return ()
    values = state.get("canonicals", ())
    if not isinstance(values, (tuple, list, set)):
        return ()
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def documented_coverage_warning(
    resource_id: str,
    start_date: date,
    canonical_variables: Sequence[str],
) -> str | None:
    """Return a dataset-level early-coverage warning without inventing station dates."""
    if str(resource_id) != "klima-v2-1h":
        return None
    selected = tuple(dict.fromkeys(str(value) for value in canonical_variables))
    affected = [
        (name, DOCUMENTED_HOURLY_BROAD_START[name])
        for name in selected
        if name in DOCUMENTED_HOURLY_BROAD_START
        and start_date < DOCUMENTED_HOURLY_BROAD_START[name]
    ]
    # Sunshine starts at the resource boundary itself and is not useful as an
    # early-warning case.  Warn only for documented later broad milestones.
    affected = [(name, threshold) for name, threshold in affected if threshold.year > 1880]
    if not affected:
        return None

    labels = {
        "dry_bulb_temperature_c": "air temperature",
        "dry_bulb_temperature_min_c": "air-temperature minimum",
        "dry_bulb_temperature_max_c": "air-temperature maximum",
        "relative_humidity_pct": "relative humidity",
        "liquid_precipitation_depth_mm": "precipitation",
        "precipitation_duration_min": "precipitation duration",
    }
    names = ", ".join(dict.fromkeys(labels.get(name, name) for name, _ in affected))
    earliest = min(threshold for _, threshold in affected)
    return (
        f"Selected start {start_date.isoformat()} predates GeoSphere Austria's documented broad hourly-data milestone "
        f"({earliest.year}) for {names}. The load is allowed: this is not a station-specific cutoff, but the early part "
        "of the selected variable series may be empty. Other selected variables with earlier observations, such as "
        "sunshine duration, remain valid and are not trimmed away."
    )


def heatmap_frame_from_index(df: pd.DataFrame) -> pd.DataFrame:
    """Refresh heat-map calendar helpers from the authoritative analysis index."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Heat-map analysis requires a DatetimeIndex.")
    attrs = dict(df.attrs)
    out = df.copy(deep=False)
    index = pd.DatetimeIndex(df.index)
    # The chart must follow the already-selected analysis clock represented by
    # the index.  A stale source/helper column must never collapse all rows to 0.
    out["hour_of_day"] = index.hour.astype(int)
    out.attrs.update(attrs)
    return out


def index_populated_hour_axis_range(df: pd.DataFrame, column: str) -> list[float] | None:
    """Return the visible hour range using the DatetimeIndex, not helper columns."""
    if column not in df.columns or not isinstance(df.index, pd.DatetimeIndex):
        return None
    valid = pd.to_numeric(df[column], errors="coerce").notna().to_numpy()
    if not bool(valid.any()):
        return None
    hours = pd.Series(pd.DatetimeIndex(df.index)[valid].hour, dtype=float)
    if hours.empty:
        return None
    return [float(hours.max()) + 0.5, float(hours.min()) - 0.5]


def temperature_gradient_colorscale(
    values: object,
    thresholds: tuple[float, float],
) -> list[list[float | str]]:
    """Build a continuous thermal scale with a real blue cold gradient.

    Unlike the former constant-blue cold band, values such as -10 °C and +10 °C
    remain visually distinguishable while the heating/cooling thresholds still
    anchor the transition through neutral and warm colours.
    """
    arr = np.asarray(values, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    heat_t, cool_t = sorted(map(float, thresholds))
    if arr.size == 0:
        return [
            [0.0, "#172554"],
            [0.30, "#2563eb"],
            [0.45, "#bfdbfe"],
            [0.55, "#22c55e"],
            [0.72, "#f59e0b"],
            [1.0, "#b91c1c"],
        ]
    vmin = float(np.nanmin(arr))
    vmax = float(np.nanmax(arr))
    if abs(vmax - vmin) < 1e-12:
        if vmax < heat_t:
            return [[0.0, "#2563eb"], [1.0, "#2563eb"]]
        if vmax > cool_t:
            return [[0.0, "#dc2626"], [1.0, "#dc2626"]]
        return [[0.0, "#22c55e"], [1.0, "#22c55e"]]

    # Entirely cold / neutral / hot ranges still receive an internal gradient.
    if vmax <= heat_t:
        return [[0.0, "#172554"], [0.5, "#2563eb"], [1.0, "#bfdbfe"]]
    if vmin >= cool_t:
        return [[0.0, "#fde68a"], [0.5, "#f97316"], [1.0, "#b91c1c"]]
    if vmin >= heat_t and vmax <= cool_t:
        return [[0.0, "#bbf7d0"], [0.5, "#22c55e"], [1.0, "#15803d"]]

    span = vmax - vmin
    anchors: list[tuple[float, str]] = []

    def add(value: float, color: str) -> None:
        if vmin <= value <= vmax:
            anchors.append(((value - vmin) / span, color))

    if vmin < heat_t:
        anchors.append((0.0, "#172554"))
        cold_mid = (vmin + min(heat_t, vmax)) / 2.0
        if vmin < cold_mid < vmax:
            add(cold_mid, "#2563eb")
        add(heat_t, "#bfdbfe")
    else:
        anchors.append((0.0, "#bbf7d0" if vmin < cool_t else "#fde68a"))

    if vmax > heat_t and vmin < cool_t:
        neutral_lo = max(vmin, heat_t)
        neutral_hi = min(vmax, cool_t)
        if neutral_hi > neutral_lo:
            add((neutral_lo + neutral_hi) / 2.0, "#22c55e")
        add(cool_t, "#fde68a")

    if vmax > cool_t:
        warm_lo = max(vmin, cool_t)
        if vmax > warm_lo:
            add((warm_lo + vmax) / 2.0, "#f97316")
        anchors.append((1.0, "#b91c1c"))
    elif not anchors or anchors[-1][0] < 1.0:
        anchors.append((1.0, "#22c55e"))

    # Sort and collapse exact duplicate stop positions deterministically.
    deduped: list[list[float | str]] = []
    for position, color in sorted(anchors, key=lambda item: item[0]):
        p = float(np.clip(position, 0.0, 1.0))
        if deduped and abs(float(deduped[-1][0]) - p) < 1e-12:
            deduped[-1] = [p, color]
        else:
            deduped.append([p, color])
    if float(deduped[0][0]) > 0.0:
        deduped.insert(0, [0.0, str(deduped[0][1])])
    if float(deduped[-1][0]) < 1.0:
        deduped.append([1.0, str(deduped[-1][1])])
    return deduped


def compare_options_with_year(options: Iterable[object]) -> list[object]:
    """Expose Year whenever the generic heat-map engine already supports it."""
    values = list(options)
    if "Hour of day" in values and "Year" not in values:
        values.append("Year")
    return values


def _install_heatmap_runtime(proxy: Any, parity: Any) -> None:
    from . import aggregations as agg
    from . import charts
    from . import source_parity_longterm_hotfix as previous_hotfix

    original_matrix = agg.temporal_heatmap_matrix

    def temporal_heatmap_matrix_index_safe(
        df: pd.DataFrame,
        column: str,
        row_group: str = "day",
        compare_across: str = agg.HEATMAP_COMPARE_HOUR,
        statistic: str = "Mean",
    ) -> pd.DataFrame:
        source = heatmap_frame_from_index(df) if compare_across == agg.HEATMAP_COMPARE_HOUR else df
        return original_matrix(
            source,
            column,
            row_group=row_group,
            compare_across=compare_across,
            statistic=statistic,
        )

    agg.temporal_heatmap_matrix = temporal_heatmap_matrix_index_safe
    charts.temporal_heatmap_matrix = temporal_heatmap_matrix_index_safe
    # The previous chart wrapper resolves this name from its module globals at
    # call time. Replace it so its axis range agrees with the corrected matrix.
    previous_hotfix.populated_hour_axis_range = index_populated_hour_axis_range

    original_colorscale = charts._heatmap_colorscale

    def heatmap_colorscale_safe(
        column: str,
        values: object = None,
        temperature_thresholds: tuple[float, float] | None = None,
    ):
        if column == "dry_bulb_temperature_c" and temperature_thresholds is not None:
            return temperature_gradient_colorscale(values, temperature_thresholds)
        return original_colorscale(column, values, temperature_thresholds)

    charts._heatmap_colorscale = heatmap_colorscale_safe

    # The backend already supports Year independently of the global time basis.
    # The old UI hid it in Chronological mode. Expand only the Compare-across
    # widget while these renderers execute; all other controls stay untouched.
    def wrap_renderer(renderer: Callable):
        def wrapped(*args: Any, **kwargs: Any):
            st = parity.st
            real_selectbox = st.selectbox
            real_radio = st.radio
            real_caption = st.caption

            def selectbox(label: str, options: Iterable[object], *w_args: Any, **w_kwargs: Any):
                if str(label) == "Compare across":
                    options = compare_options_with_year(options)
                return real_selectbox(label, options, *w_args, **w_kwargs)

            def radio(label: str, options: Iterable[object], *w_args: Any, **w_kwargs: Any):
                if str(label) == "Compare across":
                    options = compare_options_with_year(options)
                return real_radio(label, options, *w_args, **w_kwargs)

            def caption(body: object, *c_args: Any, **c_kwargs: Any):
                text = str(body)
                if "Switch Time basis to Calendar profile" in text and "compare" in text.lower():
                    body = (
                        "Chronological heat maps keep real periods in sequence for Hour of day. "
                        "Choose Compare across = Year to align equivalent calendar periods across real source years; "
                        "changing the global Time basis is not required for this interannual view."
                    )
                return real_caption(body, *c_args, **c_kwargs)

            st.selectbox = selectbox
            st.radio = radio
            st.caption = caption
            try:
                return renderer(*args, **kwargs)
            finally:
                st.selectbox = real_selectbox
                st.radio = real_radio
                st.caption = real_caption

        return wrapped

    if hasattr(proxy, "render_generic_variable_page"):
        proxy.render_generic_variable_page = wrap_renderer(proxy.render_generic_variable_page)
    if hasattr(proxy, "render_natural_ventilation"):
        proxy.render_natural_ventilation = wrap_renderer(proxy.render_natural_ventilation)


def _install_geosphere_selection_and_guidance(proxy: Any, parity: Any) -> None:
    from streamlit.delta_generator import DeltaGenerator

    from .source_parity_resource_bounds import GEOSPHERE_RESOURCE_START_UTC

    st = parity.st
    previous_selector = parity._render_geosphere_resource_selector

    def selector_with_empty_defaults_and_guidance(legacy: Any, original: Callable) -> None:
        real_data_editor = st.data_editor
        real_dataframe = st.dataframe
        real_dg_date_input = DeltaGenerator.date_input

        def data_editor(data: Any, *args: Any, **kwargs: Any):
            if kwargs.get("key") != "geosphere_variable_editor" or not isinstance(data, pd.DataFrame):
                return real_data_editor(data, *args, **kwargs)

            resource_id = str(st.session_state.get("geosphere_resource_id", "klima-v2-10min"))
            station_id = str(st.session_state.get("geosphere_selected_station_id", ""))
            source = empty_measured_variable_table(data)
            # Version and scope the widget key so an old production session that
            # previously auto-selected every variable cannot resurrect that state.
            kwargs["key"] = f"{VARIABLE_EDITOR_KEY_PREFIX}::{resource_id}::{station_id}"
            edited = real_data_editor(source, *args, **kwargs)
            st.session_state[VARIABLE_SELECTION_KEY] = selected_variable_state(
                edited,
                resource_id=resource_id,
                station_id=station_id,
            )
            return edited

        def dataframe(data: Any = None, *args: Any, **kwargs: Any):
            result = real_dataframe(data, *args, **kwargs)
            if (
                isinstance(data, pd.DataFrame)
                and {"Field", "Value"}.issubset(data.columns)
                and bool(data["Field"].astype(str).eq("Station metadata validity").any())
                and str(st.session_state.get("geosphere_resource_id", "")) == "klima-v2-1h"
            ):
                st.info(
                    "Official GeoSphere Austria availability context (translated summary): the hourly dataset begins with "
                    "Vienna sunshine-duration observations from 1880. Hourly air temperature, humidity and precipitation "
                    "are documented for a small number of stations from 1941; measured/observed parameters and station "
                    "coverage increase continuously from about 1950. Depending on the parameter, an hourly value can be "
                    "an instantaneous observation, previous-hour mean, previous-hour extreme or previous-hour sum. "
                    "Quality status is provided through matching *_flag fields. The archived dataset is refreshed every "
                    "10 minutes and retrospective changes can occur after quality control."
                )
                st.caption(
                    f"Authoritative source: GeoSphere Austria Stationsdaten-v2 (1 h) · {OFFICIAL_HOURLY_DOI} · "
                    f"{OFFICIAL_HOURLY_DATASET_PAGE}"
                )
            return result

        def dg_date_input(self: DeltaGenerator, label: str, *args: Any, **kwargs: Any):
            key = str(kwargs.get("key") or "")
            resource_id = str(st.session_state.get("geosphere_resource_id", "klima-v2-10min"))
            station_id = str(st.session_state.get("geosphere_selected_station_id", ""))
            if key in {"geosphere_start_date", "geosphere_end_date"}:
                lower_ts = GEOSPHERE_RESOURCE_START_UTC.get(resource_id)
                lower = lower_ts.date() if lower_ts is not None else None
                if lower is not None:
                    existing_min = kwargs.get("min_value")
                    if existing_min is None or pd.Timestamp(existing_min).date() < lower:
                        kwargs["min_value"] = lower
                    value = kwargs.get("value")
                    if value is not None and pd.Timestamp(value).date() < lower:
                        kwargs["value"] = lower

            warning = None
            if key == "geosphere_start_date":
                selected = selected_canonical_variables(
                    st.session_state.get(VARIABLE_SELECTION_KEY),
                    resource_id,
                    station_id,
                )
                candidate = kwargs.get("value")
                if candidate is not None:
                    warning = documented_coverage_warning(
                        resource_id,
                        pd.Timestamp(candidate).date(),
                        selected,
                    )
                if warning:
                    label = f"⚠ {label}"

            value = real_dg_date_input(self, label, *args, **kwargs)
            if key == "geosphere_start_date":
                selected = selected_canonical_variables(
                    st.session_state.get(VARIABLE_SELECTION_KEY),
                    resource_id,
                    station_id,
                )
                warning = documented_coverage_warning(
                    resource_id,
                    pd.Timestamp(value).date(),
                    selected,
                )
                if warning:
                    self.warning(warning)
            return value

        st.data_editor = data_editor
        st.dataframe = dataframe
        DeltaGenerator.date_input = dg_date_input
        try:
            previous_selector(legacy, original)
        finally:
            st.data_editor = real_data_editor
            st.dataframe = real_dataframe
            DeltaGenerator.date_input = real_dg_date_input

    parity._render_geosphere_resource_selector = selector_with_empty_defaults_and_guidance


def install_longterm_followup(proxy: Any, parity: Any) -> None:
    """Install the second production closure exactly once."""
    if bool(getattr(proxy, "_LONGTERM_GEOSPHERE_FOLLOWUP_INSTALLED", False)):
        return
    _install_heatmap_runtime(proxy, parity)
    _install_geosphere_selection_and_guidance(proxy, parity)
    proxy._LONGTERM_GEOSPHERE_FOLLOWUP_INSTALLED = True
