# R14.5A HF1 — actual Community Cloud ownership

Source: run 45091195227 artifact 14781610650, inventory captured 2026-11-23T00:51:46.916276Z. Exact deployed runtime fingerprint verified in R14.5A. Cgroup used 2705420288 / 3221225472 bytes; anon 1796468736; file 758804480; inactive file 625156096. Current PID 3298, start ticks 1709974, process inventory anon PSS 1193123840. Older matching PID 3023, start ticks 501242, PPID 1, anon PSS 576933888, no listener/established TCP, one CLOSE_WAIT, two Unix sockets. Seven observed processes and two PssAnon samples; process anon RSS sum 1797300224, difference vs cgroup anon +831488 (sampling and accounting differences). No proof older process is safe to terminate. Platform manages lifecycle.

Current observer: one active session, zero private cache owners/entries, 304305 bytes shared cache, no uploaded/media payloads, zero displayed/retired charts, zero tracked EPW, zero retained disconnected sessions. Allocator: glibc 2.41, arena 935641088, allocated 298372528, free 637268560 (68.11%), top releasable 471264, mmap 4247552. These are overlapping accounting scopes; free arena bytes do not establish physical reclamation. Startup baseline absent in this snapshot; no global heap census claimed. No explicit arena env or tunable at exec.

New ownership contract used by public on-demand memory inventory and standalone historical/fresh analysis; strict failure on incomplete inventory or other matching launch targets, absent/ambiguous allocator startup request. Two fresh observer sessions preserve evidence; no process kill, no forced restart, no new child runtime, no public configuration change.

Operator-only controlled test after evidence collection: use Manage app -> Reboot app when users can tolerate interruption. Compare process identities (PID + start ticks), anon PSS, raw cgroup usage and free arena. If old matching target survives or returns, escalate to Streamlit support with evidence; do not patch platform supervision. If operator wants to test supported Secrets UI, MALLOC_ARENA_MAX = "2" is non-sensitive, but no assumption that Cloud exports it before exec; preserve other secrets and confirm actual exec origin after reboot. If absent/late, remove experimental setting and retain normal baseline. glibc mallopt is MT-Unsafe init const; never tune live. No admission from shell or late os.environ alone. Reboot is disruptive, not automatic.

Docs: https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/reboot-your-app
https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
https://sourceware.org/glibc/manual/latest/html_node/Malloc-Tunable-Parameters.html

R14.5B remains gated on measured Cloud ownership and real workload memory. Existing R14.4B5-B6 mixed campaign is independent. Production promotion not authorized by diagnostic gates alone.
