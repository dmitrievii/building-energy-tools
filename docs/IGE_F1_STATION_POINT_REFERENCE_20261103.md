# F1 reference from the same station point

A completed GeoSphere S1 point year can now be selected as the F1 hourly
pattern and can automatically acquire its own multiyear reference. The pattern
provides the hourly sequence; the climatology comes from the separately selected
historical reference years. A manually supplied compatible reference EPW remains
an option.

## Admission and provenance

- The automatic mode requires a complete S1 mixed-source EPW with four real
  GeoSphere donors. It is unavailable for an S1 point made from uploaded EPWs,
  an arbitrary uploaded base or a gridded background base.
- The NASA historical window and the local reference window are identical.
  The window must contain at least ten consecutive years within 2002–2025
  (the existing background source limit).
- Annual runs reuse the selected donor IDs, target coordinates, height,
  fixed standard clock and S1 source/QC/physics. Each year must admit all four
  donors with identical source kinds, geometries and height conventions.
  The background cell, elevation and field provenance must also match.
  A missing year stops F1 before NASA acquisition. No replacement donor, gap filling, reduced
  sample, nearest-city preset or grid-only reference is used.
- Each annual EPW passes the existing F1 base admission. Monthly estimates
  use the existing F1 temperature-midrange, DTR and mean-field estimator.
  After excluding February 29 from the estimator, month lengths are identical
  across years: the mean of annual monthly estimates equals the pooled estimate.
  Original leap-day observations remain in the source archive.
- F1 retains separate original station and background packets for each year,
  with a manifest binding the point request, four donor identities, window,
  base EPW hash and member hashes. Offline F1 replay requires the complete
  packet and replays every annual S1 run before the future calculation.
  Live retries can reuse successfully admitted annual inputs for up to 24 hours
  within the existing bounded cache. The reference packet is limited to 128 MiB,
  subject to the existing F1 product budget.
- The existing explicit liquid-rain proxy remains required where total
  precipitation is unavailable; no snow or total precipitation is inferred.

## Scope of verification

The complete ten-year path and F1 export/replay are exercised with synthetic
annual products and model signals; this is an execution test, not validation
of an observed future year. Negative tests use the real, retained Graz 2025
source packet and test altered donor height, altered background geometry,
incomplete packets and unavailable station metadata. Existing original NASA
and background replay tests remain in the regression suite.

A live test of the retained Graz 2021 base and the default 2002–2014 reference
blocked in 2002. Three queried stations had zero admitted core hours and the
fourth was not an eligible candidate for that year's metadata. This does not
establish availability for other windows or sites. The verified 2021 EPW is a
historical pattern; it is not a multiyear reference by itself.

A separate live probe of 2012–2021 admitted the first year (2012) from all
four fixed donors and the matching background cell. Live and offline reports
calculate the displayed distance using slightly different Earth radii, so the
comparison checks source coordinates and height directly, rather than this
derived number. The probe did not establish admission of the full decade.

This feature inherits the existing S1/F1 physics and QC; it does not change
temperature, moisture, pressure, wind or radiation equations. No independent
accuracy, production qualification, or EnergyPlus validation is claimed.
