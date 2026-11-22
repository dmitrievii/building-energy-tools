"""On-demand, bounded read-only cgroup process accounting. No command lines."""
from pathlib import Path
from time import monotonic
import os
from .p66_memory import _memory_reading

def _read_kb(path,fields):
    result={}
    for line in path.read_text().splitlines():
        key,sep,value=line.partition(":")
        if sep and key in fields:
            parts=value.split()
            if parts and parts[0].isdigit():result[fields[key]]=int(parts[0])*1024
    return result

def _category(comm):
    name=comm.casefold()
    if name.startswith(("python","streamlit")):return "Python"
    if name.startswith(("chrome","chromium","kaleido")):return "Browser/renderer"
    if name.startswith("node"):return "Node"
    return "Other"

def _identity(base,uptime,app_script):
    """Emit only allowlisted classifications, not argv, paths or environment."""
    result={}
    try:
        tail=(base/"stat").read_text().rsplit(")",1)[1].split()
        result.update(parent_pid=int(tail[1]),process_state=tail[0],
                      start_ticks=int(tail[19]),
                      age_seconds=max(0.,uptime-int(tail[19])/os.sysconf("SC_CLK_TCK")))
    except (OSError,ValueError,IndexError):pass
    try:
        with (base/"cmdline").open("rb") as f:raw=f.read(32768)
        tokens=raw.rstrip(b"\x00").split(b"\x00")
        if len(raw)==32768:result["argv_classification"]="truncated"
        else:
            args=[os.fsdecode(t) for t in tokens if t]
            exe_names=[Path(t).name.casefold() for t in args[:3]]
            streamlit=any(t=="streamlit" or t.startswith("streamlit.") for t in exe_names)
            script_args=[t for t in args if t.lower().endswith(".py")]
            matches=False
            for arg in script_args:
                # Resolve only against the process's cwd, never inspect the
                # target file contents or expose a raw path.
                candidate=Path(arg)
                if not candidate.is_absolute():candidate=(base/"cwd").resolve()/candidate
                if candidate.resolve()==app_script:matches=True
            result.update(argv_classification="classified",streamlit_launcher=streamlit,
                          climate_app_target=matches,
                          role_hint=("climate-analyzer-launcher" if streamlit and matches else
                                     "climate-analyzer-script" if matches else
                                     "other-streamlit" if streamlit else "unclassified"))
    except (OSError,ValueError,RuntimeError):result["argv_classification"]="unavailable"
    return result

def _relationships(rows):
    by_pid={r["pid"]:r for r in rows}
    current=next((r for r in rows if r["app"]),None)
    if current is None:return
    def ancestors(row):
        seen=set()
        parent=row.get("parent_pid")
        while parent in by_pid and parent not in seen:
            seen.add(parent)
            parent=by_pid[parent].get("parent_pid")
        return seen
    own_ancestors=ancestors(current)
    for row in rows:
        parent=row.get("parent_pid")
        row["relation_to_app"]=("self" if row["app"] else "ancestor" if row["pid"] in own_ancestors else
            "descendant" if current["pid"] in ancestors(row) else
            "sibling" if parent is not None and parent==current.get("parent_pid") else "other/unknown")
        if row["app"]:row["role_hint"]="current-app"

def container_process_inventory(*,max_groups=64,max_pids=128,max_smaps=24):
    reading=_memory_reading()
    if reading is None:return {"status":"unavailable: no finite cgroup"}
    root=reading[2]
    started=monotonic()
    pids=set();groups=0;limited=False;errors=0
    for directory,dirs,_ in os.walk(root):
        groups+=1
        if groups>max_groups:limited=True;break
        try:
            for raw in (Path(directory)/"cgroup.procs").read_text().split():
                if raw.isdigit():pids.add(int(raw))
                if len(pids)>=max_pids:limited=True;break
        except OSError:errors+=1
        if limited:break
    rows=[]
    app_script=(Path(__file__).resolve().parents[1]/"app.py").resolve()
    try:uptime=float(Path("/proc/uptime").read_text().split()[0])
    except (OSError,ValueError,IndexError):uptime=0.
    for pid in sorted(pids|{os.getpid()}):
        base=Path("/proc")/str(pid)
        try:
            row=_read_kb(base/"status",{"VmRSS":"rss","RssAnon":"rss_anon","RssFile":"rss_file","RssShmem":"rss_shmem"})
            row.update(pid=pid,category=_category((base/"comm").read_text().strip()),app=pid==os.getpid())
            if row["category"]=="Python" or row["app"]:
                row.update(_identity(base,uptime,app_script))
            else:
                try:
                    tail=(base/"stat").read_text().rsplit(")",1)[1].split()
                    row.update(parent_pid=int(tail[1]),start_ticks=int(tail[19]),process_state=tail[0])
                except (OSError,ValueError,IndexError):pass
            rows.append(row)
        except (OSError,ValueError):errors+=1
    _relationships(rows)
    rows.sort(key=lambda p:p.get("rss_anon",0),reverse=True)
    for row in rows[:max_smaps]:
        try:row.update(_read_kb(Path("/proc")/str(row["pid"])/"smaps_rollup",
                          {"Pss":"pss","Pss_Anon":"pss_anon","Private_Dirty":"private_dirty"}))
        except (OSError,ValueError):pass
    return {"status":"partial" if limited or errors else "sampled","sampled":len(rows),
            "limited":limited,"read_errors":errors,"groups":min(groups,max_groups),
            "rss_anon_sum":sum(p.get("rss_anon",0) for p in rows),
            "pss_anon_sample_sum":sum(p.get("pss_anon",0) for p in rows),
            "pss_anon_sample_count":sum("pss_anon" in p for p in rows),
            "processes":rows,"seconds":monotonic()-started,
            "other_climate_app_candidates":[r["pid"] for r in rows if not r["app"] and r.get("climate_app_target")],
            "other_python_anon_bytes":sum(r.get("rss_anon",0) for r in rows if r["category"]=="Python" and not r["app"]),
            "scope":"Cgroup procs of selected finite limit and visible descendants; PID namespace/permissions can hide processes. RSS can double-count shared pages; PSS is partial. Only allowlisted argv classification, never raw command lines, arguments, paths or environment. Matching a launch target is not proof of an active duplicate runtime."}
