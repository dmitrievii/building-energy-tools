# MEM-PERF R14.5D HF1 — WebSocket disconnect TypeError (production hotfix)

The Community Cloud runtime logs (2026-11-23T10:21–10:22 UTC) expose a deterministic failure while disconnecting sessions:

```
File ".../epw_climate_analyzer/session_reaper.py", line 74, in close
    ctx=get_script_run_ctx(thread,suppress_warning=True)
TypeError: get_script_run_ctx() got multiple values for argument 'suppress_warning'
```

Streamlit 1.63.0 accepts only `get_script_run_ctx(suppress_warning=False)` and obtains its context from the **current thread**. The disconnect callback executes on the runtime event loop, while the context we want to mark is attached to the ScriptRunner thread. A positional thread argument is incorrect and must not be used.

HF1 reads `SCRIPT_RUN_CONTEXT_ATTR_NAME` on the exact ScriptRunner thread, and mutates the context only when its `session_id` matches the closing session. Native close, private cache cleanup, counters, and the one-session ownership policy are unchanged. New tests cover matched/mismatched context, native close, cache cleanup, and the pinned upstream signature.

Other log messages are not the crash: Arrow serialization fallback (Value mixed int/float) and the `use_container_width` deprecation. There were also HTTP 404 frontend requests; proving that this hotfix resolves all blank screens requires the deployed browser smoke.

Keep the memory-panel UI rollback in place until this hotfix is verified. Then restore the compact UI in a separate commit. No changes to allocator, scientific solvers or reports.
