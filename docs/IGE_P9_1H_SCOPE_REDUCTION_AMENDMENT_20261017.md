# IGE P9.1H — Amendment A: reduced verification scope and CI budget

**2026-10-17, prospective scope reduction after the Hyytiälä 2018 source readback.**
This is an amendment to, NOT a rewrite of, the original frozen preregistration in `docs/IGE_P9_1H_NEAR_SURFACE_INVERSION_CROSSREGIONAL_PREREG_RU.md`. The original source inventory, tests, date windows, source quality constraints, and all negative P9.1G findings remain unchanged.

## Decision

The immediate research question is limited to **whether near-surface inversion structure can be reconstructed and whether one guarded correction is credible in two contrasting surface regimes**. It is NOT a claim of worldwide/global arbitrary-point 2-m temperature accuracy.

Only TWO active independent tower sites:
- Hyytiälä (Finland): 4.2 and 67.2 m, source access and exploratory source profiles verified for Jan/Jul 2018. Forest/canopy exposure, **not** a valley-floor inversion proxy.
- Cabauw (Netherlands): 2–200 m, KNMI manually checked LB1 source *if and only if authentic native files and their QC can be accessed*. This source is not yet authenticated. If blocked, record BLOCKED and stop broadening.

**Removed from this iteration's active execution:** DOE ARM SGP; Lindenberg mast; additional station scouting; alternative years, months, station lists, and thresholds; repeated full-source downloads on every commit. Historical source metadata may remain in the frozen registry but does not constitute an active validation cohort.

### Frozen sample budget

- Development only: **10–16 January and 10–16 July 2018**, exactly as preregistered.
- Single untouched end-stage holdout: **10–16 January and 10–16 July 2021**, same sites, only after complete physical model freeze.
- No additional year/season trial on seeing errors.
- No extra geographic substitution if KNMI cannot be read independently. If unavailable, H1 cross-regional qualification remains BLOCKED, and this stage ends with Hyytiälä source-only results.
- The original H1 scientific qualification gate (two independently quality-checked regions), native QC, true simultaneous levels and original SHA is NOT relaxed.

### Minimal physical experiment

1. **H1**: verify genuine native sensor source, timestamps, physical level separation and QC for the two active sites. Use the already verified Hyytiälä 2018 hashes; no need to reacquire the same data without an identified source issue.
2. **H2 + H3**: single transparent, physically constrained hypothesis; compare only: ERA5 native grid 2m (B0), fixed 6.5 K/km regular-grid lapse (B1), provider altitude adjustment (B2), and one candidate near-surface regime guard (H). Do not undertake a large threshold grid, feature ablation, or automated hyperparameter search.
3. **H4**: one independent *blind* 2021 evaluation of the frozen model, on eligible sites only. Compare site×season MAE, signed bias, worst-cell degradation, plus observed profile inversion event counts/precision/recall if classification is used; report sample sizes and day-block uncertainty. Secondary detailed diagnostics only if necessary to explain clear failure, not to retune a heldout model.
4. **Closure**: one scientific decision: **qualified for narrow-source research** or **not established**. No geographic extrapolation beyond observed exposure types. Never auto-merge to main.

### Limited GitHub Actions policy

- No automatic `push` activation for P9.1H1.
- `workflow_dispatch(mode=contracts)`: **manual, local** lightweight source-registry and algorithm unit contracts only, no internet.
- `workflow_dispatch(mode=source_readback)`: **manual, one-time only when needed** original existing Hyytiälä 2018 4.2/67.2m observed-profile aggregate with SHA. Do not repeat OpenAPI schema, metadata, one-day probe, or any 2021 read.
- Later KNMI access must have a separately documented (native QC/source SHA) one-shot call; do not add speculative repeated attempts to CI.
- A green contract workflow validates code integrity, **not** scientific validation; no need to poll/re-run green checks without code changes.

**Production flags unchanged:** `near_surface_inversion_model_qualified=false`, `global_arbitrary_point_weather_qualified=false`, `production_epw_ready=false`. New scientific claims require source qualification and the single frozen holdout.
