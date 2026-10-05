"""Active EPW-file download control for the calculated statistics surface.

The mature Streamlit app keeps the exact selected EPW bytes in
``ClimateFilePayload``.  This installer exposes those original bytes next to the
Dataset statistics CSV download without reconstructing an EPW from the parsed or
filtered DataFrame.

The app-script namespace is session-local, so the temporary ``st`` facade below
is also session-local.  It does not mutate the process-global Streamlit module.
"""

from __future__ import annotations

from typing import Any


_DATASET_CSV_LABEL = "Download dataset statistics as CSV"
_EPW_DOWNLOAD_LABEL = "Download active EPW file"
_EPW_DOWNLOAD_KEY = "calculated_statistics_active_epw_download"


def _epw_filename(name: object) -> str:
    """Return a safe download filename while preserving the selected EPW name."""
    value = str(name or "active_climate.epw").strip() or "active_climate.epw"
    if not value.lower().endswith(".epw"):
        value = f"{value}.epw"
    return value


class _StreamlitDownloadFacade:
    """Delegate Streamlit calls while injecting one EPW download button."""

    def __init__(self, st: Any, active_file: Any) -> None:
        self._st = st
        self._active_file = active_file
        self._injected = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._st, name)

    def download_button(self, label: object, *args: Any, **kwargs: Any) -> Any:
        result = self._st.download_button(label, *args, **kwargs)
        if not self._injected and str(label) == _DATASET_CSV_LABEL:
            payload = getattr(self._active_file, "payload", None)
            if isinstance(payload, (bytes, bytearray, memoryview)):
                self._st.download_button(
                    _EPW_DOWNLOAD_LABEL,
                    data=bytes(payload),
                    file_name=_epw_filename(getattr(self._active_file, "name", None)),
                    mime="application/octet-stream",
                    key=_EPW_DOWNLOAD_KEY,
                )
                self._injected = True
        return result


def install_epw_download_surface(app: Any) -> None:
    """Add the exact active EPW payload to Calculated EPW statistics downloads."""
    original = app.render_calculated_epw_statistics
    if bool(getattr(original, "_epw_download_surface_installed", False)):
        return

    def render_calculated_epw_statistics(df: Any) -> Any:
        active_file = app.get_active_climate_file()
        if active_file is None:
            return original(df)

        real_st = app.st
        app.st = _StreamlitDownloadFacade(real_st, active_file)
        try:
            return original(df)
        finally:
            app.st = real_st

    render_calculated_epw_statistics._epw_download_surface_installed = True
    app.render_calculated_epw_statistics = render_calculated_epw_statistics
