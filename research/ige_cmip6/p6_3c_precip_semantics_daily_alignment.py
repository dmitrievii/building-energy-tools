#!/usr/bin/env python3
"""IGE P6.3C: GeoSphere official precipitation codes and independent daily lag/cross-site QC.

Research only. GeoSphere original metadata explicitly says:
 rr "-1=kein Niederschlag, 0=weniger als 1/10 mm".
NEVER discard -1 as a missing value. Do not equate trace rr=0 with
measured zero precipitation or replace q21-unverified raw data.
Validate existing immutable P6.3B external source before processing.

All comparisons are within-source descriptive associations, not model-year
weather validation. GeoSphere solar 23:00 previous UTC to 23:00 current;
rr 06:01 current to 06:00 following UTC; tl_mittel=(tlmax+tlmin)/2.
Timestamp lag sensitivity is diagnostic, NOT a data correction.
"""
from __future__ import annotations
import argparse,calendar,csv,hashlib,json,math,time
from collections import Counter,defaultdict
from datetime import date,timedelta
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

from p6_2d_solar_methods_benchmark import csvread,csvwrite,checksum
from p6_3a_solar_joint_coherence import corr_vectors,rank
from p6_3b_independent_reference_sources import (
    GEO,STATION,QC_GOOD,power_radiation_kwh,days
)
# Fixed before reading outcomes. Three separate nearby meteorological stations
# from the official original daily station metadata (no model-result selection).
DONOR_IDS=(53,94,200)   # Laßnitzhöhe, St. Radegund, Gleisdorf
SOURCE_FIELDS=("tl_mittel","rf_mittel","rr","cglo_j")
SOURCE_UNITS={"tl_mittel":"°C","rf_mittel":"%","rr":"mm","cglo_j":"J/cm²"}
LAGS=(-2,-1,0,1,2)
SEASONS={"ANNUAL":tuple(range(1,13)),"DJF":(12,1,2),
         "MAM":(3,4,5),"JJA":(6,7,8),"SON":(9,10,11)}
RELATIONS={
    "temperature_ghi":"temperature_air_c",
    "humidity_ghi":"relative_humidity_pct",
    "precipitation_ghi":"precipitation_mm_day_clean",
}
MIN_JJA=120
MIN_ANNUAL=500
COORD_ID=30

def metadata_contract(meta):
    props={p["name"]:p for p in meta.get("parameters",[])}
    for key in (*SOURCE_FIELDS,*(k+"_flag" for k in SOURCE_FIELDS)):
        if key not in props:raise ValueError("Missing authoritative daily metadata parameter "+key)
    for key,unit in SOURCE_UNITS.items():
        if props[key].get("unit")!=unit:
            raise ValueError(f"Official source daily unit mismatch {key}")
    rr=props["rr"].get("description","")
    rrflag=props["rr_flag"].get("description","")
    for description in (rr,rrflag):
        if "-1=kein Niederschlag" not in description or \
           "0=weniger als 1/10 mm" not in description or \
           "06:01 UTC bis 06:00 UTC des Folgetags" not in description:
            raise ValueError("Provider changed official rr sentinel or integration semantics")
    solar=props["cglo_j"].get("description","")
    if "23 Vortag - 23 Tag UTC" not in solar:
        raise ValueError("Solar daily integration window not provider-verified")
    temp=props["tl_mittel"].get("description","")
    if "tlmax + tlmin" not in temp:
        raise ValueError("Official tl_mittel source averaging semantics changed")
    stations={int(s["id"]):s for s in meta.get("stations",[]) if s.get("id") is not None}
    for sid in (COORD_ID,*DONOR_IDS):
        if sid not in stations or not stations[sid].get("has_global_radiation"):
            raise ValueError(f"Station {sid} lacks known source radiation availability")
    return props,stations

def decode_rain(raw,flag):
    """Keep raw immutable, return (clean amount, class, observation eligibility)."""
    if raw in ("",None) or flag in (None,""):
        return None,"missing_or_unchecked",False
    f=int(flag);v=float(raw)
    if f not in QC_GOOD or not math.isfinite(v):
        return None,"missing_or_unchecked",False
    if v==-1.:
        return 0.,"verified_no_precipitation",True
    if v==0.:
        # Physically censored interval [0,0.1) mm. The scalar lower
        # bound is used ONLY in amount sensitivity with explicit flag.
        return 0.,"trace_below_0p1_mm",True
    if v>0.:
        return v,"wet_ge_1mm" if v>=1. else "light_0p0_to_1p0_mm",True
    raise ValueError("Unknown negative precipitation code not in provider metadata")

def verify_original(base,metadata):
    src=base/"geosphere_station30_qc_joint_2005_2014.csv"
    rawmeta=base/"geosphere_station30_daily_metadata_original.json"
    if not src.is_file() or not rawmeta.is_file():
        raise FileNotFoundError("Frozen original P6.3B GeoSphere source missing")
    if checksum(rawmeta)!=hashlib.sha256(rawmeta.read_bytes()).hexdigest():
        raise ValueError("Original source corruption")
    meta=json.loads(rawmeta.read_text(encoding="utf8"))
    metadata_contract(meta)
    records=csvread(src)
    expected={d.isoformat() for d in days(2005,2014)}
    if len(records)!=3652 or {r["date"] for r in records}!=expected:
        raise ValueError("Original station observation and GHI calendar incomplete")
    clean=[];counts=Counter()
    for r in records:
        raw=r.get("precipitation_mm_day_raw")
        q=r.get("precipitation_mm_day_q21")
        amount,klass,verified=decode_rain(raw,q)
        counts[klass]+=1
        ghi=float(r["ghi_kwh_m2_day"])
        if not math.isfinite(ghi) or not 0<=ghi<=12.5:
            raise ValueError("Invalid previously audited station GHI")
        c={"station_id":30,"date":r["date"],"year":int(r["year"]),
           "month":int(r["month"]),"day":int(r["day"]),
           "ghi_kwh_m2_day":ghi,
           "temperature_air_c":float(r["temperature_air_c"]) if r["temperature_air_c"] else None,
           "relative_humidity_pct":float(r["relative_humidity_pct"]) if r["relative_humidity_pct"] else None,
           "wind_speed_m_s":float(r["wind_speed_m_s"]) if r["wind_speed_m_s"] else None,
           "precipitation_mm_day_raw":raw,
           "precipitation_mm_day_q21":q,
           "precipitation_mm_day_clean":amount,
           "precipitation_class":klass,
           "precipitation_verified":verified,
           "precipitation_trace_is_interval_censored":klass=="trace_below_0p1_mm"}
        clean.append(c)
    if counts["verified_no_precipitation"]!=2122:
        raise ValueError("Unexpected baseline count of official -1 sentinel in frozen archive")
    return clean,counts,{
        "original_geosphere_metadata_sha256":checksum(rawmeta),
        "original_joint_reference_sha256":checksum(src),
        "record_count":len(clean),
        "metadata_rr_description":next(p["description"] for p in meta["parameters"]
                                       if p["name"]=="rr"),
    }

def request(url,max_bytes=16000000):
    errors=[]
    for i in range(3):
        try:
            with urlopen(Request(url,headers={"User-Agent":"IGE-P6.3C-official-Graz-cross-station-2026",
                             "Accept":"application/json"}),timeout=90) as r:
                raw=r.read(max_bytes+1)
                if r.status!=200 or len(raw)>max_bytes:
                    raise ValueError("Official provider response invalid/too large")
                return raw,json.loads(raw)
        except (HTTPError,URLError,OSError,TimeoutError,ValueError) as e:
            errors.append(str(e))
            if isinstance(e,HTTPError) and e.code in (400,401,403,404,422):break
            if i<2:time.sleep(2**i)
    raise RuntimeError("GeoSphere independently QC reference fetch failure "+url+" "+str(errors))

def parse_donor_block(data,station_id,first,last):
    calendar_days=list(days(first,last))
    stamps=data.get("timestamps",[])
    if len(stamps)!=len(calendar_days) or any(
        str(s)[:10]!=d.isoformat() or not str(s).endswith(("Z","+00:00"))
        for s,d in zip(stamps,calendar_days)):
        raise ValueError(f"Donor {station_id} original source calendar invalid")
    entries=[]
    for f in data.get("features",[]):
        item=f.get("properties",{})
        identity=item.get("station")
        sid=int(identity if not isinstance(identity,dict) else identity["id"])
        if sid==station_id:entries.append(item)
    if len(entries)!=1:raise ValueError("Missing/ambiguous donor in provider response")
    fields=entries[0].get("parameters",{})
    for name in SOURCE_FIELDS:
        if name not in fields or name+"_flag" not in fields:
            raise ValueError("Donor daily original QC field missing "+name)
        if fields[name].get("unit")!=SOURCE_UNITS[name] or \
           len(fields[name].get("data",[]))!=len(calendar_days) or \
           len(fields[name+"_flag"].get("data",[]))!=len(calendar_days):
            raise ValueError("Donor unit/vector QC failure "+name)
    out=[];qc=Counter()
    for i,d in enumerate(calendar_days):
        row={"station_id":station_id,"date":d.isoformat(),
             "year":d.year,"month":d.month,"day":d.day}
        for field,target in (("tl_mittel","temperature_air_c"),
                             ("rf_mittel","relative_humidity_pct"),
                             ("cglo_j","ghi_kwh_m2_day")):
            value=fields[field]["data"][i];flag=fields[field+"_flag"]["data"][i]
            if flag not in (None,""):flag=int(flag)
            valid=value is not None and flag in QC_GOOD and math.isfinite(float(value))
            if valid:
                v=float(value)
                valid=(0<=v<=4500 if field=="cglo_j" else
                       -65<=v<=65 if field=="tl_mittel" else 0<=v<=105)
            row[target]=((float(value)/360. if field=="cglo_j" else float(value))
                        if valid else None)
            row[target+"_q21"]=flag
            qc[field+"_accepted" if valid else field+"_invalid"]+=1
        rain=fields["rr"]["data"][i];q=fields["rr_flag"]["data"][i]
        cleaned,klass,verified=decode_rain(rain,q)
        row.update({"precipitation_mm_day_raw":rain,
                    "precipitation_mm_day_q21":q,
                    "precipitation_mm_day_clean":cleaned,
                    "precipitation_class":klass,
                    "precipitation_verified":verified,
                    "precipitation_trace_is_interval_censored":klass=="trace_below_0p1_mm"})
        qc["rr_"+klass]+=1
        out.append(row)
    return out,dict(qc)

def nearest_km(a,b):
    lat1,lon1=math.radians(a["lat"]),math.radians(a["lon"])
    lat2,lon2=math.radians(b["lat"]),math.radians(b["lon"])
    hav=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371*2*math.asin(math.sqrt(hav))

def donors(base,out):
    met=json.loads((base/"geosphere_station30_daily_metadata_original.json").read_text())
    _,stations=metadata_contract(met)
    saved=[];provenance=[];failures=[]
    names=",".join(v for n in SOURCE_FIELDS for v in (n,n+"_flag"))
    for sid in DONOR_IDS:
        station=stations[sid];records=[];parts=[];source_qc=[]
        for first,last in ((2005,2009),(2010,2014)):
            url=GEO+"?"+urlencode({"station_ids":str(sid),"parameters":names,
                      "start":f"{first}-01-01","end":f"{last}-12-31",
                      "output_format":"geojson"})
            try:
                blob,source=request(url)
                dest=out/f"geosphere_original_station{sid}_{first}_{last}.geojson"
                dest.write_bytes(blob)
                part,counts=parse_donor_block(source,sid,first,last)
                parts.extend(part)
                source_qc.append({"years":f"{first}-{last}",
                                  "original_bytes_sha256":hashlib.sha256(blob).hexdigest(),
                                  "raw_name":dest.name,"counts":counts,"request_url":url})
            except (RuntimeError,ValueError,KeyError) as error:
                failures.append({"station_id":sid,"year_start":first,
                                 "year_end":last,"reason":str(error)})
                print("P6.3C DONOR UNAVAILABLE",sid,first,last,str(error)[:170],flush=True)
        paired_days=sum(r["ghi_kwh_m2_day"] is not None and
                        r["temperature_air_c"] is not None for r in parts)
        paired_jja=sum(r["ghi_kwh_m2_day"] is not None and
                       r["temperature_air_c"] is not None and
                       r["month"] in (6,7,8) for r in parts)
        usable=(len(parts)==3652 and len({r["date"] for r in parts})==3652
                and paired_days>=500 and paired_jja>=120)
        provenance.append({"station_id":sid,"station_name":station["name"],
            "latitude":station["lat"],"longitude":station["lon"],
            "altitude_m":station["altitude"],
            "distance_from_station30_km":nearest_km(stations[30],station),
            "original_q21_accepted_solar_temperature_days":paired_days,
            "original_q21_accepted_solar_temperature_JJA_days":paired_jja,
            "source_quality":source_qc,
            "status":"VALIDATED_QC_DONOR_SOURCE" if usable
                     else "INSUFFICIENT_QC_SAMPLE_OR_UNAVAILABLE"})
        if usable:saved.extend(parts)
    if not saved:
        raise ValueError("No independent complete 10-year station donor source confirmed")
    csvwrite(out/"geosphere_three_independent_donor_station_daily_qc.csv",saved)
    return saved,provenance,failures

def lagged(rows,method="pearson"):
    """Strict within-source timestamp-label lag; no cross-model date pairing."""
    keys={}
    for r in rows:
        key=(r["station_id"],r["date"])
        if key in keys:raise ValueError("Duplicate source station-date pair")
        keys[key]=r
    groups=defaultdict(list)
    for row in rows:groups[row["station_id"]].append(row)
    outcome=[]
    for sid,stationrows in groups.items():
        for season,months in SEASONS.items():
            solar_records=[r for r in stationrows if r["month"] in months]
            for relationship,field in RELATIONS.items():
                for lag in LAGS:
                    paired=[]
                    trace_excluded=0
                    for r in solar_records:
                        ghi=r.get("ghi_kwh_m2_day")
                        if ghi is None:continue
                        adj=(date.fromisoformat(r["date"])+timedelta(days=lag)).isoformat()
                        w=keys.get((sid,adj))
                        if w is None or w.get(field) is None:continue
                        # Rain amount is interval-censored for trace days:
                        # exclude trace from Pearson/Spearman amount correlations,
                        # but report trace frequency in a separate table.
                        if field=="precipitation_mm_day_clean" and \
                            w["precipitation_class"]=="trace_below_0p1_mm":
                            trace_excluded+=1;continue
                        paired.append((float(w[field]),float(ghi)))
                    n=len(paired)
                    xy=[x for x,y in paired];zy=[y for x,y in paired]
                    pearson=corr_vectors(xy,zy) if n>=30 else None
                    spearman=corr_vectors(rank(xy),rank(zy)) if n>=30 else None
                    nmin=MIN_ANNUAL if season=="ANNUAL" else MIN_JJA
                    outcome.append({"station_id":sid,"season":season,
                        "relationship":relationship,"weather_label_day_shift":lag,
                        "n_complete":n,"excluded_trace_censored_rain_pairs":trace_excluded,
                        "pearson":pearson,"spearman":spearman,
                        "status":"VALID_DESCRIPTIVE" if n>=nmin else "INSUFFICIENT_QC_SAMPLE",
                        "warning":"Model GCM chronological daily dates NEVER paired with station dates; this lag is only within same observed product source"})
    return outcome

def wet_dry(rows):
    result=[]
    groups=defaultdict(list)
    for r in rows:groups[r["station_id"]].append(r)
    for sid,rr in groups.items():
        for season,months in SEASONS.items():
            subset=[r for r in rr if r["month"] in months]
            cat=defaultdict(list)
            for r in subset:
                v=r.get("ghi_kwh_m2_day")
                if v is not None:cat[r["precipitation_class"]].append(float(v))
            for classification in ("verified_no_precipitation","trace_below_0p1_mm",
                                   "light_0p0_to_1p0_mm","wet_ge_1mm",
                                   "missing_or_unchecked"):
                vals=cat[classification]
                result.append({"station_id":sid,"season":season,
                    "precipitation_class":classification,
                    "solar_available_days":len(vals),
                    "ghi_climatological_mean_kwh_m2_day":fmean(vals) if vals else None,
                    "semantic_source":"Official GeoSphere rr -1=no precipitation, 0=trace below 0.1mm",
                    "rain_UTC_period":"06:01 UTC day to 06:00 UTC following day",
                    "solar_UTC_period":"23:00 UTC preceding day to 23:00 UTC day"})
    return result

def save_union(path,items):
    keys=list(dict.fromkeys(key for item in items for key in item))
    if not keys:raise ValueError("Empty provenance")
    with path.open("w",encoding="utf8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=keys)
        w.writeheader();w.writerows(items)
    return checksum(path)

def run(source_dir,out):
    out.mkdir(parents=True,exist_ok=True)
    station,counts,source=verify_original(
        source_dir,source_dir/"geosphere_station30_daily_metadata_original.json")
    observed,donor_prov,failed=donors(source_dir,out)
    allstations=[*station,*observed]
    byid=Counter(x["station_id"] for x in allstations)
    if byid[30]!=3652 or not all(n==3652 for sid,n in byid.items() if sid!=30):
        raise ValueError("Original station input or donor calendar does not have full coverage")
    lag=lagged(allstations)
    categories=wet_dry(allstations)
    selflags=[r for r in lag if r["station_id"]==30 and r["season"]=="JJA"
              and r["relationship"]=="temperature_ghi"]
    if len(selflags)!=len(LAGS):
        raise ValueError("Five JJA station solar-temperature label lags missing")
    output={
        "p6_3c_station30_precipitation_reinterpreted.csv":station,
        "p6_3c_all_station_lag_sensitivity_correlations.csv":lag,
        "p6_3c_all_station_rain_trace_dry_ghi_climatology.csv":categories,
    }
    hashes={name:csvwrite(out/name,rows) for name,rows in output.items()}
    hashes["p6_3c_donor_metadata_and_source_hashes.csv"]=save_union(
        out/"p6_3c_donor_metadata_and_source_hashes.csv",donor_prov)
    report={
        "stage":"IGE_P6_3C_PRECIPITATION_SEMANTICS_DAILY_ALIGNMENT_MULTISITE",
        "status":"PASS_FROZEN_PROVIDER_QC_AND_DONOR_SOURCE_PROVENANCE",
        "scientific_status":"DESCRIPTIVE_ONLY_TIME_ALIGNMENT_AND_SPATIAL_TRANSFER_NOT_VALIDATED",
        "station30_original_raw_minus1_dry_days":counts["verified_no_precipitation"],
        "station30_trace_days":counts["trace_below_0p1_mm"],
        "station30_precip_categories":dict(counts),
        "station30_meteorology_solar_jja_day_shift":selflags,
        "donor_stations":donor_prov,
        "donor_download_gaps":failed,
        "record_count":len(allstations),
        "source_immutable_metadata":source,
        "file_sha256":hashes,
        "methodology":["Official rr raw sentinel -1=zero observed precipitation, zero=trace below 0.1mm",
          "Station source raw values and q21 flags are retained with explicit cleaned amount and class",
          "Pearson/Spearman daily-label lag sweep -2 through +2 days never shifts stored source data",
          "Trace precipitation is interval-censored [0,0.1) mm and excluded from numeric rainfall correlation",
          "Seasonal multi-station sensitivity uses independent stations at different elevations; no station may stand in as observed radiation at original grid location",
          "Source field windows different; lag maximizing correlation is NOT a physically validated temporal shift",
          "Cross-station different exposure, altitude and measured periods preclude simple replacement of GeoSphere Graz GHI",
          "No hourly source observations in this experiment; do not claim verified hourly alignment or EPW-ready weather",
          "No change to original GCM fields, previous stage scientific results or production main"]}
    (out/"p6_3c_source_semantics_alignment_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("P6.3C",report["status"],"donor stations",
          len([r for r in donor_prov if r["status"]=="VALIDATED_QC_DONOR_SOURCE"]),
          "rr -1 days",counts["verified_no_precipitation"],
          "JJA T-GHI r0",next((round(r["pearson"],5) for r in selflags
                             if r["weather_label_day_shift"]==0),None),
          "r+1",next((round(r["pearson"],5) for r in selflags
                      if r["weather_label_day_shift"]==1),None),flush=True)
    return report

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--p6b-frozen",type=Path,required=True)
    a.add_argument("--out",type=Path,required=True)
    v=a.parse_args()
    run(v.p6b_frozen,v.out)
