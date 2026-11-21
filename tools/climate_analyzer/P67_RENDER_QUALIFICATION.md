# P6.7 — Rendering acceleration qualification

Report and Atlas exports use a sequential, export-scoped worker. On POSIX with a known finite cgroup limit, reuse for at most eight figures; recycle sooner at 72% of cap, below 512 MiB free, or after 128 MiB growth from the first warm sample. Unknown limit and non-POSIX hosts use disposable rendering. A renderer error retries once via disposable rendering; memory pressure aborts safely. Worker and descendants are killed on scope exit and before final PDF assembly. No parallel rendering.

Streamlit session owns a temporary disk cache (64 MiB / 256 entries, least recently used eviction). Keys include full styled Plotly JSON, scale, Plotly/Kaleido versions and worker source hash. No cross-session cache. Releasing PDF download bytes does not discard images; a new session or restart starts a new cache.

Timing instrumentation: serialization, Python worker startup, deserialization, combined Kaleido render and PNG encoding, post-render cleanup and wall time. Chromium cold startup is included in first render; rasterization and encoding are not separately observable through this API. Sampled cgroup peak is not a hard peak guarantee. Existing memory guard remains; OOM immunity is not claimed.

Qualification: standard P6 regression suite; actual worker reuse, failure cleanup, cache invalidation/corruption, size and ownership tests; independent Docker runs capped at 3 GiB for disposable, adaptive and cache modes. The 20-figure benchmark runs on relevant pushes; dispatch runs 20/50/100/200. Five synthetic families cover lines, heatmaps, polar, 3D and markers. Compare image geometry and pixels (MAE <= 0.2 channel levels; <=0.5% pixels differ by >2 levels). This synthetic harness does not replace live full-report validation on Streamlit. Set IGE_P67_RENDER_MODE=disposable to disable persistent reuse.

Status: candidate implemented; performance and live deployment qualification pending.
