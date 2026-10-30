"""F1 explicit base choice; no data requests on map edits, uploads or rerenders."""
from __future__ import annotations

from hashlib import sha256

from .engine.f1_base import admit_base, SURFACE, COLLOCATED, MK, BUCK, epw_reference
from .engine.f1_sources import SignalRequest, admit_nex_packet, MAX_PACKET, SCENARIOS, SCENARIO_LABELS
from .engine_application import EngineProduct
from .future_selected import base_from_engine, base_from_point, run_selected_future

PRODUCT_KEY = "ige_f1_completed_product"
REQUEST_KEY = "ige_f1_completed_identity"


def _session_bases(st):
    """Keep original bases available after exploring their future product."""
    saved = dict(st.session_state.get("ige_f1_base_candidates", {}))
    def add(label, factory, sources):
        try:
            base = factory(); saved[base.sha256] = (base, sources)
        except (ValueError, KeyError, TypeError) as exc:
            st.warning(f"{label} is not admitted for F1: {exc}")
    engine = st.session_state.get("ige_engine_completed_product")
    if isinstance(engine, EngineProduct) and engine.report.get("calendar_mode") == "historical" and not engine.report.get("product_kind"):
        add("Completed background", lambda: base_from_engine(engine), {"selected_base.sources.zip": engine.files["sources.zip"]})
    point = st.session_state.get("ige_s1_point_product")
    if point is not None and "climate.epw" in getattr(point, "files", {}):
        add("Completed point year", lambda: base_from_point(point), {"selected_point.zip": point.archive})
    station = st.session_state.get("ige_h1_station_year_product")
    if station is not None and "climate.epw" in getattr(station, "files", {}):
        add("Completed station year", lambda: admit_base(station.files["climate.epw"], calendar_kind="ACTUAL_YEAR", pressure_contract=COLLOCATED,
            water_curve=BUCK, source_kind="IGE_H1_STATION_YEAR", provenance={"source_admission": station.report}),
            {"selected_station.sources.zip": station.files["sources.zip"]})
    saved = dict(list(saved.items())[-8:])
    st.session_state["ige_f1_base_candidates"] = saved
    return saved


def render_future_source(st, activate):
    st.subheader("Future climate from a selected base")
    st.write("Choose a complete annual weather pattern and its local climate reference. NASA monthly climate changes are applied to that reference while retaining the selected pattern's event sequence.")
    bases = _session_bases(st)
    choices = list(bases)+["ACTIVE_EPW", "UPLOAD_EPW"]
    def label(key):
        if key == "ACTIVE_EPW": return "Currently loaded / found EPW"
        if key == "UPLOAD_EPW": return "Upload a base EPW"
        b = bases[key][0]
        kind = {"IGE_B0_BACKGROUND": "Grid background", "IGE_S1_INTERPOLATED_POINT": "Interpolated point",
                "IGE_H1_STATION_YEAR": "Observed station year"}.get(b.identity["source_kind"], "EPW base")
        return f"{b.request.label} · {b.request.year} · {kind}"
    map_column, selection_column = st.columns([2, 1])
    choice = selection_column.selectbox("Selected annual base", choices, format_func=label, key="ige_f1_base_choice")
    base, retained, errors = None, {}, []
    body = None
    if choice in bases:
        base, retained = bases[choice]
        st.caption("The selected completed product supplies its own pressure and water conventions; its original EPW is retained unchanged.")
        if base.identity["source_kind"] == "IGE_H1_STATION_YEAR":
            st.caption("The station method uses Buck liquid-water humidity and the published pressure level as a collocated proxy. Unconfirmed sensor heights remain recorded in the source report.")
    else:
        if choice == "UPLOAD_EPW":
            upload = st.file_uploader("Base EPW", type=["epw"], key="ige_f1_base_upload")
            if upload is not None: body = upload.getvalue()
        else:
            active = st.session_state.get("active_climate_file")
            if active is not None: body = active.payload
            else: st.info("Load / find an EPW first, upload one here, or complete a historical background / S1 point year.")
        kind = st.selectbox("Base chronology", ["Representative / typical year", "Actual observed year"], key="ige_f1_calendar")
        curve = st.selectbox("Declared liquid-water convention", [MK, BUCK], key="ige_f1_curve")
        pressure_kind = st.selectbox("Pressure interpretation", [COLLOCATED, SURFACE], key="ige_f1_pressure")
        confirmed = st.checkbox("Accept the stated water convention and pressure interpretation as source assumptions; source sensor heights may be unconfirmed", key="ige_f1_source_assumptions")
        st.caption("For uploaded EPWs, q is derived from the declared water RH, T and pressure. Rounded source dew point is retained in the ledger. A surface proxy receives the conditional 0-to-2m adapter once; collocated pressure receives none.")
        if body is not None and confirmed:
            try:
                base = admit_base(body, calendar_kind="REPRESENTATIVE_YEAR" if kind.startswith("Representative") else "ACTUAL_YEAR",
                    pressure_contract=pressure_kind, water_curve=curve)
            except (ValueError, TypeError, UnicodeError) as exc: errors.append(str(exc))
    from .climate_maps import render_source_map, grid_markers, donor_markers
    if base is not None:
        rounding = base.identity.get("source_rounding_admission")
        if rounding:
            st.warning(f"Source rounding was reconciled in {rounding['hours']} hours for future-climate calculations. "
                       "Only the derived vapour was lowered to saturation at the original temperature; the original EPW is unchanged. The quality report retains every adjustment.")
        provenance = base.identity.get("source_provenance", {})
        markers = grid_markers({"source_geometry": provenance.get("geometry", {})})
        markers += donor_markers(provenance.get("donor_admission", []))
        signal_lat, signal_lon = base.identity["signal_site"]
        with map_column:
            st.caption("Same map and source colours as historical climate. The marker follows the selected annual base.")
            render_source_map(st, signal_lat, signal_lon, base.location.elevation_m,
                              markers, key="future_base_"+base.sha256[:12])
        with selection_column:
            st.write(f"Latitude: {base.location.latitude:.5f}°")
            st.write(f"Longitude: {base.location.longitude:.5f}°")
            st.write(f"Elevation: {base.location.elevation_m:g} m")
            if (signal_lat, signal_lon) != (base.location.latitude, base.location.longitude):
                st.caption(f"Selected request / NASA signal point: {signal_lat:.5f}°, {signal_lon:.5f}°. The base weather remains at the returned grid point shown in violet.")
            st.caption("The base fixes the location and elevation. Choose or generate another historical base to change them.")
    else:
        with map_column:
            st.info("Choose an admitted annual base to display its location and sources on the map.")
    cols = st.columns(2)
    cols[0].selectbox("GCM / member", ["CanESM5 / r1i1p1f1"], key="ige_f1_model")
    scenario = cols[1].selectbox("SSP scenario", SCENARIOS, index=1, format_func=SCENARIO_LABELS.get, key="ige_f1_ssp",
        help="SSP describes a socioeconomic and emissions pathway. The final number is approximate radiative forcing in W/m² in 2100, not a temperature increase or a probability.")
    st.caption("All four NASA NEX-GDDP-CMIP6 Tier-1 SSPs can be requested for CanESM5 / r1i1p1f1. Each request must pass the original-source, calendar and variable-definition checks before export. The retained full-year replay covers SSP2-4.5; the other pathways are not independently qualified by that example.")
    with st.expander("What do the SSP scenarios mean?"):
        st.write("SSP1-2.6: sustainability with low emissions. SSP2-4.5: an intermediate pathway. SSP3-7.0: regional rivalry with high emissions. SSP5-8.5: fossil-fuel-intensive development with very high emissions. These are alternative conditional futures; none is assigned a probability here.")
        st.write("The number indicates approximate radiative forcing by 2100 relative to pre-industrial conditions. Local warming depends on model, location and period. SSP1-1.9 and other CMIP6 experiments are not part of the four-scenario NEX product used here.")
        st.caption("NASA source documentation: https://www.nasa.gov/ames/earth-science/nasa-earth-exchange-nex/gddp/downscaled-climate-projections-nex-gddp-cmip6/")
    c = st.columns(4)
    r0 = int(c[0].number_input("Reference first year", 1950, 2025, 2002, key="ige_f1_ref_first"))
    r1 = int(c[1].number_input("Reference last year", 1950, 2025, 2014, key="ige_f1_ref_last"))
    f0 = int(c[2].number_input("Future first year", 2015, 2100, 2040, key="ige_f1_future_first"))
    f1 = int(c[3].number_input("Future last year", 2015, 2100, 2059, key="ige_f1_future_last"))
    st.caption("Both climate windows require 10–30 complete years. If the reference extends beyond 2014, the model reference uses the chosen SSP from 2015 onward.")
    modes = ["Separate compatible reference EPW"]
    if base is not None and base.calendar_kind == "REPRESENTATIVE_YEAR": modes.insert(0, "Selected representative base")
    if base is not None and base.identity["source_kind"] == "IGE_B0_BACKGROUND": modes.insert(0, "Same-chain multi-year background reference")
    mode = st.selectbox("Local climate reference", modes, key="ige_f1_reference_mode")
    reference_base, evidence = None, ""
    if mode != "Same-chain multi-year background reference":
        evidence = st.text_input("Evidence for the local reference period (provider, file documentation or source record)", key="ige_f1_period_evidence")
        st.caption("TMY row-year labels do not establish its climatic reference period. An actual year outside the reference cannot be treated as its climate normal.")
        if mode == "Separate compatible reference EPW":
            uploaded = st.file_uploader("Local reference EPW — same point, elevation and fixed UTC offset", type=["epw"], key="ige_f1_reference_upload")
            if uploaded is not None and base is not None:
                try:
                    reference_base = admit_base(uploaded.getvalue(), calendar_kind="REPRESENTATIVE_YEAR",
                        pressure_contract=base.pressure_contract, water_curve=base.water_curve)
                except (ValueError, TypeError, UnicodeError) as exc: errors.append(str(exc))
    else:
        st.caption("Uses complete source years at this background cell and height. A missing year or a changed source geometry blocks the reference. Other points require fresh source acquisition; the old Graz reference is reused only for an exact matching request.")
    liquid_proxy = st.checkbox("Allow the model total-precipitation change to scale liquid rain if total precipitation is unavailable; do not infer snowfall or total precipitation", key="ige_f1_liquid_proxy")
    source_mode = st.selectbox("NASA sources", ["Acquire original data / reuse matching completed request", "Use a saved original NASA source packet"], key="ige_f1_nasa_source_mode")
    source_upload = st.file_uploader("Original F1 NASA source ZIP", type=["zip"], key="ige_f1_nasa_upload") if source_mode.startswith("Use") else None
    nex_packet = source_upload.getvalue() if source_upload is not None else None
    nex_sha = sha256(nex_packet).hexdigest() if nex_packet is not None else None
    request, identity = None, None
    if base is not None:
        st.write(f"Selected base: {base.location.latitude:.5f}°, {base.location.longitude:.5f}° · {base.location.elevation_m:g} m · {len(base.data):,} hours")
        st.caption(f"Original EPW SHA256: {base.sha256}")
        try:
            request = SignalRequest(*base.identity["signal_site"], (r0, r1), (f0, f1), scenario=scenario)
            if mode != "Same-chain multi-year background reference":
                if reference_base is not None or mode == "Selected representative base":
                    epw_reference(base, base if mode == "Selected representative base" else reference_base,
                        request.reference_window, evidence)
                else:
                    errors.append("A compatible local reference EPW is required.")
            elif not 2002 <= r0 <= r1 <= 2025: errors.append("Background reference source window is 2002–2025.")
            if source_mode.startswith("Use"):
                if nex_packet is None: errors.append("Upload the original NASA packet for this exact point, model, scenario and periods.")
                elif len(nex_packet) > MAX_PACKET: errors.append("NASA packet exceeds the 120 MiB source budget.")
                else:
                    try: admit_nex_packet(nex_packet, nex_sha, request)
                    except Exception as exc: errors.append("NASA packet is not admitted: "+str(exc))
            if not liquid_proxy and ("total_precipitation_depth_mm" not in base.data or mode != "Same-chain multi-year background reference"):
                errors.append("Total precipitation is unavailable for this base/reference pair; explicitly allow the liquid-rain proxy or supply a reference with known total precipitation.")
            identity = {"base": base.identity, "request": request.to_dict(), "reference_mode": mode,
                "reference_sha256": reference_base.sha256 if reference_base is not None else None, "period_evidence": evidence,
                "liquid_proxy": liquid_proxy, "NASA_source_mode": source_mode, "NASA_upload_sha256": nex_sha}
        except (ValueError, TypeError) as exc: errors.append(str(exc))
    for error in errors: st.warning(error)
    st.caption("Build acquires the NASA sources for this exact request. Completed responses are saved for 24 hours on this app instance, so Retry can resume after a timeout. Matching retained original packets can be reused; other points, scenarios and periods require their own sources. A first request can take about 15 minutes. The ZIP retains all original data for reuse.")
    retry_current = st.session_state.get("ige_f1_error", (None,))[0] == identity and identity is not None
    if st.button("Retry future climate from this base" if retry_current else "Build future climate from this base", type="primary", key="ige_f1_build", disabled=base is None or request is None or bool(errors)):
        st.session_state.pop("ige_f1_error", None)
        try:
            previous = st.session_state.get(PRODUCT_KEY)
            if nex_packet is None and isinstance(previous, EngineProduct) and previous.report["future_request"] == request.to_dict():
                nex_packet = previous.files["source_packets/NASA_NEX_original.sources.zip"]
                nex_sha = sha256(nex_packet).hexdigest()
            with st.status("Checking the selected base and local reference", expanded=True) as status:
                def progress(message): status.update(label=str(message)); st.write(str(message))
                completed = run_selected_future(base, request,
                    reference_mode={"Selected representative base": "REPRESENTATIVE_BASE", "Separate compatible reference EPW": "SEPARATE_REFERENCE_EPW",
                        "Same-chain multi-year background reference": "BACKGROUND_REFERENCE"}[mode],
                    period_evidence=evidence, reference_base=reference_base,
                    nex_packet=nex_packet, nex_packet_sha256=nex_sha,
                    allow_liquid_precipitation_proxy=liquid_proxy, retained_sources=retained, progress=progress)
                status.update(label="Full future year and exports verified", state="complete", expanded=False)
            st.session_state[PRODUCT_KEY] = completed; st.session_state[REQUEST_KEY] = identity
        except Exception as exc:
            st.session_state["ige_f1_error"] = (identity, f"{type(exc).__name__}: {exc}")
        st.rerun()
    if st.session_state.get("ige_f1_error"):
        failed, error = st.session_state["ige_f1_error"]
        if "VAPOUR_ABOVE_SATURATION" in error or "DEWPOINT_OR_RADIATION_INCONSISTENT" in error:
            st.error(("Current request" if failed == identity else "Previous request")+" could not be admitted: "
                "the base or reference has inconsistent temperature and dew point. Known ERA5-derived 0.1°C rounding is handled with an explicit adjustment log; other supersaturation needs a separate source check. "
                "The previous completed result remains available.")
            with st.expander("Source diagnostic"):
                st.code(error)
        elif "F1_SOURCE_UNAVAILABLE" in error:
            st.error(("Current request" if failed == identity else "Previous request")+" could not finish: NASA's data service did not respond. "
                "Use Retry to resume from completed source downloads, or load a saved original NASA packet for this exact request. The previous completed climate is still available.")
            with st.expander("NASA connection diagnostic"):
                st.code(error)
        else:
            st.error(("Current request" if failed == identity else "Previous request")+" failed: "+error)
    product = st.session_state.get(PRODUCT_KEY)
    if not isinstance(product, EngineProduct): return
    from .engine_ui import _scope, _downloads
    st.divider()
    if st.session_state.get(REQUEST_KEY) != identity: st.warning("The downloads belong to the previous completed base and climate request.")
    st.success(f"{len(product.dataset.data):,} hourly records; full future research year verified")
    _scope(st, product); _downloads(st, product)
    st.caption(f"Complete ZIP SHA256 for offline replay: {sha256(product.archive).hexdigest()}")
    st.download_button("Download all hourly adjustments", product.files["adjustment_ledger.csv.gz"],
        file_name=product.download_stem+"_adjustments.csv.gz", key="ige_f1_ledger")
    with st.expander("Source contracts and qualification"):
        st.json({key: product.report[key] for key in ("quality", "base", "future_request", "limitations")})
    if st.button("Explore this future climate", type="primary", key="ige_f1_explore"):
        st.session_state["ige_engine_completed_product"] = product
        activate(product.dataset); st.rerun()
