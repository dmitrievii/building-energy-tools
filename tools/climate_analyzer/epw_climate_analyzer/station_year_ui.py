"""One explicit station/year request; rerenders never acquire measurements."""
from __future__ import annotations

import pandas as pd

from .engine.station_epw_admission import StationYearRequest
from .geosphere_station_year import run_station_year

PRODUCT_KEY = "ige_h1_station_year_product"
ERROR_KEY = "ige_h1_station_year_error"
ERROR_REQUEST_KEY = "ige_h1_station_year_error_request"
LABELS = {
    "dry_bulb_temperature_c": "Air temperature [°C]", "dew_point_temperature_c": "Dew point [°C]",
    "relative_humidity_pct": "Relative humidity [%]", "atmospheric_station_pressure_pa": "Station pressure [Pa]",
    "horizontal_infrared_radiation_intensity_wh_m2": "Downward longwave [Wh/m²]",
    "global_horizontal_radiation_wh_m2": "Global horizontal solar [Wh/m²]",
    "direct_normal_radiation_wh_m2": "Direct normal solar [Wh/m²]",
    "diffuse_horizontal_radiation_wh_m2": "Diffuse horizontal solar [Wh/m²]",
    "wind_direction_deg": "Wind direction [°]", "wind_speed_m_s": "Wind speed [m/s]",
    "total_sky_cover_tenths": "Total cloud cover [tenths]", "liquid_precipitation_depth_mm": "Liquid rain [mm]",
}
CONSTRAINTS = {
    "NO_DECLARED_FIELD_SOURCE": "No admitted source", "UNIT_NOT_ADMITTED": "Unsupported unit",
    "TIME_OPERATOR_NOT_ADMITTED": "Time definition differs from the strict EPW contract",
    "ABSOLUTE_STATION_PRESSURE_REQUIRED": "Station pressure required; reduced pressure is unsuitable",
    "LIQUID_PHASE_NOT_ESTABLISHED": "Liquid rain is not identified separately",
}


def render_station_year(st, station, metadata):
    st.divider()
    st.subheader("Full station year and EPW admission")
    st.write("Load the available hourly observations for a selected year and check every required EPW field. Incomplete or incompatible sources produce a report with missing fields and hours.")
    today = pd.Timestamp.now(tz="UTC")
    start = pd.to_datetime(station.valid_from, utc=True, errors="coerce")
    stop = pd.to_datetime(station.valid_to, utc=True, errors="coerce")
    source_start = pd.to_datetime(metadata.get("start_time"), utc=True, errors="coerce")
    minimum = max(1800, int(start.year) if pd.notna(start) else 1800,
                  int(source_start.year) if pd.notna(source_start) else 1800)
    maximum = min(today.year, int(stop.year) if pd.notna(stop) else today.year)
    if maximum < minimum:
        st.warning("The station and source metadata have no overlapping historical year.")
        return
    key = "ige_h1_year_" + station.station_id
    year = st.number_input("Station calendar year", minimum, maximum,
                           min(maximum, max(minimum, today.year - 1)), step=1, key=key)
    st.caption(f"Selected station: {station.name} · ID {station.station_id}. Output clock: fixed CET (UTC+1), without daylight-saving shifts. Station validity is metadata, not a promise of complete parameter coverage.")
    st.caption("QC policy: provider-reviewed codes 10/11/12/20/21/22; 0 and missing flags are rejected. Reviewed values can include provider corrections or filling. This does not change the earlier QC10-only independent-validation policy.")
    st.info("This first admission profile does not fill gaps, estimate missing radiation or dew point, infer rain phase, or turn hourly-mean wind into instantaneous wind. An EPW is offered only if the complete strict input contract passes.")
    label = station.name.replace(",", ";").replace("\n", " ").replace("\r", " ")[:120]
    request = StationYearRequest(station.station_id, int(year), 60, label)
    if st.button("Load station year and check EPW", type="primary", key="ige_h1_load_year"):
        st.session_state.pop(ERROR_KEY, None)
        st.session_state.pop(ERROR_REQUEST_KEY, None)
        try:
            with st.status("Loading native hourly sources and checking the year", expanded=True) as status:
                def progress(event):
                    if event.get("event") in ("batch_start", "batch_complete", "retry", "split"):
                        status.update(label=f"GeoSphere {event['event']}: batch {event.get('batch_number', '?')}/{event.get('total_batches', '?')}")
                product = run_station_year(request, progress=progress)
                status.update(label="Station-year inventory complete", state="complete", expanded=False)
            st.session_state[PRODUCT_KEY] = product
        except Exception as exc:
            st.session_state[ERROR_KEY] = type(exc).__name__ + ": " + str(exc)
            st.session_state[ERROR_REQUEST_KEY] = request.to_dict()
    error = st.session_state.get(ERROR_KEY)
    if error:
        current = st.session_state.get(ERROR_REQUEST_KEY) == request.to_dict()
        st.error(("This request" if current else "Previous request") + " could not complete the source audit: " + error)
    product = st.session_state.get(PRODUCT_KEY)
    if product is None:
        return
    current = product.request.to_dict() == request.to_dict()
    st.markdown("#### Station-year result" if current else "#### Previous station-year result")
    if not current:
        st.warning("These files belong to the previous station/year selection. Run the current request to obtain its coverage report.")
    report = product.report
    st.write(f"Station {product.request.station_id} · {product.request.year} · {report['expected_hours']:,} expected hours")
    if "climate.epw" in product.files:
        st.success("The complete strict EPW input contract passed. Independent accuracy and production readiness remain unqualified.")
        st.download_button("Download station-year EPW", product.files["climate.epw"],
            file_name=f"IGE_station_{product.request.station_id}_{product.request.year}_RESEARCH.epw",
            mime="application/octet-stream", key="ige_h1_download_epw")
    else:
        st.warning("A complete EPW cannot be formed under this input contract. The table and gap ledger identify the missing data, QC and definition constraints.")
    columns = ("field", "numeric_hours", "reviewed_in_bounds_hours", "usable_for_epw_hours",
               "missing_value_hours", "out_of_bounds_hours", "missing_qc_hours", "rejected_qc_hours", "definition_errors", "status")
    table = pd.DataFrame(report["fields"])[list(columns)]
    table["field"] = table["field"].map(lambda value: LABELS.get(value, value))
    table["definition_errors"] = table["definition_errors"].map(
        lambda values: "; ".join(CONSTRAINTS.get(value, value.replace("_", " ").lower()) for value in values))
    table = table.rename(columns={"field": "Weather variable", "numeric_hours": "Numeric hours",
        "reviewed_in_bounds_hours": "Reviewed + in bounds", "usable_for_epw_hours": "EPW-eligible hours",
        "missing_value_hours": "Missing values", "out_of_bounds_hours": "Out of bounds",
        "missing_qc_hours": "QC missing", "rejected_qc_hours": "QC rejected", "definition_errors": "Definition constraints",
        "status": "Status"})
    st.dataframe(table, hide_index=True, width="stretch")
    if report["global_blockers"]:
        st.write("Additional blockers:")
        for blocker in report["global_blockers"]: st.write("• " + blocker)
    st.caption("A numeric value can still fail EPW admission because of QC, units, pressure semantics or temporal support. The gap download lists every affected hour as contiguous ranges. Reasons can overlap; use the per-field counts rather than summing different reasons.")
    st.download_button("Download station-year data and admission ZIP", product.archive,
        file_name=f"IGE_station_{product.request.station_id}_{product.request.year}_ADMISSION.zip",
        mime="application/zip", key="ige_h1_download_zip")
    st.download_button("Download station-year admission JSON", product.files["admission.json"],
        file_name=f"IGE_station_{product.request.station_id}_{product.request.year}_admission.json",
        mime="application/json", key="ige_h1_download_report")
    st.download_button("Download missing-hour ledger (CSV gzip)", product.files["missing_hours.csv.gz"],
        file_name=f"IGE_station_{product.request.station_id}_{product.request.year}_gaps.csv.gz",
        mime="application/gzip", key="ige_h1_download_gaps")
    with st.expander("Station-year source definitions and scientific status", expanded=False):
        st.json({key: report[key] for key in ("source_metadata", "qc_policy", "quality", "additional_source_fields")})
