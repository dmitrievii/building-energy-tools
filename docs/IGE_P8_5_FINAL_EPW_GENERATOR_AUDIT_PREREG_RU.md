# IGE P8.5 — Final Integrated EPW Generator Audit: preregistered release criteria

**2026-10-17. Immutable evidence source**: P8.4D research head `97e777ac879091a12c9b4cb05299c98626453e47`. Audit must NOT refit climate coefficients, rewrite previous EPWs, claim physical validation on missing licensed bytes or merge main.

## Objective and clearly separated artifacts

**P7C.4**: 28 full 8760×35 research EPWs from user-licensed Meteonorm baseline (original SHA256 `dad69174304c3a13cc095841c4cb9636bf99cc3f33a81502c553af862cd06677`), seven GCMs×four SSP/windows, eight-GCM 384 monthly signals and four IPSL blocked huss windows. **P7C.5B**: 28 subsequent source-linked photometrically coherent corrected EPWs that have different SHA256. *Do NOT conflate P7C.4 raw research files and P7C.5B corrected output*. Public repository contains only aggregates and source code, NOT the original 28 files or licensed Meteonorm baseline; therefore SHA manifests cross-check *reports* but cannot prove current raw bytes. P7B.4/5 and P7C.1 public artifacts are synthetic source and CI fixtures, not substitutes for Meteonorm.

## Freeze release decisions BEFORE new audits

**A. Registered climate source matrix (must PASS)**: 8 unique GCMs×four fixed windows×12 months (384 rows), no duplicates or numeric NaN/out-of-bound nonnegative solar/wind, positive humidity/daily ratio, P7C.3 source SHA provenance. Report file SHA, row count and identities. Note 40 original 20-year daily source ZIPs were checked in P7C4 historical stage, not independently reacquired now.

**B. Model-to-EPW lineage (must PASS metadata integrity)**: P7C4 28 result rows + 4 IPSL blocked + 28 independent P7C5 field-audit + 28 P7C5B photometric source hashes, member ID bijection across artifacts, original licensed baseline SHA agreement, no declared optimizer convergence if not achieved, no output marked production. P7C5B source input hash MUST match corresponding P7C4 immutable original EPW hash exactly. All P7C5B output SHA unique; no original bytes available -> `licensed_full_epw_bytes_revalidated=false`.

**C. EPW physical structural path (must PASS on actual public research artifact)**: P7B5 original-source SHA-pinned actual EPW `8760×35`, eight header lines, strict noleap local standard-time clock, wind and psychrometric sentinels handled correctly, no 999/9999 silently read as numerical observations; compare original 28 P7C4 evidence only as declared historical reports.

**D. Photometric and radiometric closure (requires caveat)**: 28 original P7C4 changed GHI/DNI/DHI while global/direct/diffuse lux were unchanged, P7C5B 28 repaired the photometric closure to ≤0.5 lux but used Meteonorm baseline luminous efficacy and 1344 fallback hours *per member*. No independent illuminance measurements -> block lighting/daylighting production. Sky cover, precipitable water, visibility and ground-temperature/IR link must be explicitly flagged, not silently assumed qualified.

**E. Humidity/temperature (requires caveat)**: 28/28 humidity optimizers reached 600 iterations with zero strict delta convergence; monthly q mass closes to 1e-13kg/kg, but 14536 100% RH hours (vs baseline 229), 28 reporting files must preserve exact 100% saturation counts, no claim scientifically accurate wetness/condensation. Need objective monotonic decline or report missing/partial. Outdoor loads via EnergyPlus PASS for synthetic public fixture does not certify humidity distribution in 28 proprietary outputs.

**F. Source time/climate assumptions**: EPW full 365d/no DST 8760h; source typical-year chronology, original wind directions, historical precipitation occurrence and original clouds are assumed unchanged in future morphs. No new temperature–humidity–cloud–wind joint synoptic sequencing, no new climate extremes/heatwaves independent of source chronology. No future wind-direction or local mountain effects inferred.

**G. Functional multi-climate scenarios**: 32 states (eight × four), 28 full research P7C4, four **BLOCKED** IPSL `huss`; 28 P7C5B photometric stage. Native EnergyPlus 26.2 verified only public synthetic/research EPWs (P7C5, P8.4D); do not declare any of 28 licensed future EPWs executed by EnergyPlus under final audit. Model emission/calendar uncertainty and native CMIP6 source baseline vs adjusted 2013 station weather remain caveats.

**H. Operational readiness**: `research_code_regression_pass` and `aggregate_manifest_consistency_pass` may be true while **`production_EPWs_ready=false`**, **`arbitrary_point_generation_validated=false`**, **`future_wind_direction_physically_validated=false`**, **`daylighting_independently_qualified=false`**, **`licensed_28_end_to_end_revalidated=false`**. Explicitly distinguish `ready_for_research_sensitivity` from `ready_for_building_design`.

## Executable gates

- Contract/unit tests include source identity bijection, source hash cross-link, IPSL block, source SHA congruence, optimizer record (false) reported as blocker, photometric repair source link, fail-closed authentic raw EPW availability, measured-vs-synthetic flags and field-level sentinel checks. Non-production research history is *not* a failing CI condition when accurately flagged, but it **is a failing RELEASE gate**.
- Reconstruct no original proprietary 28 member files in CI. Re-evaluate publicly archived source fixtures P7B5 and P7C1 in CI to show actual EPW readbacks and identify physical source-specific limitations, archived manifest SHA. Code tests and publication-status verification are independently recorded.
- Actual private requalification, if later authorized, must require original licensed baseline bytes, P7C4/P7C5B 28 EPWs and user-authorized source SHA, native 28-member EnergyPlus, cross-variable and full model audit; none can be replaced with a synthetic fixture for production certification.
