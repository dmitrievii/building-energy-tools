#!/usr/bin/env python3
"""IGE P6.3F: original open GeoSphere 10-minute cglo/chim QC, Graz 2005–2014.

DO NOT infer ten-minute quality from earlier hourly q21=0; obtain original
per-parameter flags and official metadata. DO NOT assume timestamp labels
mark start or end of averaged interval; report both hypotheses, neither is
endorsed without original provider definition. NASA POWER remains gridded.
"""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math,time
from collections import Counter,defaultdict
from datetime import datetime,timedelta,date,timezone
from pathlib import Path
from statistics import fmean
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from p6_2d_solar_methods_benchmark import checksum
from p6_3c_precip_semantics_daily_alignment import save_union

GEO="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-10min"
STATIONS=(30,16412)
SOLAR=("cglo","chim")
FLAGS=("cglo_flag","chim_flag")
PARAMS=SOLAR+FLAGS
QC_ACCEPTED=frozenset((10,11,12,20,21,22))
QC_UNCHECKED=0
YEARS=range(2005,2015)
START=datetime(2005,1,1,tzinfo=timezone.utc)
END=datetime(2015,1,1,tzinfo=timezone.utc)
HOUR_COUNT=87648
SEASONS={"ANNUAL":set(range(1,13)),"DJF":{12,1,2},"MAM":{3,4,5},
         "JJA":{6,7,8},"SON":{9,10,11}}
WINDOWS=("record_start","record_end")
NASA_FIELDS={"cglo":"GHI_kwh_m2_hour","chim":"DHI_kwh_m2_hour"}

def get_original(url,maximum=45000000):
    errs=[]
    for attempt in range(4):
        try:
            with urlopen(Request(url,headers={"Accept":"application/json",
                     "User-Agent":"IGE-P6.3F-open-geosphere-source-audit/2026"}),timeout=120) as r:
                payload=r.read(maximum+1)
                if r.status!=200 or len(payload)>maximum:
                    raise ValueError("Unexpected GeoSphere response status/size")
                obj=json.loads(payload)
                if not isinstance(obj,dict):
                    raise ValueError("Original GeoSphere returned non-object JSON")
                return payload,obj
        except (HTTPError,URLError,TimeoutError,OSError,ValueError) as e:
            errs.append(str(e)[:700])
            if isinstance(e,HTTPError) and e.code in (400,401,403,404,422):
                break
            if attempt<3:time.sleep(min(2**attempt,4))
    raise RuntimeError("Original GeoSphere API access failed; source NOT verified: "+str(errs))

def metadata_contract(metadata):
    specs={p["name"]:p for p in metadata.get("parameters",[])
           if isinstance(p,dict) and p.get("name")}
    for name in SOLAR:
        if name not in specs or specs[name].get("unit") not in ("W/m²","W/m2","W m-2","W/m^2"):
            raise ValueError("Official ten-minute solar variable/unit absent: "+name)
    for name in FLAGS:
        if name not in specs:
            raise ValueError("Official ten-minute original per-parameter QC absent: "+name)
        if specs[name].get("code_list_ref") not in ("q21",None):
            raise ValueError("Unexpected GeoSphere QC code-list reference: "+name)
    legend={int(x["key"]):str(x.get("value","")) for x in
            metadata.get("code_lists",{}).get("q21",[])
            if x.get("key") is not None}
    if not QC_ACCEPTED<=set(legend) or QC_UNCHECKED not in legend:
        raise ValueError("Official GeoSphere quality status legend incomplete")
    if "ungeprüft" not in legend[QC_UNCHECKED].lower():
        raise ValueError("Unverified original quality code 0 semantics changed")
    stations={int(x["id"]):x for x in metadata.get("stations",[])
              if isinstance(x,dict) and x.get("id") is not None}
    return specs,legend,stations

def parse_utc(stamp):
    when=datetime.fromisoformat(str(stamp).replace("Z","+00:00"))
    if when.tzinfo is None or when.utcoffset()!=timedelta(0):
        raise ValueError("Original 10-minute GeoSphere time not unambiguously UTC")
    if when.second or when.microsecond or when.minute%10:
        raise ValueError("Original 10-minute records not on 10-minute UTC grid")
    return when.astimezone(timezone.utc)

def decode_year(data,station,year):
    stamps=data.get("timestamps",[])
    start=datetime(year,1,1,tzinfo=timezone.utc)
    count=((datetime(year+1,1,1,tzinfo=timezone.utc)-start).days*144)
    if len(stamps)!=count:
        raise ValueError(f"Missing original 10-minute UTC time index {station} {year}: {len(stamps)}/{count}")
    if any(parse_utc(t)!=start+timedelta(minutes=10*i)
           for i,t in enumerate(stamps)):
        raise ValueError("Missing/duplicate/shifted original ten-minute UTC source timestamp")
    features=data.get("features",[])
    if len(features)!=1:
        raise ValueError("Original GeoSphere ten-minute response feature count invalid")
    prop=features[0].get("properties",{})
    ident=prop.get("station")
    if isinstance(ident,dict): ident=ident.get("id")
    if int(ident)!=station:raise ValueError("Original ten-minute data returned different station ID")
    p=prop.get("parameters",{})
    values={}
    for name in PARAMS:
        if name not in p or not isinstance(p[name].get("data"),list) or \
           len(p[name]["data"])!=count:
            raise ValueError("Original ten-minute variable/flag absent or wrong length "+name)
        values[name]=p[name]["data"]
        if name in SOLAR and p[name].get("unit") not in ("W/m²","W/m2","W m-2","W/m^2"):
            raise ValueError("GeoSphere original ten-minute observation unexpected unit "+name)
    rows=[];totals={v:Counter() for v in SOLAR}
    for i in range(count):
        stamp=start+timedelta(minutes=10*i)
        row={"timestamp":stamp,"station_id":station}
        for name in SOLAR:
            q=values[name+"_flag"][i]
            if q is not None:
                q=int(q)
            reading=values[name][i]
            reading=float(reading) if reading is not None else None
            if reading is not None and not math.isfinite(reading):
                raise ValueError("Nonfinite GeoSphere ten-minute radiation observation")
            ok=q in QC_ACCEPTED and reading is not None
            row[name]=reading
            row[name+"_flag"]=q
            row[name+"_accepted"]=ok
            totals[name]["original_slots"]+=1
            totals[name]["q_"+str(q)]+=1
            if reading is None:totals[name]["missing_values"]+=1
            if ok:totals[name]["approved_slots"]+=1
            if q in QC_ACCEPTED and reading is None:
                totals[name]["accepted_flag_but_missing_value"]+=1
        rows.append(row)
    return rows,totals

def hourly_aggregate(rows,window,year):
    """Strict 6 of 6 observed 10min source values, per-parameter accepted QC."""
    if window not in WINDOWS:raise ValueError("Unregistered timestamp convention")
    grouped=defaultdict(list)
    for r in rows:
        key=r["timestamp"]-(timedelta(minutes=10) if window=="record_end" else timedelta())
        key=key.replace(minute=0)
        grouped[key].append(r)
    start=datetime(year,1,1,tzinfo=timezone.utc)
    end=datetime(year+1,1,1,tzinfo=timezone.utc)
    records={}
    for i in range(int((end-start).total_seconds()/3600)):
        hour=start+timedelta(hours=i)
        items=grouped.get(hour,[])
        aligned=len(items)==6 and len({r["timestamp"] for r in items})==6
        status={"hour":hour,"window":window,"minute_slots":len(items)}
        for name in SOLAR:
            approved=sum(bool(r[name+"_accepted"]) for r in items)
            status[name+"_approved_10min"]=approved
            complete=aligned and approved==6
            status[name+"_qualified"]=complete
            status[name+"_kwh_m2"]=(sum(r[name] for r in items)/6000.0 if complete else None)
        status["joint_qualified"]=all(status[n+"_qualified"] for n in SOLAR)
        records[hour]=status
    return records

def build_global_hourly(year_rows,window):
    """Correct cross-year 10min hour semantics including the source previous/next label.

    We retain the two boundary partial hours as unqualified rather than invent
    adjacent-year observations; interior calendar hours are unaffected.
    """
    result={}
    for yr,rows in sorted(year_rows.items()):
        hrs=hourly_aggregate(rows,window,yr)
        for t,x in hrs.items():
            if t in result:raise ValueError("Overlapping ten-minute source year hours")
            result[t]=x
    return result

def nasa_reference(path):
    report=path/"p6_3e_hourly_solar_components_arad_science_audit.json"
    source=path/"p6_3e_native_hourly_ghi_dni_dhi_toa_physical_diagnostics.csv"
    if not report.is_file() or not source.is_file():raise FileNotFoundError("Frozen P6.3E source absent")
    info=json.loads(report.read_text(encoding="utf8"))
    if checksum(source)!=info["output_file_sha256"][source.name] or \
       info["production_epw_ready"] is not False:
        raise ValueError("Source frozen NASA POWER P6.3E original SHA/physics gate mismatch")
    allvals={}
    with source.open("r",newline="",encoding="utf8") as inp:
        for r in csv.DictReader(inp):
            key=(r["site"],parse_utc(r["timestamp_utc_start"]))
            if key in allvals:raise ValueError("Duplicate frozen NASA POWER UTC hour")
            if r["valid"]!="True" or r["is_satellite_not_observed_ground"]!="True":
                raise ValueError("Frozen NASA POWER ground classification/source validity drift")
            allvals[key]={"GHI":float(r[NASA_FIELDS["cglo"]]),
                          "DHI":float(r[NASA_FIELDS["chim"]])}
    if len(allvals)!=2*HOUR_COUNT:
        raise ValueError("Frozen 2-site × 2005–2014 hourly original NASA missing")
    return allvals,checksum(source)

def metric(pairs):
    if not pairs:return {"n":0,"bias":None,"mae":None,"rmse":None,"pearson_r":None}
    a=[x[0] for x in pairs];b=[x[1] for x in pairs]
    delta=[y-x for x,y in pairs]
    am=fmean(a);bm=fmean(b)
    denom=math.sqrt(sum((x-am)**2 for x in a)*sum((x-bm)**2 for x in b))
    corr=sum((x-am)*(y-bm) for x,y in pairs)/denom if len(pairs)>=30 and denom else None
    return {"n":len(pairs),"bias":fmean(delta),
            "mae":fmean(abs(d) for d in delta),
            "rmse":math.sqrt(fmean(d*d for d in delta)),
            "pearson_r":corr}

def statistics(by_station,orig,nasa):
    details=[];scores=[];qcrows=[]
    for station,ys in sorted(by_station.items()):
        for y,rows in sorted(ys.items()):
            for p in SOLAR:
                accepted=sum(r[p+"_accepted"] for r in rows)
                qcrows.append({"station_id":station,"year":y,"parameter":p,
                               "slots":len(rows),"qc_accepted":accepted,
                               "fraction":accepted/len(rows) if rows else None,
                               "flags":json.dumps(dict(sorted(Counter(
                                   str(r[p+"_flag"]) for r in rows).items())))})
        for window in WINDOWS:
            hrs=build_global_hourly(ys,window)
            for hour,rec in sorted(hrs.items()):
                for name in SOLAR:
                    record={"station_id":station,"year":hour.year,"month":hour.month,
                       "timestamp_utc":hour.isoformat(),"window":window,
                       "variable":name,
                       "original_10min_count":rec["minute_slots"],
                       "qc_accepted_10min_count":rec[name+"_approved_10min"],
                       "ground_hour_qc_approved":rec[name+"_qualified"],
                       "ground_kwh_m2_hour":rec[name+"_kwh_m2"]}
                    # Compare to both pre-registered original gridded NASA positions.
                    for site in ("graz_station30","nasa_gcm_cell"):
                        r=dict(record,nasa_location=site)
                        mod=nasa.get((site,hour))
                        r["power_kwh_m2_hour"]=mod["GHI" if name=="cglo" else "DHI"] if mod else None
                        r["power_minus_ground"]=(
                           r["power_kwh_m2_hour"]-record["ground_kwh_m2_hour"]
                           if record["ground_kwh_m2_hour"] is not None and mod is not None else None)
                        details.append(r)
            for site in ("graz_station30","nasa_gcm_cell"):
                for name in SOLAR:
                    for season,months in SEASONS.items():
                        subset=[d for d in details if d["station_id"]==station and
                                d["window"]==window and d["nasa_location"]==site and
                                d["variable"]==name and d["month"] in months]
                        pairs=[(r["ground_kwh_m2_hour"],r["power_kwh_m2_hour"]) for r in subset
                               if r["ground_hour_qc_approved"] and r["power_kwh_m2_hour"] is not None]
                        m=metric(pairs)
                        scores.append({"station_id":station,"time_hypothesis":window,
                            "nasa_location":site,"channel":name,"season":season,
                            "source_hours":len(subset),
                            "qc_verified_ground_hours":m["n"],
                            "qc_coverage_fraction":m["n"]/len(subset) if subset else None,
                            "nasa_minus_ground_bias_kwh_m2_hour":m["bias"],
                            "mae_kwh_m2_hour":m["mae"],
                            "rmse_kwh_m2_hour":m["rmse"],
                            "pearson_r":m["pearson_r"],
                            "timestamp_semantics":"UNRESOLVED_REPORT_BOTH",
                            "ground_measurement_provenance":"GEOSPHERE_KLIMA_V2_10MIN_ORIGINAL_QC",
                            "nasa_is_ground_observed":False})
    return qcrows,scores,details

def run(out,p6e,years=YEARS):
    out.mkdir(parents=True,exist_ok=True)
    meta_url=GEO+"/metadata"
    original,meta=get_original(meta_url)
    (out/"geosphere_klima_v2_10min_original_metadata.json").write_bytes(original)
    specs,legend,stations=metadata_contract(meta)
    frozen={}
    for name in PARAMS:
        frozen[name]={"unit":specs[name].get("unit"),
                      "description":specs[name].get("desc",specs[name].get("long_name")),
                      "code_list_ref":specs[name].get("code_list_ref")}
    nasa,nasa_sha=nasa_reference(p6e)
    by_station={};source=[];failures=[]
    for station in STATIONS:
        if station not in stations:
            failures.append({"station_id":station,"failure":"ABSENT_FROM_ORIGINAL_10MIN_METADATA"})
            continue
        year_map={}
        for y in years:
            url=GEO+"?"+urlencode({"parameters":",".join(PARAMS),"station_ids":str(station),
                "start":f"{y}-01-01T00:00","end":f"{y}-12-31T23:50","output_format":"geojson"})
            try:
                payload,obj=get_original(url)
                rows,tally=decode_year(obj,station,y)
            except Exception as err:
                failures.append({"station_id":station,"year":y,
                                 "failure":type(err).__name__+": "+str(err)[:1200]})
                print("P6.3F 10MIN FAILED",station,y,str(err)[:150],flush=True)
                continue
            original_path=out/f"original_geosphere_10min_station{station}_{y}.geojson.gz"
            with gzip.open(original_path,"wb",compresslevel=6,mtime=0) as f:
                f.write(payload)
            digest=hashlib.sha256(payload).hexdigest()
            source.append({"station_id":station,"year":y,
                 "original_url":url,"uncompressed_original_sha256":digest,
                 "source_file":original_path.name,"raw_record_count":len(rows),
                 "cglo_qc_good_10min":tally["cglo"]["approved_slots"],
                 "chim_qc_good_10min":tally["chim"]["approved_slots"]})
            year_map[y]=rows
            print("P6.3F 10MIN",station,y,"samples",len(rows),
                  "GHI qualified",tally["cglo"]["approved_slots"],
                  "DHI qualified",tally["chim"]["approved_slots"],flush=True)
        if year_map:by_station[station]=year_map
    # Independent NASA stats are only computable for accepted native observations.
    if by_station:
        qcs,stats,rows=statistics(by_station,meta,nasa)
        output={
            "p6_3f_geosphere_10min_annual_qc.csv":qcs,
            "p6_3f_geosphere_10min_nasa_seasonal_validation.csv":stats,
            "p6_3f_geosphere_10min_hourly_pairwise.csv":rows,
            "p6_3f_geosphere_10min_source_hashes.csv":source}
        sha={name:save_union(out/name,v) for name,v in output.items()}
    else:
        sha={}
    status=("PASS_OPEN_10MIN_ORIGINAL_QC_WITH_LIMITATIONS"
            if len(source)==len(STATIONS)*len(years) else
            "PARTIAL_OR_UNAVAILABLE_ORIGINAL_STATION_SOURCE")
    available={s:sorted(d) for s,d in by_station.items()}
    report={"stage":"IGE_P6_3F_GEOSPHERE_OPEN_TEN_MINUTE_SOLAR_QC",
      "technical_status":status,
      "scientific_status":"QC_HOURLY_OBSERVED_GHI_DHI_SOURCE_REVIEW_REQUIRED",
      "provider":"GeoSphere Austria historical klima-v2-10min CC BY 4.0",
      "provider_metadata_url":meta_url,
      "provider_metadata_sha256":hashlib.sha256(original).hexdigest(),
      "original_metadata_parameters":frozen,
      "original_qc_legend":legend,
      "station_metadata":{str(s):stations.get(s) for s in STATIONS},
      "requested_stations":STATIONS,"requested_years":list(years),
      "fetched_station_years":available,
      "failures":failures,
      "timestamp_interpretation":"UNRESOLVED: both 10-min source record-start and source record-end hourly mean hypotheses retained; do not choose by best fit",
      "original_data_license":"CC BY 4.0 (provider dataset metadata)",
      "geosphere_research_observation_qc_accepted_codes":sorted(QC_ACCEPTED),
      "nasa_p6e_source_original_sha256":nasa_sha,
      "numeric_results_status":"COMPUTED_FROM_ACTUAL_QC_APPROVED_SAMPLES_ONLY" if sha else "NONE",
      "derived_file_sha256":sha,
      "remaining_limits":[
        "chim (Himmelsstrahlung) interpreted as diffuse horizontal sky radiation; confirm instrument/spec metadata for use as measured DHI.",
        "Observed 10-minute instrument mean timestamp window convention must be confirmed before definitive 1h comparison.",
        "Only complete 6/6 independently QC-approved 10-minute channel observations qualify as observed 1h energy; neither missing data nor q=0 is imputed.",
        "Independent direct-normal radiation is NOT measured by cglo/chim: derived DNI cannot become independently measured DNI.",
        "NASA POWER is independent gridded satellite/reanalysis, not measured station data.",
        "Only station-specific direct original data and provider QC flags establish temporal and geographic availability; metadata dates alone do not.",
        "P6.3E original satellite internal source closure and P6.3F observed QC are different validation types.",
        "A historical independent solar validation does NOT certify physically coherent future hourly EPW."],
      "production_epw_ready":False}
    (out/"p6_3f_open_10min_scientific_audit.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False,default=str)+"\n",encoding="utf8")
    print("P6.3F OPEN TEN MIN SCIENCE",status,
          "fetched years",sum(len(x) for x in by_station.values()),
          "source errors",len(failures),"EPW_READY False",flush=True)
    return report

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--p6e-frozen",type=Path,required=True)
    parser.add_argument("--years",nargs="+",type=int,default=list(YEARS))
    a=parser.parse_args()
    if any(y not in YEARS for y in a.years) or len(set(a.years))!=len(a.years):
        raise ValueError("P6.3F pilot years must be unique and in 2005–2014")
    run(a.out,a.p6e_frozen,a.years)
