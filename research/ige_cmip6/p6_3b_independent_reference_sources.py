#!/usr/bin/env python3
"""IGE P6.3B independent daily *reference* provenance, 2005–2014.

GeoSphere #30 OBSERVED station data have independently QC-flagged daily
temperature, humidity, precipitation and wind. The accepted earlier
GeoSphere cglo_j solar measurements are joined by DATE LABEL ONLY.
Different station variables have unequal daily integration windows
(e.g. solar 23–23 UTC; precipitation 06–06 UTC next day). Thus daily
dependence estimates are only approximate, not synchronous flux closure.

NASA POWER is an INDEPENDENT GRIDDED SATELLITE/REANALYSIS PRODUCT, not
a station observation nor guaranteed statistically independent of ERA5.
All downloaded provider responses are archived with SHA256 and metadata.
"""
from __future__ import annotations
import calendar,csv,hashlib,json,math,time
from collections import Counter,defaultdict
from datetime import date,timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

from p6_2d_solar_methods_benchmark import csvread,csvwrite,checksum

GEO="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1d"
POWER="https://power.larc.nasa.gov/api/temporal/daily/point"
STATION=30
STATION_SPECS={"tl_mittel":("°C","temperature_air_c",(-65.,65.)),
               "rf_mittel":("%","relative_humidity_pct",(0.,105.)),
               "rr":("mm","precipitation_mm_day",(0.,300.)),
               "vv_mittel":("m/s","wind_speed_m_s",(0.,110.))}
QC_GOOD={10,11,12,20,21,22}
START=2005
END=2014
POWER_PARAMS=("T2M","RH2M","PRECTOTCORR","WS2M",
              "ALLSKY_SFC_SW_DWN","ALLSKY_SFC_LW_DWN")
POWER_LAT=46.875
POWER_LON=15.375

def days(first,last):
    d=date(first,1,1);end=date(last,12,31)
    while d<=end:
        yield d
        d+=timedelta(days=1)

def fetch(url,maximum=18000000):
    errors=[]
    for n in range(3):
        try:
            with urlopen(Request(url,headers={
                    "Accept":"application/json",
                    "User-Agent":"IGE-P6.3B-independent-climate-validation-2026"}),
                    timeout=115) as response:
                raw=response.read(maximum+1)
                if response.status!=200 or len(raw)>maximum:
                    raise RuntimeError("Unexpected response code or oversized source")
                return raw,json.loads(raw)
        except (HTTPError,URLError,OSError,TimeoutError,ValueError) as exc:
            errors.append(str(exc))
            if isinstance(exc,HTTPError) and exc.code in (400,401,403,404,422):
                break
            if n<2:time.sleep(2**n)
    raise RuntimeError("External provider could not be validated: "+url+" "+str(errors))

def validate_metadata(meta):
    specs={p["name"]:p for p in meta.get("parameters",[])}
    expected={s for key in STATION_SPECS for s in (key,key+"_flag")}
    if not expected<=set(specs):
        raise ValueError("Official GeoSphere daily reference missing required parameters "
                         +str(sorted(expected-set(specs))))
    for field,(unit,_,_) in STATION_SPECS.items():
        if specs[field].get("unit")!=unit:
            raise ValueError(f"GeoSphere official unit changed: {field} {specs[field].get('unit')}")
    stations={int(st["id"]):st for st in meta.get("stations",[])}
    if STATION not in stations:raise ValueError("Station #30 no longer in official metadata")
    return specs,stations[STATION]

def geosphere_block(meta,source,first,last):
    expected=list(days(first,last))
    if len(source.get("timestamps",[]))!=len(expected):
        raise ValueError("GeoSphere official day coverage incomplete")
    for stamp,d in zip(source["timestamps"],expected):
        if stamp[:10]!=d.isoformat() or not stamp.endswith(("Z","+00:00")):
            raise ValueError("GeoSphere source UTC label mismatch")
    features=source.get("features",[])
    if len(features)!=1:raise ValueError("Expected exactly station #30")
    f=features[0]["properties"]
    station=f.get("station")
    station=int(station if not isinstance(station,dict) else station["id"])
    if station!=STATION:raise ValueError("Wrong station selected")
    provider=f.get("parameters",{})
    for k,(unit,_,_) in STATION_SPECS.items():
        if k not in provider or k+"_flag" not in provider:
            raise ValueError(f"GeoSphere station lacks source parameter/flag {k}")
        if provider[k].get("unit")!=unit:
            raise ValueError(f"Source unit mismatch {k}")
        if len(provider[k].get("data",[]))!=len(expected) or \
           len(provider[k+"_flag"].get("data",[]))!=len(expected):
            raise ValueError(f"Missing daily GeoSphere source vectors {k}")
    out=[];qa=defaultdict(Counter)
    for i,d in enumerate(expected):
        row={"date":d.isoformat(),"year":d.year,"month":d.month,"day":d.day}
        for key,(_,target,(lo,hi)) in STATION_SPECS.items():
            raw=provider[key]["data"][i]
            flag=provider[key+"_flag"]["data"][i]
            if raw is not None:
                raw=float(raw)
                if not math.isfinite(raw):raise ValueError(f"Nonfinite observation {key}")
            if flag is not None:flag=int(flag)
            accepted=(raw is not None and flag in QC_GOOD and lo<=raw<=hi)
            row[target]=raw if accepted else None
            row[target+"_raw"]=raw
            row[target+"_q21"]=flag
            qa[key]["accepted" if accepted else "not_accepted"]+=1
            qa[key]["q21_"+str(flag)]+=1
        out.append(row)
    return out,{k:dict(v) for k,v in qa.items()}

def acquire_geosphere(out,station_solar):
    out.mkdir(parents=True,exist_ok=True)
    meta_bytes,meta=fetch(GEO+"/metadata",8000000)
    specs,station=validate_metadata(meta)
    (out/"geosphere_station30_daily_metadata_original.json").write_bytes(meta_bytes)
    blocks=[];provenance=[]
    params=",".join(s for name in STATION_SPECS for s in (name,name+"_flag"))
    for first,last in ((2005,2009),(2010,2014)):
        url=GEO+"?"+urlencode({"station_ids":str(STATION),"parameters":params,
            "start":f"{first}-01-01","end":f"{last}-12-31",
            "output_format":"geojson"})
        raw,response=fetch(url,14000000)
        path=out/f"geosphere_station30_native_daily_{first}_{last}.geojson"
        path.write_bytes(raw)
        parsed,quality=geosphere_block(meta,response,first,last)
        blocks.extend(parsed)
        provenance.append({"source":"GeoSphere official klima-v2-1d",
            "year_start":first,"year_end":last,"request_url":url,
            "response_sha256":hashlib.sha256(raw).hexdigest(),
            "file":path.name,"parameter_quality":quality})
        print("P6.3B GEOSPHERE",first,last,
              "accepted temperature",quality["tl_mittel"].get("accepted",0),
              "humidity",quality["rf_mittel"].get("accepted",0),flush=True)
    if len(blocks)!=3652 or len(set(r["date"] for r in blocks))!=3652:
        raise ValueError("GeoSphere observed source missing 2005–2014 day")
    station_map={}
    for r in csvread(station_solar):
        y=int(r["year"])
        if not START<=y<=END:continue
        key=r["date_geo_moz_utc_label"]
        if key in station_map:raise ValueError("Duplicate accepted station solar date")
        if int(r["q21"]) not in QC_GOOD:
            raise ValueError("GeoSphere accepted solar quality code changed")
        value=float(r["trusted_daily_kwh_m2"])
        if abs(value-float(r["cglo_j_raw_J_cm2"])/360.)>1.e-7:
            raise ValueError("GeoSphere previously accepted daily solar unit drift")
        station_map[key]=value
    if set(station_map)!={r["date"] for r in blocks}:
        raise ValueError("Original station solar and reference station calendar mismatch")
    for r in blocks:
        r["ghi_kwh_m2_day"]=station_map[r["date"]]
        r["solar_UTC_interval"]="23:00 prior day – 23:00 labelled day (MOZ)"
    csvwrite(out/"geosphere_station30_qc_joint_2005_2014.csv",blocks)
    return blocks,{
        "product":"GeoSphere Austria observed station #30, original daily mixed UTC integration periods",
        "metadata_sha256":hashlib.sha256(meta_bytes).hexdigest(),
        "station_meta":station,
        "historical_solar_sha256":checksum(station_solar),
        "year_interval":"2005–2014",
        "records":len(blocks),
        "source_blocks":provenance,
        "methodological_warning":"Daily labels are not identical integration intervals for different parameters. Sunshine 23–23 UTC (MOZ), precipitation 06–06 UTC next day; mean temperature is max/min-based. Joint daily correlations are approximate, NOT exact synchronized weather.",
    }

def power_radiation_kwh(val,unit):
    unit=unit.lower().replace(" ","").replace("²","^2")
    if unit in ("kw-hr/m^2/day","kwhr/m^2/day","kwh/m^2/day","kwh/m2/day",
                "kw-hr/m2/day","kwh/m^2"):
        return val
    if unit in ("mj/m^2/day","mj/m2/day","mj/m^2"):
        return val/3.6
    if unit in ("w/m^2","w/m2"):
        return val*.024
    raise ValueError("Unsupported daily NASA POWER radiation unit: "+unit)

def get_power_params(payload):
    data=payload.get("properties",{}).get("parameter",{})
    if not set(POWER_PARAMS)<=set(data):
        raise ValueError("NASA POWER daily payload lacks required multivariate components")
    info=payload.get("parameters",{})
    units={}
    for key in POWER_PARAMS:
        if key not in info or "units" not in info[key]:
            raise ValueError("NASA POWER parameter units unavailable: "+key)
        units[key]=info[key]["units"]
    for field in ("T2M","RH2M","PRECTOTCORR","WS2M"):
        expected={"T2M":("C","°C","degC"),
                  "RH2M":("%","percent"),
                  "PRECTOTCORR":("mm/day","mm"),
                  "WS2M":("m/s",)}[field]
        if units[field].replace(" ","") not in expected:
            raise ValueError("Unexpected NASA POWER field units "+field+": "+units[field])
    return data,units

def acquire_power(out):
    out.mkdir(parents=True,exist_ok=True)
    records=[];blocks=[]
    for first,last in ((2005,2009),(2010,2014)):
        url=POWER+"?"+urlencode({
            "parameters":",".join(POWER_PARAMS),"community":"RE",
            "latitude":POWER_LAT,"longitude":POWER_LON,
            "start":f"{first}0101","end":f"{last}1231",
            "format":"JSON","time-standard":"UTC"})
        raw,payload=fetch(url,16000000)
        data,units=get_power_params(payload)
        dest=out/f"nasa_power_grid_46p875N_15p375E_{first}_{last}_original.json"
        dest.write_bytes(raw)
        for d in days(first,last):
            key=d.strftime("%Y%m%d")
            if any(key not in data[name] for name in POWER_PARAMS):
                raise ValueError("POWER original daily archive missing indexed date")
            values={k:data[k][key] for k in POWER_PARAMS}
            if any(v is None or not math.isfinite(float(v)) or float(v)<=-900
                   for v in values.values()):
                # Missing POWER data must remain NULL with no infill; count.
                records.append({"date":d.isoformat(),"year":d.year,"month":d.month,
                    "day":d.day,"is_complete":False})
                continue
            ghi=power_radiation_kwh(float(values["ALLSKY_SFC_SW_DWN"]),
                                    units["ALLSKY_SFC_SW_DWN"])
            lw=power_radiation_kwh(float(values["ALLSKY_SFC_LW_DWN"]),
                                   units["ALLSKY_SFC_LW_DWN"])
            temp=float(values["T2M"]);rh=float(values["RH2M"])
            rain=float(values["PRECTOTCORR"]);wind=float(values["WS2M"])
            if not (0<=ghi<15 and 0<=lw<20 and -65<=temp<=65 and
                    0<=rh<=105 and 0<=rain<400 and 0<=wind<=110):
                raise ValueError("NASA POWER source outside declared physical range")
            records.append({"date":d.isoformat(),"year":d.year,"month":d.month,
                 "day":d.day,"is_complete":True,
                 "ghi_kwh_m2_day":ghi,"longwave_kwh_m2_day":lw,
                 "temperature_air_c":temp,"relative_humidity_pct":rh,
                 "precipitation_mm_day":rain,"wind_speed_m_s":wind})
        blocks.append({"source":"NASA POWER daily satellite/reanalysis at requested NASA cell coordinates",
            "start":first,"end":last,"url":url,"response_sha256":hashlib.sha256(raw).hexdigest(),
            "units":units,"file":dest.name})
        print("P6.3B POWER",first,last,"complete",sum(r.get("is_complete",False)
            for r in records if first<=r["year"]<=last),flush=True)
    if len(records)!=3652 or len({r["date"] for r in records})!=3652:
        raise ValueError("NASA POWER 2005–2014 external gridded record incomplete chronology")
    csvwrite(out/"nasa_power_grid_daily_joint_2005_2014.csv",records)
    return records,{"product":"NASA POWER 0.5°/native variable grid satellite-reanalysis",
                    "location":{"latitude":POWER_LAT,"longitude":POWER_LON},
                    "record_count":len(records),
                    "complete_count":sum(r.get("is_complete",False) for r in records),
                    "source_blocks":blocks,
                    "time_standard":"UTC (requested explicitly); NOT synchronized with NASA climate-model days",
                    "warning":"NASA POWER is a gridded analysis/reanalysis/remote-sensing-derived product, NOT an observed station measurement, and may share upstream reanalyses with other products.",
                    }
