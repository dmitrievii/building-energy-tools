#!/usr/bin/env python3
"""IGE P9.1G direct ERA5 pressure-level stability, true above-ground physics.

Do not use archived forecast products as ERA5, nor below-surface pressure
temperatures. Pressure sampling is a scientific SUBSAMPLE of full-hour DWD
station baseline, never an assertion of complete hourly inversion prediction.
"""
from __future__ import annotations
import datetime as dt
import hashlib,json,math
import numpy as np
import p9_1e_regular_grid_orography as geo

DATASET=geo.ARCO_REGULAR
LEVELS=(1000,975,950,925,900,875,850,825,800,775,750,700,650,600)
PILOT_HOURS_UTC=(0,12)
G0=9.80665
KAPPA=.286
MIN_AGL_M=50.
MIN_PAIR_HEIGHT_M=200.
MAX_PAIR_HEIGHT_M=3000.


def pair_above_ground(levels_hpa,temperatures_K,geopotentials,zsurface):
    p=np.asarray(levels_hpa,float)
    tk=np.asarray(temperatures_K,float)
    z=np.asarray(geopotentials,float)/G0
    if not (p.shape==tk.shape==z.shape and len(p)>=4):
        raise ValueError("P9G_PRESSURE_LEVEL_ARRAYS_NOT_CORRESPONDING")
    if (not np.all(np.isfinite(p)) or not np.all(np.isfinite(tk))
        or not np.all(np.isfinite(z)) or not math.isfinite(zsurface)):
        raise ValueError("P9G_MISSING_REAL_ERA5_PROFILE_VARIABLE")
    if not(np.all((p>=100)&(p<=1100)) and np.all((tk>170)&(tk<340))):
        raise ValueError("P9G_ERA5_PRESSURE_TEMPERATURE_UNITS_OR_DOMAIN")
    valid=sorted((float(z[i]),float(tk[i]),float(p[i])) for i in range(len(p))
                 if z[i]-zsurface>=MIN_AGL_M and z[i]-zsurface<=5000.)
    # Freeze lowest valid level then first at least 200m higher.
    if len(valid)<2:
        return {"status":"INSUFFICIENT_ABOVE_GROUND_ERA5_PRESSURE_LEVELS",
                "n_above_surface_levels":len(valid)}
    low=valid[0]
    high=next((r for r in valid[1:] if
               MIN_PAIR_HEIGHT_M<=r[0]-low[0]<=MAX_PAIR_HEIGHT_M),None)
    if high is None:
        return {"status":"INSUFFICIENT_SEPARATED_VALID_PRESSURE_LEVELS",
                "n_above_surface_levels":len(valid)}
    dz=high[0]-low[0]
    upper_minus_lower_C=high[1]-low[1]
    theta_lower=low[1]*(1000./low[2])**KAPPA
    theta_upper=high[1]*(1000./high[2])**KAPPA
    return {
        "status":"TWO_VALID_ABOVE_REGULAR_ERA5_SURFACE_LEVELS",
        "lower_pressure_hpa":low[2],"upper_pressure_hpa":high[2],
        "lower_height_m":low[0],"upper_height_m":high[0],
        "lower_height_above_model_ground_m":low[0]-zsurface,
        "upper_height_above_model_ground_m":high[0]-zsurface,
        "vertical_separation_m":dz,
        "free_air_T_upper_minus_lower_C":upper_minus_lower_C,
        "temperature_gradient_K_per_km":upper_minus_lower_C/dz*1000,
        "theta_lower_K":theta_lower,
        "theta_upper_K":theta_upper,
        "theta_gradient_K_per_km":(theta_upper-theta_lower)/dz*1000,
        "resolved_free_air_temperature_inversion":upper_minus_lower_C>0,
        "pressure_pair_is_not_measured_or_resolved_local_2m_to_200m_inversion":True,
        "below_surface_pressure_level_was_never_used":True,
    }


def hours_for_season(start,end):
    begin=dt.date.fromisoformat(start);final=dt.date.fromisoformat(end)
    rows=[]
    for k in range((final-begin).days+1):
        day=begin+dt.timedelta(days=k)
        for h in PILOT_HOURS_UTC:
            rows.append(f"{day.isoformat()}T{h:02d}:00")
    return rows


def read_original_ERA5_pressure_subsample(sites,source_selected_grid,periods):
    """Direct ARCO 0.25 ERA5 pressure profiles, sparse FULLY OBSERVED instants."""
    import xarray as xr
    import gcsfs
    ds=xr.open_zarr(gcsfs.GCSFileSystem(token="anon").get_mapper(DATASET),
                    consolidated=None,chunks=None)
    try:
        if "temperature" not in ds or "geopotential" not in ds:
            raise ValueError("P9G_ARCO_ERA5_ORIGINAL_3D_T_Z_MISSING")
        t=ds["temperature"];z=ds["geopotential"]
        if not {"time","level","latitude","longitude"}.issubset(t.dims):
            raise ValueError("P9G_ERA5_TEMPERATURE_NOT_4D_PRESSURE_LEVEL")
        if not {"time","level","latitude","longitude"}.issubset(z.dims):
            raise ValueError("P9G_ERA5_GEOPOTENTIAL_NOT_4D_PRESSURE_LEVEL")
        if str(t.attrs.get("units","")).strip().lower() not in ("k","kelvin"):
            raise ValueError("P9G_ARCO_ORIGINAL_T_MUST_BE_KELVIN")
        if not geo.n320.is_geopotential_unit(z.attrs.get("units","")):
            raise ValueError("P9G_ARCO_Z_MUST_BE_M2_S2")
        available=set(int(x) for x in np.asarray(ds["level"].values))
        chosen=[l for l in LEVELS if l in available]
        if len(chosen)<10:raise ValueError("P9G_REQUIRED_ORIGINAL_PRESSURE_LEVELS_MISSING")
        ilat=[];ilon=[]
        for s in sites:
            grid=source_selected_grid[s["id"]]
            ilat.append(geo.regular_coordinate_index(ds.latitude.values,grid["lat"]))
            ilon.append(geo.regular_coordinate_index(ds.longitude.values,grid["lon"],wrap=True))
        lat=xr.DataArray(ilat,dims="site")
        lon=xr.DataArray(ilon,dims="site")
        extracted={};original_values=[]
        for period,start,end in periods:
            timestamps=hours_for_season(start,end)
            slice_time=np.array(timestamps,dtype="datetime64[ns]")
            ti=t.sel(time=slice_time,level=chosen).isel(
                latitude=lat,longitude=lon).transpose("time","level","site")
            zi=z.sel(time=slice_time,level=chosen).isel(
                latitude=lat,longitude=lon).transpose("time","level","site")
            tv=np.asarray(ti.values,float)
            zv=np.asarray(zi.values,float)
            if tv.shape!=(len(timestamps),len(chosen),len(sites)) or zv.shape!=tv.shape:
                raise ValueError("P9G_ERA5_INCOMPLETE_ORIGINAL_PRESSURE_DATA_TIMELINE")
            if not np.isfinite(tv).all() or not np.isfinite(zv).all():
                raise ValueError("P9G_ORIGINAL_ARCO_PRESSURE_PROFILE_HAS_MISSING_VALUES")
            original_values.append((period,tv.astype("<f8").tobytes(),
                                    zv.astype("<f8").tobytes()))
            for j,site in enumerate(sites):
                key=site["id"]
                extracted.setdefault(key,{})
                extracted[key][period]={}
                for i,stamp in enumerate(timestamps):
                    extracted[key][period][stamp]=pair_above_ground(
                        chosen,tv[i,:,j],zv[i,:,j],
                        source_selected_grid[key]["model_height_m"])
            print("P9G_ARCO_PRESSURE",json.dumps({
                "period":period,"days":len(timestamps)//len(PILOT_HOURS_UTC),
                "UTC_times_per_site":len(timestamps),
                "sites":len(sites),"model_levels":chosen,
                "qualified_pairs":sum(
                    x["status"]=="TWO_VALID_ABOVE_REGULAR_ERA5_SURFACE_LEVELS"
                    for s in sites for x in extracted[s["id"]][period].values()),
            }),flush=True)
        digest=hashlib.sha256()
        for season,tvalues,zvalues in original_values:
            digest.update(season.encode())
            digest.update(tvalues);digest.update(zvalues)
        source={
            "original_ARCO_data_URI":DATASET,
            "model":"ERA5_ARCO_REGULAR_025_NOT_NATIVE_CDS_GRIB",
            "pressure_ERA5_temperature_units":str(t.attrs.get("units")),
            "pressure_ERA5_geopotential_units":str(z.attrs.get("units")),
            "data_UTC_subsampling_hours":[0,12],
            "source_sample_original_T_Z_float64_SHA256":digest.hexdigest(),
            "pressure_level_values_hpa":chosen,
            "3D_ERA5_model_pressure_temperatures_at_site_not_measured_inversions":True,
            "hourly_F1_2019_weather_forecast_not_extended_or_interpolated_from_pressure_pilot":True,
        }
        return extracted,source
    finally:
        ds.close()


def fixed_potential_temperature_stability_guard(risk_geo,ghi,wind,cloud,profile,method):
    if method not in ("T_UPPER_WARM","THETA_STABLE"):
        raise ValueError("P9G_UNKNOWN_PHYSICAL_PRESSURE_GUARD")
    if not risk_geo or ghi>10 or wind>=2.5 or cloud>=60:
        return False
    if profile.get("status")!="TWO_VALID_ABOVE_REGULAR_ERA5_SURFACE_LEVELS":
        return False
    if method=="T_UPPER_WARM":
        return profile["temperature_gradient_K_per_km"]>0.
    return profile["theta_gradient_K_per_km"]>5.
