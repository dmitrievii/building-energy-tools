# IGE P7B.2 — Accepted original-data numerical results and RH-restored historical 2013 EPW

**2026-10-11. Research only; no production or main merge.**

**Accepted original-source GitHub workflow:** [#38149471728](https://github.com/dmitrievii/building-energy-tools/actions/runs/38149471728), **SUCCESS**, execution commit \`e0d2a723bf438d428e89a7996de14b117539d839\`. Full source-regression suite: **21/21 tests** (8 new P7B.2, 6 P7B.1 and 7 original P7B), plus original-source production-readiness/EPW/physical guard. Original output artifact ID **11705552067**, \`ige-p7b2-canesm5-physically-bounded-moisture-and-geo-ground-solar-epw\`.

Original artifact independently downloaded and inspected; entire ZIP SHA-256 \`f11da30cbd8fa4b67963c96d1fcb946a1ca92c68b5ca0b89db913c6d4fcc8130\` (910,756 bytes). All five original output CSV/EPW SHA-256 values recomputed from extracted bytes and match frozen original \`p7b2_science_audit.json\`. This is a portable data artifact, **NOT** permanent TU Graz data deposition.

## Deliverable: original-new corrected experimental EPW

\`Graz_2013_CanESM5_P7B2_HISTORICAL_BIASCORRECTED_RH_RESTORED_RESEARCH.epw\` — **1,892,862 bytes**, SHA-256 **\`0f72bc607c5d00a243ffcf5d034ba26a4876109d52a92ca35d604dc78b081d96\`**.

- Exactly **8 original header lines and 8760 consecutive fixed-CET 2013 EPW hours**, 35 fields per hour, first \`2013,1,1,1,60\`, last \`2013,12,31,24,60\`. Source is original model weather for **CanESM5 historical 2013**, not the actual observed weather of Graz on those 2013 dates.
- Dry-bulb source day T mean/min/max, wind mean, rain total and downwelling longwave total conserved. Hourly GHI, DHI, DNI satisfy source-internal beam/diffuse balance, but **DHI and DNI remain Erbs-derived**, not independently observed.
- All RH values in [1%,100%], all dewpoints ≤ dry bulb; maximum original **98.9711 RH pp/hour** jumps repaired to a maximum **14.4425 pp/hour** over all consecutive hours and day boundaries, **0** hours exceed the preregistered 20-pp/hour screen.
- Original daily hurs/huss joint constraints assessed against fixed pressure proxy (not actual observed/model PS), and after 7h cross-day regularization and two-basis source restoration all source-daily errors independently recalculated.

### Truthful source humidity conservation after RH continuity

| Final original source constraint status | Number of 2013 days |
|---|---:|
| Both original daily mean \`hurs\` and \`huss\` conserved to numerical tolerance | **130** |
| Original \`huss\` conserved; original mean \`hurs\` explicitly relaxed | **208** |
| \`huss\` still not conserved under the chosen RH rate/fixed pressure/humidity constraints | **27** |
| **Total** | **365** |

Max final original \`huss\` residual **0.0007243329 kg/kg = 0.72433 g/kg**. Largest original \`hurs\` residual **24.913 RH percentage points** on constrained days. Some of the 27 days arise from source pressure/saturation incompatibility; some arise from the new temporal rate constraint. The **14 original prefilter saturated-source impossibility days** remain a separate diagnostic and must **not** be added to final 27 as distinct days.

**Not an observationally calibrated psychrometric model.** This method enforces instantaneous thermodynamic admissibility and temporal continuity while explicitly preserving only source daily constraints physically reachable under its registered family. It does not justify claiming that all original CMIP6 daily hurs/huss means are preserved.

### Genuine ground-observed GHI calibration and independent holdout

Original q21-approved GeoSphere Graz daily \`cglo_j\` is an independent *station observation* (not another model reference). Monthly calibration factors are computed **only** on 2005–2009 five-year station-vs-historical-CanESM5 daily climatological distributions; 2010–2011 excluded because of original source daily-versus-10min discrepancies. 2012–2014 withheld as a true separate historical time period, containing the synthetic model-calendar 2013; NO 2013 real observed values used to fit any factor. Model calendar days and station observed dates are not paired weather events.

| 2012–2014 separate-source 365-day-normalized climatology | Annual GHI (kWh/m²/year) |
|---|---:|
| Original ground measured GeoSphere | **1231.52458** |
| Original NASA NEX already-BCSD CanESM5 (not locally adjusted) | **1615.73971** |
| Local station-trained additionally corrected CanESM5 | **1257.97075** |

Original model-vs-ground climatology +**31.1983%**, corrected +**2.1474%**. The unpaired 12-month mean-daily GHI MAE decreases **1.05584 → 0.25569 kWh/m²/day**; monthly-climatological RMSE **1.08636 → 0.30123** kWh/m²/day. This is evidence of historical independent-heldout climatological benefit for **one** GCM/model/source/site, **not** a forecast skill estimate or proof additional local calibration is safe for future SSP where NASA NEX was already bias-corrected.

Synthetic EPW 2013 annual corrected GHI = **1271.8285 kWh/m²/year**. That value is neither the observed 2013 station GHI nor the withheld three-year average: 2013 CanESM5 is an independent model-weather realization.

### New original output SHA-256 (all verified)

| Original artifact member | SHA-256 |
|---|---|
| \`Graz_2013_CanESM5_P7B2_HISTORICAL_BIASCORRECTED_RH_RESTORED_RESEARCH.epw\` | \`0f72bc607c5d00a243ffcf5d034ba26a4876109d52a92ca35d604dc78b081d96\` |
| \`p7b2_2013_synthetic_hourly_physics_and_sources.csv\` | \`e8646b1913a2006a947f5afc2ad63ba2152626c6b7045c12194e79a1939d1377\` |
| \`p7b2_2013_native_daily_source_and_constraint_tradeoffs.csv\` | \`674aa295621c93cb4f73c2a43f9be4b47fdbf08de8fca26e637460ba938a3e63\` |
| \`p7b2_ground_observed_monthly_GHI_training_factors.csv\` | \`368b0c9ec8b84dac72b52ad0fbd01171081f1843586a18027bf5eebd3b7ffc73\` |
| \`p7b2_ground_observed_2012_2014_holdout_months.csv\` | \`a3a149c8029aec52ba062ffb4acd01cfc73435ceef4b8a02b4b1d31d22a5abf6\` |

## Honest stage conclusion

**Technical P7B.2 pilot: PASS.** P7B.2 achieves (a) a new original-source EPW with RH/Tdew bounded, (b) empirically effective 5-year local station monthly GHI calibration tested on a separate historical period, (c) explicit full-source-audited 8760 hourly temporal plausibility, and (d) transparent source-humidity compatibility classes.

**NOT PRODUCTION READY:** \`epw_production_ready=false\`. Still open: independent site pressure/humidity source linkage for 27 days and 24.9pp RH source mismatch extremes; actual observed-hour wet-air/wind/rain temporal joint distributions; 8 GCMs and uncertainty quantification; P6 bias correction transfer to SSPs 2050/2100 without leakage/double correction; practical EnergyPlus model-run test; measured direct/diffuse radiometry; source grid representativeness (CanESM5 NEX grid 46.875°N,15.375°E differs from Graz station ~47.08°N,15.45°E).

**Do not select the earlier original workflow #38148686542 output**, which had ~99 pp/hour RH jumps despite all values lying in 1–100%, or the intermediate simple 5h smoothing output which conserved no original daily hurs/huss exactly. Both are retained as method-development provenance and superseded by accepted scientific run #38149471728.

**Next research increment:** calibrated historical observed-hour distributions, native pressure sourcing / wet-air hierarchy, 8-GCM/SSP transfer gates, and an actual EnergyPlus load-run impact assessment. Keep original source EPW history immutable and production \`main\` untouched.
