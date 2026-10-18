#!/usr/bin/env python3
"""P9.3B1 original CanESM5 ps source: ESGF discovery + original-model Amon mirror.

This DOES NOT generate native NEX daily ps. Source identity strictly CanESM5
historical r1i1p1f1 gn. Monthly ps from a verified CMIP6 Pangeo mirror is
coarse atmosphere surface pressure and cannot be injected into hourly EPW.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,math,statistics,urllib.parse,urllib.request
from pathlib import Path

from p9_2b_cmip6_daily_joint_regime_solver import e_of_q,sat_pa
from p7c3_ensemble import read_source,HIST

EXACT={
    "project":"CMIP6","source_id":"CanESM5","experiment_id":"historical",
    "member_id":"r1i1p1f1","table_id":"day","variable_id":"ps",
    "grid_label":"gn","type":"Dataset"
}
PORTALS=(
    "https://esgf-node.ornl.gov/esg-search/search/",
    "https://esgf-data.dkrz.de/esg-search/search/",
    "https://esgf.ceda.ac.uk/esg-search/search/",
)
ORIGINAL_MONTHLY_ASSET="gs://cmip6/CMIP6/CMIP/CCCma/CanESM5/historical/r1i1p1f1/Amon/ps/gn/v20190429/"
BASE_GCM_GRID=(46.875,15.375)
GRAZ=(47.0707,15.4395)
NASA_SHA="77ec2e5637eb487c3cedde4e0b660b31f8bd2606198e766255d75a985d61dfef"
BLOCKED_2013=("2013-02-14","2013-02-21","2013-07-09","2013-11-19","2013-12-11","2013-12-15")
BLOCKED_2014=("2014-01-31","2014-02-09","2014-02-10","2014-04-19","2014-04-20","2014-04-22",
"2014-05-07","2014-05-13","2014-05-15","2014-05-16","2014-06-11","2014-06-12","2014-06-15","2014-12-02","2014-12-16")

def query_esgf():
    """Check exact day and independent all-frequency ps discovery.

    ESGF indexes use variant_label (sometimes member_id), hence a single
    overly restrictive member_id-only query can produce a false zero.
    Exact dataset identity is checked in returned doc, not inferred.
    """
    results=[]
    def single(value,desired):
        if isinstance(value,(list,tuple)):
            return desired in value
        return str(value)==desired
    for url in PORTALS:
        for mode in ("day_variant_label","all_ps_frequencies_variant_label"):
            args={**EXACT}
            args.pop("member_id",None)
            args["variant_label"]="r1i1p1f1"
            if mode=="all_ps_frequencies_variant_label":
                args.pop("table_id",None)
            args.update({"format":"application/solr+json","limit":200,"latest":"true"})
            requested=url+"?"+urllib.parse.urlencode(args)
            info={"endpoint":url,"query_mode":mode,"query_url":requested}
            try:
                req=urllib.request.Request(requested,headers={"User-Agent":"IGE-P9.3B1-Original-CanESM5-ps-audit/1.1"})
                with urllib.request.urlopen(req,timeout=25) as resp:
                    data=resp.read(6_000_000)
                    if resp.read(1):raise ValueError("P93B1_ESGF_RESULT_TOO_LARGE")
                raw=json.loads(data)
                docs=raw.get("response",{}).get("docs",[])
                qualified=[d for d in docs if single(d.get("source_id",""),"CanESM5")
                    and single(d.get("experiment_id",""),"historical")
                    and single(d.get("variable_id",""),"ps")
                    and (single(d.get("variant_label",""),"r1i1p1f1") or
                         single(d.get("member_id",""),"r1i1p1f1"))
                    and single(d.get("grid_label",""),"gn")]
                info.update({"status":"ESGF_JSON_RESPONSE","raw_response_sha256":hashlib.sha256(data).hexdigest(),
                    "n_total_matches_reported":raw.get("response",{}).get("numFound"),
                    "n_qualified_dataset_docs":len(qualified),
                    "n_qualified_exact_daily":sum(single(d.get("table_id",""),"day") for d in qualified),
                    "datasets":[{"id":d.get("id"),"dataset_id":d.get("dataset_id"),
                         "table_id":d.get("table_id"),"data_node":d.get("data_node"),
                         "version":d.get("version")} for d in qualified[:60]]})
            except Exception as exc:
                info["status"]="ESGF_API_UNAVAILABLE_OR_NONJSON"
                info["error"]=f"{type(exc).__name__}: {exc}"[:300]
            print("P93B1_ESGF_PROVIDER_QUERY",json.dumps({
                k:v for k,v in info.items() if k not in ("datasets",)}),flush=True)
            results.append(info)
    return results

def _native_monthly_pressure():
    import xarray as xr
    import gcsfs
    import numpy as np
    filesystem=gcsfs.GCSFileSystem(token="anon",access="read_only")
    mapper=filesystem.get_mapper(ORIGINAL_MONTHLY_ASSET)
    ds=xr.open_zarr(mapper,consolidated=True)
    try:
        for attr,val in (("source_id","CanESM5"),("experiment_id","historical"),("variant_label","r1i1p1f1")):
            if ds.attrs.get(attr)!=val:
                raise ValueError("P93B1_NATIVE_Amon_GCM_IDENTITY_"+attr)
        if ds.attrs.get("grid_label")!="gn":
            raise ValueError("P93B1_SOURCE_NOT_NATIVE_GRID_GN")
        if ds["ps"].attrs.get("units")!="Pa":
            raise ValueError("P93B1_PRESSURE_UNITS_NOT_PA")
        lat_name="lat" if "lat" in ds.coords else "latitude"
        lon_name="lon" if "lon" in ds.coords else "longitude"
        latitude=ds[lat_name].values; longitude=ds[lon_name].values
        if latitude.ndim!=1 or longitude.ndim!=1:
            raise ValueError("P93B1_EXPECTED_ORIGINAL_GCM_LAT_LON_1D_GRID")
        ilat=int(np.argmin(abs(latitude-GRAZ[0])))
        ilon=int(np.argmin(abs((longitude%360)-(GRAZ[1]%360))))
        latitude_value=float(latitude[ilat]);longitude_value=float(longitude[ilon])
        selected=ds["ps"].isel({lat_name:ilat,lon_name:ilon})
        raw=selected.sel(time=slice("2013-01-01","2014-12-31"))
        p=np.asarray(raw.values,dtype=float).ravel()
        time=raw.time.values
        if len(p)!=24 or not np.isfinite(p).all() or not np.all((p>60_000)&(p<110_000)):
            raise ValueError("P93B1_EXPECTED_24_ORIGINAL_NATIVE_Amon_MONTHLY_PRESSURES_INVALID")
        months=[str(t)[:7] for t in time]
        if months!=[f"{y}-{m:02d}" for y in (2013,2014) for m in range(1,13)]:
            raise ValueError("P93B1_ORIGINAL_CMIP6_MONTHLY_TIME_NOT_2013_2014")
        metadata={"source_asset":ORIGINAL_MONTHLY_ASSET,
          "CMIP6_trajectory":"native_GCM_historical_r1i1p1f1",
          "time_frequency":"Amon_MONTHLY_NOT_DAILY",
          "source_global_attrs":{k:ds.attrs.get(k) for k in
             ("activity_id","institution_id","source_id","experiment_id","variant_label","table_id",
              "grid_label","frequency","license","tracking_id","version","nominal_resolution")},
          "variable_attrs":{k:str(v) for k,v in ds["ps"].attrs.items() if k in
              ("units","standard_name","long_name","cell_methods","comment")},
          "native_nearest_grid_latlon":[latitude_value,longitude_value],
          "NEX_source_grid_latlon":list(BASE_GCM_GRID),"target_Graz_latlon":list(GRAZ),
          "n_original_coarse_native_months":len(p),
          "original_2013_2014_nearest_coarse_monthly_pressure_min_Pa":float(p.min()),
          "original_2013_2014_nearest_coarse_monthly_pressure_max_Pa":float(p.max()),
          "original_2013_2014_nearest_coarse_monthly_pressure_mean_Pa":float(p.mean()),
          "monthly_P_not_valid_for_native_daily_ps_data_claim":True}
        mapping=dict(zip(months,[float(x) for x in p]))
        print("P93B1_CANESM5_GENUINE_ORIGINAL_MONTHLY_PS",json.dumps({
           "grid_latlon":metadata["native_nearest_grid_latlon"],
           "n_months":24,"min_pressure_Pa":metadata["original_2013_2014_nearest_coarse_monthly_pressure_min_Pa"],
           "max_pressure_Pa":metadata["original_2013_2014_nearest_coarse_monthly_pressure_max_Pa"],
           "mean_pressure_Pa":metadata["original_2013_2014_nearest_coarse_monthly_pressure_mean_Pa"]}),flush=True)
        return mapping,metadata
    finally:
        ds.close()

def compare_nex_monthly(original_zip,month_ps):
    original,metadata=read_source(original_zip,"CanESM5",HIST)
    if metadata["daily_csv_sha256"]!=NASA_SHA:
        raise ValueError("P93B1_ORIGINAL_REGISTERED_NEX_DAILY_SHA_CHANGED")
    days=[r for r in original if r["date"].year in (2013,2014)]
    if len(days)!=730:raise ValueError("P93B1_EXPECTED_730_ORIGINAL_NEX_DAILY_ROWS")
    pairs=[]
    failed=set(BLOCKED_2013+BLOCKED_2014)
    for row in days:
        yyyy_mm=row["date"].strftime("%Y-%m")
        p=month_ps[yyyy_mm]
        t=row["tas_c"]
        q=row["huss"]
        e=e_of_q(q,p)
        rh_proxy=100*e/sat_pa(t)
        qsat_proxy=.62198*sat_pa(t)/(p-(1-.62198)*sat_pa(t))
        pairs.append({"date":row["date"].isoformat(),
          "calculated_NEX_daily_huss_as_RH_with_same_month_NATIVE_GCM_pressure":rh_proxy,
          "daily_hurs_NEX":row["hurs"],
          "daily_huss_exceeds_qsat_at_tas_and_MONTHLY_NATIVE_ps":q>qsat_proxy,
          "original_prior_P93A_blocked_day":row["date"].isoformat() in failed})
    grouped={}
    for y in (2013,2014):
        d=[x for x in pairs if x["date"].startswith(str(y))]
        grouped[str(y)]={"n_native_NEX_days":len(d),
            "n_daily_huss_above_proxy_saturation_at_daily_mean_tas_and_coarse_monthly_ps":
                sum(x["daily_huss_exceeds_qsat_at_tas_and_MONTHLY_NATIVE_ps"] for x in d),
            "mean_proxy_RH_minus_native_NEX_hurs_pp":statistics.fmean(
                 x["calculated_NEX_daily_huss_as_RH_with_same_month_NATIVE_GCM_pressure"]
                 -x["daily_hurs_NEX"] for x in d),
            "MAE_proxy_RH_vs_native_NEX_hurs_pp":statistics.fmean(
                abs(x["calculated_NEX_daily_huss_as_RH_with_same_month_NATIVE_GCM_pressure"]
                -x["daily_hurs_NEX"]) for x in d)}
    blocked=[{"date":x["date"],
       "NEX_daily_huss_above_qsat_at_daily_mean_T_and_coarse_monthly_ps":
              x["daily_huss_exceeds_qsat_at_tas_and_MONTHLY_NATIVE_ps"],
       "RH_proxy_minus_native_hurs_pp":
               x["calculated_NEX_daily_huss_as_RH_with_same_month_NATIVE_GCM_pressure"]-
               x["daily_hurs_NEX"]} for x in pairs if x["original_prior_P93A_blocked_day"]]
    return {"original_NEX_daily_SHA256":metadata["daily_csv_sha256"],
        "n_original_2013_2014_NEX_daily_comparisons":730,
        "matched_years_are_prior_DEVELOPMENT_years_not_independent_holdout":True,
        "pressure_is_COARSE_GCM_MONTHLY_NOT_DAILY_not_at_same_finegrid_surface":True,
        "daily_huss_vs_tas_sat_test_not_equivalent_to_joint_hourly_feasibility":True,
        "daily_nonlin_RH_proxy_not_equal_daily_mean_RH":True,
        "yearly_stats":grouped,"prior_source_P93A_2013_2014_failures_monthly_ps_sensitivity":blocked}

def run(out,original_nex_zip):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    result={"phase":"P9_3B1_ORIGINAL_NATIVE_CANESM5_PRESSURE_SOURCE_AND_NEX_CROSSVARIABLE",
        "native_day_ps_identified_from_original_ESGF":False,
        "native_day_ps_recovered":False,"coarse_native_monthly_Amon_ps_verified":False,
        "cannot_call_monthly_coarse_pressure_finegrid_NEX_daily_pressure":True,
        "pressure_source_ps_from_native_GCM_is_NOT_observed_station_pressure":True,
        "production_epw_ready":False}
    result["ESGF_independent_discovery"]=query_esgf()
    try:
        monthly,metadata=_native_monthly_pressure()
        result["coarse_native_monthly_Amon_ps_verified"]=True
        result["native_monthly_ps"]=metadata
        result["source_compare"]=compare_nex_monthly(original_nex_zip,monthly)
        result["status"]="ORIGINAL_CANESM5_Amon_MONTHLY_PS_RECOVERED_NATIVE_DAY_PS_UNRESOLVED"
    except Exception as e:
        result["monthly_source_blocker"]=f"{type(e).__name__}: {e}"[:750]
        result["status"]="SOURCE_COARSE_MONTHLY_PS_UNVERIFIED_OR_BLOCKED"
        print("P93B1_ORIGINAL_MONTHLY_SOURCE_FAILED",result["monthly_source_blocker"],flush=True)
    # Direct ESGF dataset discovery: metadata only, independent of Pangeo.
    qualified=[d for item in result["ESGF_independent_discovery"]
        for d in item.get("datasets",[])
        if d.get("table_id")=="day"]
    result["native_day_ps_identified_from_original_ESGF"]=bool(qualified)
    result["ESGF_qualified_other_ps_frequency_candidates"]=[
        {"endpoint":item["endpoint"],"dataset":d}
        for item in result["ESGF_independent_discovery"]
        for d in item.get("datasets",[]) if d.get("table_id")!="day"][:50]
    result["native_day_ps_recovered"]=False # no data read at daily frequency
    (out/"p9_3b1_original_pressure_provenance_and_crossvariable_diagnosis.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    print("P93B1_SOURCE_AUDIT_FINAL",json.dumps({
        "native_day_ps_ESGF_catalog_hits":len(qualified),
        "native_original_2013_2014_monthly_Amon_ps_proven":result["coarse_native_monthly_Amon_ps_verified"],
        "NEX_daily_source_comparisons":result.get("source_compare",{}).get("n_original_2013_2014_NEX_daily_comparisons",0),
        "source_status":result["status"],
        "daily_ps_qualified":result["native_day_ps_recovered"],
        "production":False}),flush=True)
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",default="outputs/p93b1-multisource")
    p.add_argument("--original-NEX-registered-archive",required=True)
    a=p.parse_args()
    run(a.out,a.original_NEX_registered_archive)
