"""Canonical GeoSphere request-state boundary shared by every provider resource.

The three GeoSphere resources (10-minute, hourly and native-monthly) differ in
provider metadata, parameter vocabulary and transport planning, but they should
not have different Streamlit request-state machines. This module establishes one
resource-neutral state contract at the final UI boundary while the existing
mature loaders remain the transport implementation.

The request boundary deliberately records only user intent. It never fetches
provider data, infers availability or changes scientific normalization.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping

import pandas as pd
from streamlit.delta_generator import DeltaGenerator


STAGED_REQUEST_KEY = "_geosphere_request_state_v1"
COMMITTED_REQUEST_KEY = "_geosphere_committed_request_state_v1"
_RESOURCE_KEY = "geosphere_resource_id"
_STATION_KEY = "geosphere_selected_station_id"
_START_KEY = "geosphere_start_date"
_END_KEY = "geosphere_end_date"
_MONTHLY_VIEW_KEY = "geosphere_monthly_parameter_catalogue_v2"
_LOAD_LABEL = "Load measured GeoSphere interval"
_EDITOR_PREFIX = "geosphere_variable_editor"


def _date_value(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        parsed = pd.Timestamp(value)
    except Exception:
        return None
    return None if pd.isna(parsed) else parsed.date()


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


@dataclass(frozen=True)
class GeoSphereRequestState:
    """Resource-neutral description of one user-configured GeoSphere request."""

    resource_id: str
    station_id: str
    start_date: date | None = None
    end_date: date | None = None
    provider_parameters: tuple[str, ...] = ()
    quality_flags: tuple[str, ...] = ()
    canonical_fields: tuple[str, ...] = ()
    catalogue_view: str = ""

    @property
    def scope(self) -> tuple[str, str]:
        return self.resource_id, self.station_id

    @property
    def is_loadable(self) -> bool:
        return bool(
            self.resource_id
            and self.station_id
            and self.start_date is not None
            and self.end_date is not None
            and self.end_date >= self.start_date
            and self.provider_parameters
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "resource_id": self.resource_id,
            "station_id": self.station_id,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "provider_parameters": list(self.provider_parameters),
            "quality_flags": list(self.quality_flags),
            "canonical_fields": list(self.canonical_fields),
            "catalogue_view": self.catalogue_view,
        }

    @classmethod
    def from_mapping(cls, value: object) -> "GeoSphereRequestState | None":
        if not isinstance(value, Mapping):
            return None
        return cls(
            resource_id=str(value.get("resource_id", "") or ""),
            station_id=str(value.get("station_id", "") or ""),
            start_date=_date_value(value.get("start_date")),
            end_date=_date_value(value.get("end_date")),
            provider_parameters=_ordered_unique([str(item) for item in value.get("provider_parameters", ()) or ()]),
            quality_flags=_ordered_unique([str(item) for item in value.get("quality_flags", ()) or ()]),
            canonical_fields=_ordered_unique([str(item) for item in value.get("canonical_fields", ()) or ()]),
            catalogue_view=str(value.get("catalogue_view", "") or ""),
        )


class GeoSphereRequestForm:
    """Capture one canonical request state from the shared mature GeoSphere UI.

    This class is intentionally resource-neutral. Monthly catalogue adapters may
    still alter which rows are visible, and resource adapters may still alter the
    provider query plan, but the final user intent is recorded here in exactly the
    same schema for ``klima-v2-10min``, ``klima-v2-1h`` and ``klima-v2-1m``.
    """

    def __init__(self, st: Any) -> None:
        self.st = st

    def _scope(self) -> tuple[str, str]:
        return (
            str(self.st.session_state.get(_RESOURCE_KEY, "") or ""),
            str(self.st.session_state.get(_STATION_KEY, "") or ""),
        )

    def staged(self) -> GeoSphereRequestState:
        resource_id, station_id = self._scope()
        current = GeoSphereRequestState.from_mapping(self.st.session_state.get(STAGED_REQUEST_KEY))
        if current is None or current.scope != (resource_id, station_id):
            current = GeoSphereRequestState(resource_id=resource_id, station_id=station_id)
        return current

    def _save(self, state: GeoSphereRequestState) -> GeoSphereRequestState:
        self.st.session_state[STAGED_REQUEST_KEY] = state.to_mapping()
        return state

    def capture_date(self, key: str, value: object) -> GeoSphereRequestState:
        current = self.staged()
        start = current.start_date
        end = current.end_date
        if str(key) == _START_KEY:
            start = _date_value(value)
        elif str(key) == _END_KEY:
            end = _date_value(value)
        return self._save(
            GeoSphereRequestState(
                resource_id=current.resource_id,
                station_id=current.station_id,
                start_date=start,
                end_date=end,
                provider_parameters=current.provider_parameters,
                quality_flags=current.quality_flags,
                canonical_fields=current.canonical_fields,
                catalogue_view=current.catalogue_view,
            )
        )

    def capture_editor(self, edited: pd.DataFrame) -> GeoSphereRequestState:
        current = self.staged()
        if not isinstance(edited, pd.DataFrame) or not {"Provider", "Selected"}.issubset(edited.columns):
            return current

        mask = edited["Selected"].fillna(False).astype(bool)
        providers = _ordered_unique(edited.loc[mask, "Provider"].fillna("").astype(str).tolist())
        canonicals: tuple[str, ...] = ()
        if "Canonical field" in edited.columns:
            canonicals = _ordered_unique(
                edited.loc[mask, "Canonical field"].fillna("").astype(str).tolist()
            )

        flags: tuple[str, ...] = ()
        if "Quality flag" in edited.columns:
            flag_mask = mask & edited["Quality flag"].fillna(False).astype(bool)
            flags = _ordered_unique(
                [f"{provider}_flag" for provider in edited.loc[flag_mask, "Provider"].fillna("").astype(str).tolist()]
            )

        return self._save(
            GeoSphereRequestState(
                resource_id=current.resource_id,
                station_id=current.station_id,
                start_date=current.start_date or _date_value(self.st.session_state.get(_START_KEY)),
                end_date=current.end_date or _date_value(self.st.session_state.get(_END_KEY)),
                provider_parameters=providers,
                quality_flags=flags,
                canonical_fields=canonicals,
                catalogue_view=str(self.st.session_state.get(_MONTHLY_VIEW_KEY, "") or ""),
            )
        )

    def commit(self) -> GeoSphereRequestState:
        state = self.staged()
        self.st.session_state[COMMITTED_REQUEST_KEY] = state.to_mapping()
        return state


def _is_request_editor(data: Any, key: object) -> bool:
    return (
        isinstance(data, pd.DataFrame)
        and {"Provider", "Selected"}.issubset(data.columns)
        and str(key or "").startswith(_EDITOR_PREFIX)
    )


def install_geosphere_request_form(parity: Any) -> None:
    """Install the one final request-state boundary for all GeoSphere resources.

    The mature transactional variable form remains the sole owner of the visible
    Load action and of the legacy load-event bridge. This boundary observes the
    same ``form_submit_button`` event only to persist the canonical committed
    request snapshot. It must never replace or intercept ``st.button`` itself.
    """
    previous = parity._render_geosphere_resource_selector
    st = parity.st

    def selector(legacy: Any, original: Callable) -> Any:
        real_editor = st.data_editor
        real_form_submit_button = st.form_submit_button
        real_dg_date_input = DeltaGenerator.date_input
        request_form = GeoSphereRequestForm(st)

        def data_editor(data: Any, *args: Any, **kwargs: Any):
            edited = real_editor(data, *args, **kwargs)
            if _is_request_editor(edited, kwargs.get("key")):
                request_form.capture_editor(edited)
            return edited

        def form_submit_button(label: Any, *args: Any, **kwargs: Any):
            submitted = real_form_submit_button(label, *args, **kwargs)
            if str(label) == _LOAD_LABEL and bool(submitted):
                # The mature form performs its own empty-selection validation.
                # Record a committed snapshot only when the staged request is
                # complete; transport remains owned by the existing loader.
                if request_form.staged().is_loadable:
                    request_form.commit()
            return submitted

        def date_input(self: DeltaGenerator, label: str, *args: Any, **kwargs: Any):
            value = real_dg_date_input(self, label, *args, **kwargs)
            key = str(kwargs.get("key") or "")
            if key in {_START_KEY, _END_KEY}:
                request_form.capture_date(key, value)
            return value

        st.data_editor = data_editor
        st.form_submit_button = form_submit_button
        DeltaGenerator.date_input = date_input
        try:
            return previous(legacy, original)
        finally:
            st.data_editor = real_editor
            st.form_submit_button = real_form_submit_button
            DeltaGenerator.date_input = real_dg_date_input

    parity._render_geosphere_resource_selector = selector
