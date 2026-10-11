#!/usr/bin/env python3
"""IGE P6.3E: NASA POWER hourly GHI–DNI–DHI closure and ARAD ground gate.

Research only. Quantifies a single gridded product's own solar component
consistency, NOT independent observed beam/diffuse skill. Original P6.3D
hourly GHI sources remain immutable. POWER hourly UTC timestamp = START
of the hour. Reconstruct solar zenith independently at mid-hour via
NOAA-style analytic position (approximation, no topographic horizon).
Use TOA shortwave to diagnose night/twilight, never to force agreement.

Independent ARAD Graz GHI/DNI/DHI/LW 1-minute measurements operated
since September 2011. Historical original ground-data access/quality
remains NOT VERIFIED or ACQUIRED: production EPW is unconditionally blocked.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math
from collections import Counter,defaultdict
from datetime import datetime,date,timedelta,timezone
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode

from p6_2d_solar_methods_benchmark import checksum,csvread
from p6_3c_precip_semantics_daily_alignment import save_union
from p6_3d_hourly_satellite_reference_validation import (
    SITES,PERIODS,BASE,http_json,energy_hourly_kwh,
    validate_power_response,PARAM as OLD_PARAMS,
)
COMPONENTS=("ALLSKY_SFC_SW_DNI","ALLSKY_SFC_SW_DIFF",
            "TOA_SW_DWN","CLRSKY_SFC_SW_DWN")
GHI="ALLSKY_SFC_SW_DWN"
MIN_COMPLETE_COVERAGE=.95
CLEAR_SKY_MARGIN_KWH=.10   # screen ONLY, not hard accept threshold
CLOSURE_ABSOLUTE_SCREEN_KWH=.10
CLOSURE_RELATIVE_SCREEN=.15
NIGHT_EXCEEDANCE_KWH=.03
NOAA_DEEP_NIGHT_COS=-.05
SOLAR_TWILIGHT_COS=.05
ARAD_EVIDENCE={
    "name":"ARAD Graz Universität",
    "provider":"University of Graz/GeoSphere Austria",
    "starting_date":"2011-09",
    "measured_components":["GHI","DNI","DHI","downwelling_LW"],
    "sampling":"1 minute original; original source QC required",
    "access":"IDENTIFIED_NOT_ACQUIRED_NOT_LICENSE_OR_QC_VERIFIED",
    "contact":"messung.physik@uni-graz.at",
    "original_provider_page":"https://climatephysics.uni-graz.at/en/meteorological-station/",
    "official_GCOS_report":"https://www.gcos.at/reports/Austrian_GCOS_Report_2025.pdf",
    "historical_overlap_with_P6_3D":"September 2011–December 2014 (data completeness still unknown)",
    "forbidden_inference":"ARAD data existence alone does NOT imply approved historical 1-minute downloads or equivalence with station #30 hourly q21=0 records",
}

def solar_cos_zenith(utc_hour_start,latitude,longitude):
    """NOAA fractional-year position at UTC mid-hour; screening precision ONLY."""
    if utc_hour_start.tzinfo is None or utc_hour_start.utcoffset()!=timedelta(0):
        raise ValueError("Solar geometry requires timezone-aware UTC hour start")
    midpoint=utc_hour_start+timedelta(minutes=30)
    doy=midpoint.timetuple().tm_yday
    hour=midpoint.hour+midpoint.minute/60
    days=366 if (midpoint.year%4==0 and (midpoint.year%100!=0 or midpoint.year%400==0)) else 365
    gamma=2*math.pi/days*(doy-1+(hour-12)/24)
    eqtime=229.18*(.000075+.001868*math.cos(gamma)-.032077*math.sin(gamma)
            -.014615*math.cos(2*gamma)-.040849*math.sin(2*gamma))
    decl=(.006918-.399912*math.cos(gamma)+.070257*math.sin(gamma)
          -.006758*math.cos(2*gamma)+.000907*math.sin(2*gamma)
          -.002697*math.cos(3*gamma)+.00148*math.sin(3*gamma))
    solar_minutes=hour*60+eqtime+4*longitude
    ha=math.radians((solar_minutes/4.-180.)%360.)
    if ha>math.pi:ha-=2*math.pi
    lat=math.radians(latitude)
    coszen=math.sin(lat)*math.sin(decl)+math.cos(lat)*math.cos(decl)*math.cos(ha)
    return max(-1.,min(1.,coszen))

def component_contract(payload,site,first,last):
    """Source-verified original companion solar fields with immutable UTC keys."""
    header=payload.get("header",{})
    if header.get("time_standard")!="UTC" or \
       header.get("start")!=f"{first}1231" or \
       header.get("end")!=f"{last}1231":
        raise ValueError("POWER companion parameter UTC/start/end identity drift")
    units=payload.get("parameters",{})
    fields=payload.get("properties",{}).get("parameter",{})
    if not set(COMPONENTS)<=set(units) or not set(COMPONENTS)<=set(fields):
        raise ValueError("Original POWER companion DNI DHI TOA clear-sky fields absent")
    coords=payload.get("geometry",{}).get("coordinates")
    if not coords or abs(float(coords[0])-site["longitude"])>1 or \
       abs(float(coords[1])-site["latitude"])>1:
        raise ValueError("POWER original companion query coordinates invalid")
    expected_start=date(first,12,31)
    dates=(date(last,12,31)-expected_start).days+1
    target={((expected_start+timedelta(days=i)).strftime("%Y%m%d")+f"{hour:02d}")
            for i in range(dates) for hour in range(24)}
    if any(set(fields[f])!=target for f in COMPONENTS):
        raise ValueError("POWER companion source hourly calendar incomplete")
    fill=float(header.get("fill_value",-999.))
    records={};missing=Counter()
    for stamp in sorted(target):
        row={}
        for param in COMPONENTS:
            unit=units[param].get("units")
            value=fields[param][stamp]
            if value is None or float(value)==fill:
                row[param]=None;missing[param]+=1
            else:
                row[param]=energy_hourly_kwh(float(value),unit)
        records[stamp]=row
    return records,{"units":{p:units[p]["units"] for p in COMPONENTS},
                    "utc_hour_count":len(records),"missing_by_field":dict(missing),
                    "sources":header.get("sources"),"location":coords,
                    "header":header}

def ground_original(blocks,site):
    """Load and verify P6.3D archived NASA POWER GHI, no new GHI retrieval."""
    whole={};checks=[]
    for first,last in PERIODS:
        name=f"power_hourly_original_{site}_{first}1231_{last}1231.json"
        source=blocks/name
        if not source.is_file():raise FileNotFoundError(name)
        payload=json.loads(source.read_bytes())
        rows,metadata=validate_power_response(payload,SITES[site],first,last)
        for k,rec in rows.items():
            if k in whole and rec!=whole[k]:
                raise ValueError("Frozen original POWER GHI hour overlap mismatch")
            whole[k]=rec
        checks.append({"site":site,"window":f"{first}1231_{last}1231",
                       "original_ghi_path":name,
                       "original_ghi_sha256":checksum(source),
                       "missing_hours":metadata["hourly_missing"],
                       "source_header":metadata["source_header"]})
    return whole,checks

def get_companion(site,out):
    allhour={};checks=[]
    place=SITES[site]
    for first,last in PERIODS:
        url=BASE+"?"+urlencode({
          "parameters":",".join(COMPONENTS),"community":"RE",
          "latitude":place["latitude"],"longitude":place["longitude"],
          "start":f"{first}1231","end":f"{last}1231",
          "format":"JSON","time-standard":"UTC"})
        raw,payload=http_json(url,limit=30000000)
        dest=out/f"power_components_{site}_{first}1231_{last}1231_original.json"
        dest.write_bytes(raw)
        rows,metadata=component_contract(payload,place,first,last)
        for key,r in rows.items():
            if key in allhour and allhour[key]!=r:
                raise ValueError("Overlapping NASA POWER DNI/DHI values changed")
            allhour[key]=r
        checks.append({"site":site,"years":f"{first}–{last}",
          "original_components_sha256":hashlib.sha256(raw).hexdigest(),
          "file_name":dest.name,"original_request":url,**metadata})
        print("P6.3E SOURCE",site,first,last,
              "UTC hours",len(rows),"source missing",metadata["missing_by_field"],
              flush=True)
    return allhour,checks

def classify_hour(original,components,latitude,longitude,stamp):
    expected=set(COMPONENTS)
    if not expected<=set(components):
        raise ValueError("Solar companion missing physical components")
    when=datetime.strptime(stamp,"%Y%m%d%H").replace(tzinfo=timezone.utc)
    cz=solar_cos_zenith(when,latitude,longitude)
    ghi=original["ghi_hour_kwh_m2"]
    if ghi is None or any(components[p] is None for p in COMPONENTS):
        return {"timestamp_utc_start":when.isoformat(),"solar_coszen_noaa_midpoint":cz,
                "valid":False}
    dni=components[COMPONENTS[0]]
    dhi=components[COMPONENTS[1]]
    toa=components[COMPONENTS[2]]
    clear=components[COMPONENTS[3]]
    # DNI measured on normal plane. Use independent solar zenith
    # at hourly midpoint, so GHI~=DHI+DNI*cosz only approx for
    # hourly means, especially changing solar elevation near sunrise.
    reconstructed=dhi+dni*max(0.,cz)
    error=ghi-reconstructed
    daytime=cz>SOLAR_TWILIGHT_COS
    night=cz<NOAA_DEEP_NIGHT_COS and toa<.001
    toa_exceeded=ghi>toa+max(.03,.10*toa) and cz>.10
    clear_exceeded=ghi>clear+CLEAR_SKY_MARGIN_KWH and cz>.10
    closure_screen=abs(error)>max(CLOSURE_ABSOLUTE_SCREEN_KWH,
                                  CLOSURE_RELATIVE_SCREEN*max(ghi,.05))
    return {"timestamp_utc_start":when.isoformat(),
        "year":when.year,"month":when.month,"hour_utc":when.hour,
        "solar_coszen_noaa_midpoint":cz,"valid":True,
        "GHI_kwh_m2_hour":ghi,"DNI_kwh_m2_hour":dni,
        "DHI_kwh_m2_hour":dhi,"TOA_kwh_m2_hour":toa,
        "clear_sky_GHI_kwh_m2_hour":clear,
        "reconstructed_GHI_DNIcosZ_plus_DHI_kwh_m2_hour":reconstructed,
        "closure_signed_residual_kwh_m2_hour":error,
        "closure_absolute_residual_kwh_m2_hour":abs(error),
        "is_deep_night_from_NOAA_and_POWER_TOA":night,
        "is_daylight_NOAA":daytime,
        "nighttime_positive_GHI_gt_0p03":night and ghi>NIGHT_EXCEEDANCE_KWH,
        "DHI_greater_than_GHI_gt_0p03":dhi>ghi+.03,
        "GHI_greater_than_TOA_screen":toa_exceeded,
        "GHI_greater_than_clear_sky_screen":clear_exceeded,
        "hourly_component_closure_review":daytime and closure_screen,
        "DNI_exceeds_1p5_kWh":dni>1.5,
        "is_satellite_not_observed_ground":True}

def season_stats(rows,site):
    result=[]
    seasons={"ANNUAL":set(range(1,13)),"DJF":{12,1,2},
             "MAM":{3,4,5},"JJA":{6,7,8},"SON":{9,10,11}}
    for name,months in seasons.items():
        period=[r for r in rows if r["month"] in months]
        good=[r for r in period if r["valid"]]
        daysun=[r for r in good if r["is_daylight_NOAA"]]
        nighttime=[r for r in good if r["is_deep_night_from_NOAA_and_POWER_TOA"]]
        if len(period)==0:raise ValueError("No original season hours")
        coverage=len(good)/len(period)
        vals=[r["closure_absolute_residual_kwh_m2_hour"] for r in daysun]
        signed=[r["closure_signed_residual_kwh_m2_hour"] for r in daysun]
        result.append({"site":site,"season":name,"source":"NASA_POWER_CERES_GRID",
            "original_hours":len(period),"valid_all_component_hours":len(good),
            "coverage_fraction":coverage,
            "daytime_hours":len(daysun),
            "nighttime_hours":len(nighttime),
            "daylight_GHI_mean_kwh_m2_hour":fmean(r["GHI_kwh_m2_hour"] for r in daysun)
                          if daysun else None,
            "daytime_DNI_mean_kwh_m2_hour":fmean(r["DNI_kwh_m2_hour"] for r in daysun)
                          if daysun else None,
            "daytime_DHI_mean_kwh_m2_hour":fmean(r["DHI_kwh_m2_hour"] for r in daysun)
                          if daysun else None,
            "daylight_component_closure_MAE_kwh_m2_hour":fmean(vals) if vals else None,
            "daylight_component_closure_bias_kwh_m2_hour":fmean(signed) if signed else None,
            "daylight_component_closure_review_count":
                sum(bool(r["hourly_component_closure_review"]) for r in daysun),
            "nighttime_GHI_gt_0p03_hour_count":
                sum(bool(r["nighttime_positive_GHI_gt_0p03"]) for r in nighttime),
            "daylight_DHI_gt_GHI_hour_count":
                sum(bool(r["DHI_greater_than_GHI_gt_0p03"]) for r in daysun),
            "daylight_GHI_gt_TOA_screen_count":
                sum(bool(r["GHI_greater_than_TOA_screen"]) for r in daysun),
            "daylight_GHI_gt_clear_sky_screen_count":
                sum(bool(r["GHI_greater_than_clear_sky_screen"]) for r in daysun),
            "solar_source_type":"GRIDDDED_NOT_OBSERVED",
            "scientific_status":"SOURCE_QC_INCOMPLETE" if coverage<MIN_COMPLETE_COVERAGE
                      else "DIAGNOSTIC_SCREEN_ONLY_NOT_CERTIFIED_HOURLY_GROUND"})
    return result

def run(p6d_frozen,out):
    out.mkdir(parents=True,exist_ok=True)
    results=[];summary=[];provenance=[];base_sources=[];source_counts={}
    for site in SITES:
        original,rawchecks=ground_original(p6d_frozen,site)
        parts,partchecks=get_companion(site,out)
        if set(parts)!=set(original):
            raise ValueError("Mismatch between immutable GHI and new companion UTC source keys")
        provenance.extend(partchecks)
        base_sources.extend(rawchecks)
        temporal=[]
        for stamp in sorted(original):
            when=datetime.strptime(stamp,"%Y%m%d%H").replace(tzinfo=timezone.utc)
            if not datetime(2005,1,1,tzinfo=timezone.utc)<=when<datetime(2015,1,1,tzinfo=timezone.utc):
                continue
            r=classify_hour(original[stamp],parts[stamp],
                SITES[site]["latitude"],SITES[site]["longitude"],stamp)
            r["site"]=site
            temporal.append(r)
        if len(temporal)!=87648:raise ValueError("Original ten-year UTC hourly sample missing")
        results.extend(temporal)
        summary.extend(season_stats(temporal,site))
        source_counts[site]=sum(r["valid"] for r in temporal)
        print("P6.3E CALC",site,"valid",source_counts[site],
              "year10 hours",len(temporal),flush=True)
    if len(results)!=2*87648 or len(summary)!=2*5:
        raise ValueError("Unexpected 2-site × ten-year solar closure cardinality")
    datasets={
       "p6_3e_native_hourly_ghi_dni_dhi_toa_physical_diagnostics.csv":results,
       "p6_3e_solar_component_seasonal_screen_summary.csv":summary,
       "p6_3e_original_power_component_source_sha_provenance.csv":provenance,
       "p6_3e_immutable_p6d_source_sha_provenance.csv":base_sources}
    hashes={name:save_union(out/name,rows) for name,rows in datasets.items()}
    if any(s["coverage_fraction"]<MIN_COMPLETE_COVERAGE for s in summary):
        technical="INSUFFICIENT_COMPONENT_SOURCE_COVERAGE"
    else:
        technical="PASS_NATIVE_UTC_SOURCE_SOLAR_COMPONENT_DIAGNOSTICS"
    report={
      "stage":"IGE_P6_3E_HOURLY_SOLAR_GHI_DNI_DHI_NIGHT_AND_ARAD_ACCESS",
      "technical_status":technical,
      "scientific_status":"ARAD_GRAZ_ORIGINAL_GROUND_DATA_NOT_YET_ACQUIRED",
      "production_epw_ready":False,
      "ground_data_candidate":ARAD_EVIDENCE,
      "spatial_points":SITES,
      "source_type":"NASA POWER hourly SYN1deg CERES satellite/reanalysis; DNI/DHI internal source consistency only",
      "reused_immutable_p6_3d_hourly_GHI":True,
      "solar_position_method":"NOAA approximated hour-midpoint independent UTC sun position, not measured site horizon",
      "source_native_calendar":"UTC hourly start; 2005-2014 after 2004-12-31 buffer preserved",
      "closure_formula":"GHI ~= DHI + DNI * max(0, cos(zenith at hourly midpoint))",
      "component_uncertainty_note":"POWER DNI and DHI have source-specific corrections; decomposition differences need not be data corruption; near sunrise/sunset midpoint geometry may be inaccurate.",
      "screen_thresholds":{
          "nighttime_positive_GHI_kwh_m2_hour":NIGHT_EXCEEDANCE_KWH,
          "daytime_component_closure_abs_kwh_m2_hour":CLOSURE_ABSOLUTE_SCREEN_KWH,
          "daytime_component_closure_relative":CLOSURE_RELATIVE_SCREEN,
          "clear_sky_screen_margin_kwh_m2_hour":CLEAR_SKY_MARGIN_KWH},
      "source_period_UTC":"2005–2014 for each two preselected locations",
      "source_derived_valid_hours_per_site":source_counts,
      "seasonal_solar_decomposition":summary,
      "output_file_sha256":hashes,
      "scientific_gates":[
        "NASA POWER GHI/DNI/DHI source-internal radiation closure does not prove any single component against independent measured solar radiation.",
        "ARAD Graz University has original 1-minute observed GHI/DNI/DHI/LW since Sept 2011; must obtain quality-flagged original data, temporal coverage and usage rights before ground-based verification.",
        "Graz ARAD high-precision source and Graz GeoSphere daily station reference may refer to adjacent sensors; source and independence must be documented.",
        "No q21-approved hourly GeoSphere source was available in 2005–2014 from P6.3D.",
        "Night and TOA screens here are diagnostic, not authoritative acceptance thresholds; independent NOAA approximation neglects horizons/refraction and hour-average zenith.",
        "Do not certify 2005–2011 independently with ARAD Graz if station began Sept 2011.",
        "No direct/diffuse generation or future EPW integration in P6.3E, and production main unchanged."]
    }
    (out/"p6_3e_hourly_solar_components_arad_science_audit.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("P6.3E",technical,"hourly",len(results),
          "ARAD",ARAD_EVIDENCE["access"],"EPW_READY",report["production_epw_ready"],flush=True)
    return report

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--p6d-frozen",type=Path,required=True)
    a.add_argument("--out",type=Path,required=True)
    args=a.parse_args()
    run(args.p6d_frozen,args.out)
