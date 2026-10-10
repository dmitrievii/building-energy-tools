# IGE Climate Engine — P6.2B, GeoSphere hourly historical provenance and source quality

Date 2026-10-10. **Execution scope:** first historical quality-screened station archive 1995–2014, not completed model bias correction. Production branch main unchanged. Stage closes only if live NASA/GeoSphere cross-source quality gates succeed.

## Inputs

GeoSphere Austria Dataset API, station 30 (Graz Universität / Heinrichstraße), dataset \`klima-v2-1h\`; hourly requested parameters \`tl,rf,rr,cglo,ff,p\` and their advertised \`_flag\` fields when present. Annual requests 1995–2014 inclusive (20 complete UTC Gregorian years, 175320 hours in total). The API has a ceiling of 1,000,000 CSV/JSON points per request, so individual annual station-30 queries stay below it, even with 12 fields. API documentation: https://dataset.api.hub.geosphere.at/v1/docs/user-guide/request-limit.html . Source code and quality-list definitions are acquired from the live metadata.

## Scientific quality gates

- Do not accept a series without a complete chronological UTC calendar, including leap days; reject timestamp shifts, duplicate timestamps or unknown units.
- Keep exact original GeoJSON response compressed with its SHA-256 of uncompressed bytes. Save individual raw observation, quality flag and quality-screened observation separately; never overwrite raw or invent missing values.
- Use GeoSphere \`q21\` codes 10/11/12/20/21/22 as *quality-checked* (automatic or manual); unverified 0, absent and unknown flags are not accepted for scientific summaries. Preserve original quality-code distributions.
- Apply generous physically plausible screening limits only to diagnostic series; preserve all source values, even out-of-range. This screening does not amount to recalibrating NASA or to replacing outliers.
- Monthly hourly summaries only where at least 90% of source hours pass QC, with actual fraction recorded. \`rr\` hourly sum is explicitly *UNVERIFIED* even with 100% hourly availability until temporal meanings in GeoSphere metadata and comparison against monthly \`rr\` are reconciled. Do not convert \`cglo\` W/m² into GHI energy until its sample/mean meaning is established.
- Compare monthly metrics with the independently downloaded official \`klima-v2-1m\` \`tl_mittel\` and \`rr\` for each of 240 months, preserving the distinction between station-monthly temperature construction and arithmetic average of hourly \`tl\`.
- The eight already NASA-BCSD-corrected GCMs must not be modified or fit against this station archive yet. Subsequent P6.2B research must test seasonal distributional differences, elevation/grid mismatches, temporal blocked validation and multivariate coherence before endorsing any local correction.

## CI plan

Initial two years (1995, 2014) serve as boundary-case feasibility gates, then 18 intervening annual retrievals. Each of 20 annual artifacts has raw provider .geojson.gz, hourly QC table, monthly coverage table and scientific QA/provenance. An independent post-download audit requires exactly 20 years, 175320 unique UTC hours, 240 month-year records, 20 provider source SHA-256 values and all 6 variables' coverage/flag distributions. It compares hourly-derived, QC-screened summaries with the official monthly station source, without assuming that all hourly parameter definitions coincide with official monthly definitions.

The provider is allowed to contain real source gaps; missing values count against QC coverage and never cause artificial completion or false PASS claims about climate-validation fitness. A successful source integrity audit means **historical station data are reproducibly available**, not that every variable has sufficient observational coverage for bias correction.

## After source validation

- Inspect source hourly \`tl,rr,cglo,rf,ff,p\` metadata semantics and 20-year coverage per parameter.
- Test the gap-free candidate subsets against \`klima-v2-1d\` official daily observations and GeoSphere monthly station 30.
- Use quality-controlled observed reference distributions for eight-model historical distribution and seasonal benchmark diagnostics. Do not compute per-date GCM RMSE (non-phase-matched simulations).
- Fit additional site transfer functions only if cross-validated residual bias and physical joint preservation demonstrably justify them; reserve observed years for holdout.
