"""R11 isolated measurement. Run from tool root; no production process mutations."""
from __future__ import annotations
import argparse
import gc
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
BASELINE="2d6c9631e93978c090c22d89973f4d18b045f9f2"

def snapshot():
    from epw_climate_analyzer.startup_runtime import _sample
    from collections import Counter
    names=tuple(sys.modules)
    groups=Counter(".".join(n.split(".")[:2]) for n in names if n.startswith("plotly."))
    return {**_sample(),"plotly_groups":dict(groups),
            "numba_modules":sum(n=="numba" or n.startswith("numba.") for n in names)}

def run_worker(variant):
    from epw_climate_analyzer import p66_memory as mem
    from epw_climate_analyzer import chart_presentation as present
    rows=[]; hashes={}
    def phase(name,fn):
        before=snapshot();start=time.perf_counter()
        value=fn()
        rows.append({"phase":name,"before":before,"after":snapshot(),"seconds":time.perf_counter()-start})
        return value
    def reclaim():
        gc.collect();mem._trim_allocator()
    def imports():
        import numpy,pandas,plotly.graph_objects,plotly.express,plotly.io
    phase("numpy pandas plotly imports",imports)
    from importlib import import_module
    phase("scipy import",lambda:import_module("scipy.interpolate"))
    phase("pvlib import",lambda:import_module("pvlib"))
    phase("psychrolib SI import",lambda:import_module("epw_climate_analyzer.psychrometrics"))
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    import plotly.io as pio
    from epw_climate_analyzer.psychrometrics import add_psychrometric_properties
    df=pd.DataFrame({"dry_bulb_temperature_c":np.linspace(-15,35,8760),
                     "relative_humidity_pct":np.linspace(30,90,8760),
                     "atmospheric_station_pressure_pa":101325.})
    for i in range(2):
        derived=phase("psychrometric derivation "+str(i+1),lambda:add_psychrometric_properties(df))
        del derived
        phase("psychrometric reclaim "+str(i+1),reclaim)
    if variant=="R10":
        # Load exact frozen implementation in this isolated process, retaining
        # relative imports. Never monkeypatch the running production module.
        source=subprocess.check_output(["git","show",BASELINE+":tools/climate_analyzer/epw_climate_analyzer/chart_presentation.py"],cwd=ROOT)
        exec(compile(source,"<frozen R10 chart presentation>","exec"),present.__dict__)
    settings=present.settings_from_state({})
    alternate=present.settings_from_state({"chart_presentation_show_grid":False,
                                           "chart_presentation_north_rotation":35})
    def cases():
        x=np.arange(8760)
        return [
            ("line",lambda:go.Figure(go.Scatter(x=x,y=np.sin(x/200)))),
            ("box",lambda:go.Figure(go.Box(y=np.sin(x/200)))),
            ("histogram",lambda:go.Figure(go.Histogram(x=np.sin(x/200)))),
            ("heatmap",lambda:go.Figure(go.Heatmap(z=np.arange(288).reshape(12,24),coloraxis="coloraxis"))),
            ("polar",lambda:go.Figure(go.Barpolar(r=[1,4,3,2],theta=[0,90,180,270]))),
            ("surface",lambda:go.Figure(go.Surface(z=np.arange(100).reshape(10,10)))),
            ("scatter3d",lambda:go.Figure(go.Scatter3d(x=[1,2],y=[2,3],z=[3,4]))),
        ]
    for repeat in range(2):
        for name,build in cases():
            key=f"{repeat+1}:{name}"
            fig=phase(key+" build",build)
            phase(key+" presentation",lambda:present.apply_chart_presentation(fig,settings if repeat==0 else alternate))
            payload=phase(key+" validated JSON",lambda:pio.to_json(fig,validate=True,remove_uids=True))
            canonical=json.dumps(json.loads(payload),sort_keys=True,separators=(",",":"))
            hashes[key]=hashlib.sha256(canonical.encode()).hexdigest()
            del fig,payload,canonical
            phase(key+" reclaim",reclaim)
    return {"variant":variant,"baseline":BASELINE,"samples":rows,"figure_hashes":hashes,"final":snapshot()}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--worker",choices=("R10","R11"))
    p.add_argument("--output",default="artifacts/mem-perf-r11/library_profile.json")
    p.add_argument("--repetitions",type=int,default=3)
    args=p.parse_args()
    if args.worker:
        print(json.dumps(run_worker(args.worker)));return
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    trials=[]
    for i in range(args.repetitions):
        for variant in (("R10","R11") if i%2==0 else ("R11","R10")):
            raw=subprocess.check_output([sys.executable,__file__,"--worker",variant],cwd=ROOT,text=True,timeout=240)
            trials.append(json.loads(raw.splitlines()[-1]))
    reference=trials[0]["figure_hashes"]
    parity=all(t["figure_hashes"]==reference for t in trials)
    output.write_text(json.dumps({"schema":"MEM-PERF-R11","trials":trials,"exact_figure_json_parity":parity,
                                  "scope":"isolated sequential synthetic chart-family trials; RSS deltas include native allocations and imports, not per-module ownership"},indent=2))
    print("Figure parity:",parity)
    if not parity:raise SystemExit(1)
if __name__=="__main__":main()
