"""MEM-PERF R1: explicitly owned session resources and memory lifecycle.

Never clear all Streamlit caches or session state. The active source, saved
report snapshots, comparison basket, generated source products, settings and
other user work are outside the disposable-resource allowlist.
"""
from __future__ import annotations

import gc
from pathlib import Path
from time import monotonic

from . import p66_memory as m

EXPORT_KEYS=("_p6_pdf","_p6_html_result","_p66_atlas_result","_utci_perf_r1_csv")
DERIVED_KEYS=("_utci_perf_r1_result","_utci_perf_r1_sensitivity")
TRANSIENT_KEYS=("_p6_displayed_charts","_active_filtered_export_df")
DISK_KEY="_p67_render_cache"
LAST_KEY="_mem_perf_r1_last_cleanup"
EXPORT_PRE_KEY="_mem_perf_r1_export_pre"
EXPORT_POST_KEY="_mem_perf_r1_export_post"
PAGE_KEY="_mem_perf_r1_page"
PRESSURE_KEY="_mem_perf_r1_pressure_at"
PRESSURE_FRACTION=.85
PRESSURE_COOLDOWN_S=30.

def memory_snapshot():
    """Cgroup totals are shared across sessions; process RSS is separate."""
    result={}
    reading=m._memory_reading()
    if reading is not None:
        used,cap,root=reading
        result.update(used=used,limit=cap)
        try:
            records={k:int(v) for k,v in (root/"memory.stat").read_text().splitlines()}
            for key,aliases in (("anonymous",("anon","total_rss","rss")),
                                ("file",("file","total_cache","cache")),
                                ("inactive_file",("total_inactive_file","inactive_file")),
                                ("shared",("shmem","total_shmem"))):
                for alias in aliases:
                    if alias in records:
                        result[key]=max(0,records[alias]);break
        except (OSError,ValueError):pass
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                result["process_rss"]=int(line.split()[1])*1024;break
    except (OSError,ValueError,IndexError):pass
    return result

def pressure_high(snapshot):
    used,limit=snapshot.get("used"),snapshot.get("limit")
    if used is None or not limit:return False
    # Match the conservative half-credit for inactive ordinary file cache.
    inactive=min(snapshot.get("inactive_file",0),
                 max(0,snapshot.get("file",0)-snapshot.get("shared",0)),used)
    return (used-max(0,inactive)//2)>=PRESSURE_FRACTION*limit

def _drop(state,keys):
    removed=[]
    for key in keys:
        if key in state:
            state.pop(key,None)
            removed.append(key)
    return removed

def cleanup(state,reason,*,exports=False,derived=False,transient=False,disk=False):
    """Release selected owned references; sample before/after actual collection.

    A disk cache belongs to this session, but do not remove it while any export
    holds the process export lock. Never kill another session's renderer.
    Memory changes are observations, not attribution or an OOM guarantee.
    """
    before=memory_snapshot()
    removed=[];warnings=[]
    if exports:removed.extend(_drop(state,EXPORT_KEYS))
    if derived:removed.extend(_drop(state,DERIVED_KEYS))
    if transient:removed.extend(_drop(state,TRANSIENT_KEYS))
    if disk and DISK_KEY in state:
        if m.EXPORT_LOCK.acquire(blocking=False):
            try:
                obj=state.get(DISK_KEY)
                if obj is not None:
                    try:
                        obj.cleanup()
                        state.pop(DISK_KEY,None)
                        removed.append(DISK_KEY)
                    except (OSError,AttributeError) as exc:
                        warnings.append("Private render cache cleanup failed: "+str(exc))
            finally:m.EXPORT_LOCK.release()
        else:warnings.append("Private render cache retained while an export is active.")
    gc.collect()
    m._trim_allocator()
    after=memory_snapshot()
    result={"reason":reason,"before":before,"after":after,"released":removed,"warnings":warnings}
    state[LAST_KEY]=result
    return result

def prepare_export(state):
    """Run before the new export, preferably in the widget click callback.

    Old downloads must be released before fresh chart/renderer allocation.
    Retain the image cache for reuse unless actual memory pressure warrants
    cleanup. Saved report entries and source frames are never deleted.
    """
    result=cleanup(state,"Before export",exports=True,derived=True,
                   disk=pressure_high(memory_snapshot()))
    state[EXPORT_PRE_KEY]=result
    state.pop(EXPORT_POST_KEY,None)
    return result

def finish_export(state):
    # Do not delete the newly created output. Trim freed intermediates.
    result=cleanup(state,"After export")
    state[EXPORT_POST_KEY]=result
    return result

def dataset_changed(state):
    return cleanup(state,"Climate source changed",exports=True,derived=True,
                   transient=True,disk=True)

def manual_cleanup(state):
    return cleanup(state,"Manual cleanup",exports=True,derived=True,transient=True,disk=True)

def begin_rerun(state,page):
    previous=state.get(PAGE_KEY)
    state[PAGE_KEY]=page
    # Previous capture callbacks have already run at this safe boundary.
    # Discard old filtered/export references; current pages rebuild them.
    if previous!=page and any(key in state for key in TRANSIENT_KEYS):
        cleanup(state,"Analysis page changed",transient=True)
    snapshot=memory_snapshot()
    now=monotonic()
    if pressure_high(snapshot) and now-state.get(PRESSURE_KEY,-1e9)>=PRESSURE_COOLDOWN_S:
        state[PRESSURE_KEY]=now
        # Preserve ready downloads during routine navigation. New exports or
        # an explicit cleanup are the responsibility of the corresponding action.
        cleanup(state,"Automatic memory pressure cleanup",derived=True,disk=True)

def _mib(value):
    return f"{value/m.MIB:,.0f} MiB" if value is not None else "Unavailable"

def render_sidebar(st):
    state=st.session_state
    with st.sidebar.expander("Memory management",expanded=False):
        snapshot=memory_snapshot()
        used,limit=snapshot.get("used"),snapshot.get("limit")
        if used is not None and limit:
            st.write(f"Container: {_mib(used)} / {_mib(limit)}")
            st.progress(min(1.,max(0.,used/limit)))
            if pressure_high(snapshot):st.warning("High container memory pressure")
            st.caption("Container memory is shared across sessions.")
        else:st.caption("Container memory limit unavailable on this host.")
        for key,label in (("anonymous","Anonymous memory"),("file","File-backed memory"),
                          ("inactive_file","Inactive file cache"),("process_rss","Application process RSS")):
            if key in snapshot:st.caption(f"{label}: {_mib(snapshot[key])}")
        st.caption("Active climate data, comparison data and saved report diagrams are retained. Prepared downloads and recomputable caches are released.")
        st.button("Clean unused caches",key="mem_perf_r1_clean",
                  on_click=manual_cleanup,args=(state,))
        st.caption("Automatic cleanup before exports and under memory pressure is enabled.")
        result=state.get(LAST_KEY)
        if result:
            st.caption("Last cleanup: "+result["reason"])
            b,a=result["before"].get("used"),result["after"].get("used")
            if b is not None and a is not None:
                st.caption(f"Container usage: {_mib(b)} → {_mib(a)} (net change {(a-b)/m.MIB:+,.0f} MiB; concurrent activity may affect measurement).")
            st.caption(f"Released resource entries: {len(result['released'])}")
            for warning in result["warnings"]:st.caption(warning)
        pre,post=state.get(EXPORT_PRE_KEY),state.get(EXPORT_POST_KEY)
        if pre:
            st.caption("Most recent export lifecycle")
            for label,record,phase in (("Before cleanup",pre,"before"),("After cleanup",pre,"after"),
                                       ("After export",post,"after")):
                if record:
                    st.caption(f"{label}: {_mib(record[phase].get('used'))}")
