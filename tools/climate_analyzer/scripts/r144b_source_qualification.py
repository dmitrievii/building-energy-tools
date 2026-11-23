"""Isolated real-app AppTest source fixtures; no provider transport claimed."""
from pathlib import Path
import os
import sys
import json
from dataclasses import replace
from unittest.mock import patch
from contextlib import ExitStack
import pandas as pd
from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
sys.path.insert(0,str(APP/"tests"))

def fixture(kind):
    if kind=="monthly":
        from test_geosphere_monthly_canonical_ui_0_7_5_3 import GeoSphereMonthlyCanonicalUiTests
        d=GeoSphereMonthlyCanonicalUiTests().dataset()
        return replace(d,provenance=replace(d.provenance,retrieval_time_utc="2026-01-01T00:00:00+00:00"))
    from test_canonical_hourly_pipeline_0_6_5 import CanonicalHourlyPipeline065Tests as T
    minutes=10 if kind=="ten-minute" else 60
    raw=T._ten_minute_frame()
    df=pd.concat([raw]*48,ignore_index=True)
    df.index=pd.date_range("2026-01-01",periods=len(df),freq=f"{minutes}min",tz="UTC")
    df.attrs.update(canonical_native_interval_minutes=minutes,canonical_calendar_mode="historical",canonical_timezone_name="UTC",
                    geosphere_resource_id="klima-v2-10min" if minutes==10 else "klima-v2-1h")
    df["precipitation_duration_min"]=0.
    return T._dataset(df,minutes)

def clean(app):
    if len(app.exception) or len(app.error):
        raise AssertionError({"exception":[x.message for x in app.exception],"error":[x.value for x in app.error]})

def chart(app,page):
    from epw_climate_analyzer.r143_scientific_parity import evidence
    from epw_climate_analyzer.chart_lifecycle import DISPLAYED
    from epw_climate_analyzer.p6_report import REPORT_KEY
    app.sidebar.radio(key="climate_analyzer_navigation").set_value(page).run()
    clean(app)
    state=app.session_state.filtered_state
    prior=evidence(state)
    if not prior["displayed"]:raise AssertionError("No registered chart on "+page)
    key=prior["displayed"][0]["key"]
    app.button(key=key).click().run()
    clean(app)
    after=evidence(app.session_state.filtered_state)
    if not any(x["complete"]==prior["displayed"][0]["complete"] for x in after["saved"]):
        # Exact capture witness independently addresses metadata created on rerun.
        cap=after.get("capture")
        if not cap or cap["before"]["complete"]!=cap["saved"]["complete"]:
            raise AssertionError("Report capture evidence missing on "+page)
    if not any(x["complete"]==prior["displayed"][0]["complete"] for x in after["displayed"]):
        raise AssertionError("Displayed chart changed across rerun on "+page)
    return {"before":prior["displayed"],"after":after}

def main():
    kind=sys.argv[1]; output=Path(sys.argv[2]); output.parent.mkdir(parents=True,exist_ok=True)
    with ExitStack() as stack:
        for target in ("socket.socket.connect","socket.socket.connect_ex"):
            stack.enter_context(patch(target,side_effect=AssertionError("R144B_NO_NETWORK")))
        stack.enter_context(patch("streamlit_folium.st_folium",return_value={}))
        app=AppTest.from_file(APP/"app.py",default_timeout=120).run()
        clean(app)
        app.session_state["active_canonical_climate"]=fixture(kind)
        app.session_state["climate_source_mode"]="GeoSphere Austria"
        app.session_state["climate_analyzer_navigation"]="Temperature"
        app.run();clean(app)
        result={}
        for page in ("Temperature","Precipitation and Snow"):
            result[page]=chart(app,page)
        # Confirm alternate climate/report navigation returns to an unchanged figure.
        app.sidebar.radio(key="climate_analyzer_navigation").set_value("Report").run();clean(app)
        app.sidebar.radio(key="climate_analyzer_navigation").set_value("Temperature").run();clean(app)
        from epw_climate_analyzer.r143_scientific_parity import evidence
        result["return"]=evidence(app.session_state.filtered_state)
        if not result["return"]["displayed"] or not result["return"]["saved"]:raise AssertionError("Return navigation lost chart/report")
        from epw_climate_analyzer.source_parity_runtime import runtime_stats
        stats=runtime_stats()
        if os.environ.get("IGE_R143_PERSISTENT_APP")=="1" and (stats.get("persistent_compositions")!=1 or not stats.get("persistent_reuses",0)):
            raise AssertionError("Persistent path not demonstrated")
        output.write_text(json.dumps({"kind":kind,"observations":result},sort_keys=True,indent=2))
        print(kind,"PASS",stats)

if __name__=="__main__":main()
