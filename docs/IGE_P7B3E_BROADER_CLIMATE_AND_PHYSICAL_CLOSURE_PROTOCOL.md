# IGE P7B.3E — Broader Climate Generalization and Physical Closure

**Pre-registered 2026-10-11; research only. No production EPW, no release to `main`.**

## 1. Science questions and what may be claimed

1. **Geographical transfer:** Does the *frozen* Graz-trained M2 transfer to genuinely independent, geographically separated Austrian climate regimes, conditioned on the **observed QC-approved daily GHI**? This is a conditional sub-daily disaggregation test, not a true full GCM climate prediction.
2. **Eight-GCM historical input stress:** For all eight original NASA NEX-GDDP-CMIP6 v2 BCSD 1995–2014 raw daily datasets on their **original model grid cells**, how often does the *physical-cap assumption* conflict with supplied daily solar energy? This is a numerical multi-GCM constraint study, not a globally validated meteorological generator or independent station-verification of GCM daily bias.
3. **GHI/DHI/DNI closure:** Given one synthetic GHI, can an independently implemented, guarded Erbs (1982) diffuse-fraction correlation produce nonnegative DHI and DNI with hourly identity `GHI = DHI + DNI × mean_cosine_zenith` under an extraterrestrial DNI limit? Closure is a **necessary physics/units contract, not sensor-grade validation of the direct and diffuse components**.
4. **Clear-sky cap sensitivity:** The historic source algorithm uses cap = `min(TOA, max(1.25×Haurwitz, 0.65×TOA))` as a near-horizon engineering allowance; repeat feasibility at 0.45 / 0.65 / 0.85 TOA floors, without tuning by test performance. These are hypotheses, **not claims about true atmospheric transmissivity**.

## 2. Original immutable data and explicit provenance

- **Graz cloud library and alpha:** original station #30 GeoSphere 10-minute QC-approved `cglo`, training 2007–2008, model choice 2009, `alpha=0.75`, *frozen at P7B.3C*. Original CSV SHA-256 `95dc8f9b7341be69d0ee236b38029a3f171b7f6a9eb0aed75b03cd2e473500c0`.
- **New geography, pre-registered before accessing station-year values:** Wiener Hohe Warte #105 (48.24861 N,16.35639 E,198m); Innsbruck Universität #39 (47.25986 N,11.38425 E,578m); Klagenfurt Flughafen #48 (46.64833 N,14.31833 E,450m); Linz Stadt #56 (48.29639 N,14.28528 E,262m); Sonnblick #213 (47.05417 N,12.95750 E,3109m). Live source metadata and *all* original 10-minute GHI+QC for 2012, 2013, 2014, two unresolved hour-label conventions. Original provider flags accepted **10,11,12,20,21,22 only**. Use only complete original six-of-six ten-minute samples per hour and 24/24 complete hours per day. Neither an unavailable station nor an incomplete year is declared a success. Fail-closed geographical *coverage gate* requires ≥2 independent stations, ≥2 years and ≥4 distinct external site–year groups. 8 predeclared random seeds, identical across comparisons. More than a local Graz-region comparison, **still Austria only**.
- **Eight native GCMs:** ACCESS-CM2, CanESM5, EC-Earth3, GFDL-ESM4, IPSL-CM6A-LR, MPI-ESM1-2-HR, MRI-ESM2-0 and NorESM2-MM. Source archived P6.1 runs 38067931031 (ACCESS), 38072042977 (CanESM5, GFDL, MRI, NorESM), 38077903914 (EC-Earth3, MPI, IPSL repairs). Each original `joint_daily_raw.csv` must pass **both** source QA/provenance status and original SHA-256; any missing source or mismatched calendar/model identity is hard failure. Historical 1995–2014, retain original `CF calendar`, original `rsds_kwh_m2_day`, and original grid latitude/longitude. **No double bias correction** on already NASA-BCSD-adjusted source. Do not identify model dates with measured station event dates.

## 3. Physics, scopes and test design

- Independent daily TOA and simple Haurwitz clear-sky hourly geometry at **5-minute quadrature**, no invented turbidity. Solar geometry is approximate, fixed CET for sources in Austria, and not a final astronomical standard.
- Predeclare cap sensitivity floors 0.45 / 0.65 / 0.85. Inspect all original 20 years × 8 GCMs for feasibility; do not change original daily energy, suppress a bad day or reclassify cap failure as an error in the NASA daily measurement. Error coverage and exclusion counts are primary findings.
- For **2012–2014** of each GCM generate only physically feasible native-source days with frozen M2 and three deterministic independent seeds. Preserve each daily source GHI to 1e-9 kWh/m²/day. Report excluded days, not deceptively complete 8,760-hour files. This **does not** deliver full EPW or leap-year/calendar-normalized weather.
- Use Erbs, Klein & Duffie (1982) original hourly diffuse-fraction correlation as estimated empirical partition: `kt=GHI/TOA`; diffuse fraction piecewise at 0.22 and 0.8; `DHI=kd×GHI`, `DNI=(GHI−DHI)/mean_coszen`. Under `coszen<0.065`, set `DNI=0, DHI=GHI` to prevent singular DNI, and bound estimated DNI to original extraterrestrial normal. Reconcile DHI to close algebraically. This is not a complete atmospheric-radiance model. Ground `chim` DHI remains unapproved QC=0; observed DNI unavailable.
- Full multi-GCM output must be labelled **CLIMATE STRESS / PHYSICAL CLOSURE**, not observed model performance. Detailed meteorological verification and building energy loads remain a separate future deliverable; it is invalid to assert energy-use improvements from solar-only radiometric algebra.

## 4. Prior local numerical preflight (CanESM5, original data)

For original CanESM5 7,300 historical days from 1995–2014, 0.45/0.65/0.85 floors respectively flag **214 / 174 / 20** daily cap incompatibilities. This diagnoses the *chosen cap*, not faulty measurements. Under 0.65, 31 original days are excluded from 2012–2014 3-year synthetic-hourly stress; 1,064 feasible days × 24 = 25,536 hours were decomposed. Maximum daily GHI residual ~`1.78e-15` kWh/m²/day; maximum instantaneous component-closure residual ~`1.11e-16` kWh/m²/hour. **These are CanESM5-only preflight results**, to be verified along with all seven other GCMs by GitHub CI.

## 5. Scientific acceptance is conditional

Pass GitHub technical jobs only if original provider QA, locked source SHA-256, fixed observational periods and all physical identity/unit contracts hold. **Scientific release remains `REVIEW_REQUIRED`**: external atmospheric regimes outside Austria, independent measured DHI/DNI and solar aerosol/clear-sky validation, native calendar consistency, cloud-conditional cross-variable structure, multi-GCM *future* SSP source generation, and actual building load simulations remain open. GitHub green is not scientific approval.

References:
- D.G. Erbs, S.A. Klein, J.A. Duffie (1982), *Estimation of the diffuse radiation fraction for hourly, daily and monthly-average global radiation*, Solar Energy 28(4):293–302, DOI: 10.1016/0038-092X(82)90302-4.
- pvlib methods documentation, https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.irradiance.erbs.html (independent methodology check; note low-sun issues).
- GeoSphere Klima v2 10-minute dataset: https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-10min and DOI 10.60669/8fya-7x87.