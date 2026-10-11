# IGE Climate Research — Data Custody, Provenance and Reproducibility Contract

Freeze date: **2026-10-11**. This repository is confirmed **PUBLIC**. Publicly committing third-party original climate data, proprietary Meteonorm material, or the full portable freeze is **prohibited by default**, pending a dataset-specific rights review.

## 1. Immutable portable evidence bundle

**Exact filename:** \`IGE_RESEARCH_P6_1_TO_P6_3E_FREEZE_2026-10-11.zip\`  
**Size:** \`68062328\` bytes  
**SHA-256:** \`2c3ceecaf83aa3ff2b3e19d109d866111f1145eb5fe48ac6a4fdd010b27a22d7\`.

File created outside GitHub and locally tested after an independent ZIP extraction. Until an institutional deposit ID exists, this file is a **portable user-download**, not a guaranteed permanent repository record.

### Internal directory layout

\`\`\`text
IGE_RESEARCH_P6_1_TO_P6_3E_FREEZE_2026-10-11/
  MANIFEST.json
  README.md
  SHA256SUMS.txt
  evidence_index.csv
  scientific_snapshot.json
  verify_freeze.py
  model_window_sources/                  # 40 original derived NASA NEX window ZIPs
  station30_1995_2014_hourly/            # 20 original GeoSphere annual hourly ZIPs
  stage_evidence/                        # 21 nonredundant P6.1–P6.3E analysis ZIPs
\`\`\`

Each original ZIP has outer SHA-256, original name, exact size, and every constituent member's own SHA-256 in \`MANIFEST.json\`: **81 ZIPs / 467 members**. The 40 model windows are an 8×5 complete Cartesian product. The 20 station annual source archives cover 1995 through 2014 (expected 175,320 UTC hours).

These \`model_window_sources/*.zip\` contain NASA-derived \`joint_daily_raw.csv\`, \`source_provenance.json\`, \`quality_report.json\`, and annual/monthly summaries. **They are not the complete underlying annual NCSS NetCDF byte stream**. Exact original yearly-variable NCSS URLs, unit/calendar, model/member and original subset SHA are kept in each \`source_provenance.json\`. When NetCDF itself is required, retrieve exact subsets and verify source SHA, recognizing that upstream APIs can change.

## 2. Offline verification on an extracted ZIP

\`\`\`shell
unzip IGE_RESEARCH_P6_1_TO_P6_3E_FREEZE_2026-10-11.zip
cd IGE_RESEARCH_P6_1_TO_P6_3E_FREEZE_2026-10-11
python verify_freeze.py .
\`\`\`

Expected:

\`\`\`text
IGE freeze 2026-10-11 ZIP files 81 NEX model-window archives 40 GeoSphere hourly years 20
PASS integrity errors 0
\`\`\`

If any checksum differs, **do not silently refetch and substitute new source responses**. Open a scientific source drift incident and record both originals.

## 3. Provenance runs and short-lived GitHub artifacts

GitHub Actions artifacts were configured for **30 days retention** in the science workflows, not perpetual preservation.

| Source class | Accepted workflow ID | Content |
|---|---|---|
| ACCESS-CM2 original 5 windows | [38067931031](https://github.com/dmitrievii/building-energy-tools/actions/runs/38067931031) | NASA 5 model-scenario window original-derived P6.1 archives |
| Seven other GCM source windows | [38072042977](https://github.com/dmitrievii/building-energy-tools/actions/runs/38072042977) | Native 7-GCM model-window archives, some original failed windows later repaired |
| Corrected model original windows | [38077903914](https://github.com/dmitrievii/building-energy-tools/actions/runs/38077903914) | Repaired 3 historical and 4 future source windows selected over bad or missing predecessors |
| GeoSphere 20 hourly years | [38082122721](https://github.com/dmitrievii/building-energy-tools/actions/runs/38082122721) | 20 original station #30 yearly GeoJSON+hourly QC archives |
| P6.2D method benchmarks | [38088092141](https://github.com/dmitrievii/building-energy-tools/actions/runs/38088092141), [38089064925](https://github.com/dmitrievii/building-energy-tools/actions/runs/38089064925), [38090002603](https://github.com/dmitrievii/building-energy-tools/actions/runs/38090002603) | M1/M2/M3 holdouts and all model/SSP source-preserving future sensitivity |
| P6.3A | [38123017733](https://github.com/dmitrievii/building-energy-tools/actions/runs/38123017733) | 40-source dependence physics audit, two M3 review flags |
| P6.3B | [38124674795](https://github.com/dmitrievii/building-energy-tools/actions/runs/38124674795) | GeoSphere original daily / NASA POWER gridded reference and reproducibility |
| P6.3C | [38126567048](https://github.com/dmitrievii/building-energy-tools/actions/runs/38126567048) | Official original precipitation semantics, 3 donor station archive, 87,648 original hourly source flags |
| P6.3D | [38128314291](https://github.com/dmitrievii/building-energy-tools/actions/runs/38128314291) | Original NASA POWER hourly 2 points and accepted daily GeoSphere solar |
| P6.3E | [38129047139](https://github.com/dmitrievii/building-energy-tools/actions/runs/38129047139) | Original two-point NASA POWER GHI/DNI/DHI/TOA/clear-sky, 175,296 rows |

The 81-archive portability freeze captures critical workflow artifacts **before their expiration**, with the deliberately selected accepted source windows. Failed runs and redundant intermediate outputs are intentionally not retained as separate ZIP files; Git commit and Actions historical logs still record debug attempts.

## 4. Intellectual property, attribution and redistribution

| Dataset | Source/rights status | Action |
|---|---|---|
| GeoSphere \`klima-v2-1d\`, \`klima-v2-1h\` unauthenticated station data | GeoSphere official API guide: open unauthenticated data **CC BY 4.0**; dataset/resource metadata is authoritative | Cite GeoSphere Austria, original station/API source and version; preserve licensing and metadata |
| NASA POWER gridded products | Public NASA-led science data ordinarily openly accessible, but source-specific terms must still be verified | Attribute NASA POWER, product and source version; do not misstate gridded proxy as measured ground |
| NASA NEX-GDDP-CMIP6 | **Original CMIP6 GCM model licenses are source-specific** (\`cmip6_license\` original NetCDF global attribute); NASA v2 technical note explicitly requires checking them | No automatic public redistribution of the 40 ZIPs before source-model license inventory and research institute IP clearance |
| PVGIS European Commission original API | Original service usage conditions permit use, source acknowledgement expected | Preserve JRC/PVGIS source, requested source (SARAH3 vs ERA5), API date, original response SHA |
| ARAD Graz original precision radiometry | **NOT ACQUIRED**, published QC is not an original time series; access and permission unconfirmed | Contact custodians, obtain written use/publication rights and original per-record flags before analysis |
| Meteonorm 8 scenario EPWs, proprietary software/output | User-generated licensed materials; **excluded** from freeze | Never publicly publish or treat its RCP EPWs as NASA SSP/GCM model data; use locally for validation subject to license |
| IGE analysis code/documentation | Public GitHub repository does not alone settle university employee IP/ownership | Institutional licensing/IP approval required before publication/branding/external release |

Authoritative source pointers:
- https://dataset.api.hub.geosphere.at/v1/docs/user-guide/license.html
- https://data.hub.geosphere.at/en/about
- https://www.nccs.nasa.gov/sites/default/files/NEX-GDDP-CMIP6-v2-Tech_Note.pdf
- https://science.data.nasa.gov/about/license
- https://power.larc.nasa.gov/docs/services/api/temporal/hourly/
- https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/general-information/usage-conditions-data-protection_en

## 5. Long-term institutional deposit — status: **PENDING**

Deposit a SHA-verified copy to a supported **TU Graz-managed research data storage / university-approved storage** (with access policy matching per-GCM source licenses), possibly later a dataset DOI repository for distributable derived tables/code.

Do not confuse:
- a downloaded ChatGPT attachment;
- an ephemeral GitHub Actions artifact;
- a public GitHub source-code commit;
- an institutional research data archive with retention, documented access and preservation policy.

They are not equivalent archival media.

After deposit, append **without replacing historical evidence**:
- custodial repository/service;
- dataset/revision/accession ID or stable URI;
- exact archived file name, bytes, SHA;
- deposited UTC date, owner and access-control classification;
- backup/redundancy/retention contract and restore-test result;
- redistribution/DOI/CMIP6-license decision.

Until all these fields are confirmed, describe the current result accurately as **a complete locally verified portable freeze awaiting durable deposit**.

## 6. Research workflow for future phases

- Read \`docs/IGE_CLIMATE_RESEARCH_HANDOFF.md\` at new-chat start.
- Each new stage generates a reviewed **source inventory**, original source hash, methods/clock/QC contract, code/CI commit, scientific limitations, results and independent review decision.
- After successful CI, update MASTER_RECORD, DECISION_LOG, PAPER_EVIDENCE_REGISTER, HANDOFF and add the new artifact to a newly versioned (never silently overwritten) external freeze snapshot.
- Avoid rebaking previously frozen source rows with updated API responses without preserving both and marking source drift.
- Never promote scientific status to \`PRODUCTION_HOURLY_EPW_READY\` without a separate independent ground observation and simulation-impact validation gate.
