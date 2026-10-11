#!/usr/bin/env python3
"""P7A research: 2013 historical, multi-source ORIGINAL-hourly EPW reference.

This is NOT a stochastic daily->hourly synthesizer, future SSP projection,
TMY selection, or a validated production weather file. Original station
T/RH/pressure/wind-speed with provider QC; NASA POWER gridded fallback
and original P6.3E 2005-14 gridded GHI/DNI/DHI. Strict 8760 hours,
fixed CET UTC+01:00 with NO DST, EnergyPlus EPW 35-field syntax.
All source-origin decisions and original byte SHA-256 are audited.
"""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from p6_2d_solar_methods_benchmark import checksum
from p6_3c_precip_semantics_daily_alignment import save_union

YEAR=2013
OFFSET=timedelta(hours=1)
SITE=(47.08,15.45)
ELEVATION_PROXY_M=366
POWER="https://power.larc.nasa.gov/api/temporal/hourly/point"
M_VARS=("T2M","T2MDEW","RH2M","PS","WS10M","WD10M",
        "ALLSKY_SFC_LW_DWN","PRECTOTCORR")
STATION=("tl","rf","p","ff")
SPECS={
    "tl":(-70,70),"rf":(0,100),"p":(310,1200),"ff":(0,40)}
EPW_COLUMNS=35
CORE_FIELDS=("dry_bulb","dew_point","relative_humidity",
             "station_pressure","ghi","dni","dhi",
             "sky_infrared","wind_speed","wind_direction")
START_LOCAL=datetime(YEAR,1,1,tzinfo=timezone(OFFSET))
START_UTC=START_LOCAL.astimezone(timezone.utc)
END_LOCAL=datetime(YEAR+1,1,1,tzinfo=timezone(OFFSET))
LAST_UTC=(END_LOCAL-timedelta(hours=1)).astimezone(timezone.utc)
EXPECTED_HOURS=int((END_LOCAL-START_LOCAL).total_seconds()/3600)

def as_utc(s):
    t=datetime.fromisoformat(s.replace("Z","+00:00"))
    if t.tzinfo is None or t.utcoffset()!=timedelta(0) or t.minute or t.second:
        raise ValueError("Original UTC hourly source label absent/unexpected")
    return t.astimezone(timezone.utc)

def station_input(root):
    allrows={};prov=[]
    for year in (2012,2013):
        path=root/str(year)/"hourly_raw_qc.csv.gz"
        metadata=root/str(year)/"quality_provenance.json"
        if not path.is_file() or not metadata.is_file():
            raise FileNotFoundError(f"Original GeoSphere hourly source archive incomplete {year}")
        m=json.loads(metadata.read_text(encoding="utf8"))
        if m["station_id"]!=30 or m["year"]!=year or m["expected_hours"] not in (8784,8760):
            raise ValueError("GeoSphere original source station/year/period drift")
        if m["parameter_units"].get("p")!="hPa":
            raise ValueError("Pressure conversion requires official hPa unit")
        # Unchanged gzip bytes and accepted QC are retained; do not
        # redefine q21=0 as erroneous, but do not mark it QC-approved.
        b=path.read_bytes()
        if hashlib.sha256(b).hexdigest()!=m["hourly_csv_gzip_sha256"]:
            raise ValueError("Original GeoSphere extracted hourly bytes differ from source QA")
        prov.append({"year":year,"source_station":30,
            "source_hourly_sha256":hashlib.sha256(b).hexdigest(),
            "provenance_sha256":checksum(metadata),
            "official_unit_pressure":"hPa"})
        with gzip.open(path,"rt",encoding="utf8",newline="") as f:
            for r in csv.DictReader(f):
                dt=as_utc(r["timestamp_utc"])
                if dt in allrows:raise ValueError("Duplicate station source UTC record")
                allrows[dt]=r
    if START_UTC not in allrows or LAST_UTC not in allrows:
        raise ValueError("Cross-year fixed-standard-time UTC station seam missing")
    return allrows,prov

def load_solar(root):
    report=root/"p6_3e_hourly_solar_components_arad_science_audit.json"
    src=root/"p6_3e_native_hourly_ghi_dni_dhi_toa_physical_diagnostics.csv"
    if not src.is_file() or not report.is_file():raise FileNotFoundError("P6.3E immutable solar source absent")
    qa=json.loads(report.read_text(encoding="utf8"))
    digest=checksum(src)
    if digest!=qa["output_file_sha256"][src.name] or qa["production_epw_ready"] is not False:
        raise ValueError("Original NASA source hash/scientific status drift")
    solar={}
    with src.open("r",newline="",encoding="utf8") as f:
        for r in csv.DictReader(f):
            if r["site"]!="graz_station30":continue
            t=as_utc(r["timestamp_utc_start"])
            if not START_UTC<=t<=LAST_UTC:continue
            if r["valid"]!="True" or r["is_satellite_not_observed_ground"]!="True":
                raise ValueError("Cannot use invalid NASA POWER source as hourly solar")
            if t in solar:raise ValueError("Duplicate solar UTC start")
            solar[t]={
              "ghi":float(r["GHI_kwh_m2_hour"])*1000,
              "dni":float(r["DNI_kwh_m2_hour"])*1000,
              "dhi":float(r["DHI_kwh_m2_hour"])*1000,
              "closure_review":r["hourly_component_closure_review"]=="True",
              "coszen":float(r["solar_coszen_noaa_midpoint"])}
    if len(solar)!=EXPECTED_HOURS:raise ValueError("Original NASA POWER solar UTC year not full")
    return solar,digest

def original_power_met(raw_json,request_url):
    d=json.loads(raw_json)
    if d.get("messages") not in ([],None,{}):
        raise ValueError("NASA POWER provider returned messages: "+str(d["messages"])[:300])
    props=d.get("properties",{})
    par=props.get("parameter",{})
    if not set(M_VARS)<=set(par):
        raise ValueError("NASA POWER missing original requested hourly meteorological variable: "+
                         str(sorted(set(M_VARS)-set(par))))
    units=d.get("parameters",{})
    # Require provider returned their original units, so the unit
    # conversion below is not an unverified guess.
    expected={"T2M":("C","°C"),"T2MDEW":("C","°C"),"RH2M":("%",),
              "PS":("kPa",),"WS10M":("m/s",),"WD10M":("Degrees","degree","degrees"),
              "ALLSKY_SFC_LW_DWN":("W/m^2","W/m²","W m-2"),
              "PRECTOTCORR":("mm/hour","mm/hr","mm/h")}
    for name,aliases in expected.items():
        actual=str(units.get(name,{}).get("units",""))
        if actual not in aliases:
            raise ValueError(f"NASA POWER unknown unit for {name}: {actual!r}, expected {aliases}")
    result={}
    hours=[START_UTC+timedelta(hours=h) for h in range(EXPECTED_HOURS)]
    keys=[x.strftime("%Y%m%d%H") for x in hours]
    for p in M_VARS:
        source=par[p]
        missing=float(d.get("header",{}).get("fill_value",-999))
        if not all(k in source for k in keys):
            raise ValueError(f"NASA POWER {p} missing mandatory UTC records")
    for key,t in zip(keys,hours):
        met={}
        for p in M_VARS:
            value=float(par[p][key])
            if not math.isfinite(value) or value in (-999,-9999):
                met[p]=None
            else:met[p]=value
        result[t]=met
    return result,{"nasa_power_weather_original_url":request_url,
                   "nasa_power_weather_original_sha256":hashlib.sha256(raw_json).hexdigest(),
                   "original_power_parameter_units":{p:units[p]["units"] for p in M_VARS},
                   "raw_utc_hours":len(result),
                   "source_type":"NASA POWER gridded, NOT on-site observed"}

def power_url():
    query=urlencode({"parameters":",".join(M_VARS),"community":"SB",
                     "latitude":SITE[0],"longitude":SITE[1],
                     "start":"20121231","end":"20131231",
                     "format":"JSON","time-standard":"UTC"})
    return POWER+"?"+query

def get_meteorology(url,out):
    with urlopen(Request(url,headers={"User-Agent":"IGE-P7A-Research-EPW/2026",
                "Accept":"application/json"}),timeout=180) as resp:
        if resp.status!=200:raise RuntimeError("NASA POWER hourly source failed")
        b=resp.read(15000000)
    out.write_bytes(b)
    return original_power_met(b,url)

def dewpoint_c(t,rh):
    """Reference Magnus inverted RH; no reliance on invented wet-bulb."""
    if not (-70<t<70 and 0<rh<=100):
        raise ValueError("Dewpoint thermodynamic input invalid")
    a=17.625;b=243.04
    alpha=math.log(rh/100.0)+(a*t)/(b+t)
    td=b*alpha/(a-alpha)
    if td>t+1e-7:raise ValueError("Dewpoint above dry bulb")
    return td

def finite_range(v,low,high):
    return v is not None and math.isfinite(v) and low<=v<=high

def choose_source(source_record,field,metval,scale,limit,stats):
    key=field+"_accepted"
    orig=source_record.get(key)
    if orig not in ("",None):
        x=float(orig)
        if finite_range(x,*limit):
            stats[field+"_station_qc"]+=1
            return x*scale,"GEOSPHERE_Q21_APPROVED"
    if finite_range(metval,*limit):
        stats[field+"_nasa_fallback"]+=1
        return metval*scale,"NASA_POWER_GRID_FALLBACK"
    raise ValueError(f"Core meteorological variable {field} not resolvable; EPW fail closed")

def make_rows(station,solar,meteorology):
    rows=[];lineage=[];counts=Counter();risk=Counter()
    for n in range(EXPECTED_HOURS):
        local=START_LOCAL+timedelta(hours=n)
        utc=local.astimezone(timezone.utc)
        st=station.get(utc)
        met=meteorology.get(utc)
        rad=solar.get(utc)
        if st is None or met is None or rad is None:
            raise ValueError("Missing source hourly UTC seam")
        t,ts=choose_source(st,"tl",met["T2M"],1,(-70,70),counts)
        rh,rhs=choose_source(st,"rf",met["RH2M"],1,(.1,100),counts)
        p,ps=choose_source(st,"p",met["PS"]*10 if met["PS"] is not None else None,
                           100,(310,1200),counts)
        ws,wss=choose_source(st,"ff",met["WS10M"],1,(0,40),counts)
        wd=met["WD10M"]
        if not finite_range(wd,0,360):raise ValueError("Wind direction NASA missing")
        lwr=met["ALLSKY_SFC_LW_DWN"]
        if not finite_range(lwr,0,850):raise ValueError("Horizontal sky IR source missing")
        # NASA POWER hourly LW intensity in W/m2, numerically same Wh/m2
        # for a one-hour interval, without inventing opaque cloud cover.
        td=dewpoint_c(t,rh)
        if met["T2MDEW"] is not None:
            risk["nasa_dewpoint_source_available_not_substituted"]+=1
        ghi,dni,dhi=rad["ghi"],rad["dni"],rad["dhi"]
        if not all(finite_range(x,0,1600) for x in (ghi,dni,dhi)):
            raise ValueError("Unexpected NASA original shortwave solar")
        if rad["closure_review"]:risk["nasa_solar_component_review_hours"]+=1
        rain=met["PRECTOTCORR"]
        liquid=rain if finite_range(rain,0,300) else 999
        if liquid==999:risk["missing_precipitation_hours"]+=1
        # 35 EPW fields, see EnergyPlus AuxiliaryPrograms EPW dictionary.
        # Hour1 represents preceding hour 00:00–01:00 standard time.
        rec=[
          local.year,local.month,local.day,local.hour+1,60,
          "?9"*22,round(t,3),round(td,3),round(rh,2),
          round(p,1),
          9999,9999,round(lwr,3),round(ghi,3),round(dni,3),round(dhi,3),
          999999,999999,999999,9999,
          round(wd,2),round(ws,3),
          99,99,9999,99999,9,"999999999",999,.999,999,99,999,
          round(liquid,3) if liquid!=999 else 999,
          1 if liquid!=999 and liquid>0 else 99]
        if len(rec)!=EPW_COLUMNS:raise AssertionError("EPW row count mismatch")
        rows.append(rec)
        lineage.append({"local_time_start":local.isoformat(),
           "utc_time_start":utc.isoformat(),"geosphere_station":30,
           "temperature_source":ts,"rh_source":rhs,
           "pressure_source":ps,"wind_speed_source":wss,
           "wind_direction_source":"NASA_POWER_GRID",
           "sky_lw_source":"NASA_POWER_GRID",
           "solar_source":"NASA_POWER_GRID_P6_3E_ORIGINAL",
           "dewpoint_method":"MAGNUS_FROM_MIXED_TEMP_RH",
           "precipitation_source":"NASA_POWER_PRECTOTCORR" if rain is not None else "MISSING",
           "solar_ghi_dni_dhi_closure_review":rad["closure_review"]})
    return rows,lineage,counts,risk

def write_epw(path,rows):
    if len(rows)!=EXPECTED_HOURS:raise ValueError("EPW must have 8760 hours in non-leap 2013")
    headers=[
       ["LOCATION","Graz","Styria","AUT","IGE_P7A_NASA_GEOSPHERE_RESEARCH",
        "999999",SITE[0],SITE[1],1.0,ELEVATION_PROXY_M],
       ["DESIGN CONDITIONS",0],
       ["TYPICAL/EXTREME PERIODS",0],
       ["GROUND TEMPERATURES",0],
       ["HOLIDAYS/DAYLIGHT SAVINGS","No",0,0,0],
       ["COMMENTS 1","RESEARCH ONLY 2013 actual year; NOT TMY, SSP, or calibrated future EPW"],
       ["COMMENTS 2","GeoSphere QC meteorology; NASA POWER gridded solar and fallback; fixed CET no DST; see provenance JSON"],
       ["DATA PERIODS",1,1,"2013 research","Tuesday","1/1","12/31"]]
    with path.open("w",encoding="utf8",newline="") as f:
        w=csv.writer(f,lineterminator="\n")
        w.writerows(headers)
        w.writerows(rows)
    readback=list(csv.reader(path.open("r",encoding="utf8",newline="")))
    if len(readback)!=8+EXPECTED_HOURS or not all(len(r)==35 for r in readback[8:]):
        raise ValueError("EPW readback 8 headers / 35 data columns invalid")
    for i,r in enumerate(readback[8:]):
        t=START_LOCAL+timedelta(hours=i)
        if list(map(int,r[:5]))!=[t.year,t.month,t.day,t.hour+1,60]:
            raise ValueError("EPW local-standard-time hour/date mismatch")
    return checksum(path)

def run(geo_root,solar_root,out):
    out.mkdir(parents=True,exist_ok=True)
    station,station_prov=station_input(geo_root)
    solar,solar_digest=load_solar(solar_root)
    source=out/"nasa_power_20121231_20131231_hourly_weather_original.json"
    met,provenance=get_meteorology(power_url(),source)
    rows,lineage,counts,risk=make_rows(station,solar,met)
    epw=out/"Graz_2013_P7A_Historical_Reference_RESEARCH_ONLY.epw"
    epw_hash=write_epw(epw,rows)
    lineage_sha=save_union(out/"Graz_2013_P7A_hourly_source_lineage.csv",lineage)
    report={
     "stage":"IGE_P7A_HISTORICAL_HOURLY_EPW_REFERENCE",
     "technical_status":"FORMAT_AND_SOURCE_CONTRACTS_PASS",
     "scientific_status":"HISTORICAL_MULTISOURCE_REFERENCE_ONLY_NOT_HOURLY_CLIMATE_SYNTHESIS",
     "production_epw_ready":False,
     "reference_year":YEAR,"observed_site_name":"Graz Universität #30",
     "location_utc_offset_hours":1,
     "local_2013_hour_count":len(rows),
     "radiation_original_utc_source_P6E_sha256":solar_digest,
     "geo_original_hourly_data":station_prov,
     "meteorology_original":provenance,
     "hourly_source_choice_counts":dict(counts),
     "source_quality_risks":dict(risk),
     "research_output_files_sha256":{
       epw.name:epw_hash,
       "Graz_2013_P7A_hourly_source_lineage.csv":lineage_sha,
       source.name:checksum(source)},
     "limitations":[
       "This is hourly source assembly, NOT new hourly climate synthesis nor future SSP/RCP/EPW projection.",
       "EPW standard time is CET UTC+1 year round, no European daylight saving; NASA original UTC hours shifted +1 with previous-year last-hour input.",
       "Station variables used only when original GeoSphere q21 approved; gaps filled from explicitly identified NASA POWER gridded meteorology without concealed interpolation.",
       "Original solar GHI/DNI/DHI is NASA POWER gridded, not ARAD ground. All 3 solar components preserved even if source-internal GHI≈DNI*cosz+DHI flags review.",
       "Atmospheric sky IR is original NASA POWER LW down, if present and validated in W/m2, 1h energy equivalent Wh/m2.",
       "Unreported fields have their actual EPW missing-value sentinels, not invented weather observations: in particular opaque/total sky cover, visibility, snow and illuminance.",
       "Relative-humidity-derived dewpoint via stated Magnus formula is a derived psychrometric field, source/uncertainty recorded.",
       "NASA precipitation is provider gridded PRECTOT mm/hour, not station precipitation. Missing is EPW sentinel 999 and never encoded as zero.",
       "EPW parser/count checks do NOT constitute a successful EnergyPlus building simulation; runnable-ness must be tested with actual EnergyPlus.",
       "2013 is a chronological historical year, NOT a typical meteorological year, weather-normal, calibrated station-only product or future projection.",
       "P7B must independently synthesize native hourly weather from daily model inputs with explicit intra-day, cross-variable and future climate-change-signal validation." ]}
    (out/"p7a_epw_research_science_audit.json").write_text(
       json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P7A",report["technical_status"],"hours",len(rows),
          "epw_SHA256",epw_hash,"EPW_PRODUCTION_READY",False,flush=True)
    return report

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--geosphere-source",required=True,type=Path)
    ap.add_argument("--solar-source",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args()
    run(args.geosphere_source,args.solar_source,args.out)
