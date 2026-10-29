"""Private offline acceptance harness around the actual public app/components.

Never a deployment entrypoint. Only network acquisition is replaced with
hash-pinned, disclosed source packets. Production admission and solvers run.
"""
from pathlib import Path
from hashlib import sha256
import os
import json
import runpy
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"tools/climate_analyzer"), str(ROOT/"research/ige_cmip6")]
import streamlit as st
from epw_climate_analyzer.engine_application import run_historical_product, pilot_historical_request
from epw_climate_analyzer import future_selected, point_interpolation_ui, point_interpolation
from epw_climate_analyzer.engine.f1_sources import SignalRequest
from epw_climate_analyzer.engine.station_epw_admission import StationYearRequest
from epw_climate_analyzer.geosphere_station_year import run_station_year, read_sources
from epw_climate_analyzer.geosphere import parse_stations

DATA = ROOT/"research/ige_cmip6"


@st.cache_resource(show_spinner=False)
def inputs():
    bg = run_historical_product(pilot_historical_request())
    c = json.loads((DATA/"h1_graz16412_2023_source_contract_20261028.json").read_bytes())
    h1 = (DATA/c["source_packet"]).read_bytes()
    _, captured = read_sources(h1, c["source_packet_sha256"])
    metadata = json.loads(captured[0][2])
    station = next(s for s in parse_stations(metadata) if s.station_id == "16412")
    nex = (DATA/"f1_nex_graz_original_point_sources_20261029.zip").read_bytes()
    assert sha256(nex).hexdigest() == "2df672bc6cb2929ca4f59fb8eed061b46561849c0e716a7419d5c56d938b69bd"
    return bg, c, h1, metadata, station, nex


bg, h1_contract, h1_bytes, metadata, station, nex = inputs()


def replay_nasa(request, **kwargs):
    if request.to_dict() != SignalRequest(47.0707, 15.4395).to_dict():
        raise ValueError("VISUAL_HARNESS_NO_UNREGISTERED_SOURCE_REQUEST")
    return nex


def replay_point(request, **kwargs):
    if kwargs.get("include_background"):
        kwargs.update(background_packet=bg.files["sources.zip"],
            background_sha256=sha256(bg.files["sources.zip"]).hexdigest())
    return point_interpolation.run_point_product(request, **kwargs)


future_selected.acquire_nex = replay_nasa
point_interpolation_ui.run_point_product = replay_point
if not st.session_state.get("_ige_visual_seeded"):
    st.session_state["ige_engine_completed_product"] = bg
    st.session_state["ige_engine_completed_request"] = pilot_historical_request().to_dict()
    st.session_state["_ige_visual_seeded"] = True

if st.query_params.get("visual") == "h1":
    from epw_climate_analyzer import station_year_ui
    def replay_station(request, **kwargs):
        if (request.station_id, request.year, request.utc_offset_minutes) != ("16412", 2023, 60):
            raise ValueError("VISUAL_HARNESS_NO_UNREGISTERED_STATION_YEAR")
        return run_station_year(StationYearRequest(**h1_contract["request"]),
            source_packet=h1_bytes, expected_sha256=h1_contract["source_packet_sha256"])
    station_year_ui.run_station_year = replay_station
    st.set_page_config(page_title="IGE H1 offline visual acceptance", layout="wide")
    st.caption("OFFLINE ACCEPTANCE · real disclosed Graz source · not an independent accuracy test")
    station_year_ui.render_station_year(st, station, metadata)
else:
    runpy.run_path(str(ROOT/"tools/climate_analyzer/app.py"), run_name="__main__")
if os.environ.get("IGE_VISUAL_OUT"):
    keys = ["ige_point_latitude", "ige_point_longitude", "ige_point_selected_coordinates", "ige_point_height_m",
        "ige_point_height_reference", "ige_s1_phase", "ige_s1_height_proxy", "ige_s1_actual_year", "ige_s1_source"]
    state = {k: st.session_state.get(k) for k in keys}
    state["uploaded_EPWs"] = [f.name for f in st.session_state.get("ige_s1_epws", [])]
    with (Path(os.environ["IGE_VISUAL_OUT"])/"widget-state.jsonl").open("a") as stream:
        stream.write(json.dumps(state)+"\n")
