# AT real-station usability pilot — 2 November 2026

Base: published `main` commit `acf3c029024a745f717cad21103119fbcd913f7c`.

The deliverable is a real-station S1 point-year and an explicitly mixed-source
EPW, preserving the existing interpolation, source/QC and physical admission.
This is development/integration evidence, not independent accuracy validation.

## Frozen method and scope

- No changes to frozen P8.2F equations, calibration, 100 km / 1500 m operational
  caps, nearest-20 search, four complete admitted donors, Buck-water assumption,
  absolute-pressure meaning, fixed UTC+1 clock or monthly moisture constraints.
- No engine filling of station gaps; missing/rejected observations remain so.
- Wind, radiation, cloud and liquid rain retain the separately identified
  original ERA5-derived / NASA POWER background. They are not station weather.
- The real station H1 admission and the S1 composite EPW admission remain
  separate. H1 can lack radiation while providing complete S1 core inputs.
- AT 2018 and IV1 2022 remain unopened. No tuning on old 2013/2014 examples.
- `main`, old source packets and prior outputs are not overwritten or merged.

## Development requests

1. Replay the disclosed 2023 Graz packet with its original 20 station sources;
   classify missing values, QC, definitions and identity/transport failures.
2. Retain fresh original hourly boundary responses for the same region in 2023
   and 2025. These are explicitly exploratory source-availability probes.
3. After observing 2025 boundary availability, run the **development** point:
   47.0707 N, 15.4395 E, nominal target 375 m, year 2025, fixed UTC+1,
   label `Graz real-station usability`. Year selection is informed by the
   disclosed probe and must not be presented as a blind validation choice.
4. Use the unchanged nearest-20 search and stop at four fully admitted donors.
   Record every checked/rejected station, original metadata and data response,
   SHA256, field coverage, physical corrections and background geometry.
5. If the core year passes, acquire the same-year background and construct EPW.
   If any stage fails, retain the failure and report its specific source or
   physical blocker. A successful source probe is not an annual qualification.

The complete 2025 search subsequently found zero eligible donors among twenty:
many stations have missing or QC0 values on 18 December. That failure is retained.
A bounded fallback availability probe of the previously disclosed 2021
development period checks 16400, 16413, 16511 and 16411. It finds complete core
data for the last three, while airport T/RH lacks one hour. An additional full
nearest-20 **2021 development run**, with the identical point, height and rules,
is therefore allowed. This adaptive year selection is disclosed, is not a new
preregistered independent sample, and is not used to fit or select equations.

## Software changes permitted in this block

Reuse one explicitly acquired original metadata body in each station's retained
annual source packet, with unchanged admission and offline replay. Expose the
three core admitted-hour counts and distinguish their blockers from missing
non-core EPW fields. Add an executable offline audit of the retained originals.

## Acceptance

- The 2023 disclosed negative case remains blocked with the same one eligible
  station. The four original grid-donor EPWs remain regression examples only.
- If the development request is admitted: 8760 unique actual-year records,
  existing EPW readback/bounds/component checks, four real station donors,
  unmodified source hashes, explicit per-field provenance and correction logs.
- Offline replay must produce the same weather within existing EPW readback
  precision, with no network and no weaker acceptance tolerance.
- UI must show counts and failures, allow complete downloads only on admission,
  and keep previous results correctly identified after edits or failures.
- Tests cover metadata reuse, altered metadata, request identity, mixed blocker
  categories and the station-core / complete-EPW distinction.
- Long GitHub CI is launched once and then left for the user to request results.

Future multiyear station/point reference automation, independent AT/DE/CH
accuracy validation, TMY interpolation, EnergyPlus qualification and public
deployment are subsequent gates. No new independent or production accuracy is
claimed by a complete EPW or a successful CI run.
