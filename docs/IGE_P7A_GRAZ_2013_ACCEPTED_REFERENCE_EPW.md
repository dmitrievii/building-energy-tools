# IGE P7A — Accepted historical EPW reference for Graz 2013

**Source execution date:** 2026-10-11. **Accepted workflow:** [#38142594430](https://github.com/dmitrievii/building-energy-tools/actions/runs/38142594430), \`SUCCESS\`, source commit \`b8638d6830849a6c123c3c7f7bf7bcd576c7f737\`. Its scientific execution and source-format tests passed, original GitHub Actions artifact **11703014978**, \`ige-p7a-graz-2013-historical-reference-epw-original-source\`. The research code and execution protocol are in this working branch; \`main\` is untouched.

## Actual produced EPW

**Filename:** \`Graz_2013_P7A_Historical_Reference_RESEARCH_ONLY.epw\`  
**Bytes:** \`1,837,333\`  
**SHA-256:** \`da8a4e08e032bebbb3105b6584c319714fc85c99fc06a59d5fa1d125bf3478fc\`.

Independently extracted and inspected after GitHub completion:
- **8** EPW headers followed by **8,760** fully sequential local-CET 2013 hourly records.
- Exactly **35 fields on every** data row.
- First: \`2013,1,1,1,60\`. Last: \`2013,12,31,24,60\`.
- Native source time: NASA UTC start of hour; EPW: UTC+01:00 all year without DST, no additional synthetic time-shift. Jan 1 00:00 local maps to 2012-12-31 23:00 UTC.
- Reference T/RH/pressure/wind speed: **all 8,760 hours** draw on original GeoSphere Graz #30 \`q21\`-accepted \`tl/rf/p/ff\`; no gridded fallback was necessary for these **four measured parameters** in 2013.
- Other weather: original NASA POWER gridded wind direction, longwave sky irradiance and \`PRECTOTCORR\` hourly precipitation, with original units checked.
- Solar: **unchanged** frozen NASA POWER P6.3E \`GHI,DNI,DHI\` for each 2013 UTC hour, all three converted from hourly kWh/m² to EPW hourly Wh/m².
- Original NASA P6.3E flagged **47 original hours** for internal GHI/DNI*coszen+DHI component closure review during this EPW's fixed-local-year period. These are retained, not silently rebalanced.
- Dew point derived from QC-observed T/RH with documented Magnus relation. Original independent NASA \`T2MDEW\` is also present, but was deliberately not substituted into a mixed-source station thermodynamic pair.
- Missing station auxiliary attributes not invented: e.g. sky cover/illuminance/visibility/snow use EPW-standard missing sentinels; this affects downstream-model uncertainty.

**Independent file hashes checked after original artifact extraction:**
- EPW: \`da8a4e08e032bebbb3105b6584c319714fc85c99fc06a59d5fa1d125bf3478fc\`
- NASA POWER 2012-12-31–2013-12-31 auxiliary JSON: \`fc410b7417127b268429f12dd2e60ff547bd340f2fc755508303ac8cce5c60e1\`
- Per-hour observation/gridded-source lineage CSV: \`db49ac192265dac8f7a06a7c95f5a51f9acca298f7fe346a7b48779b4328747c\`
- Original P6.3E solar source CSV (unchanged): \`aa6529e317c96d7591cf99407671091acbc3420f55a81bbcfaee3d1d2c3495e9\`

All hash values match original \`p7a_epw_research_science_audit.json\`.

## Portable preservation

Exact file \`IGE_P7A_GRAZ_2013_PORTABLE_RESEARCH_FREEZE.zip\` (**545,498 bytes**), outer SHA-256 \`2bda61d9bacd4a91918e2e3a6dd9e3e263f5bb14758c618247f5561c3e4631a7\`. It retains **the original unchanged 4-file GitHub Actions ZIP byte stream**, \`MANIFEST.json\` with whole-ZIP and four member SHA256s, original source/run/commit, \`README.txt\`, and executable \`verify_portable_p7a.py\`. SHA verification after **independent extraction** PASS.

This is **not** a permanent TU Graz storage deposit. Preserve outside the short-lived GitHub artifact window, along with original P1–P6.3E freeze and P6.3F addendum. Do not redistribute or relicense upstream files without source licence evaluation.

## What is and is NOT scientifically established

**Confirmed:** technically valid 8-header/35-field/8760-record historic EPW; faithful source input/units and deterministic fixed standard-time calendar; underlying original science archive provenance verified, source-selection report; a real downloadable \`.epw\`.

**Not confirmed:** execution with an installed EnergyPlus building model, hourly climate **synthesis** from daily CMIP6, bias-adjustment accuracy beyond prior reported source studies, physically validated future meteorology, direct/diffuse independently measured site validation, or future SSP2050/2100 weather. Not a typical meteorological year and not an original pure-station EPW.

**Scientific EPW state:** \`FORMAT_AND_SOURCE_CONTRACTS_PASS\` / \`HISTORICAL_MULTISOURCE_REFERENCE_ONLY_NOT_HOURLY_CLIMATE_SYNTHESIS\` / \`production_epw_ready=false\`.

## Next scientific work

- **P7B:** independently reconstruct 8760 correlated hourly variables from original CMIP6 daily source, with source-preregistered 2013/2005–14 historic evaluation, careful constraints on astronomical solar shape, daily-energy conservation, dew point/RH/pressure closure, and wind temporal autocorrelation. Do not confuse historical GCM member day numbers with observed real 2013 date-specific weather.
- **P7C:** SSP245/585 future model windows, local uncertainty ensemble, downscaling/urban/altitude terms (P1–P5), EnergyPlus executable comparison, benchmark against P7A and user-supplied Meteonorm EPWs under relevant licensing.
