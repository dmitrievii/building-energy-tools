# MEM-PERF R14.5C — Compact memory controls

UI-only change. The default Memory management panel now presents container usage and pressure, application anonymous RSS, manual cache cleanup, consent-gated reset, snapshot capture/download/release, and concise last-cleanup feedback. A duplicate Climate Analyzer process still produces a visible warning. Advanced diagnostics (existing mem_r6_detail_tables key) exposes allocator recovery, object census, cache, runtime, session, process and export counters only when selected. All existing inventory JSON evidence and its schema remain unchanged. The Scientific Report, diagrams, runtime lifecycle, memory samplers and production allocator configuration are unaffected.

Keep stable automation keys and selectors (Inspect retained resources (refresh snapshot), Download memory inventory JSON, Clean unused caches, Reset session), including Snapshot captured: prefix. No nested Streamlit expander.
