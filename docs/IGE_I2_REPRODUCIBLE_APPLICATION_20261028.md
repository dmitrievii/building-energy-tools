# IGE I2 — reproducibly usable research application

28 October 2026. Base: `cc5222a109121bc7b2a0f3fbc3a8151c4d6ed5f9`.
Research branch: `research/ige-i2-reproducible-app-20261028`.

## User outcome

From one checkout, Python 3.12 users can install a dedicated environment, start
the existing application, check the installation and export all four demonstrated
annual products. Instructions: [IGE_QUICKSTART.md](../IGE_QUICKSTART.md).

```text
python ige.py setup
python ige.py run
python ige.py check
```

On Windows the equivalent prefix is `py -3.12`. No activation is required.
The application binds to `127.0.0.1:8501`; a different port can be selected.

## Implementation boundary

I2 adds installation, launch, verification and documentation around the current
application. It preserves the earlier engine, UI, scientific modules, source
packets and weather outputs. Main, the public deployment, prior research branch
heads and scientific acceptance decisions are not changed.

- 56 application/transitive packages and three bootstrap tools are version-pinned
  with upstream SHA-256 hashes. The original direct requirements remain unchanged.
- PsychroLib is built from its hashed source with pinned pip/setuptools/wheel;
  build isolation does not introduce an unpinned backend.
- The dedicated `.venv/ige` environment rejects unexpected packages/version drift
  and checks `pip check`. User Python import paths are removed from child processes.
- The baseline manifest verifies 690 inherited application/scientific/source files,
  totalling 79,678,538 bytes. It uses file hashes, without requiring Git history.
- Committed source bytes are preserved across Windows/Linux line-ending settings.
- Existing result directories are never overwritten. Failed acceptance writes a
  failure receipt; only a complete successful run writes `verification.json`.

## Available routes and preserved outputs

| Product | Rows | Original EPW SHA-256 |
|---|---:|---|
| Graz historical 2023 background | 8760 | `acf8e7d82be69de5fa19f76c599143559d477aa01cdb7c56414fc23c93796635` |
| Graz CanESM5/SSP245/2040–2059, 2023 pattern | 8760 | `fc00e09811498c368965785ee8873bc4ca1cd01761eaebb19c759faebd0e3c28` |
| Basel/Binningen historical 2025 research reconstruction | 8760 | `b7cc31ac7cf6a71329f85a7d60f41fe2ea43be86692f8f012cc2b02009c378e1` |
| Altdorf historical 2025 research reconstruction | 8760 | `53a0a904ec7141d26d9941e1ed5dbf473a8cd461c8bb86e5a6f091da450ff538` |

Graz historical/future products are rebuilt from frozen original source packets.
CH products are loaded from the original verified A1.4 snapshot, as in A1.5;
I2 does not silently regenerate or change the station reconstruction.
Each export includes the same files offered by the UI plus the complete download
ZIP, with explicit field provenance and quality reports. Archive members are
compared with the actual download bytes.

## Verification

The new I2 acceptance suite deduplicates test IDs across the application tests,
relevant existing scientific regressions and 12 new installation/runtime tests.
Six V1/V2 acquisition/preregistration modules are outside this application suite:
their historical Git-ancestry gates remain in the original research CI. Their
tests and scientific results are preserved.

The offline regression/export phase forbids socket connect/connect_ex. A separate
real Streamlit process is started on loopback to check HTTP health and the page,
then stopped. Existing AppTest tests exercise the actual app entrypoint, generated
climate routes, views, psychrometrics, downloads, reruns and error handling.
No visual browser audit or public deployment is claimed.

Initial broad local run: 1025/1025 checks PASS, 147.90 seconds, no skips; all four
EPWs retain their original hashes. Real Streamlit HTTP health/page PASS, startup
about 0.76 seconds. This development run included the acquisition-campaign tests
before their isolation from the user-facing suite. It is not added to subsequent
acceptance counts. Final source-archive and CI verification are recorded separately.

Fresh CI installs are defined for Ubuntu 24.04 and Windows 2025, Python 3.12,
from a depth-one checkout. They run the same documented setup/check commands and
retain the actual four products, test logs and verification receipt.

## Scientific and product status

| Axis | I2 scope |
|---|---|
| Software correctness | Fresh installation, combined regressions, original EPW hashes, actual local server and complete downloads |
| Physical admissibility | Preserves existing per-route checks and explicit pressure/humidity/time conventions |
| Independent accuracy | No new meteorological qualification; V2-M4 negative general R1 decision retained |
| Operational use | Locally usable research application in its demonstrated scope; production and deployment remain separate |

The coordinates form remains an explicitly labelled live grid-background request;
its arbitrary-location transport and local accuracy are not qualified by offline
examples. General station interpolation, arbitrary-station/point future generation,
additional GCM/SSP combinations and real EnergyPlus qualification are later product
milestones. A successful I2 check does not promote R1, B4, P2 or C2, and does not
open old AT2018 or IV1 2022 controls.
