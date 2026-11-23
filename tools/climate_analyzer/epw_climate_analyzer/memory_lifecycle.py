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

def _render_sidebar(st):
    state=st.session_state
    with st.sidebar.expander("Memory management",expanded=False):
        snapshot=memory_snapshot()
        used,limit=snapshot.get("used"),snapshot.get("limit")
        if used is not None and limit:
            st.write(f"Container: {_mib(used)} / {_mib(limit)}")
            st.progress(min(1.,max(0.,used/limit)))
            if pressure_high(snapshot):st.warning("High container memory pressure")
            st.caption("Container memory is shared across sessions.")
            st.caption(f"Raw unallocated headroom: {_mib(max(0,limit-used))}; usage less inactive file cache: {_mib(used-min(used,snapshot.get('inactive_file',0)))} (diagnostic only; not an admission credit).")
        else:st.caption("Container memory limit unavailable on this host.")
        for key,label in (("anonymous","Anonymous memory"),("file","File-backed memory"),
                          ("inactive_file","Inactive file cache"),("process_rss","Application process RSS"),
                          ("process_anon","Application anonymous RSS"),("process_file","Application file RSS"),
                          ("process_shmem","Application shared-memory RSS"),("process_hwm","Application RSS high-water mark")):
            if key in snapshot:st.caption(f"{label}: {_mib(snapshot[key])}")
        st.caption("Active climate data, comparison data and saved report diagrams are retained. Prepared downloads and recomputable caches are released.")
        st.button("Clean unused caches",key="mem_perf_r1_clean",
                  on_click=manual_cleanup,args=(state,))
        st.caption("Reset session closes the current connection and requests a fresh session without restarting the server. Shared scientific libraries remain initialized.")
        consent=st.checkbox("Confirm deletion of this session's climate data, reports and settings",key="mem_r12_reset_confirm")
        st.button("Reset session",disabled=not consent,key="mem_r12_reset",on_click=reset_session,args=(state,))
        st.caption("Manual cleanup releases only this session's disposable resources. Shared public caches may be evicted under resource pressure.")
        inventory=cache_inventory()
        private=session_cache_inventory(state)
        st.caption(f"Session cache payload: {_mib(sum(r['estimated_bytes'] for r in private))} / {_mib(sum(r['budget_bytes'] for r in private))} registered budgets.")
        st.caption(f"Shared server cache payload: {_mib(sum(r['estimated_bytes'] for r in inventory))} / {_mib(sum(r['budget_bytes'] for r in inventory))} registered budgets.")
        st.button("Inspect retained resources (refresh snapshot)",key="mem_r4_inspect",on_click=inspect_resources,args=(state,),
                  help="Collect a new lightweight snapshot before downloading; does not run a Python heap census.")
        st.button("Measure allocator recovery",key="mem_r9_recovery",on_click=inspect_recovery,args=(state,),
                  help="Measure garbage collection and glibc trim separately; retains all active climate data and reports.")
        st.button("Inspect Python object types",key="mem_r5_heap_inspect",on_click=inspect_heap,args=(state,),
                  help="On demand, requires substantial raw memory headroom. Counts shallow GC-tracked objects; no content is exported.")
        from .startup_runtime import runtime_status
        runtime=runtime_status()
        ready=sum(r["status"] in ("ready","already loaded") for r in runtime["startup"])
        st.caption(f"Library stages ready: {ready}/{len(runtime['startup'])}.")
        persistent=runtime.get("persistent_runtime",{})
        st.caption(f"Process reruns: {runtime['event_counts'].get('script rerun',0)}; compatibility compositions: {persistent.get('wrapper_compositions',0)}; full module resets: {persistent.get('baseline_builds',0)}.")
        details=st.checkbox("Show detailed memory tables",value=False,key="mem_r6_detail_tables",
                            help="Detailed tables are rendered only on request, even when this expander is closed.")
        if details:
            st.caption("One-time startup library initialization")
            st.text("\n".join(f"{row['stage']}: {row['status']} · {row['seconds']:.3f} s · RSS delta {_mib(row['rss_delta'])}"
                              for row in runtime["startup"]))
            st.text("\n".join(f"{key}: {value}" for key,value in persistent.items()))
        from .session_reaper import reaper_summary
        live_reaper=reaper_summary()
        st.caption(f"Live session maintenance: {live_reaper.get('status','unavailable')}; sweeps: {live_reaper.get('sweeps',0)}; disconnected at last sweep: {live_reaper.get('disconnected_sessions','Unavailable')}; closed immediately: {live_reaper.get('closed_on_disconnect',0)}; expired reaped (fallback): {live_reaper.get('expired_reaped',0)}.")
        st.caption(f"Active sessions: {live_reaper.get('active_sessions','Unavailable')}; WebSocket disconnect dispatches: {live_reaper.get('disconnect_events',0)}; native closes: {live_reaper.get('native_closes',0)}; closed session objects still reachable: {live_reaper.get('closed_session_refs_alive',0)}.")
        st.caption(f"Native resets: {live_reaper.get('native_resets',0)}; reset failures: {live_reaper.get('reset_failures',0)}; retired payload cleanups: {live_reaper.get('retired_payloads_cleared',0)}.")
        st.caption(f"Session policy: {live_reaper.get('policy_version','not verified')}; hook replacements: {live_reaper.get('policy_replacements',0)}.")
        queue_sample=live_reaper.get("forward_queue_sample",{})
        if queue_sample.get("status")=="sampled":
            st.caption(f"Pending forward messages at last sweep: {queue_sample['pending_messages_in_sampled_sessions']}; sampled wire payload: {_mib(queue_sample['sampled_wire_bytes'])}; {queue_sample['captured_at_utc']} (not websocket backlog or RSS).")
        inspected=state.get(INVENTORY_KEY)
        if inspected and inspected.get("snapshot_schema")!="MEM-PERF-R13-HF2":
            release_inventory(state)
            inspected=None
        from .memory_recovery import recovery_summary
        recovery=recovery_summary().get("last")
        if recovery:
            st.caption(f"Last allocator recovery: {recovery['reason']}; {recovery['status']}.")
            if recovery.get("status")=="complete":
                before=recovery["before"].get("process_anon")
                after=recovery["after_trim"].get("process_anon")
                if before is not None and after is not None:
                    st.caption(f"Application anonymous RSS: {_mib(before)} → {_mib(after)}.")
        if inspected:
            st.caption(f"Snapshot captured: {inspected['captured_at_utc']}. Current memory above is live at rerun; snapshot below is historical. Refresh before downloading.")
            st.caption("Last on-demand inventory; sizes are estimates and overlap with RSS. Session rows may overlap; unmeasurable objects are marked unavailable.")
            counters=inspected.get("session_runtime",{})
            if counters:
                st.caption(f"Active sessions (process-wide): {counters.get('active_sessions','Unavailable')}; current session visible keys: {counters.get('visible_keys','Unavailable')}.")
                st.caption(f"Streamlit uploaded payloads: {_mib(counters.get('uploaded_payload_bytes'))}; media/download payloads: {_mib(counters.get('media_payload_bytes'))}.")
            charts=inspected.get("chart_lifecycle",{})
            if charts:
                st.caption(f"Displayed figures: {charts['current_page_figures']}; recently retired figures still alive: {charts['retired_alive']}/{charts['retired_tracked']} (process-wide sample).")
            reaper=counters.get("session_reaper",{})
            if reaper:
                st.caption(f"Disconnected sessions within reconnect window: {reaper.get('disconnected_sessions','Unavailable')}; expired sessions reaped: {reaper.get('expired_reaped',0)}.")
            heap=inspected.get("heap_census")
            if heap:st.caption("Python object census (separate historical snapshot): "+heap["status"]+"; captured: "+str(inspected.get("heap_census_captured_at_utc") or "unknown"))
            processes=inspected.get("container_processes",{})
            if processes:
                st.caption(f"Visible cgroup processes: {processes.get('sampled',0)}; total sampled anonymous RSS: {_mib(processes.get('rss_anon_sum'))} (may overlap shared pages).")
                if details:
                    st.text("\n".join(f"{p['category']}: PID {p['pid']} · PPID {p.get('parent_pid','?')} · {p.get('role_hint','unclassified')} · {p.get('relation_to_app','unknown')} · anonymous RSS {_mib(p.get('rss_anon'))} · PssAnon {_mib(p.get('pss_anon'))}" for p in processes.get("processes",[])[:15]))
                st.caption(f"Other Python anonymous RSS: {_mib(processes.get('other_python_anon_bytes'))}; matching climate launch targets: {len(processes.get('other_climate_app_candidates',[]))}.")
                for p in processes.get("processes",[]):
                    if not p.get("app") and p.get("climate_app_target"):
                        st.caption(f"PID {p['pid']}: {p.get('orphan_assessment','unknown')}; listener ports {p.get('sockets',{}).get('tcp_listen_ports','unknown')}; established TCP {p.get('sockets',{}).get('tcp_established','unknown')}.")
                st.caption("Process checks are read-only. No process termination from this public interface.")
            ownership=inspected.get("cloud_memory_ownership",{})
            if ownership:
                candidates=ownership["processes"]["other_matching_targets"]
                if candidates:
                    st.warning(f"{len(candidates)} other matching Climate Analyzer launch target(s); sampled anonymous RSS {_mib(ownership['processes']['other_matching_anon_bytes'])}. Platform ownership unresolved. Do not terminate from this application.")
                allocator=ownership["allocator"]
                st.caption(f"Allocator admission: {allocator['classification']}; reported free arena space {_mib(allocator.get('free_arena_bytes'))}. Free arena space is not necessarily reclaimable RSS.")
                st.caption("Allocator startup evidence and process ownership are separate gates. Neither is a guarantee of total container memory recovery.")
            if details:
                # Text summaries avoid Arrow/dataframe marshalling and repeated
                # construction of nested JSON elements on each unrelated rerun.
                st.text("\n".join(f"{r['cache']}: {r['entries']} entries, {_mib(r['estimated_bytes'])} / {_mib(r['budget_bytes'])}"
                                   for r in inspected["shared_caches"]))
                st.text("\n".join(f"{r['resource']}: {r['type']}, {_mib(r['estimated_bytes'])}"
                                   for r in inspected["session_resources"]))
                st.caption(f"Python allocation blocks: {inspected['python_allocated_blocks']}. Full diagnostic tables and histories are in the JSON download.")
                st.text("\n".join(f"{k}: {v}" for k,v in inspected.get("loaded_libraries",{}).items() if v))
                capture=inspected.get("diagnostic_capture",{})
                if capture:
                    st.caption(f"Inventory capture callback: {capture['seconds']:.3f} s; anonymous RSS {_mib(capture['before'].get('process_anon'))} → {_mib(capture['after'].get('process_anon'))}.")
                if heap:st.caption("Complete heap census is available in the JSON download.")
            payload=state.get(INVENTORY_BYTES_KEY)
            if isinstance(payload,bytes):
                st.download_button("Download memory inventory JSON",data=payload,file_name="memory_inventory_"+inspected["captured_at_utc"].replace(":","-").replace("+","_")+".json",mime="application/json",key="mem_r4_inventory_download",on_click="ignore")
            st.button("Release memory inventory",key="mem_r10_release_inventory",on_click=release_inventory,args=(state,))
        result=state.get(LAST_KEY)
        if result:
            st.caption("Last cleanup: "+result["reason"])
            b,a=result["before"].get("used"),result["after"].get("used")
            if b is not None and a is not None:
                st.caption(f"Container usage: {_mib(b)} → {_mib(a)} (net change {(a-b)/m.MIB:+,.0f} MiB; concurrent activity may affect measurement).")
            st.caption(f"Released session resource entries: {len(result['released'])}")
            evicted=result.get("evicted_caches",[])
            st.caption(f"Evicted shared cache entries: {sum(r['entries'] for r in evicted)}; estimated payload {_mib(sum(r['estimated_bytes'] for r in evicted))}.")
            if result.get("kept_active_cache_names"):
                st.caption("Active station-map caches retained to avoid immediate reconstruction.")
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
