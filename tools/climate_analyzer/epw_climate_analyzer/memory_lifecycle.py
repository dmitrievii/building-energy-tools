"""MEM-PERF R1: explicitly owned session resources and memory lifecycle.

Never clear all Streamlit caches or session state. The active source, saved
report snapshots, comparison basket, generated source products, settings and
other user work are outside the disposable-resource allowlist.
"""
from __future__ import annotations

import gc
from pathlib import Path
from time import monotonic
import json
from datetime import datetime, timezone

from . import p66_memory as m
from .byte_cache import (cache_inventory,clear_recomputable_caches,session_inventory,
                         session_cache_inventory,clear_session_caches,session_cache_summary,SESSION_CACHE_KEY)

RUNTIME_MEMORY_SCHEMA="MEM-PERF-R6"
RUNTIME_CHART_SCHEMA="MEM-PERF-R7"
RUNTIME_INVENTORY_SCHEMA="MEM-PERF-R13-HF2"
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
INVENTORY_BYTES_KEY="_mem_r10_inventory_bytes"
DIAGNOSTIC_KEYS=(INVENTORY_KEY,INVENTORY_BYTES_KEY,"_mem_r5_heap_census","_mem_r5_heap_census_at")
EXPORT_CACHE_FRACTION=.72
PROTECTED_KEYS=("active_climate_file","active_canonical_climate","comparison_climate_payloads",
                "canonical_comparison_climates","ige_engine_completed_product","_p6_report_items","_p6_custom_presets")
MAP_CACHE_NAMES=("station_catalog","station_group_snapshot","station_filter_options",
                 "filtered_station_groups","station_group_options","station_markers","station_group_rows")

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

def _collect_inventory(state,process):
    """On-demand inventory; never enable global Python allocation tracing."""
    import sys
    import os
    import tracemalloc
    result={"snapshot_schema":"MEM-PERF-R13-HF2","captured_at_utc":datetime.now(timezone.utc).isoformat(),
            "capture_phase":"on-demand; before next page rendering when called by widget callback",
            "memory":process,"shared_caches":cache_inventory(),
            "session_caches":session_cache_inventory(state),
            "session_cache_summary":session_cache_summary(),
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
    from .startup_runtime import runtime_summary,library_footprint_snapshot
    from .session_memory import inspect_session_counters
    result["runtime"]=runtime_summary()
    result["library_footprint"]=library_footprint_snapshot(result["memory"])
    result["session_runtime"]=inspect_session_counters(state,PROTECTED_KEYS+EXPORT_KEYS+DERIVED_KEYS+TRANSIENT_KEYS)
    from .chart_lifecycle import chart_lifecycle_summary
    result["chart_lifecycle"]=chart_lifecycle_summary(state)
    # Explicit CI-only scientific parity capture. No serialization overhead
    # in normal memory inventories or the previously qualified RSS screen.
    if os.environ.get("IGE_R143_PARITY")=="1":
        from .r143_scientific_parity import evidence
        result["r143_parity"]=evidence(state)
    from .memory_recovery import allocator_snapshot, recovery_summary
    from .process_memory import container_process_inventory
    result["container_processes"]=container_process_inventory()
    from .byte_cache import native_owner_enabled
    result["r14_pilot"]={"native_owner":native_owner_enabled(),
                         "degree_fragment":os.environ.get("IGE_R14_DEGREE_FRAGMENT")=="1",
                         "full_runs":state.get("_r14_full_runs",0),
                         "degree_fragment_runs":state.get("_r14_degree_fragment_runs",0)}
    from .runtime_loop_patch import status as runtime_loop_status
    result["runtime_loop"]=runtime_loop_status()
    if process.get("limit",0)-process.get("used",0)>256*m.MIB:
        from .session_reaper import retired_reference_summary
        result["retired_reference_diagnostics"]=retired_reference_summary()
    from .epw_lifecycle import lifecycle_summary
    result["epw_lifecycle"]=lifecycle_summary()
    result["allocator"]=allocator_snapshot()
    result["recovery"]=recovery_summary()
    from .cloud_memory_ownership import summarize_ownership
    result["cloud_memory_ownership"]=summarize_ownership(result)
    result["raw_headroom_bytes"]=(result["memory"]["limit"]-result["memory"]["used"]
        if "limit" in result["memory"] and "used" in result["memory"] else None)
    reading=result["memory"]
    if reading.get("limit") and "used" in reading:
        inactive=min(reading.get("inactive_file",0),max(0,reading.get("file",0)-reading.get("shared",0)),reading["used"])
        result["admission_diagnostics"]={"raw_headroom_bytes":result["raw_headroom_bytes"],
            "inactive_ordinary_file_bytes":max(0,inactive),
            "usage_less_inactive_file_bytes":reading["used"]-max(0,inactive),
            "pdf_parent_reserve_bytes":min(192*m.MIB,max(64*m.MIB,int(reading["limit"]*.20))),
            "html_parent_reserve_bytes":min(384*m.MIB,max(96*m.MIB,int(reading["limit"]*.20))),
            "scope":"Diagnostic only; export admission still uses raw cgroup usage. Child renderers have additional guards."}
    if "_mem_r5_heap_census" in state:
        result["heap_census"]=state["_mem_r5_heap_census"]
        result["heap_census_captured_at_utc"]=state.get("_mem_r5_heap_census_at")
        result["heap_census_note"]="Separate historical measurement; not refreshed by resource inspection."
    return result

def inspect_resources(state):
    """One capture and one serialization per explicit refresh.

    Keep diagnostic events separate from the scientific interaction history.
    The current capture delta is embedded in its own JSON; serialization is
    sampled afterwards and appears in the next inventory's diagnostic ledger.
    """
    from .startup_runtime import begin_phase,end_phase
    release_inventory(state,include_heap=False)
    capture=begin_phase()
    result=_collect_inventory(state,capture[1])
    result["diagnostic_capture"]=end_phase(capture,"inventory capture callback",diagnostic=True)
    serialization=begin_phase()
    payload=json.dumps(result,ensure_ascii=True,separators=(",",":")).encode("utf-8")
    state[INVENTORY_KEY]=result
    state[INVENTORY_BYTES_KEY]=payload
    end_phase(serialization,"inventory JSON serialization",diagnostic=True)
    return result

def release_inventory(state,include_heap=True):
    keys=DIAGNOSTIC_KEYS if include_heap else (INVENTORY_KEY,INVENTORY_BYTES_KEY)
    return _drop(state,keys)

def inspect_recovery(state):
    from .memory_recovery import recovery_probe
    recovery_probe("Manual allocator recovery probe")
    return inspect_resources(state)

def inspect_heap(state):
    from .startup_runtime import heap_census
    try:
        report=heap_census()
    except Exception as exc:
        # Diagnostics must never prevent use of the application.
        # Report only the exception type, not potentially sensitive contents.
        report={"status":"failed: "+type(exc).__name__}
    state["_mem_r5_heap_census"]=report
    state["_mem_r5_heap_census_at"]=datetime.now(timezone.utc).isoformat()
    return inspect_resources(state)

def _drop(state,keys):
    removed=[]
    for key in keys:
        if key in state:
            state.pop(key,None)
            removed.append(key)
    return removed

def cleanup(state,reason,*,exports=False,derived=False,transient=False,disk=False,shared_caches=False,keep_shared=(),diagnostics=False,private_caches=False):
    """Release selected owned references; sample before/after actual collection.

    A disk cache belongs to this session, but do not remove it while any export
    holds the process export lock. Never kill another session's renderer.
    Memory changes are observations, not attribution or an OOM guarantee.
    """
    before=memory_snapshot()
    removed=[];warnings=[]
    if diagnostics:removed.extend(release_inventory(state))
    if exports:removed.extend(_drop(state,EXPORT_KEYS))
    if derived:removed.extend(_drop(state,DERIVED_KEYS))
    if transient:
        from .chart_lifecycle import release_page
        if "_p6_displayed_charts" in state:
            release_page(state)
            removed.append("_p6_displayed_charts")
        removed.extend(_drop(state,tuple(key for key in TRANSIENT_KEYS if key!="_p6_displayed_charts")))
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
    if shared_caches:
        evicted=clear_recomputable_caches(keep=keep_shared) if keep_shared else clear_recomputable_caches()
    else:evicted=[]
    if private_caches:evicted.extend(clear_session_caches(state))
    gc.collect()
    m._trim_allocator()
    after=memory_snapshot()
    result={"reason":reason,"before":before,"after":after,"released":removed,"warnings":warnings,
            "evicted_caches":evicted,"kept_active_cache_names":list(keep_shared)}
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
                   disk=cache_pressure(snapshot),shared_caches=cache_pressure(snapshot),private_caches=cache_pressure(snapshot))
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
                   transient=True,disk=True,private_caches=True)

def manual_cleanup(state):
    # Private user action never evicts shared server catalogue/metadata.
    return cleanup(state,"Manual cleanup",exports=True,derived=True,transient=True,
                   disk=True,private_caches=True,diagnostics=True)

def reset_session(state):
    """Destroy the live AppSession rather than clearing a still-live widget tree."""
    from streamlit.runtime import Runtime
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    if Runtime.exists() and get_script_run_ctx(suppress_warning=True) is not None:
        from .session_reaper import request_native_reset
        import streamlit as st
        if not request_native_reset():
            st.error("Native session reset unavailable. Reload the page.")
        else:
            # A fixed, trusted script; never interpolate user content. The
            # full document reload clears browser widget state as well.
            st.html("<script>window.location.reload();</script>",unsafe_allow_javascript=True)
        st.stop()
        return
    _reset_local_state(state)

def _reset_local_state(state):
    """Standalone test/CLI fallback, with no live WebSocket."""
    from uuid import uuid4
    from streamlit.runtime import Runtime
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    # Callback runs before the next script body; no active chart construction.
    cleanup(state,"Reset session",exports=True,derived=True,transient=True,
            disk=True,private_caches=True,diagnostics=True)
    clear_session_caches(state,close=True)
    ctx=get_script_run_ctx(suppress_warning=True)
    if ctx is not None and Runtime.exists():
        rt=Runtime.instance()
        rt.uploaded_file_mgr.remove_session_files(ctx.session_id)
        rt.media_file_mgr.clear_session_refs(ctx.session_id)
        rt.media_file_mgr.remove_orphaned_files()
        rt.dataframe_source_mgr.clear_all_for_session(ctx.session_id)
        from .byte_cache import close_session_caches
        close_session_caches(ctx.session_id)
        # Native SessionState.clear releases old/new widget state, not only
        # filtered user keys. Use the current script's own safe state lock.
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        safe=ctx.session_state
        with safe._lock:safe._state.clear()
    else:
        for key in list(state.keys()):state.pop(key,None)
    state["_mem_r12_reset_epoch"]=uuid4().hex
    state["_mem_r12_reset_notice"]=True
    gc.collect()
    m._trim_allocator()

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
        cleanup(state,"Automatic memory pressure cleanup",derived=True,disk=True,shared_caches=True,private_caches=True)

def _mib(value):
    return f"{value/m.MIB:,.0f} MiB" if value is not None else "Unavailable"

def render_sidebar(st):
    from .startup_runtime import profile_diagnostic
    return profile_diagnostic("memory sidebar rendering",_render_sidebar,st)

def render_service_memory(st):
    """Diagnostics are constructed only on the explicit service route."""
    from .startup_runtime import profile_diagnostic
    return profile_diagnostic("memory service rendering",_render_sidebar,st,st)

def _render_sidebar(st,area=None):
    """Compact summary, with detailed diagnostics explicitly opt-in."""
    state=st.session_state
    area=st.sidebar if area is None else area
    with area.expander("Memory & caches",expanded=area is st):
        snapshot=memory_snapshot()
        used,limit=snapshot.get("used"),snapshot.get("limit")
        if used is not None and limit:
            st.write(f"Container: {_mib(used)} / {_mib(limit)}")
            st.progress(min(1.,max(0.,used/limit)))
            if pressure_high(snapshot):
                st.warning("High container memory pressure")
        else:
            st.caption("Container memory unavailable")
        st.caption(f"App RAM: {_mib(snapshot.get('process_anon'))} anonymous RSS")

        st.button("Clean unused caches",key="mem_perf_r1_clean",
                  on_click=manual_cleanup,args=(state,),
                  help="Release disposable resources. Climate data and saved report diagrams are preserved.")
        consent=st.checkbox("Confirm session reset (deletes climate data and reports)",
                            key="mem_r12_reset_confirm")
        st.button("Reset session",disabled=not consent,key="mem_r12_reset",
                  on_click=reset_session,args=(state,),
                  help="Close the current session without restarting the application server.")
        st.button("Inspect retained resources (refresh snapshot)",key="mem_r4_inspect",
                  on_click=inspect_resources,args=(state,),
                  help="Collect detailed metrics for the downloadable inventory.")

        inspected=state.get(INVENTORY_KEY)
        if inspected and inspected.get("snapshot_schema")!=RUNTIME_INVENTORY_SCHEMA:
            release_inventory(state)
            inspected=None
        if inspected:
            st.caption(f"Snapshot captured: {inspected['captured_at_utc']}")
            candidates=inspected.get("cloud_memory_ownership",{}).get("processes",{}).get("other_matching_targets",[])
            if candidates:
                st.warning(f"{len(candidates)} other Climate Analyzer process(es) found; platform ownership unresolved.")
            payload=state.get(INVENTORY_BYTES_KEY)
            if isinstance(payload,bytes):
                st.download_button("Download memory inventory JSON",data=payload,
                                   file_name="memory_inventory_"+inspected["captured_at_utc"].replace(":","-").replace("+","_")+".json",
                                   mime="application/json",key="mem_r4_inventory_download",on_click="ignore")
            st.button("Release memory inventory",key="mem_r10_release_inventory",
                      on_click=release_inventory,args=(state,))
        result=state.get(LAST_KEY)
        if result:
            b,a=result["before"].get("used"),result["after"].get("used")
            delta=f"; container {_mib(b)} → {_mib(a)}" if b is not None and a is not None else ""
            st.caption(f"Last cleanup: {result['reason']}{delta}")

        advanced=st.checkbox("Advanced diagnostics",key="mem_r6_detail_tables",value=False,
                             help="Additional measurements and technical counters; the full evidence remains in the JSON.")
        if advanced:
            _render_memory_diagnostics(st,snapshot,state,inspected)


def _render_memory_diagnostics(st,snapshot,state,inspected):
    """On-demand UI only; all raw diagnostic evidence remains in the JSON."""
    used,limit=snapshot.get("used"),snapshot.get("limit")
    if used is not None and limit:
        st.caption(f"Raw headroom: {_mib(max(0,limit-used))}; usage excluding inactive file cache: {_mib(used-min(used,snapshot.get('inactive_file',0)))} (diagnostic).")
    for key,label in (("anonymous","Container anonymous"),("file","File-backed"),
                      ("inactive_file","Inactive file cache"),("process_rss","Application RSS"),
                      ("process_file","Application file RSS"),("process_hwm","Peak application RSS")):
        if key in snapshot:
            st.caption(f"{label}: {_mib(snapshot[key])}")
    inventory=cache_inventory()
    private=session_cache_inventory(state)
    st.caption(f"Session cache: {_mib(sum(x['estimated_bytes'] for x in private))}; shared cache: {_mib(sum(x['estimated_bytes'] for x in inventory))}.")
    st.button("Measure allocator recovery",key="mem_r9_recovery",on_click=inspect_recovery,args=(state,),
              help="Run a separate garbage collection and allocator trim measurement.")
    st.button("Inspect Python object types",key="mem_r5_heap_inspect",on_click=inspect_heap,args=(state,),
              help="Count shallow object types when raw memory headroom permits.")
    from .startup_runtime import runtime_status
    runtime=runtime_status()
    persistent=runtime.get("persistent_runtime",{})
    st.caption(f"Library stages: {sum(row['status'] in ('ready','already loaded') for row in runtime['startup'])}/{len(runtime['startup'])}; reruns: {runtime['event_counts'].get('script rerun',0)}; compositions: {persistent.get('wrapper_compositions',0)}.")
    st.text("\n".join(f"{row['stage']}: {row['status']} · {row['seconds']:.3f} s · RSS delta {_mib(row['rss_delta'])}" for row in runtime["startup"]))
    from .session_reaper import reaper_summary
    reaper=reaper_summary()
    st.caption(f"Sessions: {reaper.get('active_sessions','Unavailable')}; native closes: {reaper.get('native_closes',0)}; closed references alive: {reaper.get('closed_session_refs_alive',0)}.")
    from .memory_recovery import recovery_summary
    recovery=recovery_summary().get("last")
    if recovery:
        st.caption(f"Last allocator recovery: {recovery.get('status','unknown')} · {recovery.get('reason','unknown')}")
    if inspected:
        processes=inspected.get("container_processes",{})
        st.caption(f"Snapshot process count: {processes.get('sampled','Unavailable')}; sampled anonymous RSS: {_mib(processes.get('rss_anon_sum'))}.")
        for p in processes.get("processes",[])[:15]:
            st.caption(f"PID {p['pid']}: {p.get('role_hint','unclassified')} · anon {_mib(p.get('rss_anon'))}.")
        ownership=inspected.get("cloud_memory_ownership",{})
        a=ownership.get("allocator",{})
        if a:
            st.caption(f"Allocator admission: {a.get('classification','Unavailable')}; free arena: {_mib(a.get('free_arena_bytes'))} (not guaranteed reclaimable).")
        charts=inspected.get("chart_lifecycle",{})
        if charts:
            st.caption(f"Displayed figures: {charts.get('current_page_figures','Unavailable')}; retired still alive: {charts.get('retired_alive','Unavailable')}.")
        st.caption(f"Python blocks: {inspected.get('python_allocated_blocks','Unavailable')}. More details in JSON.")
    launch=state.get("_mem_perf_r4_launch_cleanup")
    if launch:
        st.caption(f"Pre-export cache cleanup: {_mib(launch['before'].get('used'))} → {_mib(launch['after'].get('used'))}.")
    pre,post=state.get(EXPORT_PRE_KEY),state.get(EXPORT_POST_KEY)
    if pre:
        for label,record,phase in (("Before cleanup",pre,"before"),("After cleanup",pre,"after"),("After export",post,"after")):
            if record:
                st.caption(f"{label}: {_mib(record[phase].get('used'))}")
