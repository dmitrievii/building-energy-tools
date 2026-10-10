#!/usr/bin/env python3
"""IGE P6.2B solar bias root-cause discrimination (NO correction).

Independent evidence: accepted GeoSphere station #30 1995–2014,
NASA NEX-GDDP-CMIP6 v2.0 8-model source historical monthly rsds,
EU JRC PVGIS ERA5/SARAH3, and NASA POWER CERES historical solar radiation.

Matched period 2005–2014; compare annual/global-horizontal irradiation and
monthly seasonal profiles on both station and NASA cell coordinates.
No model-year station-day matching and no assumption GMFD has been validated.
"""
from __future__ import annotations
import argparse, calendar,csv,hashlib,json,math,time
from collections import defaultdict
from pathlib import Path
from statistics import fmean,median
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import URLError,HTTPError

from p6_2a_eight_model_ensemble import MODELS,original_quality

START,END=2005,2014
SITE=(47.08,15.448056)
CELL=(46.875,15.375)
HIST="historical-1995-2014"
REPAIR={"EC-Earth3","IPSL-CM6A-LR","MPI-ESM1-2-HR"}
def sha(b):return hashlib.sha256(b).hexdigest()

def get(url,limit=3000000):
    errors=[]
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={
                "User-Agent":"IGE-P6.2B-Independent-GHI-Reference-QA",
                "Accept":"application/json",
            }),timeout=100) as response:
                blob=response.read(limit+1)
                if response.status!=200 or len(blob)>limit:
                    raise ValueError("Unexpected HTTP source or response size")
                return blob,json.loads(blob)
        except (HTTPError,URLError,OSError,TimeoutError) as e:
            errors.append(str(e))
            if isinstance(e,HTTPError) and e.code in (400,401,403,404,422):break
            if attempt<2:time.sleep(2**attempt)
    raise RuntimeError(f"External solar source unavailable: {url} / {errors}")

def observed_station(path):
    rows=list(csv.DictReader(Path(path).open(encoding="utf8",newline="")))
    if len(rows)!=7305:raise ValueError("Station solar reference must contain 7305 days")
    mapping=defaultdict(list);dates=set()
    for row in rows:
        year=int(row["year"]);month=int(row["month"])
        stamp=row["date_geo_moz_utc_label"]
        if stamp in dates:raise ValueError("Duplicate GeoSphere date")
        dates.add(stamp)
        if START<=year<=END:
            value=row["trusted_daily_kwh_m2"]
            if value in ("",None):
                raise ValueError("Reference station solar QC missing within 2005–2014")
            if int(row["q21"]) not in (10,11,12,20,21,22):
                raise ValueError("Unverified station GHI was promoted to accepted")
            mapping[(year,month)].append(float(value))
    if len(mapping)!=120 or any(len(mapping[(y,m)])!=calendar.monthrange(y,m)[1]
             for y in range(START,END+1) for m in range(1,13)):
        raise ValueError("Incomplete station reference monthly coverage")
    return {(y,m):sum(values) for (y,m),values in mapping.items()}

def load_gcm(access,original,repaired):
    models={}
    for name in MODELS:
        if name=="ACCESS-CM2":folder=access/"ige-p6-access-historical-1995-2014"
        elif name in REPAIR:folder=repaired/f"ige-p6-{name}-{HIST}"
        else:folder=original/f"ige-p6-{name}-{HIST}"
        quality,prov,hashes,days=original_quality(folder,name,HIST)
        with (folder/"model_monthly.csv").open(encoding="utf8",newline="") as f:
            rows=list(csv.DictReader(f))
        if len(rows)!=240:raise ValueError(f"Missing monthly model data {name}")
        series={}
        for row in rows:
            y,m=int(row["year"]),int(row["month"])
            if row["scenario"]!="historical" or row["window"]!=HIST or (y,m) in series:
                raise ValueError("Bad source model chronology")
            energy=float(row["ghi_kwh_m2"])
            if not math.isfinite(energy) or energy<0:
                raise ValueError("Unphysical original model GHI")
            if START<=y<=END:series[y,m]=energy
        if len(series)!=120:raise ValueError("Ten-year model source incomplete")
        models[name]={"series":series,"grid":quality["grid"],"calendar":quality["calendar"],
                     "sha256":hashes["model_monthly.csv"]}
    return models

def parse_pvgis(doc):
    inputs=doc.get("inputs",{})
    source=inputs.get("meteo_data",{}).get("radiation_db")
    rows=doc.get("outputs",{}).get("monthly",[])
    if not isinstance(rows,list):raise ValueError("PVGIS monthly source schema changed")
    dates={}
    for r in rows:
        year,month=int(r["year"]),int(r["month"])
        if not START<=year<=END:continue
        if (year,month) in dates:raise ValueError("Duplicate PVGIS months")
        value=float(r["H(h)_m"])
        if not math.isfinite(value) or not 0<=value<=400:
            raise ValueError("Incorrect PVGIS monthly horizontal irradiation unit/value")
        dates[year,month]=value
    if len(dates)!=120:raise ValueError(f"PVGIS missing monthly radiation {len(dates)}")
    return source,dates

def parse_power(doc):
    meta=doc.get("parameters",{})
    units=meta.get("ALLSKY_SFC_SW_DWN",{}).get("units",None)
    if units is None:
        units=doc.get("header",{}).get("parameter_information",{}).get(
            "ALLSKY_SFC_SW_DWN",{}).get("units")
    # POWER solar monthly API reports monthly average of *daily* kWh/m²/d.
    # No unit guessing: accept explicit documented unit spelling only.
    if units is None or not any(t in str(units).lower().replace(" ","")
                                for t in ("kwh/m", "kw-hr/m")) or "day" not in str(units).lower():
        raise ValueError(f"NASA POWER solar monthly unit missing/changed: {units}")
    raw=doc.get("properties",{}).get("parameter",{}).get("ALLSKY_SFC_SW_DWN")
    if not isinstance(raw,dict):raise ValueError("NASA POWER missing output")
    entries={}
    for k,val in raw.items():
        if len(k)!=6 or not k.isdigit():continue
        year,month=int(k[:4]),int(k[4:])
        if not START<=year<=END:continue
        # POWER monthly endpoint also returns YYYY13 = annual climatology.
        # It is NOT a thirteenth month: never pass it to monthrange() or
        # include it in the 120 real-calendar-month comparison.
        if month==13:continue
        if not 1<=month<=12:
            raise ValueError(f"NASA POWER unexpected non-calendar month {month}")
        if (year,month) in entries:raise ValueError("Duplicate NASA POWER month")
        daily=float(val)
        if not math.isfinite(daily) or not 0<=daily<16:raise ValueError("Invalid POWER daily mean")
        entries[year,month]=daily*calendar.monthrange(year,month)[1]
    if len(entries)!=120:raise ValueError("NASA POWER 120 matched monthly records missing")
    return entries,str(units)

def pv_request(lat,lon,db):
    return "https://re.jrc.ec.europa.eu/api/v5_3/MRcalc?"+urlencode({
        "lat":lat,"lon":lon,"horirrad":1,"raddatabase":db,
        "startyear":START,"endyear":END,"usehorizon":0,"outputformat":"json"})

def power_request(lat,lon):
    return "https://power.larc.nasa.gov/api/temporal/monthly/point?"+urlencode({
        "parameters":"ALLSKY_SFC_SW_DWN","community":"RE",
        "latitude":lat,"longitude":lon,
        "start":START,"end":END,"format":"JSON"})

def statistics(series):
    return {"mean_annual_kwh_m2":fmean(
        sum(series[y,m] for m in range(1,13)) for y in range(START,END+1)),
        "monthly_climatology_kwh_m2":[fmean(series[y,m] for y in range(START,END+1))
                                   for m in range(1,13)]}

def execute(station_csv,access,original,repaired,out):
    out.mkdir(parents=True,exist_ok=True)
    station=observed_station(station_csv)
    model=load_gcm(access,original,repaired)
    sources={"geosphere_station30":{"series":station,"site":list(SITE),"units":"kWh/m²/month",
                                     "metadata":"raw GeoSphere calibrated cglo_j /360 with 20"},
             **{f"nex_gddp_{k}":{"series":v["series"],"site":v["grid"],"units":"kWh/m²/month",
                                "p6_1_raw_model_monthly_sha256":v["sha256"]}
                for k,v in model.items()}}
    external={}
    for label,coordinate in (("station",SITE),("nasa_cell",CELL)):
        for db in ("PVGIS-ERA5","PVGIS-SARAH3"):
            url=pv_request(*coordinate,db)
            try:
                raw,doc=get(url)
                actual,series=parse_pvgis(doc)
                key=f"pvgis_{db}_{label}"
                sources[key]={"series":series,"site":list(coordinate),
                              "units":"kWh/m²/month","source_radiation_db":actual}
                (out/f"{key}.json").write_bytes(raw)
                external[key]={"url":url,"sha256":sha(raw),"status":"PASS",
                               "reported_db":actual}
                print("EXTERNAL SOLAR",key,"PASS",round(statistics(series)["mean_annual_kwh_m2"],1),flush=True)
            except (RuntimeError,ValueError,KeyError) as ex:
                external[f"pvgis_{db}_{label}"]={"url":url,"status":"UNAVAILABLE",
                                                 "error":str(ex)}
                print("EXTERNAL SOLAR",db,label,"UNAVAILABLE",str(ex)[:150],flush=True)
        url=power_request(*coordinate)
        try:
            raw,doc=get(url)
            series,unit=parse_power(doc)
            key=f"nasa_power_{label}"
            sources[key]={"series":series,"site":list(coordinate),"units":unit,
                          "provider_header":doc.get("header",{})}
            (out/f"{key}.json").write_bytes(raw)
            external[key]={"url":url,"sha256":sha(raw),"status":"PASS","unit":unit}
            print("EXTERNAL SOLAR",key,"PASS",round(statistics(series)["mean_annual_kwh_m2"],1),flush=True)
        except (RuntimeError,ValueError,KeyError) as ex:
            external[f"nasa_power_{label}"]={"url":url,"status":"UNAVAILABLE",
                                            "error":str(ex)}
            print("EXTERNAL SOLAR",label,"UNAVAILABLE",str(ex)[:150],flush=True)
    def stats(name,value):
        s=statistics(value["series"])
        return {"name":name,"site":value.get("site"),"annual_kwh_m2":s["mean_annual_kwh_m2"],
                "delta_geosphere_kwh_m2":s["mean_annual_kwh_m2"]-statistics(station)["mean_annual_kwh_m2"],
                "delta_geosphere_percent":100*(s["mean_annual_kwh_m2"]/statistics(station)["mean_annual_kwh_m2"]-1),
                "months_kwh_m2":s["monthly_climatology_kwh_m2"]}
    aggregate=[stats(name,value) for name,value in sources.items()]
    (out/"source_annual_and_monthly_audit.json").write_text(
        json.dumps(aggregate,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    station_yr=statistics(station)["mean_annual_kwh_m2"]
    gcm_years=[statistics(v["series"])["mean_annual_kwh_m2"] for v in model.values()]
    validated=[v for k,v in external.items() if v["status"]=="PASS"]
    report={
        "status":"PASS_CROSSSOURCE_TRIANGULATION" if len(validated)>=3 else
                 "PARTIAL_INDEPENDENT_TRIANGULATION",
        "stage":"P6.2B_SCIENTIFIC_SOLAR_ROOT_CAUSE",
        "period":"2005-2014",
        "station_graz_kwh_m2_year":station_yr,
        "median_of_eight_nex_gddp_models_kwh_m2_year":median(gcm_years),
        "all_eight_nex_gddp_values_kwh_m2_year":dict(zip(model,gcm_years)),
        "intercomparison":aggregate,"external":external,
        "diagnostic_logic":{
            "NASA_common_reference_dataset":"GMFD/PGF 0.25 degree climatology 1960-2014 through BCSD",
            "input_conversion":"rsds W/m² daily mean * 0.024 kWh/m²/day is correct",
            "station_conversion":"cglo_j J/cm² daily sum /360 kWh/m²/day is correct",
            "shared_bias_cause":"a COMMON solar reference/grid processing issue is suggested when 8 model means cluster",
            "what_can_confirm_GMFD_as_root":"independent extraction of original GMFD rsds at 46.875N 15.375E, 2005-2014",
            "site_vs_grid_check":"PVGIS / POWER at both station and NASA coordinates show whether ~20km distance can explain amplitude",
            "not_permissible":"automatically scale all future rsds by 0.76 without independent historical validation, holdout or change-signal preservation",
        },
        "cautions":[
            "PVGIS-ERA5 and PVGIS-SARAH3 have overlapping model/satellite source uncertainty and are not pure independent station observations.",
            "NASA POWER pre-2001 SRB vs post-2001 CERES transition avoided by selecting 2005-2014.",
            "NASA historical simulated weather is not synchronized day-for-day with station observations.",
            "Site may have terrain obstruction; neither gridded product uses the same local station sensing geometry.",
            "Source provenance of NASA GMFD not yet directly independently fetched.",
        ]}
    (out/"solar_discrepancy_root_cause_report.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("ROOT-CAUSE INTERCOMPARISON",report["status"],
          "station",round(station_yr,1),"median NASA",round(median(gcm_years),1),
          "external successful",len(validated),flush=True)
    return report

def main():
    p=argparse.ArgumentParser()
    for key in ("station-csv","access","original","repaired","out"):
        p.add_argument("--"+key,type=Path,required=True)
    a=p.parse_args()
    execute(a.station_csv,a.access,a.original,a.repaired,a.out)

if __name__=="__main__":main()
