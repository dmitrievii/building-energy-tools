#!/usr/bin/env python3
"""P9.3B2 source-independent hypsometric pressure baseline.

No observed station p used for model design or calibration. Model p is Open-
Meteo ERA5-derived unadjusted surface pressure at selected source grid cell.
SRTM90 at its nominal grid center is a *terrain proxy*, NOT validated native
ERA5 model orography. Station elevation is original provider metadata.
"""
from __future__ import annotations
import math
from p9_2b_cmip6_daily_joint_regime_solver import q_of_e,sat_pa
GRAVITY=9.80665
R_D=287.05
LAPSE_K_M=.0065
SRC_PRESSURE="OPEN_METEO_DERIVED_ERA5_GRID_SURFACE_PRESSURE_NOT_NATIVE_CDS_GRIB"
DEM_SOURCE="OPENTOPODATA_SRTM90M_AT_NOMINAL_ERA5_GRID_CENTER_NOT_MODEL_OROGRAPHY"

def virtual_T_kelvin(temperature_C,dewpoint_C,pressure_hPa):
    t=float(temperature_C)
    dp=float(dewpoint_C)
    p=float(pressure_hPa)*100.
    if not (200<t+273.15<335 and -110<dp<t+.6 and 30000<p<112000):
        raise ValueError("P93B2_INVALID_ERA5_INPUT_T_DP_P")
    q=q_of_e(sat_pa(dp),p)
    if not 0<q<.1:raise ValueError("P93B2_INVALID_VAPOUR_FOR_VIRTUAL_T")
    return (t+273.15)*(1+.61*q)

def correct_pressure(p_hPa,T_C,dewpoint_C,z_station_m,z_grid_SRTM_m,method):
    p=float(p_hPa)
    z_s=float(z_station_m);z_g=float(z_grid_SRTM_m)
    if not (300<p<1100 and -500<z_s<5000 and -500<z_g<5000):
        raise ValueError("P93B2_PRESSURE_OR_ELEVATION_SOURCE_OUT_OF_RANGE")
    dz=z_s-z_g
    if abs(dz)>2000:
        raise ValueError("P93B2_UNCERTIFIED_VERTICAL_EXTRAPOLATION_GT_2000M")
    Tv=virtual_T_kelvin(T_C,dewpoint_C,p)
    if method=="ISOTHERMAL_VIRTUAL_T":
        factor=math.exp(-GRAVITY*dz/(R_D*Tv))
    elif method=="FIXED_LAPSE_0065_SENSITIVITY":
        base=1.-LAPSE_K_M*dz/Tv
        if base<=0:raise ValueError("P93B2_LAPSE_NEGATIVE_COLUMN_T")
        factor=base**(GRAVITY/(R_D*LAPSE_K_M))
    else:
        raise ValueError("P93B2_UNREGISTERED_PRESSURE_METHOD")
    corrected=p*factor
    if not 350<corrected<1080:
        raise ValueError("P93B2_NONPHYSICAL_CORRECTED_PRESSURE")
    return corrected

def evaluate_methods(p_hPa,T_C,dewpoint_C,z_station_m,z_grid_SRTM_m):
    return {"B0_UNCHANGED_ERA5_GRID_hPa":float(p_hPa),
        "B1_FIXED_HYPSOMETRIC_ISOTHERMAL_hPa":
           correct_pressure(p_hPa,T_C,dewpoint_C,z_station_m,z_grid_SRTM_m,
                           "ISOTHERMAL_VIRTUAL_T"),
        "B2_FIXED_LAPSE_SENSITIVITY_hPa":
           correct_pressure(p_hPa,T_C,dewpoint_C,z_station_m,z_grid_SRTM_m,
                           "FIXED_LAPSE_0065_SENSITIVITY")}
