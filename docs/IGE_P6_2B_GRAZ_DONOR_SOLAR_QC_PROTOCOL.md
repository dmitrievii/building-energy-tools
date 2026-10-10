# IGE P6.2B — Graz donor-station QC and independent solar-source screening

**Date:** 2026-10-10. **Status:** research reconnaissance; CI not yet confirmed. Production \`main\` must remain untouched.

## Reason for this phase

The 1995–2014 historical hourly source closure at Graz GeoSphere station #30 retrieved all 175,320 UTC timestamps, but our source-QC rules accepted only 106/240 monthly temperature/humidity/wind/precipitation/pressure months and no solar-radiation months at 90% coverage. From the original provider data: before March 2006 many measurements carry \`q21=0\` (unverified) and \`cglo\` observations still carry \`q21=0\` in later years. A complete timestamp index is NOT evidence of a fully quality-approved reference climate archive.

GeoSphere code list \`q21\`: \`0=ungeprüfte Daten\`; \`10,11,12\` automatically checked; \`20,21,22\` manually checked. Source: https://dataset.api.hub.geosphere.at/v1/docs/changelog.html

## Experiments (strictly source discovery, NO calibration)

1. Retrieve live GeoSphere \`klima-v2-1h\` metadata (station coordinates, altitude, parameter units, \`q21\` meanings). Dynamically select closest stations within a 75 km great-circle radius of the Graz research target (46.983 N, 15.450 E), up to 12 closest, plus the six previously used P3 donor IDs (30,116,200,54,8,13605) if present. Preserve provider names/IDs/coordinates. No station chosen only by intuition.
2. For all selected stations, request \`tl,rr,cglo\` and advertised \`_flag\` fields for January and July of 1995, 2000, 2005, 2010 and 2014 (ten sampled months). Compare raw non-null counts to quality-checked \`q21 \in \{10,11,12,20,21,22\}\` hours. Preserve all ten original GeoJSON response hashes and snapshots. Report solar measurements as **quality-approved ONLY** when recorded \`cglo\` has the official checked flag. Geographic proximity alone does not prove transferability.
3. Independently retrieve \`klima-v2-1m\` 1995–2014 monthly \`tl_mittel\` and \`rr\` for the known six donor stations, with provider quality flags where supplied. Quantify source completeness; retain provider raw response.
4. Inspect live metadata from \`klima-v2-1d\` and \`klima-v2-1m\` for potential direct global-radiation parameters. Probe daily source for Graz #30 in July 1995, 2005 and 2014 **only when a direct global-radiation parameter exists**. Do NOT use sunshine duration as GHI; no solar unit conversion until verified.
5. Explicitly note that the 2026 GeoSphere \`apolis-v2-1d-100m\` solar dataset warns of an erroneous EPSG definition producing 70–80 m positional shift; do not use this product as an uncorrected solar reference. Source: https://data.hub.geosphere.at/dataset/apolis-v2-1d-100m

## Limits and decision gates

These ten monthly snapshot probes cannot establish 20-year solar continuity or local building-site representativeness. A station with verified radiation in snapshots becomes a **candidate** for subsequent full-year QC, not an accepted historic calibration station. Keep NASA NEX-GDDP-CMIP6 v2.0 raw BCSD-adjusted results unchanged. Do not manufacture missing irradiance, pressure or precipitation and do not merge this source scouting into production.

After live QA, rank potential donor stations by usable checked GHI hours, distance, altitude difference, collection timeframe and representativeness. If all candidates have no quality-approved solar history, document the limitation and consider a **separately validated** gridded solar product rather than marking unverified q21 data as verified.
