"""Map-based S1 request. Edits do not fetch data or relabel previous results."""
from __future__ import annotations

import gzip
from hashlib import sha256
import io

import pandas as pd

from .engine.point_interpolation import PointRequest, T, P, RH
from .location_picker import render_point_picker
from .point_interpolation import PointProduct, run_point_product

PRODUCT_KEY = "ige_s1_point_product"
REQUEST_KEY = "ige_s1_completed_identity"
ERROR_KEY = "ige_s1_error"
ERROR_REQUEST_KEY = "ige_s1_failed_identity"


def render_point_interpolation(st):
    st.subheader("Interpolate a climate year to a point")
    st.write("Select a point and its elevation. Four nearest complete eligible donor years provide temperature, pressure and moisture, with the frozen P8.2F height equations.")
    lat, lon, height, reference = render_point_picker(st, purpose="interpolation")
    source = st.selectbox("Interpolation inputs", ["GeoSphere Austria — real station years", "Upload synchronous actual-year EPWs"], key="ige_s1_source")
    cols = st.columns(2)
    year = cols[0].number_input("Source year", 1901, 2025, 2023, step=1, key="ige_s1_year")
    offset = cols[1].selectbox("Standard UTC offset [hours]", list(range(-12, 13)), index=13, key="ige_s1_offset")
    label = st.text_input("Point label", "Selected point", max_chars=120, key="ige_s1_label")
    phase = st.checkbox("Use Buck liquid-water moisture at all temperatures (explicit source assumption)", key="ige_s1_phase")
    proxy = st.checkbox("Use published station / EPW altitudes as sensor-height proxies where sensor elevations are unconfirmed", key="ige_s1_height_proxy")
    st.caption("The corrections are applied to the selected elevation. Sensor datums, regional lapse rates and dry-temperature pressure transfer remain conditional research approximations. No automatic R1 correction is used.")
    uploads, confirmed = [], False
    if source.startswith("Upload"):
        uploads = st.file_uploader("Donor EPWs — same actual year and fixed UTC offset", type=["epw"], accept_multiple_files=True, key="ige_s1_epws")
        confirmed = st.checkbox("These are synchronous actual-year weather files, with known chronology; they are not TMY / TRY files", key="ige_s1_actual_year")
        st.caption("Up to 20 files; 12 MiB each and 128 MiB in total. The four nearest eligible years are selected after full annual checks. Missing values are not filled.")
    else:
        st.caption("Search: up to 20 nearest single-site stations within 100 km and 1500 m height difference; stop after four complete admitted donors. Values and QC are checked using H1. No complete donor set means no fabricated year. DE/CH station-service adapters remain separate work.")
    background = st.checkbox("Add ERA5-derived / NASA POWER background for wind, radiation, cloud and liquid rain to attempt a complete research EPW", key="ige_s1_background")
    if background:
        st.info("The EPW will be a mixed-source research year: T/p/moisture from station or EPW interpolation; other fields retain the background grid geometry and hourly pattern. Those other fields are not station-interpolated or height-corrected.")
    request = None
    try:
        request = PointRequest(lat, lon, height, reference, int(year), int(offset)*60, label,
                               assume_buck_water=phase, allow_nominal_height_proxy=proxy)
    except (ValueError, TypeError) as exc:
        st.caption("Enter the required elevation and its source / vertical reference to enable interpolation.")
    epws = [(file.name, file.getvalue()) for file in uploads]
    identity = {"request": request.to_dict() if request else None, "source": source,
                "epws": [sha256(body).hexdigest() for name, body in epws], "actual_year_confirmed": confirmed,
                "include_background": background}
    ready = request is not None and phase and proxy and (not source.startswith("Upload") or (len(epws) >= 4 and confirmed))
    st.caption("Only the button below sends requests. Editing the map, fields or files does not acquire weather data. Independent accuracy and production readiness are not qualified.")
    if st.button("Check donors and interpolate year", type="primary", key="ige_s1_build", disabled=not ready):
        st.session_state.pop(ERROR_KEY, None); st.session_state.pop(ERROR_REQUEST_KEY, None)
        try:
            with st.status("Checking donor years and applying height corrections", expanded=True) as status:
                def progress(message):
                    status.update(label=str(message)); st.write(str(message))
                product = run_point_product(request, mode="EPW" if source.startswith("Upload") else "GEOSPHERE",
                    epws=epws, actual_year_confirmed=confirmed, include_background=background, progress=progress)
                status.update(label="Point-year calculation and source report completed", state="complete", expanded=False)
            st.session_state[PRODUCT_KEY] = product
            st.session_state[REQUEST_KEY] = identity
        except Exception as exc:
            st.session_state[ERROR_KEY] = f"{type(exc).__name__}: {exc}"
            st.session_state[ERROR_REQUEST_KEY] = identity
    if st.session_state.get(ERROR_KEY):
        current_error = st.session_state.get(ERROR_REQUEST_KEY) == identity
        st.error(("This request" if current_error else "Previous request")+" failed: "+st.session_state[ERROR_KEY])
    product = st.session_state.get(PRODUCT_KEY)
    if not isinstance(product, PointProduct): return
    current = st.session_state.get(REQUEST_KEY) == identity
    st.divider()
    st.subheader("Point-year result" if current else "Previous point-year result")
    if not current: st.warning("The downloads below belong to the previous completed point, year and source selection.")
    r, report = product.request, product.report
    st.write(f"{r.label} · {r.latitude:.5f}°, {r.longitude:.5f}° · {r.elevation_m:g} m · {r.year}")
    if report["status"] == "POINT_YEAR_COMPLETE_RESEARCH":
        st.success(f"{report['hours']:,} hours of T / p / water vapour / RH / dew point reconstructed")
        st.caption(f"Maximum change from the uncorrected donor blend: temperature {report['max_abs_temperature_height_correction_K']:.3f} K; pressure {report['max_abs_pressure_height_correction_pa']/100:.3f} hPa. Complete correction and saturation ledgers are in the ZIP.")
        if report["target_height_outside_donor_envelope"]:
            st.warning("The target elevation is outside the selected donors' height range. This is vertical extrapolation within the operational limit; local accuracy is unqualified.")
        if report["target_outside_horizontal_donor_hull"]:
            st.warning("The point lies outside the horizontal donor hull. The result includes spatial extrapolation; local representativeness is unqualified.")
        frame = pd.read_csv(io.BytesIO(gzip.decompress(product.files["hourly.csv.gz"])), index_col=0)
        frame.index = pd.to_datetime(frame.index, utc=True)
        monthly = frame[[T, P, RH]].resample("MS").mean()
        monthly[P] /= 100
        st.dataframe(monthly.rename(columns={T: "Mean T [°C]", P: "Mean p [hPa]", RH: "Mean RH [%]"}), width="stretch")
    else:
        st.warning("A complete point year cannot be reconstructed from this donor set. The report lists every admission failure.")
        st.write(report["global_blockers"])
    rows = report["donor_admission"]
    if rows:
        table = pd.DataFrame(rows)
        st.dataframe(table[["station_id", "distance_km", "temperature_elevation_m", "pressure_elevation_m", "eligible", "selected", "reasons"]].rename(
            columns={"station_id": "Donor", "distance_km": "Distance [km]", "temperature_elevation_m": "T/RH altitude [m]",
                     "pressure_elevation_m": "Pressure altitude [m]", "eligible": "Admitted", "selected": "Selected", "reasons": "Admission failures"}),
                     hide_index=True, width="stretch")
        st.caption("The report includes complete per-variable hour counts. For station inputs the ZIP also contains the H1 source admission and exact missing-hour ranges for every checked station.")
    stem = f"IGE_point_{r.year}_RESEARCH"
    if "climate.epw" in product.files:
        st.success("Complete mixed-source research EPW passed the existing format and bounds screen.")
        st.download_button("Download interpolated research EPW", product.files["climate.epw"], file_name=stem+".epw", key="ige_s1_download_epw")
    else:
        st.warning("EPW is not available: "+"; ".join(report["EPW_blockers"]))
    st.download_button("Download point year, sources and correction ledgers", product.archive, file_name=stem+".zip", mime="application/zip", key="ige_s1_download_zip")
    st.download_button("Download point-year report", product.files["report.json"], file_name=stem+"_report.json", mime="application/json", key="ige_s1_download_report")
    st.download_button("Download point hourly data (CSV gzip)", product.files["hourly.csv.gz"], file_name=stem+".csv.gz", mime="application/gzip", key="ige_s1_download_csv")
    with st.expander("Method, source assumptions and quality status"):
        st.json({key: report[key] for key in ("method", "quality", "limitations", "selected_base_sha256", "future_base_status")})
