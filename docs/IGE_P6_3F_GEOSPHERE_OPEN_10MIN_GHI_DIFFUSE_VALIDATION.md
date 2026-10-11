# IGE P6.3F — Open GeoSphere 10-minute ground GHI / Himmelsstrahlung audit

**Research-only pivot on 2026-10-11.** Replaces ARAD-first acquisition as a **necessary** prerequisite with an audit of the publicly accessible GeoSphere historical \`klima-v2-10min\` resource. The earlier ARAD request was drafted only and **not sent**. ARAD remains a *possible* later independent DNI/ground precision validation source, not a mandatory step for historically observed GHI and Himmelsstrahlung if open-data QC is sufficient.

## Official provider and missing evidence

- [GeoSphere klima-v2-10min](https://data.hub.geosphere.at/en/dataset/klima-v2-10min): official station archive, from 1992, 10-minute resolution, availability of individual \`_flag\` codes, majority source QC since 2006; CC BY 4.0, dataset DOI https://doi.org/10.60669/8fya-7x87.
- [GeoSphere API endpoints](https://dataset.api.hub.geosphere.at/v1/docs/getting-started.html): historical station data/metadata are separate original endpoints; station ID is not sufficient to establish availability of a given *variable* in a given year.
- [Parameter catalogue](https://dataset.api.hub.geosphere.at/app/frontend/station/historical/klima-v2-10min): original \`cglo\` (Globalstrahlung Mittelwert), \`chim\` (Himmelsstrahlung Mittelwert), \`cglo_flag\`, \`chim_flag\` and original unit W/m² as determined from official API metadata on every live research run.

**CRITICAL:** \`chim\` is labelled Himmelsstrahlung by the original API. Treat it provisionally as *diffuse horizontal sky radiation* pending verification of instrument measurement geometry and source data documentation. NEVER treat \`chim\` as downwelling longwave (LW) or independently measured DNI. Neither \`cglo\` nor \`chim\` measures direct-normal solar irradiance.

## Preregistered original-source coverage

Locations: **Graz station IDs 30 and 16412**, independent verification of identity and coordinates from the 10min **original metadata** (not implicit from hourly metadata). Calendar: all 10 years **2005–2014** inclusive, 3,652 calendar days, expected **525,888** 10-minute UTC labels per station if complete (3652×144); source 10-min levels are never imputed.

**Note**: *recording existence* must be measured separately for each parameter and station/year, and the observed station may have migrated location/instrument. The original 2005–2014 q21 status for previous \`klima-v2-1h cglo\` **cannot be inherited** by a \`klima-v2-10min\` record or vice versa.

Original provider API 10-min metadata and requested annual source GeoJSON are preserved *byte-for-byte before compression* with SHA-256 and exact source request URLs. Provider rate policy: max 5 requests/s / 240/h and 1 million values per JSON request. Each one-year, one-station source request uses exactly 4 variables × about 52,560 labels = ~210,240 values and is below the limit. Source request errors are explicit coverage failures, not silent synthetic data.

## Official quality and six-of-six hourly construction

Per ten-minute source parameter, accept only original \`q21\` codes **10, 11, 12, 20, 21, 22** when the original metadata confirms these labels. **q21=0 means ungeprüfte Daten (unchecked)** and is not accepted. Per year and station report the original histogram of every observed quality code and missing observation, not just accepted counts.

One accepted hourly solar component requires **all six distinct original ten-minute source means** in that hour and accepted QC on **all six** of them. Do not fill gaps, drop unchecked minutes, inflate an incomplete 5/6 average, or convert a suspect reading to 0.

With W/m² ten-minute interval mean, hourly energy is:

\[
E_{\mathrm{hour}}={\sum_{i=1}^{6}G_i\over 6000}
\quad\mathrm{kWh/m^2}.
\]

Global and sky diffuse are checked **independently**; joint verified GHI+DHI hourly completeness requires both channels 6/6 q21-accepted. Preserve original small negative sensor offsets without unlabelled clipping.

### Timestamp uncertainty

The code compares **two unendorsed hypotheses**:

1. \`record_start\` (source label is beginning of averaging interval);
2. \`record_end\` (source label is end of averaging interval, subtract 10 min before hour grouping).

**Neither hypothesis is accepted simply because it obtains higher correlation.** Exact original provider 10-min mean averaging window is still an external metadata/documentation question. Cross-year first/last hours at incomplete edges remain not-qualified; there is no hidden imputation.

## Independent comparisons

Frozen NASA POWER P6.3E GHI and DHI are the external gridded/satellite/reanalysis reference (not station observation): **2 preselected reference points** (\`graz_station30\` and \`nasa_gcm_cell\`), hourly 2005–2014 data verified against original frozen P6.3E SHA.

Per station × 2 time-window hypotheses × two NASA points × two measured channels × ANNUAL/DJF/MAM/JJA/SON, report **number of exact UTC matched verified hours**, fraction of total hours, bias, MAE, RMSE and Pearson r. Values are **NULL**, not fake zero, where no valid observed q21 hourly pair exists. Store exact time labels, source SHA and per-parameter QC coverage.

Additionally, a further independent solar-day benchmark is available: original GeoSphere station #30 approved \`cglo_j\` daily data, P6.3D, with official 23:00–23:00 UTC day label. Cross-sample hourly derived GHI *should eventually* be reconciled against this source, but it is not an independently measured second institution — it may share station instrumentation and processing. The current audit reports year/hour QC and NASA comparisons first; a subsequent independent calendar-day closure check is mandatory before final scientific approval.

## Required interpretation / go-no-go

- If station/year original data have no q21-approved 10-minute GHI or \`chim\`, report \`PARTIAL_OR_UNAVAILABLE_ORIGINAL_STATION_SOURCE\` or inadequate QC with exact counts. Do not promote stage to independent validated observed GHI/DHI.
- If only GHI is confirmed, independently validate GHI and retain **DHI OPEN**.
- If both GHI and \`chim\` have adequate coverage and original measurement geometry is verified, the open-source station can establish independent measured *ground* GHI/DHI skill without ARAD.
- **DNI remains not independently measured**. The algebraic expression \`(GHI-DHI)/cos(zenith)\` is a derived estimate only and unstable at low solar elevations.
- Native \`GeoSphere\` 10-min/1-h/day label windows cannot be chosen post hoc to optimize correlations.
- Neither satellite-vs-ground accuracy nor physical component closure certifies future hourly EPW or multivariate future climate validation.

**No application production, no \`main\` merge without explicit approval**. Scientific state stays **REVIEW_REQUIRED** until original station/provider availability, QC and timestamp semantics are confirmed and documented.
