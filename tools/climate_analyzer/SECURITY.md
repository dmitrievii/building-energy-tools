# Climate Analyzer security boundaries

This document records the public-input and network boundaries introduced in WEB-0.3.

## EPW uploads

- Streamlit upload limit: 10 MiB.
- Raw EPW parser limit: 10 MiB, including non-UI callers.
- Embedded NUL bytes are rejected.
- LOCATION latitude, longitude, UTC offset and elevation are range checked.
- EPW data rows must contain the expected 35 fields.
- Data records are bounded to 24...9000 rows to prevent unbounded parser input while retaining annual and leap-year EPW use cases.
- No uploaded EPW file is intentionally written to persistent storage by the application; active and comparison payloads remain in Streamlit session state.

## Climate.OneBuilding downloads

- Only HTTPS is accepted.
- The hostname is restricted to `climate.onebuilding.org`.
- User-info credentials and non-standard ports are rejected.
- Redirects are followed manually, with each target revalidated against the same allowlist.
- Redirect count is bounded.
- Network response size is bounded to 32 MiB using streamed reads.

## ZIP archives

- Archives are read in memory; members are never extracted to filesystem paths.
- Member count and total uncompressed size are bounded.
- EPW member size is bounded to the EPW input limit.
- Absolute/traversal member paths are rejected.
- Encrypted EPW members are rejected.
- Suspicious compression ratios are rejected.
- The extracted EPW bytes pass the same structural validator as local uploads.

## Deferred

WEB-0.3 does not yet redesign the public Climate.OneBuilding catalog-refresh workflow, add scientific regression fixtures, or perform a full dependency supply-chain lock with hashes. Those remain separate auditable stages.
