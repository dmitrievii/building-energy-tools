"""R14.5A HF1: read-only ownership evidence, never a process-control surface.

RSS/PSS, allocator space, payload sizes and cgroup counters have different
accounting scopes. Never sum them as mutually exclusive heap components.
"""
from __future__ import annotations

def _nonnegative(value):
    return value if type(value) is int and value>=0 else None

def _total(rows, field):
    vals=[_nonnegative(r.get(field)) for r in rows]
    return sum(vals) if all(v is not None for v in vals) else None

def summarize_ownership(inventory):
    mem=inventory.get("memory",{})
    pinv=inventory.get("container_processes",{})
    rows=pinv.get("processes",[])
    self_rows=[r for r in rows if r.get("app") is True]
    current=self_rows[0] if len(self_rows)==1 else {}
    candidates=[r for r in rows if r.get("app") is not True and r.get("climate_app_target") is True]
    unknown=[r for r in rows if r.get("app") is not True and r.get("category")=="Python" and
             (r.get("argv_classification")!="classified" or "climate_app_target" not in r)]
    complete=(pinv.get("status")=="sampled" and pinv.get("limited") is False and
              pinv.get("read_errors")==0 and len(self_rows)==1 and not unknown)
    def brief(r):
        s=r.get("sockets",{})
        return {"pid":r.get("pid"),"start_ticks":r.get("start_ticks"),"parent_pid":r.get("parent_pid"),
                "age_seconds":r.get("age_seconds"),"relation":r.get("relation_to_app"),
                "rss_anon":_nonnegative(r.get("rss_anon")),"rss":_nonnegative(r.get("rss")),
                "pss_anon":_nonnegative(r.get("pss_anon")),"pss":_nonnegative(r.get("pss")),
                "socket_status":s.get("status"),"listener_count":len(s["tcp_listen_ports"]) if isinstance(s.get("tcp_listen_ports"),list) else None,
                "tcp_established":s.get("tcp_established"),"tcp_other":s.get("tcp_other"),
                "tcp_close_wait":s.get("tcp_states",{}).get("CLOSE_WAIT"),
                "assessment":r.get("orphan_assessment")}
    a=inventory.get("allocator",{})
    origin=a.get("arena_setting_origin")
    exec_value=a.get("arena_max_exec_env");tunable=a.get("arena_tunable_exec")
    # Only admit an explicit, unambiguous exec request. Actual allocator
    # configuration still requires independent workload qualification.
    if a.get("status")!="sampled" or origin is None or origin=="exec environment unavailable":
        allocator="STARTUP_EVIDENCE_UNAVAILABLE"
    elif exec_value==2 and tunable is None:
        allocator="A2_EXEC_REQUEST_OBSERVED"
    elif tunable==2 and exec_value in (None,2):
        allocator="A2_TUNABLE_REQUEST_OBSERVED"
    elif exec_value is not None or tunable is not None:
        allocator="DIFFERENT_OR_CONFLICTING_EXEC_REQUEST"
    elif a.get("arena_max_env") is not None:
        allocator="RUNTIME_ONLY_NOT_ADMITTED"
    else:
        allocator="NO_EXPLICIT_EXEC_REQUEST"
    cache=inventory.get("session_cache_summary",{})
    runtime=inventory.get("session_runtime",{})
    reaper=runtime.get("session_reaper",{})
    charts=inventory.get("chart_lifecycle",{})
    used=_nonnegative(mem.get("used"));limit=_nonnegative(mem.get("limit"))
    headroom=limit-used if used is not None and limit is not None else None
    anon=_nonnegative(mem.get("anonymous"));sum_anon=_total(rows,"rss_anon") if rows else None
    gates={
        "process_inventory_complete":complete,
        "single_visible_matching_target":complete and not candidates,
        "allocator_exec_request_a2":allocator in ("A2_EXEC_REQUEST_OBSERVED","A2_TUNABLE_REQUEST_OBSERVED"),
        "raw_headroom_observed":headroom is not None,
    }
    return {"schema":"R145A-HF1","gates":gates,"admission":"EVIDENCE_GATES_PASS_NOT_PROMOTED" if all(gates.values()) else "BLOCKED",
            "container":{"used_bytes":used,"limit_bytes":limit,"raw_headroom_bytes":headroom,
                         "anonymous_bytes":anon,"file_bytes":_nonnegative(mem.get("file")),
                         "inactive_file_bytes":_nonnegative(mem.get("inactive_file")),
                         "rss_anon_sample_minus_cgroup_anon_bytes":sum_anon-anon if sum_anon is not None and anon is not None else None},
            "processes":{"status":pinv.get("status"),"current":brief(current),
                         "other_matching_targets":[brief(r) for r in candidates],
                         "other_matching_anon_bytes":_total(candidates,"rss_anon"),
                         "other_matching_pss_anon_bytes":_total(candidates,"pss_anon"),
                         "unknown_python_classifications":len(unknown),
                         "sampled_processes":len(rows),"pss_anon_samples":sum("pss_anon" in r for r in rows)},
            "allocator":{"classification":allocator,"exec_env":exec_value,"exec_tunable":tunable,
                         "current_env":a.get("arena_max_env"),"arena_bytes":a.get("arena_bytes"),
                         "allocated_arena_bytes":a.get("allocated_arena_bytes"),"free_arena_bytes":a.get("free_arena_bytes"),
                         "free_arena_fraction":a.get("free_arena_fraction"),"top_releasable_bytes":a.get("top_releasable_bytes"),
                         "mmap_bytes":a.get("mmap_bytes"),"glibc":a.get("glibc")},
            "session_observations":{"active_sessions":runtime.get("active_sessions"),
                        "shared_cache_bytes":_total(inventory["shared_caches"],"estimated_bytes") if isinstance(inventory.get("shared_caches"),list) else None,
                        "private_cache_bytes":cache.get("estimated_bytes"),"private_owners":cache.get("owners"),
                        "uploaded_payload_bytes":runtime.get("uploaded_payload_bytes"),"media_payload_bytes":runtime.get("media_payload_bytes"),
                        "displayed_figures":charts.get("current_page_figures"),"retired_figures_alive":charts.get("retired_alive"),
                        "disconnected_sessions":reaper.get("disconnected_sessions"),"closed_session_refs_alive":reaper.get("closed_session_refs_alive"),
                        "tracked_climate_objects_alive":inventory.get("epw_lifecycle",{}).get("alive")},
            "scope":"Snapshot evidence only; no routing/termination authority. RSS can overlap; cgroup samples are not simultaneous; free arena bytes are not reclaimable RSS. Admission is not a production promotion."}
