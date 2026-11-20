"""Stable GeoSphere query validation, independent of runtime UI wrappers."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def strict_provider_parameters_with_quality_flags(
    metadata: Mapping[str, Any],
    provider_parameters: Iterable[str],
    *,
    resource_id: str,
) -> tuple[str, ...]:
    # Import at call time to keep the provider model and validator acyclic.
    from .geosphere import _normalise_unit, parse_parameters, resource_spec

    parameters = parse_parameters(metadata)
    allowed = resource_spec(resource_id).field_by_provider
    result: list[str] = []
    for name in dict.fromkeys(str(item).strip() for item in provider_parameters if str(item).strip()):
        if name not in allowed:
            raise ValueError(f"Unsupported GeoSphere physical parameter: {name}")
        result.append(name)
        flag_name = f"{name}_flag"
        flag = parameters.get(flag_name)
        if flag is None:
            continue
        if _normalise_unit(flag.unit) != "code":
            raise ValueError(
                f"GeoSphere quality flag '{flag_name}' unit changed: expected 'code', got '{_normalise_unit(flag.unit)}'."
            )
        result.append(flag_name)
    return tuple(result)
