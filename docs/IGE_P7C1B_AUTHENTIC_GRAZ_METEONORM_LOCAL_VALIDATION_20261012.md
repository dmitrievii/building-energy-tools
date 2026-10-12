# P7C.1B — Authenticated user-supplied Meteonorm Graz Contemporary EPW: real-baseline validation

2026-10-12. Research-only. This summary contains **no original Meteonorm records and no generated hourly records**.

## Source provenance and baseline gate

A user-supplied `EPW_collection.zip` was inspected locally. It contains 18 Meteonorm Version 8.2.0.24079 EPWs (5 Graz, 11 Wien-Hohe Warte, 2 Tripoli), all structurally 8 EPW header rows plus 8,760 hourly records, 35 columns per record. Source EPW files and hourly derived EPWs are not committed to GitHub.

- Graz authentic baseline: `Graz-hour_contemporary_seed1.epw`.
- Exact original SHA-256: `dad69174304c3a13cc095841c4cb9636bf99cc3f33a81502c553af862cd06677`.
- Original LOCATION: Graz, 46.983 N, 15.450 E, 342 m, UTC+1.
- Original source: Meteonorm 8.2.0.24079, representative contemporary **synthetic/weather-generator** EPW; calendar label 2005 does **not** establish that these are measurements taken in actual 2005.
- Baseline 8,760 wind directions present (no missing 999). Mean dry bulb 10.508 °C, global solar horizontal annual energy 1255.482 kWh/m².
- The original source is within the registered P7C.1 allowable distance to the NASA NEX-GDDP-CMIP6 CanESM5 source grid (46.875 N, 15.375 E); original 5×7300 source-day windows pass recorded P6 source QA and SHA.

## Authenticated local scientific rerun

Ran unchanged P7C.1 and P7C.1B modules, with the real contemporary baseline and its SHA-pinned user-source provenance JSON, for four CanESM5 r1i1p1f1 SSP windows. Existing P7C.1B authentic-provenance gate accepted the source; no P7B.4 synthetic baseline substitution.

| Scenario | Annual delta T, C | Annual GHI, kWh/m² | P7C.1B RH=100% h | >20 pp/hour RH jumps | Max RH jump pp/hour |
|---|---:|---:|---:|---:|---:|
| SSP245 2040–2059 | +2.4756 | 1265.8790 | 243 | 11 | 30.28 |
| SSP245 2080–2099 | +3.5492 | 1266.7943 | 228 | 9 | 34.18 |
| SSP585 2040–2059 | +3.1991 | 1258.8199 | 179 | 7 | 28.98 |
| SSP585 2080–2099 | +6.9274 | 1265.2070 | 65 | 6 | 23.69 |

Independent numeric read-back checked all 4 P7C.1B output EPWs (8760×35), exact retention of original hourly date stamps and original wind direction, unchanged P7C.1 non-moisture fields (only dewpoint and RH change in P7C.1B), RH within [1,100] and dewpoint <= dry bulb, and 48/48 monthly q targets against the original baseline and climate-ratio signals. Maximum monthly q residual recomputed from serialized EPW fields across four scenarios: <1e-13 kg/kg. Existing P7C.1 (17) and P7C.1B (12) unit tests: **29/29 locally PASS**.

The full user-source-specific rerun was executed and SHA verified locally: do **not** describe it as GitHub CI validation of proprietary inputs. The existing CI passing on the synthetic public research baseline is a separate claim.

## Study limitations / release gate

- `production_epw_ready=false`. This resolves only the missing authentic Meteonorm input and its scientific integration, **not** external future-climate accuracy.
- GCM SSP and Meteonorm RCP products differ in GCM families, scenario trajectories and time windows (EPW labels 2050/2100 vs CMIP6 2040–59 and 2080–99): no calendar-day or direct equivalent-model validation can be claimed.
- Unchanged typical meteorological hour sequences are not independent future event realizations.
- Monthly q conservation does not enforce exact daily q, nor valid RH temporal persistence; >20 pp/h jumps remain (6–11).
- Erbs partition is empirically derived GHI/DNI/DHI, not an independently observed radiative component benchmark.
- No EnergyPlus simulation or scientifically qualified production EPW validation.
- The user-original and regenerated hourly files were retained in a private, downloaded research package, not published publicly.

**Disposition:** authenticated Graz Contemporary input requirement closed for P7C.1B; numerical monthly humidity closure locally passes; meteorological/production qualification remains pending.
