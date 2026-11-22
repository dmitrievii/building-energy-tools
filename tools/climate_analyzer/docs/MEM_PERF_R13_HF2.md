# MEM-PERF R13 HF2 — runtime ownership

The production Streamlit Community Cloud app is launched by its platform, not
by the repository's managed launcher. The application performs read-only
process diagnostics. A second matching launcher is not sufficient authority
to terminate it, even if its current parent is PID 1.

## Live verification
Download the HF2 memory inventory. For each matching launcher compare PID,
start ticks, parent PID, listening ports and TCP connection counts, and
whether socket enumeration was complete. A listener with no established
connections can still receive routed requests; an absence of observed sockets
does not establish platform ownership. The operator must verify deployment
routing and ownership outside the public application before stopping an old
process. Never expose a process termination button to app visitors. No PID is
hardcoded and no signal is sent by HF2.

## Self-managed Linux deployment
From the repository root:
`python tools/climate_analyzer/scripts/run_managed_climate.py --server.headless=true --server.port=8501`

The launcher holds a cooperative exclusive lock by resolved application path
and UID. All launches of this deployment must use it; it cannot enforce
ownership on a platform launcher or another UID. The lock is released by the
OS on process exit. An already running unmanaged process must be resolved by
the deployment operator. No routine full restart is part of session reset.

The launcher installs a version-guarded Streamlit 1.63.0 runtime-loop
correction before Runtime creation. The upstream long-lived coroutine retains
the last ActiveSessionInfo, message list and message across its wait. The
correction clears those locals after flushing all sessions and before waiting.
It is not applied to a suspended coroutine. Direct platform startup is
reported as unpatched in the diagnostic JSON. Both the 20-cycle real EPW
workflow and arena screening exercise the managed launcher. Platform-specific
validation remains necessary.
