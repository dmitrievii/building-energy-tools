# IGE P7C.1 — EPW-Based Future Climate Morphing: Source & Physics Protocol

**Date:** 2026-10-11. **Status:** research-only. No production EPW or `main` modification.

## Goal and caveat

Create four 8760-hour *morphed representative-year* EPWs for Graz with CanESM5 r1i1p1f1, scenarios SSP245/SSP585 and 20-year source windows 2040–2059 and 2080–2099. The original **Meteonorm Graz-hour_contemporary_seed1.epw is not available as raw bytes in the accessible project container**. Therefore these four demonstrators use the accepted SHA-pinned **synthetic P7B.4 CanESM5 2013 baseline**, NOT an independent observed or Meteonorm baseline. This is a reproducibility pilot of the generic EPW morphing algorithm, not independent Meteonorm benchmarking or a completed operational future climate file. Actual Meteonorm EPW must later be passed to the same CLI and audited.

## Immutable sources

P6.1 original NASA NEX-GDDP-CMIP6 v2 CanESM5 r1i1p1f1 daily sources, five 20-year windows, original QA+provenance `PASS`, mandatory per-file SHA-256 of four source data files, native `noleap` 7300 days/window, grid center 46.875°N, 15.375°E. Historical = 1995–2014. Future = 2040–2059 or 2080–2099 under SSP245/585. Original GitHub Actions run #38072042977. No source-day matching or future instant-weather forecasts; **calendar year in EPW remains its historical pattern year 2013**. Effective period labels `~2050` / `~2090` are climate windows, not literal simulated year 2050/2090.

Original P7B.4 synthetic 2013 base file sha256 `2e45abbcba52c49e51e3811676ba37167bc8700f697e13032ee103ff8f3f7012`, from accepted workflow #38171672579. Preserve its unmodified copies in previous artifact history. Baseline has wind direction=999, total/opaque sky cover=99, visibility=9999 and precipitable water=999 for all 8760 hours. These missing values must NOT be converted to fake weather by the morphing routine. **Generic input EPW:** can be an arbitrary complete Graz-region 365-day source file with 35 EPW columns, valid weather and immutable source identifier. It must satisfy the geographical difference ≤0.4° from source grid; proximity is still not a formal downscaling demonstration.

## Explicit morphing policy

1. **Temperature:** for each calendar month, compare future and original 20-year daily mean-temperature distributions. Map each *baseline EPW day's mean-temperature quantile within that month* to a difference of GCM daily-mean quantiles. Center all within-month shifts to conserve the future-minus-historical **monthly mean-temperature anomaly exactly**. Modify within-day temperature deviations using the ratio of GCM future-vs-historical mean daily T max-min ranges, leaving the EPW day ordering unchanged. No GCM day-event pairing. This is an empirical quantile-delta assumption, not a physically simulated changing heatwave chronology.
2. **Moisture:** reconstruct hourly baseline specific humidity from existing T/RH/p. Scale specific humidity by future/historical GCM *monthly* mean `huss` ratio, combine with transformed T and the original EPW pressure, calculate RH and Td via consistent saturation vapour pressure. Bound 1%≤RH≤100%, log saturations explicitly. Where RH clips, source target q is **not** conserved; no false claim. Pressure stays the original input proxy: P6.1 has no surface pressure.
3. **Solar:** multiply baseline EPW hourly GHI by 20-year GCM monthly `rsds` ratio, preserve the resulting target daily energy. Reproject within each day if necessary onto the **TOA-bounded conservative research geometry**, retaining no daytime negative flux. Reject a physically infeasible daily target rather than concealing it. Estimate DHI/DNI from an Erbs correlation and close `GHI = DHI + DNI*cosz`. DHI/DNI not ground-validated.
4. **Longwave:** scale horizontal infrared sky radiation by monthly `rlds` ratio (a research proxy, not a detailed cloud/temperature radiation closure).
5. **Wind:** scale wind speed by GCM monthly `sfcWind` ratio. **Wind direction is copied byte-for-byte from original EPW** and never generated here; unknown 999 stays unknown. A source baseline with valid real directions will retain them.
6. **Rain:** scale existing liquid precipitation amount by monthly ratio from GCM `pr`, **without changing original rainy-hour timing/frequency**. Precipitation quantity interval field remains unchanged. Extreme storms and wet-day frequency trends are not reproduced.
7. All 26 nonedited EPW columns preserved byte-for-byte; edited column indices are `6,7,8,12,13,14,15,21,33` (0-indexed). Header comments disclose scenario, window, data limitations. 8 headers+8760 records×35 columns with strict hourly time order.

## Acceptance gates

- Identical CanESM5 grid/member/source calendar for all 5 20-year P6.1 windows; source SHA checks all pass.
- Exactly 4 scenario files, each with 8760 × 35 columns and same base EPW time axis, no invented wind direction or missing cloud values.
- Monthly mean T anomaly agrees with original GCM future-historical monthly change up to EPW rounding.
- Each source-day GHI target closes <1e-8 kWh/m²/day; hourly DNI/DHI identity closes <1e-8 kWh/m²/hour.
- Dewpoint ≤ dry bulb, 1≤RH≤100%, no negative rain/wind/radiation, and count of saturation-clipped hours explicitly reported.
- All original unmodified EPW fields remain exactly identical after a write/read cycle, including missing flags and pressure.
- No production release: full-year EnergyPlus checks, measured baseline (Meteonorm contemporary), future period uncertainty, precipitation event frequency, saturation humidity losses, and measured direct/diffuse solar remain open. Models have meteorological internal biases even after NASA BCSD; **P6 daily values are already bias corrected**. No additional model bias correction is silently imposed here.

## User-facing future workflow

When the actual `Graz-hour_contemporary_seed1.epw` is available, replace only `--baseline-epw`, re-run unchanged `--source-root` daily data, verify the baseline SHA and all 4 outputs, then perform a genuine independent Meteonorm comparison. For user-uploaded EPW at other locations, fetch/validate GCM grid data at the appropriate coordinates; do not reuse Graz data outside its currently registered geographical tolerance.

Official EPW field contract: [EnergyPlus Auxiliary Programs](https://energyplus.readthedocs.io/en/latest/auxiliary-programs/auxiliary-programs.html). NASA NEX-GDDP-CMIP6 source: https://www.nccs.nasa.gov/services/data-collections/land-based-products/nex-gddp-cmip6