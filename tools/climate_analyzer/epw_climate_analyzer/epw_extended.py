"""Extended EPW ingestion normalization.

The original parser historically cleaned only fields used by the first Climate
Analyzer pages. As additional EPW atmospheric quantities become canonical, their
standard EPW missing sentinels must be removed before any generic explorer or
comparison sees them.
"""

from __future__ import annotations

import pandas as pd


# EnergyPlus EPW data dictionary missing thresholds. Existing core parser rules
# may overlap; applying them again is harmless and keeps this extension explicit.
EPW_EXTENDED_MISSING_LIMITS: dict[str, float] = {
    "extraterrestrial_horizontal_radiation_wh_m2": 9999.0,
    "extraterrestrial_direct_normal_radiation_wh_m2": 9999.0,
    "horizontal_infrared_radiation_intensity_wh_m2": 9999.0,
    "zenith_luminance_cd_m2": 9999.0,
    "visibility_km": 9999.0,
    "ceiling_height_m": 99999.0,
    "precipitable_water_mm": 999.0,
    "aerosol_optical_depth_thousandths": 0.999,
    "snow_depth_cm": 999.0,
    "days_since_last_snowfall": 99.0,
    "albedo": 999.0,
    "liquid_precipitation_depth_mm": 999.0,
    "liquid_precipitation_quantity_hr": 99.0,
}


def clean_extended_epw_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Replace official EPW sentinels in extended fields with missing values."""
    data = df.copy()
    attrs = dict(df.attrs)
    for column, limit in EPW_EXTENDED_MISSING_LIMITS.items():
        if column not in data.columns:
            continue
        values = pd.to_numeric(data[column], errors="coerce")
        data[column] = values.mask(values >= float(limit))
    data.attrs.update(attrs)
    data.attrs["epw_extended_sentinel_cleanup"] = True
    return data
