# IGE P8.4A1 — verified original-source findings and QC diagnosis

**16 October 2026 · research only.** Original run [#38895396312](https://github.com/dmitrievii/building-energy-tools/actions/runs/38895396312), code `6295968f7a4666b3fd07fb5ae32f97f4664c32ec`: 2/2 CI jobs SUCCESS; **67/67 original contracts PASS**; [artifact 12044036752](https://github.com/dmitrievii/building-energy-tools/actions/runs/38895396312/artifacts/12044036752), containing original-source aggregates and hashes. This is a **completed evidence-preserving pilot**, not source physical closure.

## Verified MeteoSwiss vs explicit Open-Meteo ERA5 (2024 January)

Three original Swiss sites BAS, GRA, MUB; 744 nominal original UTC hours, strict same 742 interior speed hours for shifts -1, 0 and +1. Each source's original SHA256 is in the original CI JSON.

| Site | ERA5 -1h speed MAE (m/s) | 0h speed MAE | +1h speed MAE |
|---|---:|---:|---:|
| BAS | 0.854919 | 0.880620 | 0.905984 |
| GRA | 1.749757 | 1.760445 | 1.778396 |
| MUB | 0.962507 | 0.977089 | 1.004151 |

**Do not pick -1h as correct alignment from lower MAE.** MeteoSwiss official reference window after 2018 is a mean over the preceding hour ending at the labelled timestamp (e.g. 16:00 combines ten-minute end stamps 15:10..16:00). ERA5 gateway reports instantaneous valid-time wind. An hourly station mean cannot be made equivalent to ERA5 instantaneous by a simple one-hour shift. Prior directional diagnostics were not on strictly common noncalm hours for all shifts (GRA 636/633/634; MUB 553/555/556), which is now corrected in follow-up research code `9412c1ec` and `c0647b3e`, **not yet confirmed by new source-run evidence**.

## GeoSphere: Jan 2024 station 30 cannot pass original wind QC

Station 30 = `Graz Universität/Heinrichstraße`. The API returned 744 nominal hourly axis entries, but **all 744 `ff_flag` and all 744 `dd_flag` were null**. Approved wind hours **0/744**; failed 85% source coverage gate. Returned empty flags are not inferred to be unapproved finite values or source downtime until values themselves are separately counted. Original station metadata/dataset SHA256 in artifact.

Crucial provider physical definition from original GeoSphere `klima-v2-1h` metadata:
- `ff`: *Windgeschwindigkeit, vektorieller Stundenmittelwert*, unit m/s.
- `dd`: *Windrichtung [360°], vektorieller Stunden-Mittelwert*, unit °.

These are **not numerically identical** to MeteoSwiss `fkl010h0` scalar hourly mean speed. Wind magnitude from mean vector is generally less than or equal to the mean of instantaneous scalar magnitudes for the same sampling. Station instrument/support differences further impede direct parameter interchangeability. GeoSphere QC legend `0` = ungeprüfte Daten (unapproved), valid allowed flags 10/11/12/20/21/22.

## Repair2 — provider wind source census, without weakening gates

Research-only additions:
- Fixed **four Graz source identities** for Jan 2024: composite site `30`, separate series `16414` (Graz Universität/Heinrichstraße), `16400` (Graz Thalerhof Flughafen), `16412` (Graz Universität).
- Each source independently audited for hour-axis completeness, physical values actually present vs null, raw QC flag distribution, approved speed, approved direction and **joint approved wind hours**.
- An independent source is qualified only when **>=85% of all 744 nominal hours have both physically valid `ff` and `dd` with original approved QC flag**. The failed original station 30 remains in results; no silently substituted source and no source selected on ERA5 forecast error.
- Code additionally enforces **identical hours for all -1/0/+1 shifts including direction and u/v error**, rather than only speed-sample-count equality.

The latest follow-up [GitHub Actions on this research branch](https://github.com/dmitrievii/building-energy-tools/actions) is running; **results of four-site source census have not yet been verified**. Do not label Repair2 as science PASS from code alone.

## Release status

`A1_original_source_pilot_code_executed=true`
`A1_geosphere_2024_station_30_QC_qualified=false`
`same_station_temporal_support_as_ERA5=false`
`full_P8_4A_physical_closure=false`
`P8_4B/C/D_not_executed=true`
`production_epw_ready=false`

All reports aggregate only, with source SHA256; no raw original hourly records redistributed. Repository `main` and Climate Analyzer untouched.
