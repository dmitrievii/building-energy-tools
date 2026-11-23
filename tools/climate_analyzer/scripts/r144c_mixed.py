"""B5/B6 matched A0/A2 mixed-source campaign; retain all raw evidence."""
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import threading
import time
from r144a_factorial import APP,ROOT,health,stop,sample,cgroup,write

OUT=ROOT/"artifacts/r144c"
ORDER=("A0","A2")
CYCLES=6

def summarize(data,external):
    if data.get("error") or data.get("schema")!="R144C-MIXED":raise AssertionError("Failed mixed source workload")
    rows=data["samples"]
    expected=[(i,k) for i in range(1,CYCLES+1) for k in (("epw","geo") if i%2 else ("geo","epw"))]
    if [(r["cycle"],r["kind"]) for r in rows]!=expected:raise AssertionError("Incomplete paired source coverage")
    if not external or not any("rss" in r for r in external):raise AssertionError("Missing external monitoring")
    measures={}
    for kind in ("epw","geo","combined"):
        series=[r["idle"]["memory"]["process_anon"] for r in rows if kind=="combined" or r["kind"]==kind]
        warm=series[4:] if kind=="combined" else series[2:]
        measures[kind]={"series_bytes":series,"warm_median_bytes":statistics.median(warm),"warm_drift_bytes":warm[-1]-warm[0],"final_bytes":warm[-1]}
    # Keep the provisional lifecycle threshold consistent with prior R14 gates.
    for kind,m in measures.items():
        if m["warm_drift_bytes"]>64*1024**2:raise AssertionError("Warm drift gate: "+kind)
    for key in ("rss","anon","pss","pss_anon","hwm","cgroup_used","cgroup_anon","cgroup_file"):
        values=[r[key] for r in external if key in r]
        measures["peak_"+key+"_bytes"]=max(values) if values else None
    return measures

def run(arm,fixture):
    dest=OUT/arm;dest.mkdir(parents=True,exist_ok=False)
    env=os.environ.copy()
    for k in ("MALLOC_ARENA_MAX","GLIBC_TUNABLES","IGE_R144B_EXTENDED","IGE_R143_PARITY","IGE_R14_NATIVE_OWNER","IGE_R14_DEGREE_FRAGMENT"):env.pop(k,None)
    env.update(IGE_R143_PERSISTENT_APP="0",IGE_R144B_THREAD_DIAGNOSTICS="1",STREAMLIT_SERVER_DISCONNECTED_SESSION_TTL="0",
               R144C_OUTPUT=str(dest),R144C_CYCLES=str(CYCLES),GEOSPHERE_SMOKE_FIXTURE=str(fixture),
               TARGET_URL="http://127.0.0.1:8513/")
    if arm=="A2":env["MALLOC_ARENA_MAX"]="2"
    server=None;watcher=None;halt=threading.Event();observations=[]
    try:
        with (dest/"server.log").open("w") as log:
            server=subprocess.Popen([sys.executable,str(APP/"scripts/run_managed_climate.py"),"--server.headless=true","--server.port=8513"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            health(server)
            actual=[e for e in Path(f"/proc/{server.pid}/environ").read_bytes().split(b"\0") if e.startswith(b"MALLOC_ARENA_MAX=")]
            if actual!=([b"MALLOC_ARENA_MAX=2"] if arm=="A2" else []):raise AssertionError("Exec environment mismatch")
            group=cgroup(server.pid);start=time.monotonic()
            def monitor():
                while not halt.is_set():
                    observations.append({"elapsed_s":time.monotonic()-start,**sample(server.pid,group)})
                    halt.wait(.5)
            watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
            subprocess.run(["node","deployment/r144c_mixed_memory.mjs"],cwd=ROOT,env=env,check=True,timeout=2100)
    finally:
        halt.set()
        if watcher:watcher.join(5)
        stop(server)
        write(dest/"external.json",observations)
    result=summarize(json.loads((dest/"mixed.json").read_text()),observations)
    write(dest/"metrics.json",result)
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    fixture=OUT/"provider-fixture.json"
    subprocess.run([sys.executable,"deployment/geosphere_precip_snow_provider_probe.py","--output",str(fixture),"--timeout","60"],cwd=ROOT,check=True,env={**os.environ,"PYTHONPATH":str(APP)})
    results={};errors={}
    for arm in ORDER:
        try:results[arm]=run(arm,fixture)
        except Exception as exc:
            errors[arm]=f"{type(exc).__name__}: {exc}";print(arm,errors[arm],flush=True)
    comparison={}
    if len(results)==2:
        for k in ("epw","geo","combined"):
            a=results["A0"][k]["warm_median_bytes"];b=results["A2"][k]["warm_median_bytes"]
            comparison[k]={"delta_bytes":b-a,"percent":100*(b-a)/a}
    payload={"schema":"R144C","order":ORDER,"cycles_per_arm":CYCLES,"arms":results,"errors":errors,"comparison":comparison,
             "limitations":"One same-runner block, live provider transport varies; six short 10-minute provider intervals per arm, no concurrency or generated-climate endurance claim; cgroup includes runner and browser."}
    write(OUT/"comparison.json",payload);print(json.dumps(payload,indent=2))
    if errors:raise SystemExit(1)
if __name__=="__main__":main()
