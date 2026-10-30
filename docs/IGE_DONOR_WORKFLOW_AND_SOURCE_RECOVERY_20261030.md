# Donor workflow and original-source recovery

Base: public PR #122 / `02a7ff655b558ba3c9216b9e65378a4a171b2291`.
Scope: Generate climate → historical station/EPW interpolation and selected-base future climate.

## Problems reproduced

The public interpolation page initially showed no stations: its metadata map was opt-in. With a valid height, **Check donors and interpolate year** remained disabled until the user accepted two technical assumptions. A third, separate, unchecked option meant that even a successful donor calculation would not attempt a complete EPW.

The reported future error occurred at the NASA `ssp245/pr` catalogue, before NASA source admission or climate morphing. The previous acquisition kept no default checkpoints. A later failure therefore discarded successful responses and repeated the local multi-year reference on the next attempt. HTTP errors and invalid responses were also retried indiscriminately.

## User-visible changes

- GeoSphere station locations load automatically on entering interpolation. Metadata are cached for 24 hours. A metadata failure offers an immediate **Retry station locations** button and does not disable a valid weather request. Map movement does not download station weather.
- Unchecked candidates remain grey; selected admitted donors become violet, with connections to the target. Other known station locations remain visible after the calculation. A location is not a claim of annual completeness.
- The existing Buck liquid-water convention and nominal-altitude proxies are method settings, recorded in the request/report, rather than mandatory acceptance checkboxes. The numerical interpolation and height equations are unchanged. Unknown sensor elevations remain unknown.
- A complete EPW is attempted by default. Temperature, pressure and moisture come from the admitted donors; wind, radiation, cloud and liquid rain use the separately attributed ERA5-derived / NASA POWER background. A core-only output option remains under **Method and output details**.
- The button still requires an elevation. Uploaded donors still require four files and actual-year chronology confirmation: a typical year cannot establish simultaneous station weather.
- Source batching/retry progress is displayed during donor acquisition. A blocked donor result states the number of eligible years and retains every admission failure. No four-donor year is fabricated.
- NASA connection failures now have a readable explanation and a working **Retry future climate from this base** control. Detailed diagnostics remain available. Previous completed products keep their original identity and downloads.

## Recovery and provenance

`engine/source_cache.py` stores public original-source bodies only, in the instance's temporary directory. Entries have exact keys, byte limits, a SHA-256, original metadata and a 24-hour expiry. Writes are atomic; the cache has a 256 MiB budget. An unavailable cache does not block live acquisition. App restarts or eviction may remove it.

NASA keys are complete request URLs, including point, model/member, scenario, year and variable. A cached catalogue must still identify every requested v2.0 source. A cached point must still pass the original unit, cell, noleap calendar, daily census and time-axis checks. A corrupt cache entry is not an admitted source. Partial successful acquisitions survive a later timeout. Original retrieval times are preserved in the new receipts.

The retained original NASA packet is reused automatically only when its entire request matches: exact point, model/member, scenario and both climate periods. Its fixed SHA-256 and the usual complete-packet scientific admission are still required. It is never substituted for another site or scenario. No older NASA version or alternate physical definition is introduced.

For background-reference bases, NASA admission now precedes the expensive local multi-year acquisition. Complete admitted local reference years are checkpointed separately, with original source bundles and receipts. A later annual source failure can resume without reacquiring earlier years. Cell/orography, chronology and physical checks still run.

Transient connection/HTTP failures retain bounded retries. Permanent HTTP failures and invalid responses fail immediately. A retry cannot guarantee the availability of an external NASA service.

## Verification and limits

The exact public error catalogue and original point subsets for `pr`, `tas` and `huss`, CanESM5/r1i1p1f1/ssp245/2040 at the disclosed Graz request, responded in the live probe. Each returned 365 admitted daily values, with zero difference from the retained v2 values. GeoSphere metadata returned 616 single-site station locations. Original responses and hashes are retained in `deployment/audits/ige-donor-recovery-20261030/live-sources/`.

New regression cases interrupt NASA acquisition after partial success, resume it, compare all original response bytes and the resulting monthly signals, reject another point, check cache corruption/expiry/budgets, and resume local reference years after a later-year timeout. Real Streamlit AppTest cases cover the default station map, removal of the technical gates, default composite EPW request, map retry, disabled-input explanations, readable NASA failure and successful retry. The common historical/future annual replay and existing mathematical tests remain required.

Run the source health probe into a new directory:

```bash
python deployment/ige_donor_recovery_source_probe.py --out outputs/new-source-health
```

Run the application checks with the pinned Cloud dependencies:

```bash
python -m pip install -r tools/climate_analyzer/requirements.txt
PYTHONPATH=tools/climate_analyzer:research/ige_cmip6 python -m unittest discover -s tools/climate_analyzer/tests -p 'test_*.py' -v
python deployment/verify_ige_cloud_candidate.py --contract deployment/ige-donor-recovery-candidate-20261030.json --out outputs/new-cloud-preflight
```

Final results are recorded in the new audit receipt. Existing research reports, source packets, annual outputs and old deployment manifests are preserved.

These are execution and usability corrections. The disclosed Graz 2023 GeoSphere example still has only one eligible donor among twenty checked; removing UI gates does not make it a four-donor year. The successful retained S1 composite uses disclosed ERA5-derived donor EPWs, not an independently validated station reconstruction. A new location/reference can still be unavailable or physically inadmissible. Independent AT/DE/CH accuracy, global generalization and production EPW readiness are not established by these changes. B4, R1, P2 and the advanced P9.3 closure are not promoted.
