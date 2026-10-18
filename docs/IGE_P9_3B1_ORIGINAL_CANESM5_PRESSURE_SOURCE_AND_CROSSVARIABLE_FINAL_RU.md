# IGE P9.3B1 — Original CanESM5 Pressure Recovery & NEX-GDDP Cross-Variable Consistency: Final Source Audit

**18 October 2026.** Research branch `research/ige-p9-3b1-canesm5-native-ps-recovery-20261018`. Scope strictly original CanESM5 historical member `r1i1p1f1` at Graz; prior 2013/2014 DEVELOPMENT cases; `main` unchanged.

## Verified results

**Source-discovery original CMIP6 Pangeo catalog:** 514,818 Zarr assets / 80,751,521 original response bytes, raw SHA256 `a19a343d57f3137d11ce89e07e4c66586ed02e3d396361bf209eb7a324328b89`. Exact CMIP6 / CMIP / CCCma / CanESM5 / historical / r1i1p1f1 / day / ps / gn had **zero** catalog records. Corresponding exact model/member/grid pressure `Amon` exists, v20190429, Pangeo original ESGF mirror Zarr asset `gs://cmip6/CMIP6/CMIP/CCCma/CanESM5/historical/r1i1p1f1/Amon/ps/gn/v20190429/`. **No assertion that absence from this mirror alone proves that native daily ps does not exist.**

**Independent ESGF federation queries:** [Final workflow #39164378032](https://github.com/dmitrievii/building-energy-tools/actions/runs/39164378032) returned genuine JSON from both DKRZ and CEDA. Exact table day, variable ps, member `r1i1p1f1`, native grid gn: **0 records**. Broader original-model ps search returns four physical dataset records, with `Amon` and `AERmon` from DKRZ and CEDA replicas; these are two unique MONTHLY datasets (`CMIP6.CMIP.CCCma.CanESM5.historical.r1i1p1f1.Amon.ps.gn.v20190429`, `CMIP6.CMIP.CCCma.CanESM5.historical.r1i1p1f1.AERmon.ps.gn.v20190429`). ORNL index did not deliver machine-readable JSON. **Do not claim the entirety of ESGF includes no native daily pressure; available queried inventories do not identify it.** Correctly use ESGF `variant_label`, not a member-only search that can produce false negatives; original raw source JSON query fingerprints remain recorded.

**Direct read of actual original-model CMIP6 `Amon/ps/gn` source:** Verified immutable metadata for the source asset:
- `source_id=CanESM5`, `experiment_id=historical`, `variant_label=r1i1p1f1`, `table_id=Amon`, `grid_label=gn`, `frequency=mon`, units `Pa`, `standard_name=surface_air_pressure`, `cell_methods=area: time: mean`, `version=v20190429`.
- Tracking ID: `hdl:21.14100/fbafebd7-4e82-4dc0-b23f-caf1c042ce08`; original dataset nominal resolution **500 km**; original data source license CC BY-SA 4.0.
- Same native coarse-grid nearest cell `(46.0447266311°N, 14.0625°E)` for Graz nominal `(47.0707°N, 15.4395°E)`, **approximately 155 km** away. Registered NASA NEX fine grid `(46.875°N,15.375°E)` is different from both.
- Genuine original 2013 and 2014 monthly pressure: 24 values, **mean 94,339.83 Pa**, minimum **93,673.34 Pa**, maximum **95,479.45 Pa**. This is pressure at the coarse model's *own model surface*, NOT a fine-grid, hourly, daily or station pressure.

**Original NASA NEX-GDDP daily source:** Full original `CanESM5/historical-1995-2014` `joint_daily_raw.csv` SHA256 `77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef`, verified against P7C.3 original registered source. Original 730 daily records for 2013 and 2014 matched at year-month level to corresponding original CanESM5 MONTHLY surface pressure, specifically as a **hypothetical diagnostic**, never as an assertion of synchronous daily ps at NASA fine grid.

| Hypothetical monthly-P proxy diagnostic | 2013 | 2014 |
|---|---:|---:|
| Original NASA daily source days | 365 | 365 |
| Native daily `huss > q_sat(tas, ps_Amon_coarse)` | **8** | **20** |
| Proxy RH calculated from `huss,tas,ps_Amon` minus original `hurs` mean, pp | −3.317 | −1.372 |
| Mean absolute deviation proxy RH vs native `hurs`, pp | **5.600** | **4.695** |
| Previously physically blocked P9.2D/P9.3A days satisfying same simplified saturation mismatch | **6/6** | **15/15** |

**Interpretation is essential:** a single averaged T and q with monthly P do not define a valid mean RH; `mean(q_sat(T,P)) ≠ q_sat(mean(T),mean(P))` and mean RH is nonlinear. This indicator is **NOT a count of proven impossible days**, NOT proof NASA invalid, and not proof any original daily CanESM5 native P/T/q exceeds true hourly saturation. It is positive evidence that naive replacement of 2019/2020 ERA5 external pressure by a coarse MONTHLY pressure does not automatically remove the source-variable mismatch. NASA separately bias-adjusted and spatially downscaled T/huss/hurs, and its own grid and surface elevation differ from the native GCM grid.

## Quality, release gates and next step

| Scientific condition | Outcome |
|---|---|
| Pangeo complete 514,818 source-assets scanned and SHA pinned | PASS |
| ESGF DKRZ/CEDA correct variant-label independent native `ps` inventories | PASS; daily `ps` not indexed |
| Original CanESM5 exact `Amon/ps/gn/r1i1p1f1` pressure retrieved and source metadata checked | **PASS (24 genuine monthly values)** |
| Original exact CanESM5 native daily (or 6h) `ps` recovered | **NOT RECOVERED** |
| Original P6 NASA NEX 730 daily values lineage preserved | PASS |
| Exact native GCM monthly ps is the original NASA fine-grid target pressure | **FALSE** |
| 2013/2014 diagnosed mismatch is proven true hourly saturation conflict | **NOT PROVEN** |
| New actual independently withheld original future year or station pressure skill benchmark | NOT PERFORMED |
| Engineering EPW generator qualified | **BLOCKED** |

**Scientific decision:** P9.3B1 *source search and original MONTHLY pressure recovery completed*, genuine high-frequency original `ps` **not recovered**, so pressure-reference and native fine-grid T/q/RH alignment remain **UNRESOLVED**. Do not add `Amon` as fake `ps_day`, invent intra-monthly variations, solve pressure backwards from native relative humidity or alter source original NASA daily climate fields.

**Next P9.3B2:** design and independently benchmark a pressure-aware, terrain-corrected ERA5 historical/future baseline for Graz AT (later DE/CH), using geospatially qualified source surface height and separate native GCM MONTHLY `ps` climatological/change signal as a boundary condition, NOT raw monthly assignment to each daily record. Validate pressure against source-original high-frequency observed station pressure and GPS/DEM before any joint T/q numerical closure. Pre-register new holdout years and source qualification before tuning. No global station sweep, no production EPW, no main merge.

### Original references
- CanESM5 original model: Swart et al. 2019, *Geoscientific Model Development* `https://gmd.copernicus.org/articles/12/4823/2019/`
- NASA NEX-GDDP-CMIP6 technical note `https://www.nccs.nasa.gov/sites/default/files/NEX-GDDP-CMIP6-v2-Tech_Note.pdf`
- Pangeo original model mirror `https://storage.googleapis.com/cmip6/pangeo-cmip6.json`
- ESGF metagrid / CMIP source `https://esgf-data.dkrz.de/esg-search/search/`
