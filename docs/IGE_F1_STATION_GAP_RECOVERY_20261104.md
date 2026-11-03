# Experimental F1 station gap recovery

The new reference option is opt-in. The strict reference and H1/S1 defaults
remain unchanged. The four fixed original stations and the same target,
background, geometry and calendar still apply.

For a contiguous missing episode bracketed by observations, calculate the
inverse-square-distance weighted hourly series from the three other original
stations (distance floor 1 km). Add the interpolated difference between the
target and peer series at the two observed edges. Apply this to temperature,
absolute pressure and (when RH is missing) Buck liquid-water vapour pressure.
Recompute RH from vapour pressure and the resulting temperature, or retain the
observed RH when it was supplied. The existing Buck conversion derives vapour
pressure from the resulting T/RH. No estimated value is used as an anchor or
peer. Missing timestamps that cannot be bracketed and any other QC, definition
or identity rejection remain blocked.

Limits: at most 72 consecutive hours and at most 1% missing hours per station
per year. For each gap, repeat its field mask on up to 12 disjoint comparable
windows, at the same UTC hour within ±45 days. Require at least eight usable
windows and coverage on both sides of the episode. The upper bounds on
MAE/maximum absolute error are 1.5/4 K for temperature, 8/20 percentage points
for RH, and 100/300 Pa for absolute pressure. These are engineering admission
limits for the experimental option, not independently qualified accuracy.
Out-of-bounds reconstructions are rejected without clipping. Original values,
quality codes and source packets remain intact.

The archive records each estimated value, timestamp, field, station and its
masked-window metrics. The policy is bound to the multiyear archive manifest
and cache identity. F1 replay reruns the recovery from the original packets.
EPW headers and reports identify reconstruction. A rejected year still blocks
the whole window before any NASA download.

## Graz development replay

The original provider response packets and SHA-256 identities are retained in
`research/ige_cmip6/f1_gap_recovery_20261104/`. These are disclosed
development/regression cases, not independent target verification.

| Year | Gap | Masked-window MAE | Outcome |
| --- | --- | --- | --- |
| 2014 | 61 h T/RH, St. Radegund | Not evaluated: estimated RH exceeds 100% | Blocked; estimated range 58.0–114.0% RH |
| 2015 | 2 h T/RH/p, Graz Universität | 0.387 K, 1.850 pp, 9.14 Pa | Complete 8760-hour mixed-source historical EPW |
| 2016 | 2 h T, Graz Universität | 0.236 K | Complete 8784-hour mixed-source historical EPW; observed RH and p retained |

Both successful years passed the existing annual and F1 base admission with
the fixed station network. The historical decade 2012–2021 is still blocked
by 2014. No future EPW from that decade or new independent accuracy result is
claimed. The method and thresholds were not changed to admit the 2014 case.
