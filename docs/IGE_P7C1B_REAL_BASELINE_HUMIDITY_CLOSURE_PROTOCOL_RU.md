# IGE P7C.1B — Authentic Graz Contemporary EPW & bounded humidity closure

**Date:** 2026-10-12. **Parent:** research/ige-p7c1-epw-future-morphing-20261011, commit `b8b06aae69ca7546812f4f1e5a3b2a80a8e0b3f9`. **Research-only; main not changed.**

## 1. Status and distinction between two acceptance gates

The intended *authentic* Graz Contemporary file `Graz-hour_contemporary_seed1.epw` was previously provided by the user in another conversation, but is **not present as an authorized mountable source** in the currently accessible GitHub history or project file runtime. Library ZIP files were listed, yet raw-byte materialization failed. We must NOT substitute the P7B.4 synthetic 2013 EPW and claim successful real-baseline validation. This phase therefore has two explicitly independent gates:

- **Gate H — quantitative research humidity repair:** implemented and tested with the **immutable P7B.4 synthetic 2013 EPW**, SHA-256 `2e45abbcba52c49e51e3811676ba37167bc8700f697e13032ee103ff8f3f7012`, and the four original P7C.1 CanESM5 research morphs. This can pass.
- **Gate R — authentic contemporary baseline:** requires actual `Graz-hour_contemporary_seed1.epw` bytes plus explicit filename/provider/sha256 and research-use authorization. It must be used as the **input to regenerate all four parent P7C.1 future EPWs**; no reuse of scenarios morphed from P7B.4 is permitted. This remains **BLOCKED / NOT EXECUTED** while the original input is inaccessible. Meteonorm files are often *generated typical weather* rather than observed individual weather year: "real original file" is not equivalent to measured actual weather.

## 2. Physical humidity and finite-volume motivation

P7C.1 applies a monthly `huss` climate ratio to source hourly EPW specific humidity using baseline pressure and new temperature, then clips RH above saturation to 100%. For each climate window and month the unsaturated target is

\[q^*_i = q_{EPW,i}\,\frac{\overline{huss}_{future,m}}{\overline{huss}_{historical,m}}\]

where `q_EPW` is computed from original dry bulb, RH and EPW pressure. The old method's clipped `q_final < q_target` discards humidity without an explicit monthly mass-closure audit; in SSP245 2040–2059 there are 590 supersaturated raw target hours, and in SSP585 2080–2099 there are 270.

The P7C.1B candidate minimizes

\[ \min_{q_1,...,q_n}\sum_{i\in m}(q_i-q^*_i)^2 \]

subject to physical bounds (at P7C.1 future temperature and inherited pressure)

\[q_{sat}(T_i,p_i,1\%RH)\leq q_i\leq q_{sat}(T_i,p_i,100\%RH),\quad \sum_{i\in m}q_i=\sum_{i\in m}q_i^*.\]

Note: the notation `q_sat(T,p,1%RH)` denotes the same psychrometric conversion formula at the RH=1% lower limit, not saturated air.

The KKT solution is the bounded offset `q_i = clip(q_i*+lambda, q_i^min,q_i^max)` with one monthly lambda, found by bisection. This provides a unique minimum L2 adjustment when feasible. Fail-closed if the month cannot fit the target; never silently raise saturation RH or change temperature/pressure. **This conserves a monthly mean of specific humidity, NOT the true column water mass integral or individual daily huss.** Hourly air-mass weighting and surface pressure from GCM are not supplied. No future-hour event coupling with native GCM dates.

For every scenario preserve all EPW weather columns except RH and dewpoint (columns indices 8 and 7, zero-based). Retain wind-direction unknown markers if original lacked wind direction; no fabrication. Original P7C.1 T, pressure, rain, GHI/DNI/DHI, wind, longwave unchanged. Parse roundtrip 8 headers + 8,760 × 35 fields, no leap mapping.

## 3. Verified numerical preflight on synthetic P7B.4 baseline (NOT authentic Meteonorm)

| Future scenario | Unattainable raw target hours | RH=100% after monthly closure | RH >20 pp/h jumps before → after | Maximum absolute RH change (pp) | Maximum absolute daily mean q redistribution (g/kg) |
|---|---:|---:|---|---:|---:|
| SSP245 2040–2059 | 590 | 631 | 1 → 1 | 0.88 | 0.693 |
| SSP245 2080–2099 | 537 | 631 | 4 → 3 | 3.40 | 0.605 |
| SSP585 2040–2059 | 505 | 591 | 3 → 3 | 2.60 | 0.601 |
| SSP585 2080–2099 | 270 | 301 | 4 → 4 | 2.48 | 0.619 |

All 48 monthly specific-humidity targets conserved at approx `2.5e-18 kg/kg` numerical error (before EPW text rounding). **More RH=100% hours is expected**: minimum-L2 redistribution raises humidity in physically available hours and may reach saturation at additional hours. These meteorological changes require independent validation; they must not be portrayed as proven improved hourly skill. The synthetic baseline means these results do not validate the authentic Graz Contemporary file.

## 4. Fail-closed implementation and scientific limitations

- `research/ige_cmip6/p7c1b_humidity_closure.py` implements a deterministic, source-hashed repair of the frozen P7C.1 outputs.
- The original P7B.4 baseline and P7C.1 audit and all monthly-signal EPW file hashes are checked. A different baseline cannot be substituted without regenerating the parent P7C.1 outputs and matching their recorded source SHA.
- Real-baseline mode requires a separate original provenance JSON with `original_filename`, `provider`, `source_description`, `sha256`, `user_authorized_research_use`. The original file cannot be treated as real measured weather without a separate measurement proof.
- Parent P7C.1 residual uncertainties remain: Erbs DNI/DHI are estimated, future precipitation frequency and wind direction inherit base patterns, pressure source and hourly cloud dynamics are unverified, no EnergyPlus test, no native future day pairing, only CanESM5.
- The new monthly KKT redistribution is source-constrained **arithmetic**, not an experimentally calibrated humidity-transport model. It allows per-day shifts; measure, disclose and independently validate any extreme or discontinuous values before scientific or production release. RH=100% is physically admissible but may be climatologically biased. File structural validity is not scientific validation.

## 5. Exit criteria

Gate H: complete 4×8,760 source-checked outputs, 48 monthly q targets within 1e-9 kg/kg, RH 1–100%, dew point <= temperature, all non-humidity hourly fields unchanged, complete audit and test CI PASS.

Gate R: independently acquire the exact user's authentic Graz Contemporary EPW and provenance; re-run P7C.1 against it, run humidity closure with its exact parent P7C.1 source hash; audit EPW completeness and wind direction; compare independent model changes. Do not call P7C.1B *scientifically complete* before Gate R. No `main` merge or production EPW authorization.