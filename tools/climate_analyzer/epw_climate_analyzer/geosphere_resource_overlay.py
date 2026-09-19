"""Declarative GeoSphere resource-contract extensions discovered by live census.

This migration module contains provider vocabulary only.  It does not implement
calculations: values are converted into the same canonical variables consumed by
the source-neutral engines.  The overlay can be folded into the base adapter once
the multi-resource migration is complete.
"""

from __future__ import annotations

from dataclasses import replace

from . import geosphere


HOURLY_RESOURCE_ID = "klima-v2-1h"


def apply_geosphere_resource_overlay() -> None:
    """Add live hourly-only provider fields to the declarative resource spec."""
    current = geosphere.GEOSPHERE_RESOURCES[HOURLY_RESOURCE_ID]
    by_provider = current.field_by_provider
    additions: list[geosphere.ProviderFieldSpec] = []

    if "so_h" not in by_provider:
        additions.append(
            geosphere.ProviderFieldSpec(
                "so_h",
                "sunshine_duration_s",
                ("h",),
                scale=3600.0,
                description="Sonnenscheindauer, Stundensumme",
                interval_semantics="duration",
            )
        )
    if "tb100" not in by_provider:
        additions.append(
            geosphere.ProviderFieldSpec(
                "tb100",
                "ground_temperature_1_00m_c",
                ("°c", "c", "degc"),
                description="Bodentemperatur 100 cm",
                interval_semantics="provider-defined temperature state/mean",
            )
        )
    if "tb200" not in by_provider:
        additions.append(
            geosphere.ProviderFieldSpec(
                "tb200",
                "ground_temperature_2_00m_c",
                ("°c", "c", "degc"),
                description="Bodentemperatur 200 cm",
                interval_semantics="provider-defined temperature state/mean",
            )
        )

    if additions:
        geosphere.GEOSPHERE_RESOURCES[HOURLY_RESOURCE_ID] = replace(
            current,
            field_specs=current.field_specs + tuple(additions),
        )
