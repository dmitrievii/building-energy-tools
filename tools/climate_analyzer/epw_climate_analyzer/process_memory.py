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
    for pid in sorted(pids|{os.getpid()}):
        base=Path("/proc")/str(pid)
        try:
            row=_read_kb(base/"status",{"VmRSS":"rss","RssAnon":"rss_anon","RssFile":"rss_file","RssShmem":"rss_shmem"})
            row.update(pid=pid,category=_category((base/"comm").read_text().strip()),app=pid==os.getpid())
            rows.append(row)
        except (OSError,ValueError):errors+=1
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
            "scope":"Cgroup procs of selected finite limit and visible descendants; PID namespace/permissions can hide processes. RSS can double-count shared pages; PSS is partial. No cmdline, arguments or environment."}
