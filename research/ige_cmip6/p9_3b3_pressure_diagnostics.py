"""Date/frame-separated pressure diagnostics. No station p calibration.

MSL candidate is a new, explicitly provisional physical reconstruction:
Tv(z)=Tv_site + Gamma_v*(z_site-z), fixed specific humidity through column.
p_site=p_msl*[Tv_site/(Tv_site+Gamma_v*z_site)]**(g/(Rd*Gamma_v)).
ERA5 grid T/q are site proxies; MSL reduction is provider-derived, not native
high-frequency CanESM5 ps. No variant is selected from station errors.
"""
from __future__ import annotations
import dataclasses
import hashlib
import json
import urllib.parse
import numpy as np
from p9_3b3_pressure_reference import PressureReference
from p9_3b3_thermodynamics import RD,EPSILON,q_from_e,saturation

G=9.80665


def pressure_from_msl(msl_Pa,T_proxy_K,q_proxy,height_m,lapse_K_m=.0065):
    p,t,q=np.broadcast_arrays(np.asarray(msl_Pa,float),np.asarray(T_proxy_K,float),np.asarray(q_proxy,float))
    if (not np.all(np.isfinite([p,t,q])) or np.any((p<80000)|(p>115000)) or
            np.any((t<173)|(t>332)|(q<0)|(q>.1)) or not np.isfinite(height_m) or
            not -100<height_m<3000 or lapse_K_m not in (0.,.0065)):
        raise ValueError("P93B3_MSL_CANDIDATE_DOMAIN")
    factor=1+(1/EPSILON-1)*q;tv=t*factor
    if lapse_K_m==0:return p*np.exp(-G*height_m/(RD*tv))
    gamma=lapse_K_m*factor
    return p*np.exp(-G/(RD*gamma)*np.log1p(gamma*height_m/tv))


def target_day_references(days,source_meta,country):
    refs={}
    for day in days:
        date=day.date.isoformat()
        refs[date]=PressureReference(tuple(v["surface_pressure"]*100 for v in day.vectors),
            "OPEN_METEO_DERIVED_ERA5_TARGET_DAY_GRID",f"ERA5_GRID_{source_meta['selected_cell_latitude']}_{source_meta['selected_cell_longitude']}",
            source_sha256=day.original_sha256,reference_date=date,
            time_support="TARGET_DATE_ALIGNED_INSTANTANEOUS_HOURLY_NODES")
    return refs


def with_legacy_pressure(day,reference):
    """Explicit derived donor, retaining original date/other weather fields."""
    if len(day.vectors)!=len(reference.values_Pa):raise ValueError("P93B3_LEGACY_PRESSURE_LENGTH")
    vectors=tuple({**v,"surface_pressure":p/100} for v,p in zip(day.vectors,reference.values_Pa))
    sha=hashlib.sha256(json.dumps({"donor_sha":day.original_sha256,
        "external_pressure_sha":reference.fingerprint,"operation":"REPLACE_PRESSURE_ONLY"},sort_keys=True).encode()).hexdigest()
    return dataclasses.replace(day,vectors=vectors,original_sha256=sha)


def source_msl(cache,lat,lon,start,end,expected_meta):
    params={"latitude":f"{lat:.6f}","longitude":f"{lon:.6f}","start_date":start,"end_date":end,
        "hourly":"pressure_msl","models":"era5","timezone":"UTC","elevation":"nan","cell_selection":"nearest"}
    url="https://archive-api.open-meteo.com/v1/archive?"+urllib.parse.urlencode(params)
    raw=cache.fetch(url,2_000_000);obj=json.loads(raw)
    if (obj.get("hourly_units",{}).get("pressure_msl")!="hPa" or
            abs(obj["latitude"]-expected_meta["selected_cell_latitude"])>1e-6 or
            abs(obj["longitude"]-expected_meta["selected_cell_longitude"])>1e-6):
        raise ValueError("P93B3_MSL_SOURCE_UNIT_OR_GRID_MISMATCH")
    stamps=obj["hourly"]["time"];values=obj["hourly"]["pressure_msl"]
    if len(set(stamps))!=len(stamps) or len(stamps)!=len(values):raise ValueError("P93B3_MSL_SOURCE_AXIS")
    return dict(zip(stamps,values)),{"url":url,"sha256":hashlib.sha256(raw).hexdigest(),
        "source":"OPEN_METEO_ERA5_DERIVED_MSL_PRESSURE","MSL_is_not_station_pressure":True}


def pressure_candidates(reference,site,msl,source_meta):
    """Generate without observed p; site contains provider metadata only."""
    height=site.get("height_m")
    if height is None:raise ValueError("P93B3_SOURCE_STATION_HEIGHT_MISSING_NO_GUESS")
    hourly={}
    for day in reference:
        for h,v in enumerate(day.vectors):
            stamp=day.date.isoformat()+f"T{h:02d}:00"
            m=msl.get(stamp)
            if m is None or not np.isfinite(m):raise ValueError("P93B3_TARGET_DAY_MSL_HOUR_MISSING")
            t=v["temperature_2m"]+273.15;p=v["surface_pressure"]*100
            q=float(q_from_e(saturation(v["dew_point_2m"]+273.15),p))
            hourly[stamp]={"DATE_ALIGNED_ERA5_GRID":v["surface_pressure"],
                "MSL_SITE_FIXED_LAPSE_PROVISIONAL":float(pressure_from_msl(m*100,t,q,height))/100,
                "MSL_SITE_ISOTHERMAL_SENSITIVITY":float(pressure_from_msl(m*100,t,q,height,0.))/100}
    return {"hourly":hourly,"height_m":height,"source":source_meta,
        "temperature_and_humidity_are_grid_proxies_for_site":True,
        "site_height_is_metadata_not_fitted_from_station_pressure":True,
        "all_variants_retained_no_selection_from_errors":True,"pressure_model_qualified":False}


def score_pressure_diagnostics(predictions,observations):
    """Aggregate on identical times for all pressure variants, fixed CH operator."""
    import datetime as dt
    result=[]
    bycell={(x["country"],x["period"]):x for x in predictions}
    for country,period in ((c,p) for c in ("AT","DE","CH") for p in ("winter","summer")):
        item=bycell.get((country,period),{"hourly":{}})
        original=observations[country]["cells"].get(period,{}).get("p_hPa",{})
        hour=item["hourly"];rows=[]
        for ts,true in original.items():
            if ts not in hour:continue
            vals=dict(hour[ts])
            if observations[country]["time_support"]=="PRECEDING_HOUR_MEAN_END_STAMP":
                previous=(dt.datetime.fromisoformat(ts)-dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
                if previous not in hour:continue
                vals={k:(v+hour[previous][k])/2 for k,v in vals.items()}
            rows.append({k:v-true for k,v in vals.items()})
        for variant in ("DATE_ALIGNED_ERA5_GRID","MSL_SITE_FIXED_LAPSE_PROVISIONAL","MSL_SITE_ISOTHERMAL_SENSITIVITY"):
            errors=np.array([r[variant] for r in rows]);n=len(errors)
            cell={"country":country,"period":period,"variant":variant,"matched_hours":n,
                "expected_hours":336,"status":"SCORED_REVEALED_REGRESSION" if n>=.9*336 else "COVERAGE_BLOCKED",
                "pressure_accuracy_gate":"INCONCLUSIVE_COVERAGE","pressure_model_qualified":False}
            if n:
                cell.update(MAE_hPa=float(np.mean(abs(errors))),bias_hPa=float(np.mean(errors)),
                    RMSE_hPa=float(np.sqrt(np.mean(errors**2))))
                if n>=.9*336:cell["pressure_accuracy_gate"]="PASS_THIS_REVEALED_CELL_ONLY" if cell["MAE_hPa"]<=2 else "FAIL_THIS_CELL"
            result.append(cell)
    return {"cells":result,"previously_revealed_2021_windows":True,
        "independent_accuracy":"NOT_REESTABLISHED_AFTER_REPAIR","pressure_model_qualified":False,
        "operational_ready":False,"B4_negative_result_retained":True}
