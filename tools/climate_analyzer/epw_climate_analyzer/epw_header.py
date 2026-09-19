"""Structured parsing of EPW header metadata.

The hourly EPW body is only part of the source.  These helpers expose header
information without coupling downstream engines to EnergyPlus token positions.
Ground temperatures receive a typed physical representation; other structured
header sections are normalized into small source-neutral records so they can be
shown as provenance/context without pretending they are hourly measurements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class EpwGroundTemperatureProfile:
    depth_m: float
    conductivity_w_mk: float | None
    density_kg_m3: float | None
    specific_heat_j_kgk: float | None
    monthly_temperature_c: tuple[float | None, ...]

    def as_monthly_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "month_index": range(1, 13),
                "month": MONTH_NAMES,
                "depth_m": float(self.depth_m),
                "temperature_c": list(self.monthly_temperature_c),
                "source": "EPW header ground temperature",
            }
        )


@dataclass(frozen=True)
class EpwTypicalExtremePeriod:
    name: str
    period_type: str
    start: str
    end: str


@dataclass(frozen=True)
class EpwHeaderMetadata:
    ground_temperatures: tuple[EpwGroundTemperatureProfile, ...] = ()
    typical_extreme_periods: tuple[EpwTypicalExtremePeriod, ...] = ()
    design_conditions_tokens: tuple[str, ...] = ()
    holidays_daylight_savings_tokens: tuple[str, ...] = ()
    comments_1: str = ""
    comments_2: str = ""
    data_periods_tokens: tuple[str, ...] = ()


def _tokens(line: str) -> list[str]:
    return [item.strip() for item in str(line).split(",")]


def _float_or_none(value: object) -> float | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_epw_ground_temperatures(line: str) -> tuple[EpwGroundTemperatureProfile, ...]:
    """Parse the EPW ``GROUND TEMPERATURES`` header line.

    Each depth block contains depth, soil conductivity, density, specific heat
    and twelve monthly ground temperatures.  Malformed/incomplete trailing
    blocks are ignored rather than inventing values; a declared count mismatch
    raises because it indicates structurally inconsistent source metadata.
    """
    parts = _tokens(line)
    if not parts or parts[0].upper() != "GROUND TEMPERATURES":
        return ()
    try:
        declared = int(float(parts[1])) if len(parts) > 1 and parts[1] else 0
    except ValueError as exc:
        raise ValueError("EPW GROUND TEMPERATURES count is not numeric.") from exc
    block_size = 16
    payload = parts[2:]
    profiles: list[EpwGroundTemperatureProfile] = []
    for index in range(declared):
        start = index * block_size
        block = payload[start : start + block_size]
        if len(block) < block_size:
            raise ValueError(
                f"EPW GROUND TEMPERATURES declares {declared} profile(s) but profile {index + 1} is incomplete."
            )
        depth = _float_or_none(block[0])
        if depth is None:
            raise ValueError(f"EPW ground-temperature profile {index + 1} has no valid depth.")
        monthly = tuple(_float_or_none(value) for value in block[4:16])
        profiles.append(
            EpwGroundTemperatureProfile(
                depth_m=float(depth),
                conductivity_w_mk=_float_or_none(block[1]),
                density_kg_m3=_float_or_none(block[2]),
                specific_heat_j_kgk=_float_or_none(block[3]),
                monthly_temperature_c=monthly,
            )
        )
    return tuple(profiles)


def parse_epw_typical_extreme_periods(line: str) -> tuple[EpwTypicalExtremePeriod, ...]:
    parts = _tokens(line)
    if not parts or parts[0].upper() != "TYPICAL/EXTREME PERIODS":
        return ()
    try:
        declared = int(float(parts[1])) if len(parts) > 1 and parts[1] else 0
    except ValueError as exc:
        raise ValueError("EPW TYPICAL/EXTREME PERIODS count is not numeric.") from exc
    payload = parts[2:]
    periods: list[EpwTypicalExtremePeriod] = []
    for index in range(declared):
        block = payload[index * 4 : index * 4 + 4]
        if len(block) < 4:
            raise ValueError("EPW TYPICAL/EXTREME PERIODS header is incomplete.")
        periods.append(EpwTypicalExtremePeriod(*block))
    return tuple(periods)


def parse_epw_header(header_lines: Iterable[str]) -> EpwHeaderMetadata:
    """Return typed metadata from the eight standard EPW header records."""
    by_name: dict[str, str] = {}
    for line in header_lines:
        parts = _tokens(line)
        if parts:
            by_name[parts[0].upper()] = str(line)

    design = _tokens(by_name.get("DESIGN CONDITIONS", ""))[1:]
    holidays = _tokens(by_name.get("HOLIDAYS/DAYLIGHT SAVINGS", ""))[1:]
    data_periods = _tokens(by_name.get("DATA PERIODS", ""))[1:]
    comments1 = _tokens(by_name.get("COMMENTS 1", ""))
    comments2 = _tokens(by_name.get("COMMENTS 2", ""))
    return EpwHeaderMetadata(
        ground_temperatures=parse_epw_ground_temperatures(by_name.get("GROUND TEMPERATURES", "")),
        typical_extreme_periods=parse_epw_typical_extreme_periods(by_name.get("TYPICAL/EXTREME PERIODS", "")),
        design_conditions_tokens=tuple(design),
        holidays_daylight_savings_tokens=tuple(holidays),
        comments_1=",".join(comments1[1:]).strip() if comments1 else "",
        comments_2=",".join(comments2[1:]).strip() if comments2 else "",
        data_periods_tokens=tuple(data_periods),
    )


def ground_temperature_frame(metadata: EpwHeaderMetadata) -> pd.DataFrame:
    """Flatten all EPW ground-temperature depth profiles for generic plotting."""
    frames = [profile.as_monthly_frame() for profile in metadata.ground_temperatures]
    if not frames:
        return pd.DataFrame(columns=["month_index", "month", "depth_m", "temperature_c", "source"])
    return pd.concat(frames, ignore_index=True)
