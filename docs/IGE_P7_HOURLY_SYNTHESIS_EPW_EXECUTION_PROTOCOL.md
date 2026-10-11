# IGE P7 — Hourly Climate Synthesis and EPW Generation: execution plan and P7A baseline

**Date:** 2026-10-11. **Research branch:** \`research/ige-p7a-historical-hourly-epw-reference-20261011\`. Forks completed P6.3F-B science line. **Never automatically merge into production main**. Source P1–P6.3E immutable freeze plus P6.3F source addendum remain external research custody.

## Why the research moves to EPW now

The end goal is to reconstruct independent Meteonorm-like **building simulation climate workflows**, without its proprietary algorithms. The immediate deliverable is a falsifiable end-to-end ***historical reference*** file, not another endless solar-only audit. Later stages can synthesize hourly meteorological dynamics from daily CMIP6 and apply future SSP signals.

This **P7A** establishes *format, units, time convention, physical field audit, source provenance and testable original-data assembly* for one original calendar year: **Graz 2013**, 8760 consecutive hours. A 2013 reference is not a typical-year selection, synthetic future year, or representative normal year.

## Canonical EnergyPlus EPW contract

Primary official spec:
- [EnergyPlus weather EPW data dictionary](https://energyplus.readthedocs.io/en/stable/auxiliary-programs/auxiliary-programs.html)
- [NASA POWER official hourly API time standards](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/)

EPW 8 header lines and 35 CSV fields per hour. **Hour 1 (EPW) covers local standard time 00:00–01:00**, EPW minute is 60 for each completed hour, hour 24 ends at midnight of the next day. The reference runs in **fixed CET UTC+01:00, NO daylight saving time**. Thus local EPW first hour is original **2012-12-31 23:00 UTC**; last 2013 EPW hour begins **2013-12-31 22:00 UTC**. 2012 source is needed even though EPW carries 2013 local time.

Raw local-station year 2013 and late-2012 original \`GeoSphere klima-v2-1h\` archives were obtained and QC-preserved in P6.2B; all q21 quality codes remain unmodified. If a station scalar \`tl,rf,p,ff\` is not original source-QC-approved, use explicitly original NASA POWER hourly meteorology and mark the per-hour source lineage. These are different observation types (on-station vs grid). Source units:
- GeoSphere station \`tl\`: °C.
- GeoSphere station \`rf\`: %.
- GeoSphere station \`p\`: hPa ⇒ ×100 Pa.
- GeoSphere \`ff\`: m/s.
- NASA POWER original ancillary hourly: \`T2M, T2MDEW, RH2M, PS, WS10M, WD10M, ALLSKY_SFC_LW_DWN, PRECTOT\`; source original unit for each verified at runtime; \`PS\` kPa ⇒ ×1000 Pa and \`PRECTOT\` mm/hour, direct LW W/m² ⇒ Wh/m² over complete hour.
- Original gridded NASA POWER **GHI, DNI, DHI** from unchanged P6.3E, original satellite/reanalysis source (NOT original ARAD ground radiation). kWh/m²/hour archive ×1000 ⇒ EPW hourly Wh/m².
- Dew point, when original station T/RH chosen, is derived with explicit Magnus inversion; neither a raw station dewpoint nor wet-bulb measured source. Source-lineage explains calculation. No unmeasured moisture variable is silently borrowed.

No fabrication of cloud cover, snow depth, visibility, illuminance or aerosols: exact EPW missing-data markers. The EPW may still use EnergyPlus internal substitutions for some missing auxiliary variables. **A file that parses and is structurally valid is NOT itself proof of a successful building simulation or a physically accurate all-field climate**.

Hard reject on absent hourly source/invalid original units/unknown source pressure/no solar field/ill-posed dew point. Do not fill in synthetic future weather during P7A.

## Three P7 research increments

1. **P7A historical original-source EPW benchmark** (this branch): pinned GeoSphere + NASA POWER source data and 8760-h strict EnergyPlus-compatible 35-field syntactic EPW; source QC and climate uncertainty visible; compare to external NASA POWER SB-community EPW output later as a reference, not as a license to copy Meteonorm logic.
2. **P7B real hourly weather synthesis from daily source**: select one accepted original NASA CMIP6 daily model-window, construct hourly temperature/humidity/cloud/wind/sun with an explicit stochastic/disaggregation model, deterministic seed, correlated multivariate innovation, daily/monthly conservation and physically coherent hourly GHI/DNI/DHI. Historical 2005–2014 heldout validation uses GeoSphere original historical source, NASA POWER reference; no claim of matching exact observation dates to historical CMIP6 GCM years.
3. **P7C future SSP scenario & building simulation evaluation**: carefully transfer the daily-source model to \`ssp245\`/\`ssp585\` 2040–2059/2080–2099 without leakage of future ground observations, quantify scenario uncertainty/ensemble spread and run EnergyPlus sample case. No production until power/psychrometric/multivariate/solar validations and building impact credible.

## Acceptance for P7A only

- Original provider downloads and station archives preserve exact sha256/URL and native units; 2013 cross-year time origin confirmed.
- Output exactly 8760 unique consecutive 2013 fixed-CET hours, each 35 fields; 8 correct header records.
- All critical weather fields finite and within documented broad physical bounds; quantity conversions explicit; never classify NASA grid as station.
- Original NASA solar GHI/DNI/DHI left unchanged; source component discrepancies counted, not "corrected" by balancing.
- Single \`Graz_2013_P7A_Historical_Reference_RESEARCH_ONLY.epw\` plus original API JSON, line-by-line source lineage CSV, science audit JSON, exact output SHA256s.
- Public/research EPW may be generated as an executable test deliverable, **not** used to claim production-ready. \`production_epw_ready=false\`.
- CI PASS does not constitute EnergyPlus executable validation, an independent solar instrument calibration, or validation of any future climate.

**Primary research question for P7B:** how to preserve the thermal/day-night relationships and original daily CMIP6 energy/statistics while reconstructing physically feasible hourly multi-variable climate, and how sensitive are building energy/comfort results to the statistical model and its uncertainty?
