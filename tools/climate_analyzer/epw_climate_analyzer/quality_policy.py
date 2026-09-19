"""Provider-neutral observation-quality policy for canonical climate frames.

Quality flags remain adapter metadata; calculation engines never interpret a
provider field name directly.  Adapters expose a small mapping from provider
flag identity to canonical physical column through DataFrame attrs.  Applying a
quality policy masks only the affected physical variable, not the entire row,
so unrelated observations remain usable and canonical hourly completeness rules
continue to operate correctly.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd


QualityPolicy = Literal["all", "checked", "manual"]
QUALITY_POLICY_ALL = "all"
QUALITY_POLICY_CHECKED = "checked"
QUALITY_POLICY_MANUAL = "manual"
QUALITY_POLICY_ATTR = "canonical_quality_policy"
PROVIDER_TO_CANONICAL_ATTR = "geosphere_provider_to_canonical"
QUALITY_FLAG_PREFIX = "quality_flag__"

# GeoSphere v2 quality codes documented by the provider.  Unknown/new codes are
# not silently accepted under a restrictive policy; users can always select All
# observations to retain them while their meaning is reviewed.
GEOSPHERE_AUTOMATIC_OR_MANUAL_CODES = frozenset({10, 11, 12, 20, 21, 22})
GEOSPHERE_MANUAL_CODES = frozenset({20, 21, 22})


def quality_policy_label(policy: QualityPolicy) -> str:
    return {
        QUALITY_POLICY_ALL: "All observations",
        QUALITY_POLICY_CHECKED: "Automatically or manually checked",
        QUALITY_POLICY_MANUAL: "Manually checked only",
    }[policy]


def _allowed_codes(policy: QualityPolicy) -> frozenset[int] | None:
    if policy == QUALITY_POLICY_ALL:
        return None
    if policy == QUALITY_POLICY_CHECKED:
        return GEOSPHERE_AUTOMATIC_OR_MANUAL_CODES
    if policy == QUALITY_POLICY_MANUAL:
        return GEOSPHERE_MANUAL_CODES
    raise ValueError(f"Unsupported climate quality policy: {policy}")


def apply_quality_policy(df: pd.DataFrame, policy: QualityPolicy = QUALITY_POLICY_ALL) -> pd.DataFrame:
    """Mask canonical observations that fail the selected provider-quality rule.

    A provider parameter without a matching quality flag is left untouched. This
    is deliberate: absence of a flag is not interpreted as bad quality.  The
    returned frame records masking counts in attrs for provenance/diagnostics.
    """
    allowed = _allowed_codes(policy)
    data = df.copy()
    attrs = dict(df.attrs)
    data.attrs.update(attrs)
    if allowed is None:
        data.attrs[QUALITY_POLICY_ATTR] = policy
        data.attrs["canonical_quality_masked_counts"] = {}
        return data

    provider_map = attrs.get(PROVIDER_TO_CANONICAL_ATTR, {})
    if not isinstance(provider_map, dict):
        provider_map = {}
    masked_counts: dict[str, int] = {}
    for flag_column in [name for name in data.columns if str(name).startswith(QUALITY_FLAG_PREFIX)]:
        provider_name = str(flag_column).split(QUALITY_FLAG_PREFIX, 1)[1]
        canonical_name = provider_map.get(provider_name)
        if not canonical_name or canonical_name not in data.columns:
            continue
        flags = pd.to_numeric(data[flag_column], errors="coerce")
        # Restrictive policies only accept explicitly recognized allowed codes.
        accepted = flags.isin(allowed)
        physical = pd.to_numeric(data[canonical_name], errors="coerce")
        to_mask = physical.notna() & ~accepted
        if to_mask.any():
            data.loc[to_mask, canonical_name] = pd.NA
        masked_counts[str(canonical_name)] = int(to_mask.sum())

    data.attrs[QUALITY_POLICY_ATTR] = policy
    data.attrs["canonical_quality_masked_counts"] = masked_counts
    return data
