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
                resolved=candidate.resolve()
                if resolved==app_script:matches=True
                if resolved==app_script.parent/"scripts"/"run_managed_climate.py":
                    matches=True
                    streamlit=True
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

def socket_inventory(pid,*,max_fds=2048,max_rows=20000):
    """Read-only FD inode correlation. No endpoint addresses, remote ports or payload."""
    base=Path("/proc")/str(pid)
    inodes=set()
    try:
        with os.scandir(base/"fd") as entries:
            for i,entry in enumerate(entries):
                if i>=max_fds:return {"status":"partial: fd limit"}
                try:target=os.readlink(entry.path)
                except OSError:return {"status":"partial: fd changed or inaccessible"}
                if target.startswith("socket:[") and target.endswith("]"):
                    inodes.add(target[8:-1])
    except OSError:return {"status":"unavailable: fd access"}
    found=set();listeners=[];established=0;other_tcp=0;udp=0;unix=0
    tcp_states={}
    state_names={"01":"ESTABLISHED","02":"SYN_SENT","03":"SYN_RECV","04":"FIN_WAIT1",
                 "05":"FIN_WAIT2","06":"TIME_WAIT","07":"CLOSE","08":"CLOSE_WAIT",
                 "09":"LAST_ACK","0A":"LISTEN","0B":"CLOSING","0C":"NEW_SYN_RECV"}
    try:
        for name in ("tcp","tcp6","udp","udp6","unix"):
            with (base/"net"/name).open() as f:
                next(f,None)
                for i,line in enumerate(f):
                    if i>=max_rows:return {"status":"partial: network table limit"}
                    fields=line.split()
                    inode=fields[6] if name=="unix" else fields[9]
                    if inode not in inodes:continue
                    found.add(inode)
                    if name=="unix":unix+=1
                    elif name.startswith("udp"):udp+=1
                    else:
                        state=state_names.get(fields[3],"UNKNOWN")
                        tcp_states[state]=tcp_states.get(state,0)+1
                        if state=="LISTEN":listeners.append(int(fields[1].rsplit(":",1)[1],16))
                        elif state=="ESTABLISHED":established+=1
                        else:other_tcp+=1
    except (OSError,IndexError,ValueError):return {"status":"partial: network table unavailable"}
    return {"status":"sampled","socket_fds_unique":len(inodes),"tcp_listen_ports":sorted(set(listeners)),
            "tcp_established":established,"tcp_other":other_tcp,"tcp_states":tcp_states,"udp":udp,"unix":unix,
            "unclassified_sockets":len(inodes-found),
            "scope":"FD/socket snapshot; no user-session or routing guarantee."}

def _orphan_assessment(row,current):
    if row.get("app") or not (row.get("streamlit_launcher") and row.get("climate_app_target")):
        return "not-candidate"
    if row.get("parent_pid")!=1 or not row.get("start_ticks",0)<current.get("start_ticks",0):
        return "blocked: ancestry or age"
    sockets=row.get("sockets",{})
    if sockets.get("status")!="sampled":return "blocked: incomplete socket evidence"
    if any(sockets.get(k,0) for k in ("tcp_established","tcp_other","udp","unclassified_sockets")):
        return "blocked: network activity or unknown sockets"
    if sockets.get("tcp_listen_ports") or sockets.get("unix"):
        return "review: older reparented listener; routing/ownership not proved"
    return "review: older reparented process with no observed sockets; operator verification required"

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
    current=next((row for row in rows if row["app"]),{})
    for row in rows:
        if row["app"] or row.get("climate_app_target"):
            row["sockets"]=socket_inventory(row["pid"])
            row["orphan_assessment"]=_orphan_assessment(row,current)
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
