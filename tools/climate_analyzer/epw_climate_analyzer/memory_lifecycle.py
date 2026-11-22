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
from .byte_cache import cache_inventory,clear_recomputable_caches,session_inventory

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
INVENTORY_KEY="_mem_perf_r4_inventory"
EXPORT_CACHE_FRACTION=.72
PROTECTED_KEYS=("active_climate_file","active_canonical_climate","comparison_climate_payloads",
                "ige_engine_completed_product","_p6_report_items","_p6_custom_presets")

def memory_snapshot():
    """Cgroup totals are shared across sessions; process RSS is separate."""
    result={}
    reading=m._memory_reading()
    if reading is not None:
        used,cap,root=reading
        result.update(used=used,limit=cap)
        try:
            records={}
            for line in (root/"memory.stat").read_text().splitlines():
                parts=line.split()
                if len(parts)!=2:continue
                try:records[parts[0]]=int(parts[1])
                except ValueError:continue
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
            tag=line.split(":",1)[0]
            key={"VmRSS":"process_rss","RssAnon":"process_anon","RssFile":"process_file",
                 "RssShmem":"process_shmem","VmHWM":"process_hwm"}.get(tag)
            if key:result[key]=int(line.split()[1])*1024
    except (OSError,ValueError,IndexError):pass
    return result

def pressure_high(snapshot):
    used,limit=snapshot.get("used"),snapshot.get("limit")
    if used is None or not limit:return False
    # Match the conservative half-credit for inactive ordinary file cache.
    inactive=min(snapshot.get("inactive_file",0),
                 max(0,snapshot.get("file",0)-snapshot.get("shared",0)),used)
    return (used-max(0,inactive)//2)>=PRESSURE_FRACTION*limit

def cache_pressure(snapshot):
    used,limit=snapshot.get("used"),snapshot.get("limit")
    return bool(limit and used is not None and used>=EXPORT_CACHE_FRACTION*limit)

def inspect_resources(state):
    """On-demand inventory, without enabling global Python allocation tracing."""
    import sys
    import os
    import tracemalloc
    result={"memory":memory_snapshot(),"shared_caches":cache_inventory(),
            "session_resources":session_inventory(state,PROTECTED_KEYS+EXPORT_KEYS+DERIVED_KEYS+TRANSIENT_KEYS),
            "python_allocated_blocks":getattr(sys,"getallocatedblocks",lambda:None)()}
    # Inspect module presence without importing expensive analysis libraries.
    roots=("numpy","pandas","scipy","numba","llvmlite","pythermalcomfort","pvlib",
           "plotly","folium","streamlit","kaleido","matplotlib","pyarrow","psychrolib",
           "epw_climate_analyzer.historical","epw_climate_analyzer.charts")
    loaded=tuple(sys.modules)
    result["loaded_libraries"]={name:sum(key==name or key.startswith(name+".") for key in loaded)
                                for name in roots}
    try:
        # Linux stat field 22 (starttime) follows the parenthesized comm field,
        # which can itself contain spaces. Tail begins at field 3.
        tail=Path("/proc/self/stat").read_text().rsplit(")",1)[1].split()
        started=int(tail[19])/os.sysconf("SC_CLK_TCK")
        uptime=float(Path("/proc/uptime").read_text().split()[0])
        result["process_age_seconds"]=max(0.,uptime-started)
    except (OSError,ValueError,IndexError,AttributeError):pass
    if tracemalloc.is_tracing():
        current,peak=tracemalloc.get_traced_memory()
        result["python_traced_bytes"]=current;result["python_traced_peak_bytes"]=peak
    try:
        for line in Path("/proc/self/smaps_rollup").read_text().splitlines():
            key=line.split(":",1)[0]
            if key in ("Pss","Private_Clean","Private_Dirty","Shared_Clean","Shared_Dirty"):
                result.setdefault("process_smaps",{})[key]=int(line.split()[1])*1024
    except (OSError,ValueError,IndexError):pass
    from .startup_runtime import runtime_summary
    result["runtime"]=runtime_summary()
    if "_mem_r5_heap_census" in state:result["heap_census"]=state["_mem_r5_heap_census"]
    state[INVENTORY_KEY]=result
    return result

def inspect_heap(state):
    from .startup_runtime import heap_census
    state["_mem_r5_heap_census"]=heap_census()
    return inspect_resources(state)

def _drop(state,keys):
    removed=[]
    for key in keys:
        if key in state:
            state.pop(key,None)
            removed.append(key)
    return removed

def cleanup(state,reason,*,exports=False,derived=False,transient=False,disk=False,shared_caches=False):
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
    evicted=clear_recomputable_caches() if shared_caches else []
    gc.collect()
    m._trim_allocator()
    after=memory_snapshot()
    result={"reason":reason,"before":before,"after":after,"released":removed,"warnings":warnings,
            "evicted_caches":evicted}
    state[LAST_KEY]=result
    return result

def prepare_export(state):
    """Run before the new export, preferably in the widget click callback.

    Old downloads must be released before fresh chart/renderer allocation.
    Retain the image cache for reuse unless actual memory pressure warrants
    cleanup. Saved report entries and source frames are never deleted.
    """
    snapshot=memory_snapshot()
    result=cleanup(state,"Before export",exports=True,derived=True,
                   disk=cache_pressure(snapshot),shared_caches=cache_pressure(snapshot))
    state[EXPORT_PRE_KEY]=result
    state.pop(EXPORT_POST_KEY,None)
    state.pop("_mem_perf_r4_launch_cleanup",None)
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
    return cleanup(state,"Manual cleanup",exports=True,derived=True,transient=True,disk=True,shared_caches=True)

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
        cleanup(state,"Automatic memory pressure cleanup",derived=True,disk=True,shared_caches=True)

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
                          ("inactive_file","Inactive file cache"),("process_rss","Application process RSS"),
                          ("process_anon","Application anonymous RSS"),("process_file","Application file RSS"),
                          ("process_shmem","Application shared-memory RSS"),("process_hwm","Application RSS high-water mark")):
            if key in snapshot:st.caption(f"{label}: {_mib(snapshot[key])}")
        st.caption("Active climate data, comparison data and saved report diagrams are retained. Prepared downloads and recomputable caches are released.")
        st.button("Clean unused caches",key="mem_perf_r1_clean",
                  on_click=manual_cleanup,args=(state,))
        st.caption("Automatic cleanup before exports and under memory pressure is enabled. Registered shared recomputable caches may be evicted; active references and user work remain intact.")
        inventory=cache_inventory()
        st.caption(f"Registered cache payload: {_mib(sum(r['estimated_bytes'] for r in inventory))} / {_mib(sum(r['budget_bytes'] for r in inventory))} combined individual budgets.")
        st.button("Inspect retained resources",key="mem_r4_inspect",on_click=inspect_resources,args=(state,))
        st.button("Inspect Python object types",key="mem_r5_heap_inspect",on_click=inspect_heap,args=(state,),
                  help="On demand, requires substantial raw memory headroom. Counts shallow GC-tracked objects; no content is exported.")
        from .startup_runtime import runtime_summary
        runtime=runtime_summary()
        st.caption("One-time startup library initialization")
        st.dataframe([{"Stage":row["stage"],"Status":row["status"],"Seconds":round(row["seconds"],3),
                       "RSS delta [MiB]":round((row["after"]["process_rss"]-row["before"]["process_rss"])/m.MIB,1)
                       if "process_rss" in row["after"] and "process_rss" in row["before"] else None}
                      for row in runtime["startup"]],hide_index=True)
        st.caption(f"Process reruns recorded: {runtime['event_counts'].get('script rerun',0)}; parity installations: {runtime['event_counts'].get('source parity installation',0)}.")
        inspected=state.get(INVENTORY_KEY)
        if inspected:
            st.caption("Last on-demand inventory; sizes are estimates and overlap with RSS. Session rows may overlap; unmeasurable objects are marked unavailable.")
            st.dataframe([{**r,"estimated MiB":round(r["estimated_bytes"]/m.MIB,2),"budget MiB":round(r["budget_bytes"]/m.MIB,2)} for r in inspected["shared_caches"]],hide_index=True)
            st.dataframe([{**r,"estimated MiB":round(r["estimated_bytes"]/m.MIB,2) if r["estimated_bytes"] is not None else None} for r in inspected["session_resources"]],hide_index=True)
            st.caption(f"Python allocation blocks: {inspected['python_allocated_blocks']}. Tracemalloc is not enabled by this diagnostic.")
            if "process_age_seconds" in inspected:
                st.caption(f"Process age at inspection: {inspected['process_age_seconds']/60:.1f} min")
            st.caption("Loaded library module counts (not memory sizes):")
            st.json({k:v for k,v in inspected.get("loaded_libraries",{}).items() if v},expanded=False)
            if inspected.get("process_smaps"):st.json({key:_mib(value) for key,value in inspected["process_smaps"].items()},expanded=False)
            heap=inspected.get("heap_census")
            if heap:
                st.caption("Python object census: "+heap["status"])
                if heap.get("types"):st.dataframe(heap["types"],hide_index=True)
            import json
            st.download_button("Download memory inventory JSON",data=json.dumps(inspected,indent=2).encode(),file_name="memory_inventory.json",mime="application/json",key="mem_r4_inventory_download",on_click="ignore")
        result=state.get(LAST_KEY)
        if result:
            st.caption("Last cleanup: "+result["reason"])
            b,a=result["before"].get("used"),result["after"].get("used")
            if b is not None and a is not None:
                st.caption(f"Container usage: {_mib(b)} → {_mib(a)} (net change {(a-b)/m.MIB:+,.0f} MiB; concurrent activity may affect measurement).")
            st.caption(f"Released session resource entries: {len(result['released'])}")
            evicted=result.get("evicted_caches",[])
            st.caption(f"Evicted shared cache entries: {sum(r['entries'] for r in evicted)}; estimated payload {_mib(sum(r['estimated_bytes'] for r in evicted))}.")
            for warning in result["warnings"]:st.caption(warning)
        launch=state.get("_mem_perf_r4_launch_cleanup")
        if launch:
            st.caption(f"Pre-launch cache eviction: {_mib(launch['before'].get('used'))} → {_mib(launch['after'].get('used'))}.")
        pre,post=state.get(EXPORT_PRE_KEY),state.get(EXPORT_POST_KEY)
        if pre:
            st.caption("Most recent export lifecycle")
            for label,record,phase in (("Before cleanup",pre,"before"),("After cleanup",pre,"after"),
                                       ("After export",post,"after")):
                if record:
                    st.caption(f"{label}: {_mib(record[phase].get('used'))}")
