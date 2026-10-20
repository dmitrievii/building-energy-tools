# IGE P9.3B2D — Amendment A (source-only recovery, before model readback)

Date 2026-10-20, after original first DWD 6-station census
GitHub Actions [#39473786078](https://github.com/dmitrievii/building-energy-tools/actions/runs/39473786078).

**Observed availability only:** in both 2023 Jan/Jul fixed weeks, each of 01420,
03015, 01443, 05440, 02559, 01550 has 168 original hourly rows with
native `QN_8=3` but *zero valid station P and zero P0*. Total 2016 rows and
2016 missing P. **No pressure values or any model residuals were exposed.**
The pre-registered original hourly-source holdout is SOURCE_BLOCKED, not
silently replaced or called failed accuracy.

Before any additional German station-pressure observation or ERA5 comparison,
pre-register two alternative official DWD original source families:
1. `climate_urban/10_minutes/pressure/historical/` original 10-min pressure
   for fixed station `00399`, 2023 Jan 10–16 and Jul 10–16 UTC.
   Check source schema and select genuine station absolute pressure ONLY;
   preserve exact-hour (minute 00) samples for eventual comparison to
   instantaneous hourly ERA5, with source native time-support warnings.
   Need at least 144 distinct genuine station P exact-hour samples in EACH
   week, source quality labels separately.
2. `climate/subdaily/pressure/historical/` original measurement times for
   fixed candidates `01420` (first lowland), `02559` (alpine approach),
   `01550` (fallback alpine) in exactly the same original 2023 weeks.
   Detect the authentic station pressure field from ORIGINAL schema, never
   use reduced `P0` or an unverified field. Minimum 35 genuine exact-UTC
   source hours per week; do not present subdaily as hourly coverage.

Source-only qualification counts valid pressure records, time stamps and
native QC by field; it may inspect headers and bounded metadata but must not
log pressure measurements or consult predictions/errors. A second
pre-registered freeze must select eligible source(s) and direct pressure
variable(s) BEFORE evaluating B0/B4. No new arbitrary station/year search
after scoring; no tuning. Original AT/CH 2024 remain retrospective.
Original 2023 hourly DWD cohort remains permanently reported BLOCKED.
