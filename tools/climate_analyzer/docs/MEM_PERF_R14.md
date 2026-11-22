# MEM-PERF R14 — experimental qualification, not production promotion

## Frozen constraints
Production remains Streamlit 1.63.0; preserve every scientific algorithm,
chart specification, and report interface. Do not change or terminate
platform-owned processes. The HF2 managed launcher remains separate.

## R14.1–R14.2: upstream reproduction
Confirmed upstream issues:
- https://github.com/streamlit/streamlit/issues/17860
- https://github.com/streamlit/streamlit/issues/17861

Both pinned runtime sources retain the final flush-loop local. Compare
unmodified native TTL, immediate native close, and immediate close plus
startup-only loop-local release on 1.63.0 and 1.67.0. Three serial sessions
per arm; actual disconnected TTL 2 s, sample after 6.5 s additional idle
time, no observer websocket needed. Synthetic 8 MiB native session resource
and fragment interaction. Capture exact dependency freezes, raw RSS,
weak references, physical TTL storage size, shutdown state, release counts,
and immediate wrapper holder classes. Native arms can report retention
without failing solely for the known defect. The corrected arm must reach
zero live sessions, zero cached payloads and zero physical entries.

## R14.3–R14.5: migration admission
Only migrate a private cache after demonstrating native scope, on_release,
isolation across simultaneously connected users and byte budget equivalence.
Native max_entries is not a byte budget; preserve existing ByteLRU guards.
Do not put the climate DataFrame into cache_data without measuring copying.
Separately audit parity wrapper captures and concurrent install semantics;
no blanket st.fragment decorator around legacy code. Start with independent
read-only chart controls; verify navigation, report capture and science parity
before promotion. The fixture demonstrates fragment/full-run separation,
not real-app compatibility.

## R14.6–R14.8: remaining tests
The fixture supports opt-in R14_TRACE=1 (tracemalloc); trace overhead makes
it a separate diagnostic run, not a timing comparator. RSS includes native
allocations, and is not a measure of Python object bytes. Run the HF2
matched allocator screen after the session lifecycle gate passes. Then use
a real app version matrix with coherent dependency constraints, 100 serial
and 1/2/5/10 simultaneous sessions, exact EPW and report parity, and warmed
memory drift. Community Cloud needs a distinct qualification; the managed
launcher patch cannot be assumed active when the platform owns startup.

## Platform incident
Two matching launch targets were found in production, one no longer listening
on TCP. No automatic termination is authorized by this evidence. Platform
support or a controlled operator reboot is needed to establish and restore
single-instance operation. No ongoing reboot schedule is part of R14.
