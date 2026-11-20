"""GeoSphere resource temporal bounds and station-validity UI clarification.

Station metadata can predate the temporal extent of a particular GeoSphere
resource and does not imply per-parameter coverage.  The resource bounds below
come from the published GeoSphere Austria dataset metadata:

* ``klima-v2-10min``: 1992-05-20 06:10 UTC
* ``klima-v2-1h``: 1880-04-01 00:00 UTC
* ``klima-v2-1m``: 1767-12-01 00:00 UTC (published extent starts Dec 1767)

Parameter-specific coverage can begin later still and is determined from the
returned numeric observations rather than inferred from station validity.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Mapping

import pandas as pd


GEOSPHERE_RESOURCE_START_UTC: dict[str, pd.Timestamp] = {
    "klima-v2-10min": pd.Timestamp("1992-05-20T06:10:00Z"),
    "klima-v2-1h": pd.Timestamp("1880-04-01T00:00:00Z"),
    "klima-v2-1m": pd.Timestamp("1767-12-01T00:00:00Z"),
}


def resource_start_date(resource_id: str) -> date | None:
    value = GEOSPHERE_RESOURCE_START_UTC.get(str(resource_id))
    return value.date() if value is not None else None


def hourly_request_date_bounds(
    metadata: Mapping[str, Any], *, today: date | None = None
) -> tuple[date, date]:
    """Return resource-level request dates, not a station coverage assertion.

    Station validity can describe an individual station record or metadata
    segment. It is useful for advising a user, but does not establish the
    numeric coverage of the requested measurements. Only resource-wide
    temporal bounds may limit an explicit hourly data request.
    """
    today = today if today is not None else pd.Timestamp.now(tz="UTC").date()
    minimum = GEOSPHERE_RESOURCE_START_UTC["klima-v2-1h"].date()
    start = pd.to_datetime(metadata.get("start_time"), errors="coerce", utc=True)
    if pd.notna(start):
        minimum = max(minimum, start.date())
    maximum = today
    end = pd.to_datetime(metadata.get("end_time"), errors="coerce", utc=True)
    if pd.notna(end):
        maximum = min(maximum, end.date())
    if maximum < minimum:
        raise ValueError("The hourly GeoSphere resource has no available historical date range.")
    return minimum, maximum


def hourly_station_validity_warning(station: Any, start: date, end: date) -> str | None:
    """Display incomplete station metadata coverage without gating acquisition."""
    valid_from = pd.to_datetime(station.valid_from, errors="coerce", utc=True)
    valid_to = pd.to_datetime(station.valid_to, errors="coerce", utc=True)
    if (pd.notna(valid_from) and start < valid_from.date()) or (
        pd.notna(valid_to) and end > valid_to.date()
    ):
        first = valid_from.date().isoformat() if pd.notna(valid_from) else "unknown"
        last = valid_to.date().isoformat() if pd.notna(valid_to) else "unknown"
        return (
            f"Selected interval extends outside this station record's metadata validity "
            f"({first} through {last}). The request is allowed, but measurements may be "
            "missing or the station may have been discontinued. Check the returned "
            "coverage, or choose another station ID with the desired recording period."
        )
    return None


def install_resource_temporal_bounds(proxy: Any, parity: Any) -> None:
    """Clamp GeoSphere date controls to resource extent and clarify station metadata."""
    if bool(getattr(proxy, "_GEOSPHERE_RESOURCE_BOUNDS_INSTALLED", False)):
        return

    st = parity.st
    original_selector = parity._render_geosphere_resource_selector

    def selector_with_resource_bounds(legacy: Any, original: Callable) -> None:
        real_date_input = st.date_input
        real_dataframe = st.dataframe

        def bounded_date_input(label: str, *args: Any, **kwargs: Any):
            key = str(kwargs.get("key") or "")
            if key in {"geosphere_start_date", "geosphere_end_date"}:
                resource_id = str(st.session_state.get("geosphere_resource_id", "klima-v2-10min"))
                lower = resource_start_date(resource_id)
                if lower is not None:
                    existing_min = kwargs.get("min_value")
                    if existing_min is None or pd.Timestamp(existing_min).date() < lower:
                        kwargs["min_value"] = lower
                    value = kwargs.get("value")
                    if value is not None and pd.Timestamp(value).date() < lower:
                        kwargs["value"] = lower
            return real_date_input(label, *args, **kwargs)

        def clarified_dataframe(data: Any = None, *args: Any, **kwargs: Any):
            changed = False
            display = data
            if isinstance(data, pd.DataFrame) and {"Field", "Value"}.issubset(data.columns):
                field_values = data["Field"].astype(str)
                if bool(field_values.eq("Provider validity").any()):
                    display = data.copy()
                    display.loc[field_values.eq("Provider validity"), "Field"] = "Station metadata validity"
                    changed = True
            result = real_dataframe(display, *args, **kwargs)
            if changed:
                resource_id = str(st.session_state.get("geosphere_resource_id", "klima-v2-10min"))
                lower = GEOSPHERE_RESOURCE_START_UTC.get(resource_id)
                start_text = (
                    "Dec 1767 UTC"
                    if resource_id == "klima-v2-1m"
                    else lower.strftime("%d %b %Y %H:%M UTC") if lower is not None
                    else "the published resource start"
                )
                st.caption(
                    f"Station metadata validity describes the station record, not measurement coverage for every variable. "
                    f"This resource starts at {start_text}; individual parameters can begin later and are verified from returned observations."
                )
            return result

        st.date_input = bounded_date_input
        st.dataframe = clarified_dataframe
        try:
            original_selector(legacy, original)
        finally:
            st.date_input = real_date_input
            st.dataframe = real_dataframe

    parity._render_geosphere_resource_selector = selector_with_resource_bounds
    proxy._GEOSPHERE_RESOURCE_BOUNDS_INSTALLED = True
