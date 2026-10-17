# IGE P9.1F3 — Original GeoSphere July 2019 source-QC gap forensic

**Registered after P9.1F1 and P9.1F2 showed zero QC-accepted 2019 July temperature records on ALL registered stations.** This is an independent **source diagnosis**, not a redefinition of P9.1F1 and not new station-temperature error tuning.

Freeze stations as P9.1F1 (9 original IDs), compare original `tl/tl_flag` records in 7-day weeks **2018-07-10..16, 2019-06-10..16, 2019-07-10..16, 2019-08-10..16, 2020-07-10..16**. Record provider SHA, station record count, `tl` non-null count, accepted original QC flag count and histogram of flag codes, without outputting any station temperature values. Validate UTC timestamps, metadata and exact source fields. **Never relax QC classes merely to make the result pass.** No source reanalysis needed for this forensic stage.

If the missing source is confined to July 2019, it may be a provider historical QC discontinuity or missing segment; if flags are present but unaccepted, identify the actual flag code for scientific review. If missing across other months, report that. Do not infer source of failure from missing-count alone without inspecting the original recorded schema.

A 2018 or 2020 summer evaluation would be an **exploratory different-year follow-up**, and must not be counted among P9.1F1's preregistered 2019 original summer cases. P9.1F1 remains 18/27 QC-qualified source cases even if a later year is valid.
