# Climate Analyzer 0.7 — Precipitation and Snow Analytics

Status: implementation branch

## Goal

Promote precipitation and snow from basic variable explorers into quantity-correct multi-year climate analytics for GeoSphere historical observations while preserving EPW compatibility.

## Quantity contract

### Liquid precipitation depth (`rr`)

- canonical variable: `liquid_precipitation_depth_mm`;
- interval-extensive quantity;
- aggregation: **sum**;
- canonical hourly normalization conserves precipitation depth across complete source hours;
- daily/monthly/seasonal/annual totals are sums, never min/mean/max centre lines.

### Measured precipitation duration (`rrm`)

- canonical variable: `precipitation_duration_min`;
- GeoSphere provider field: `rrm`, unit `min`;
- interval-extensive quantity;
- aggregation: **sum**;
- duration is used only when independently available from the provider;
- duration is never inferred from `rr` precipitation depth.

### Snow depth (`sh`)

- canonical variable: `snow_depth_cm`;
- state quantity;
- aggregation for canonical hourly state: mean;
- snow depth is never summed.

## Dual-resolution contract

The page deliberately uses two resolutions because not every precipitation/snow metric is conserved by hourly normalization.

Canonical hourly analysis frame:

- precipitation totals;
- daily precipitation totals;
- annual precipitation totals/indices;
- measured precipitation duration (`rrm`) sums;
- ordinary liquid-precipitation explorer.

Provider-native frame under the same global Data filter:

- precipitation-record occurrence;
- true native-interval precipitation maxima (10-minute for GeoSphere);
- snow-cover duration from thresholded snow-depth states;
- snow-season first/last dates;
- snow-cover days and days above 5 cm;
- true native snow-depth maxima.

For snow-cover duration, each valid native record with `sh > 0 cm` contributes exactly the declared source interval. Missing timestamps contribute no duration.

## Precipitation indices

Default climate-index thresholds:

- wet day: daily precipitation >= 1 mm;
- heavy precipitation day: >= 10 mm;
- very heavy precipitation day: >= 20 mm;
- dry day for consecutive dry-spell analysis: < 1 mm;
- fully unobserved days break a dry spell and are never silently treated as zero precipitation.

Annual outputs include:

- total precipitation;
- wet/heavy/very-heavy day counts;
- maximum daily precipitation;
- maximum native source-interval precipitation where native data are available;
- longest dry spell;
- measured precipitation duration where `rrm` is available;
- year-by-year trend visualization.

## Snow-season indices

Default snow season is a transparent July–June analysis year so autumn and spring snow from one cold season are not split at 31 December.

Outputs include:

- snow-cover days (`daily observed max sh > 0 cm`);
- days with snow depth > 5 cm;
- maximum observed snow depth;
- first snow-cover date;
- last snow-cover date;
- first-to-last snow-season span;
- season-by-season trend visualization.

Missing days do not count as snow-cover days.

## Global Data filter

0.7 replays the already-rendered global Data filter on the provider-native frame. No second precipitation-specific date/month/hour filter is introduced.

The same selection therefore governs both canonical-hourly and native-resolution branches:

- All available / Year / Custom;
- Chronological / Calendar profile;
- month selection;
- hour range.

Annual/season trend outputs preserve real source years/seasons while using only observations admitted by the current Data filter.

## UI constraints

- match the existing Climate Analyzer page structure;
- no new KPI strip;
- do not compare precipitation period sums against per-record min/mean/max;
- capability-gate `rrm` duration analytics;
- EPW remains valid when `rrm` is unavailable;
- precipitation record occurrence remains distinct from physical rain duration.
