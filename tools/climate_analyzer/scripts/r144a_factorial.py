"""R14.4A: matched real-app factorial arms; only CI, no production changes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

APP=Path(__file__).resolve().parents[1]
ROOT=APP.parents[1]
OUT=APP/"artifacts/r144a"
RAW=APP/"artifacts/mem-perf-r12-hf1"
ARMS={"A0":("0",None),"A1":("1",None),"A2":("0","2"),"A3":("1","2")}
ORDER=("A0","A3","A1","A2")
MIB=1024**2

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True),encoding="utf-8")

def fields(path,keys):
    result={}
    try:
        for line in path.read_text().splitlines():
            tag,_,value=line.partition(":")
            if tag in keys:result[keys[tag]]=int(value.split()[0])*1024
    except (OSError,ValueError,IndexError):pass
    return result

def cgroup(pid):
    try:
        line=next(x for x in Path(f"/proc/{pid}/cgroup").read_text().splitlines() if x.startswith("0::"))
        return Path("/sys/fs/cgroup")/line[3:].lstrip("/")
    except (OSError,StopIteration):return None

def sample(pid,group):
    base=Path(f"/proc/{pid}")
    row=fields(base/"status",{"VmRSS":"rss","RssAnon":"anon","VmHWM":"hwm"})
    row.update(fields(base/"smaps_rollup",{"Pss":"pss","Pss_Anon":"pss_anon"}))
    if group:
        try:row["cgroup_used"]=int((group/"memory.current").read_text())
        except (OSError,ValueError):pass
        try:
            for line in (group/"memory.stat").read_text().splitlines():
                k,v=line.split()
                if k in ("anon","file","inactive_file"):row["cgroup_"+k]=int(v)
        except (OSError,ValueError):pass
    return row

def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=20)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()

def health(proc):
    for _ in range(60):
        if proc.poll() is not None:raise RuntimeError("Server terminated before health check")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8513/_stcore/health",timeout=1) as response:
                if response.status==200:return
        except OSError:pass
        time.sleep(1)
    raise RuntimeError("Server health timeout")

def run_arm(name,cycles,parity=False):
    persistent,arena=ARMS[name]
    dest=OUT/("parity" if parity else "performance")/name
    dest.mkdir(parents=True,exist_ok=False)
    if RAW.exists():raise RuntimeError("Raw artifact directory already exists; refusing to overwrite")
    RAW.mkdir(parents=True)
    env=os.environ.copy()
    for key in ("MALLOC_ARENA_MAX","GLIBC_TUNABLES","IGE_R143_PARITY","IGE_R14_NATIVE_OWNER","IGE_R14_DEGREE_FRAGMENT"):
        env.pop(key,None)
    env.update(IGE_R143_PERSISTENT_APP=persistent,HF1_CYCLES=str(cycles),STREAMLIT_SERVER_DISCONNECTED_SESSION_TTL="0")
    if arena:env["MALLOC_ARENA_MAX"]=arena
    if parity:env["IGE_R143_PARITY"]="1"
    args=[sys.executable,str(APP/"scripts/run_managed_climate.py"),"--server.headless=true","--server.port=8513"]
    server=browser=None
    samples=[]; events=[]; started=time.monotonic(); halt=threading.Event(); watcher=None
    meta={"arm":name,"persistent":int(persistent),"arena":int(arena) if arena else None,"cycles":cycles,
          "parity":parity,"git_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
          "fixture_sha256":hashlib.sha256((ROOT/"research/ige_cmip6/at_graz2021_point_original_output_20261102.epw").read_bytes()).hexdigest(),
          "cpu_count":os.cpu_count(),"python":sys.version,"platform":os.uname().release,
          "scope":"Same runner, fresh application and browser per arm; sampled PSS/cgroup includes diagnostic overhead, cgroup includes other runner processes."}
    try:
        with (dest/"server.log").open("w",encoding="utf-8") as log:
            server=subprocess.Popen(args,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            health(server)
            # Verify cooperative duplicate-launch exclusion without loading a second app.
            duplicate=subprocess.run(args[:-1]+["--server.port=8514"],cwd=ROOT,env=env,
                                     capture_output=True,text=True,timeout=15)
            if duplicate.returncode==0 or "managed runtime already owns the instance lock" not in duplicate.stdout+duplicate.stderr:
                raise RuntimeError("Duplicate launch guard failed")
            group=cgroup(server.pid)
            if not parity:
                def watch():
                    while not halt.is_set():
                        samples.append({"elapsed_s":time.monotonic()-started,**sample(server.pid,group)})
                        halt.wait(0.5)
                watcher=threading.Thread(target=watch,daemon=True);watcher.start()
            browser_started=time.monotonic()
            browser=subprocess.Popen(["node","scripts/mem_perf_r12_hf1_browser.mjs"],cwd=APP,env=env,
                                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
            with (dest/"browser.log").open("w",encoding="utf-8") as out:
                for line in browser.stdout:
                    print(name,line.rstrip(),flush=True);out.write(line);out.flush()
                    m=re.search(r"Completed real EPW cycle (\d+) idle anon (\d+)",line)
                    if m:events.append({"cycle":int(m[1]),"elapsed_s":time.monotonic()-browser_started,
                                        "idle_anon":int(m[2])})
            rc=browser.wait()
            meta["browser_elapsed_s"]=time.monotonic()-browser_started
            meta["browser_exit_code"]=rc
            if rc!=0:raise RuntimeError(f"Browser qualification failed: {rc}")
    except BaseException as exc:
        meta["error"]=str(exc)
        raise
    finally:
        stop(browser);halt.set()
        if watcher:watcher.join(timeout=5)
        stop(server)
        write(dest/"run.json",meta);write(dest/"cycle_events.json",events)
        if not parity:write(dest/"samples.json",samples)
        if RAW.exists():shutil.move(str(RAW),str(dest/"inventory"))
    return dest

def summarize(dest):
    meta=json.loads((dest/"run.json").read_text())
    s=json.loads((dest/"inventory/summary.json").read_text())
    events=json.loads((dest/"cycle_events.json").read_text())
    n=meta["cycles"]
    if meta.get("error") or meta.get("browser_exit_code")!=0 or s.get("error") or s.get("completed")!=n or not s.get("warmGate"):
        raise AssertionError(f"Unqualified lifecycle: {dest}")
    idle=s["idle"]
    if len(idle)!=n or [x["cycle"] for x in events]!=list(range(1,n+1)):raise AssertionError("Incomplete cycle coverage")
    if any(x["active_sessions"]!=0 or x["closed_session_refs_alive"]!=0 or
           x["session_caches"]["entries"]!=0 or x["session_caches"]["owners"]!=0 or
           any(x["epw_lifecycle"].get("alive",{}).values()) for x in idle):
        raise AssertionError("Retained session resources")
    if any(x["allocator"].get("status")!="sampled" or x["allocator"].get("arena_max_env")!=meta["arena"] for x in idle):
        raise AssertionError("Allocator setting not verified in application")
    stages={r["stage"] for r in s["rows"]}
    if not {"concurrent-a","concurrent-b","graphs-b","reload"}.issubset(stages):raise AssertionError("Missing concurrency/lifecycle evidence")
    runtime=[r.get("persistentRuntime") or {} for r in s["rows"] if r["stage"]=="graphs-b"]
    if len(runtime)!=n:raise AssertionError("Missing runtime evidence")
    if meta["persistent"]:
        if any(r.get("persistent_compositions")!=1 or not r.get("persistent_reuses",0)>0 for r in runtime):
            raise AssertionError("Persistent path not exercised")
    elif any(r.get("persistent_compositions",0) for r in runtime):
        raise AssertionError("Baseline unexpectedly persistent")
    values=[x["memory"]["process_anon"] for x in idle]
    if values!=[x["idle_anon"] for x in events]:raise AssertionError("Idle log/JSON mismatch")
    samples=json.loads((dest/"samples.json").read_text())
    if not samples or not any("rss" in x for x in samples):raise AssertionError("External process sampling missing")
    def peak(key):
        v=[x[key] for x in samples if key in x]
        return max(v) if v else None
    def median_field(key):
        v=[x["allocator"][key] for x in idle[3:] if key in x["allocator"]]
        return statistics.median(v) if v else None
    intervals=[events[i]["elapsed_s"]-events[i-1]["elapsed_s"] for i in range(1,n)]
    blocks=[];pss=[];pss_anon=[]
    for path in sorted((dest/"inventory").glob("*_idle-observer.json")):
        d=json.loads(path.read_text())
        if isinstance(d.get("python_allocated_blocks"),int):blocks.append(d["python_allocated_blocks"])
        if "Pss" in d.get("process_smaps",{}):pss.append(d["process_smaps"]["Pss"])
        for proc in d.get("container_processes",{}).get("processes",[]):
            if proc.get("relation_to_app")=="self" and "pss_anon" in proc:pss_anon.append(proc["pss_anon"])
    return {**meta,"qualification":"PASS","idle_anon_bytes":values,
            "warm_median_anon_bytes":statistics.median(values[3:]),"final_idle_anon_bytes":values[-1],
            "warm_drift_bytes":values[-1]-values[3],"warm_range_bytes":max(values[3:])-min(values[3:]),
            "median_cycle_s":statistics.median(intervals[2:]),"cycle_intervals_s":intervals,
            "sample_count":len(samples),"sampled_peak_rss_bytes":peak("rss"),"sampled_peak_anon_bytes":peak("anon"),
            "sampled_peak_pss_bytes":peak("pss"),"sampled_peak_pss_anon_bytes":peak("pss_anon"),
            "process_hwm_bytes":peak("hwm"),"sampled_peak_cgroup_used_bytes":peak("cgroup_used"),
            "sampled_peak_cgroup_anon_bytes":peak("cgroup_anon"),"sampled_peak_cgroup_file_bytes":peak("cgroup_file"),
            "observer_pss_bytes":pss,"observer_pss_anon_bytes":pss_anon,"observer_python_allocated_blocks":blocks,
            "warm_glibc_allocated_bytes":median_field("allocated_arena_bytes"),"warm_glibc_free_bytes":median_field("free_arena_bytes"),
            "allocation_scope":"Live Python allocated blocks (not allocation event counts); mallinfo2 is partial; observer PSS is not zero-session PSS."}

def effects(rows,key):
    a,b,c,d=(rows[x][key] for x in ARMS)
    if any(x is None for x in (a,b,c,d)):return None
    return {"runtime_default":b-a,"runtime_arena2":d-c,"allocator_baseline":c-a,
            "allocator_persistent":d-b,"interaction":d-b-c+a,"combined_vs_reference":d-a,
            "runtime_mean_effect":((b-a)+(d-c))/2,"allocator_mean_effect":((c-a)+(d-b))/2,
            "combined_percent":100*(d-a)/a if a else None}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--parity-arm",choices=tuple(ARMS))
    args=parser.parse_args()
    if args.parity_arm:
        run_arm(args.parity_arm,6,True);return
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"pip-freeze.txt").write_text(subprocess.check_output([sys.executable,"-m","pip","freeze"],text=True))
    rows={};failures={}
    for arm in ORDER:
        try:
            dest=run_arm(arm,20)
            rows[arm]=summarize(dest)
            write(dest/"metrics.json",rows[arm])
        except Exception as exc:
            failures[arm]=str(exc);print(arm,"FAIL",exc,flush=True)
    keys=("warm_median_anon_bytes","final_idle_anon_bytes","warm_drift_bytes","median_cycle_s","sampled_peak_rss_bytes",
          "sampled_peak_anon_bytes","sampled_peak_pss_bytes","sampled_peak_pss_anon_bytes","sampled_peak_cgroup_used_bytes")
    result={"schema":"R144A","order":ORDER,"arms":rows,"failures":failures,
            "effects":{k:effects(rows,k) for k in keys} if len(rows)==4 else {},
            "limitations":"One sequential same-runner block, no independent replication or statistical confidence intervals. Cgroup includes browser/runner; sampled peak is a lower bound. No automatic production selection."}
    write(OUT/"factorial.json",result);print(json.dumps(result,indent=2))
    if failures or len(rows)!=4:raise SystemExit(1)

if __name__=="__main__":main()
