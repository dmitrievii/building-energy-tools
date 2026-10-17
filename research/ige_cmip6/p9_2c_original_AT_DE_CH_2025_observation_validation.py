#!/usr/bin/env python3
"""P9.2C independently observed AT/DE/CH original 2025 station T and RH audit.

Reanalysis-driven *retrospective* downscaling, not a CMIP6 future validation:
2025 daily conditional targets are derived from ERA5 2025, not station data.
One frozen seed, no parameter training to original station errors. Original
DWD/GEO/MeteoSwiss QC semantics retained; never create a missing RH measurement.
All station-source hourly values remain private within CI; aggregates only.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,io,json,math,re,statistics,urllib.parse,zipfile
from collections import Counter
from pathlib import Path

import p9_1b_geosphere_original_station_holdouts as at
import p9_1g_dwd_original_2019_observations as de
import p8_1e_swiss_external as ch
from p9_2a_real_era5_at_de_ch_pilot import original_days
from p9_2a_joint_weather_regimes import sampler
from p9_2c_physical_donor_and_humidity import generate as physical_generate
from p9_2b_cmip6_daily_joint_regime_solver import SIGMA,q_of_e,sat_pa

PERIODS=(("January","2025-01-10","2025-01-16"),
         ("July","2025-07-10","2025-07-16"))
SEED=7313
MIN=96
STATIONS={"AT":30,"DE":3730,"CH":"DAV"}
FIELD_MAP={"T2m":"temperature_2m","RH2m":"relative_humidity_2m"}

def hour_stamps(start):
    t=dt.datetime.fromisoformat(start+"T00:00")
    return [(t+dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(168)]

def _obs_geo_parameters(response,parameter,flag):
    result={}
    stamps=[dt.datetime.fromisoformat(str(t).replace("Z","+00:00")).astimezone(
        dt.timezone.utc).strftime("%Y-%m-%dT%H:%M") for t in response["timestamps"]]
    if len(stamps)!=168 or len(set(stamps))!=168:
        raise ValueError("P92C_AT_ORIGINAL_168_UTC_HOUR_AXIS_INVALID")
    for f in response["features"]:
        params=f["properties"]["parameters"]
        vals=params[parameter]["data"];flags=params[flag]["data"]
        if len(vals)!=168 or len(flags)!=168:
            raise ValueError("P92C_AT_NATIVE_QC_HOUR_ARRAY_LENGTH_INVALID")
        for ts,v,q in zip(stamps,vals,flags):
            if v is not None and q in at.GOOD_FLAGS:
                if ts in result:raise ValueError("P92C_AT_DUPLICATE_SENSOR_UTC_HOUR")
                try:val=float(v)
                except ValueError:continue
                if math.isfinite(val):result[ts]=val
    return result

def observations_AT():
    meta,meta_sha=at.source_json(at.BASE+"/metadata")
    stations={int(x["id"]):x for x in meta["stations"]}
    station=stations[STATIONS["AT"]]
    params={p["name"]:p for p in meta["parameters"]}
    assert {"tl","tl_flag"}.issubset(params)
    humid_ok={"rf","rf_flag"}.issubset(params)
    site={"country":"AT","station":"Graz","latitude":float(station["lat"]),
          "longitude":float(station["lon"]),"original_metadata_SHA256":meta_sha}
    output={}
    for name,start,end in PERIODS:
        packet={"station_ids":str(STATIONS["AT"]),"start":start+"T00:00Z",
                "end":end+"T23:00Z","output_format":"geojson"}
        for val,flag,key in [("tl","tl_flag","T2m"),("rf","rf_flag","RH2m")]:
            if (val,flag)==("rf","rf_flag") and not humid_ok:
                output[(name,key)]={"values":{},"status":"ORIGINAL_GEOSPHERE_RH_OR_QC_NOT_IN_METADATA",
                                    "qc_tier":"NOT_AVAILABLE","sha256":None}
                continue
            packet["parameters"]=val+","+flag
            obj,sha=at.source_json(at.BASE+"?"+urllib.parse.urlencode(packet))
            arr=_obs_geo_parameters(obj,val,flag)
            arr={t:v for t,v in arr.items() if (-90<v<65 if key=="T2m" else 0<=v<=100)}
            output[(name,key)]={"values":arr,"status":"ORIGINAL_SOURCE_READ",
                       "qc_tier":"GeoSphere_"+flag+"_native_goodflags","sha256":sha}
    return site,output

def observations_DE():
    id=STATIONS["DE"]
    listing=de.get_original(de.ROOT,maximum=1500000).decode("utf8",errors="replace")
    station_meta=de.get_original(de.ROOT+"TU_Stundenwerte_Beschreibung_Stationen.txt",maximum=1200000)
    site=None
    for line in station_meta.decode("latin1").splitlines():
        p=line.split(maxsplit=6)
        if len(p)==7 and p[0].isdigit() and int(p[0])==id:
            if p[1]>"20250110" or p[2]<"20250716":
                raise ValueError("P92C_DE_NATIVE_STATION_COVERAGE_NOT_2025")
            site={"country":"DE","station":"Oberstdorf","latitude":float(p[4]),
                "longitude":float(p[5]),
                "original_metadata_SHA256":hashlib.sha256(station_meta).hexdigest()}
    if site is None:raise ValueError("P92C_DWD_FIXED_STATION_NOT_IN_ORIGINAL_METADATA")
    matches=set(re.findall(rf"stundenwerte_TU_{id:05d}_(\d{{8}})_(\d{{8}})_hist\.zip",listing,re.I))
    eligible=sorted((a,b) for a,b in matches if a<="20250110" and b>="20250716")
    if len(eligible)!=1:raise ValueError("P92C_DWD_2025_REGISTERED_ARCHIVE_COVERAGE_NOT_UNIQUE_"+str(eligible))
    a,b=eligible[0]
    raw=de.get_original(de.ROOT+f"stundenwerte_TU_{id:05d}_{a}_{b}_hist.zip",maximum=16*1024*1024)
    digest=hashlib.sha256(raw).hexdigest()
    expected={n:set(hour_stamps(st)) for n,st,_ in PERIODS}
    out={};buffers={(n,k):{} for n,_,_ in PERIODS for k in FIELD_MAP}
    hist={n:Counter() for n,_,_ in PERIODS}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() is not None:raise ValueError("P92C_DWD_ORIGINAL_CRC_ERROR")
        names=[x for x in z.namelist() if x.startswith("produkt_tu_stunde_") and x.endswith(".txt")]
        if len(names)!=1:raise ValueError("P92C_DWD_NATIVE_PRODUCT_MEMBER_NOT_UNIQUE")
        fields=io.TextIOWrapper(z.open(names[0]),encoding="latin1")
        reader=csv.DictReader(fields,delimiter=";")
        if not {"MESS_DATUM","STATIONS_ID","QN_9","TT_TU","RF_TU"}.issubset(reader.fieldnames or ()):
            raise ValueError("P92C_DWD_RF_TU_AND_TT_TU_WITH_NATIVE_QC_REQUIRED")
        for line in reader:
            ts=line["MESS_DATUM"].strip()
            try:t=dt.datetime.strptime(ts,"%Y%m%d%H").strftime("%Y-%m-%dT%H:%M")
            except ValueError:continue
            n=next((n for n in expected if t in expected[n]),None)
            if n is None:continue
            if int(line["STATIONS_ID"])!=id:raise ValueError("P92C_DWD_FOREIGN_STATION")
            qc=int(line["QN_9"]);hist[n][qc]+=1
            if qc not in (3,10):continue
            for key,rawkey in (("T2m","TT_TU"),("RH2m","RF_TU")):
                x=line.get(rawkey,"").strip()
                if x in ("","-999","-999.0"):continue
                try:v=float(x)
                except ValueError:continue
                if not math.isfinite(v) or not (-90<v<65 if key=="T2m" else 0<=v<=100):continue
                if t in buffers[(n,key)]:raise ValueError("P92C_DE_DUPLICATE_ORIGINAL_HOUR")
                buffers[(n,key)][t]=(v,qc)
    for n,_,_ in PERIODS:
        for key in FIELD_MAP:
            cells=buffers[(n,key)]
            tier="DWD_QN9_3_AUTOMATIC_QC_NOT_EQUIVALENT_QN10"
            if cells and all(q==10 for v,q in cells.values()):
                tier="DWD_QN9_10_FULL_NATIVE_QC"
            out[(n,key)]={"values":{t:v for t,(v,q) in cells.items()},
                "status":"ORIGINAL_SOURCE_READ","qc_tier":tier,
                "native_QN9_counts":dict(hist[n]),"sha256":digest}
    return site,out

def observations_CH():
    meta_url="https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/ogd-smn_meta_stations.csv"
    raw,meta_sha=ch.fetch(meta_url,max_bytes=14_000_000)
    s,cols=ch.parse_meta(raw)
    ss=s[STATIONS["CH"]]
    site={"country":"CH","station":"Davos","latitude":ss["lat"],
          "longitude":ss["lon"],"original_metadata_SHA256":meta_sha}
    url=f"https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/dav/ogd-smn_dav_h_historical_2020-2029.csv"
    file,sha=ch.fetch(url,max_bytes=150*1024*1024)
    rows,cols=ch.decode_csv(file)
    temp=ch.pick_col(cols,"tre200h0")
    humid=ch.pick_col(cols,"ure200h0")
    stamp=ch.pick_col(cols,"reference_timestamp")
    ident=ch.pick_col(cols,"station_abbr","station")
    if not temp or not stamp:
        raise ValueError("P92C_CH_NATIVE_T_AND_UTC_TIME_NOT_PROVEN")
    expected={n:set(hour_stamps(st)) for n,st,_ in PERIODS}
    got={(n,key):{} for n,_,_ in PERIODS for key in FIELD_MAP}
    for r in rows:
        if ident and (r.get(ident) or "").upper()!=STATIONS["CH"]:
            raise ValueError("P92C_CH_NATIVE_STATION_MISMATCH")
        try:t=dt.datetime.strptime(r[stamp],"%d.%m.%Y %H:%M").strftime("%Y-%m-%dT%H:%M")
        except (TypeError,ValueError):continue
        n=next((n for n in expected if t in expected[n]),None)
        if n is None:continue
        for key,column in (("T2m",temp),("RH2m",humid)):
            if not column:continue
            v=(r.get(column) or "").strip()
            if v in ("","-","-999","NaN","-9999"):continue
            try:v=float(v)
            except ValueError:continue
            if not math.isfinite(v) or not (-90<v<65 if key=="T2m" else 0<=v<=100):continue
            if t in got[(n,key)]:raise ValueError("P92C_CH_DUPLICATED_NATIVE_HOUR")
            got[(n,key)][t]=v
    out={}
    for n,_,_ in PERIODS:
        for key in FIELD_MAP:
            available=(key=="T2m" or humid is not None)
            out[(n,key)]={"values":got[(n,key)] if available else {},
                "status":"ORIGINAL_PUBLISHED_OGD_HOURLY" if available else "CH_NATIVE_URE200H0_UNAVAILABLE",
                "qc_tier":"MeteoSwiss_PUBLISHED_HOURLY_QC_PER_SAMPLE_NOT_CERTIFIED" if available else "NOT_AVAILABLE",
                "timestamp_semantics":"UTC_END_OF_PRECEDING_INTERVAL",
                "sha256":sha}
    return site,out

def era_daily_source_constraint(day):
    """Explicit ERA5 daily hindcast forcing, with NO native LW field in P9.1A.

    The LW surrogate here only enables *T/RH* model diagnostics and is NEVER
    scored nor called CMIP6, measured, or full crossfield science closure.
    """
    v=day.vectors
    T=[x["temperature_2m"] for x in v]
    q=[q_of_e(sat_pa(x["dew_point_2m"]),x["surface_pressure"]*100) for x in v]
    lw=[]
    for x in v:
        epsilon=min(1.1,max(.4,.60+.0025*x["relative_humidity_2m"]+
                                 .0015*x["cloud_cover"]))
        lw.append(epsilon*SIGMA*(x["temperature_2m"]+273.15)**4)
    return {"date":day.date,"tas_c":statistics.fmean(T),
            "tasmin_c":min(T),"tasmax_c":max(T),
            "hurs":statistics.fmean(x["relative_humidity_2m"] for x in v),
            "huss":statistics.fmean(q),
            "pr_mm_day":sum(x["precipitation"] for x in v),
            "rsds_kwh_m2_day":sum(x["shortwave_radiation"] for x in v)/1000,
            "rlds_kwh_m2_day":sum(lw)/1000, # surrogate NOT observationally qualified
            "sfcWind":statistics.fmean(x["wind_speed_10m"] for x in v)}

def metric(measured,pred,times):
    pairs=[(measured[t],pred[t]) for t in times if t in measured and t in pred]
    if len(pairs)<MIN:return None
    errors=[p-o for o,p in pairs]
    return {"n":len(errors),"MAE":statistics.fmean(abs(e) for e in errors),
            "RMSE":math.sqrt(statistics.fmean(e*e for e in errors)),
            "bias":statistics.fmean(errors)}

def run(output):
    output.mkdir(parents=True,exist_ok=True)
    report={"phase":"P9_2C_ORIGINAL_2025_REGIONAL_OBS_QC_INDEPENDENT_MEASUREMENTS",
       "preregistered_sites":STATIONS,"eval_year":2025,"donor_years":[2019,2020],
       "registered_windows":PERIODS,"seed":SEED,
       "2025_conditional_daily_targets_are_ERA5_reanalysis_NOT_original_CMIP6":True,
       "2025_conditional_daily_forcing_NOT_an_independent_future_forecast":True,
       "LW_2025_hindcast_only_surrogate_UNQUALIFIED":True,
       "station_measured_RH_missing_stays_missing":True,
       "original_measured_rain_cloud_LW_qualifications_NOT_PERFORMED":True,
       "production_epw_ready":False,"rows":[],"country_sources":{}}
    for country,source in (("AT",observations_AT),("DE",observations_DE),("CH",observations_CH)):
        try:
            site,observed=source()
            report["country_sources"][country]={"status":"ORIGINAL_SOURCE_READ",
                     "latitude":site["latitude"],"longitude":site["longitude"],
                     "original_metadata_sha256":site["original_metadata_SHA256"]}
        except Exception as e:
            reason=f"{type(e).__name__}: {e}"[:500]
            report["country_sources"][country]={"status":"PROVIDER_OR_QC_SOURCE_BLOCKED","reason":reason}
            print("P92C_OBS_PROVIDER_BLOCKED",country,reason,flush=True)
            for season,_,_ in PERIODS:
                for var in FIELD_MAP:
                    report["rows"].append({"country":country,"season":season,"variable":var,
                        "status":"ORIGINAL_PROVIDER_SOURCE_BLOCKED","reason":reason,
                        "n_QC_hourly_original":0})
            continue
        for season,start,end in PERIODS:
            reference={};meta=[];orig=[];error=None
            try:
                for year in (2019,2020,2025):
                    days,src=original_days(site["latitude"],site["longitude"],
                                           year,season,start[5:],end[5:])
                    if year==2025:reference=days
                    else:orig.extend(days)
                    meta.append({"year":year,
                        "original_ERA5_OpenMeteo_SHA256":src["original_provider_http_SHA256"]})
                dates=[x.date for x in reference]
                simple=sampler(orig,dates,SEED,"joint_day_blocks")
                conditioned,blocked=physical_generate(
                    [era_daily_source_constraint(x) for x in reference],
                    orig,site["latitude"],site["longitude"],seed=SEED)
                reference_map={f"{d.date.isoformat()}T{h:02d}:00":x for d in reference
                               for h,x in enumerate(d.vectors)}
                analog_map={f"{d.date.isoformat()}T{h:02d}:00":x for d in simple
                             for h,x in enumerate(d.vectors)}
                cond_map={f"{d.date.isoformat()}T{h:02d}:00":x for d,_,info in conditioned
                           for h,x in enumerate(d.vectors)}
                print("P92C_2025_CONDITIONAL_GENERATOR",country,season,json.dumps({
                    "n_reference_ERA5":len(reference_map),"n_P92A":len(analog_map),
                    "n_P92C":len(cond_map),"blocked_days":blocked,
                    "n_RH_exact_days":sum(m["hurs_joint_status"]=="FEASIBLE_BOTH_Q_AND_RH"
                                           for d,lw,m in conditioned)}),flush=True)
            except Exception as e:
                error=f"{type(e).__name__}: {e}"[:420]
                reference_map=analog_map=cond_map={}
                blocked=[]
                print("P92C_GENERATION_BLOCKED",country,season,error,flush=True)
            times=hour_stamps(start)
            for var,key in FIELD_MAP.items():
                o=observed.get((season,var),{"values":{},"qc_tier":"NOT_AVAILABLE",
                                            "status":"MEASUREMENT_NOT_PRESENT","sha256":None})
                v=o["values"]
                # Only identical measured original hours where all three
                # variants have generated actual finite predictions: no
                # preferential removal of poorly-performing/model-blocked days.
                baseline={t:x[key] for t,x in reference_map.items()}
                old={t:x[key] for t,x in analog_map.items()}
                new={t:x[key] for t,x in cond_map.items()}
                common=[t for t in times if t in v and t in baseline and t in old and t in new]
                base_metrics=metric(v,baseline,common)
                old_metrics=metric(v,old,common)
                new_metrics=metric(v,new,common)
                result={"country":country,"season":season,"variable":var,
                        "n_nominal_hours":168,"n_QC_hourly_original":len(v),
                        "n_common_support":len(common),"original_QC_tier":o["qc_tier"],
                        "original_observation_source_SHA256":o["sha256"],
                        "original_observation_status":o["status"],
                        "ERA5_original_reanalysis_2025":base_metrics,
                        "P92A_joint_original_analog_2019_2020":old_metrics,
                        "P92C_physical_donor_ERA5_daily_conditioned":new_metrics,
                        "blocked_generator_days":blocked,
                        "source_meta":meta}
                if error:result["generation_blocker"]=error
                result["status"]=("SCORED_ON_IDENTICAL_ORIGINAL_STATION_QC_HOURS" if new_metrics
                                  else "ORIGINAL_QC_OR_GENERATION_INSUFFICIENT")
                if new_metrics:
                    result["P92C_MAE_minus_unadjusted_ERA5"]=new_metrics["MAE"]-base_metrics["MAE"]
                    result["P92C_MAE_minus_P92A_day_analog"]=new_metrics["MAE"]-old_metrics["MAE"]
                    if country=="CH":
                        # Same nominal timestamp is one predetermined first
                        # semantic comparison; shifted case is diagnostic,
                        # never chosen as post-hoc best reported method.
                        shift={t:(dt.datetime.fromisoformat(t)+dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
                               for t in times}
                        aligned={t:v[shift[t]] for t in times if shift[t] in v}
                        alternate=[t for t in times if t in aligned and t in baseline and t in old and t in new]
                        result["CH_end_time_shift_minus_one_hour_sensitivity"]={
                           "B0":metric(aligned,baseline,alternate),
                           "P92A":metric(aligned,old,alternate),
                           "P92C":metric(aligned,new,alternate)}
                report["rows"].append(result)
                print("P92C_REAL_STATION_QC_RESULT",json.dumps({
                    "country":country,"season":season,"variable":var,
                    "native_QC":o["qc_tier"],"n_source":len(v),"n_common":len(common),
                    "status":result["status"],
                    "MAE_B0":base_metrics["MAE"] if base_metrics else None,
                    "MAE_A":old_metrics["MAE"] if old_metrics else None,
                    "MAE_C":new_metrics["MAE"] if new_metrics else None,
                    "delta_vs_B0":result.get("P92C_MAE_minus_unadjusted_ERA5")
                }),flush=True)
    qualified=[x for x in report["rows"] if x["status"]=="SCORED_ON_IDENTICAL_ORIGINAL_STATION_QC_HOURS"]
    report["n_registered_country_season_variable_cases"]=12
    report["n_original_observed_variable_cases_scored"]=len(qualified)
    report["n_scored_temperature_cases"]=sum(x["variable"]=="T2m" for x in qualified)
    report["n_scored_RH_cases"]=sum(x["variable"]=="RH2m" for x in qualified)
    report["n_P92C_worse_than_B0"]=sum(x["P92C_MAE_minus_unadjusted_ERA5"]>1e-6 for x in qualified)
    report["n_P92C_worse_than_original_day_donors"]=sum(x["P92C_MAE_minus_P92A_day_analog"]>1e-6 for x in qualified)
    report["original_station_independent_hours_paired_per_variable"]=sum(x["n_common_support"] for x in qualified)
    report["no_C_P9_2C_release_qualification"]=True
    file=output/"p9_2c_original_2025_AT_DE_CH_hourly_station_temperatures_and_RH_aggregate.json"
    file.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    print("P92C_FINAL",json.dumps({"scored":len(qualified),
        "temp":report["n_scored_temperature_cases"],"RH":report["n_scored_RH_cases"],
        "n_pairs":report["original_station_independent_hours_paired_per_variable"],
        "worse_vs_ERA5":report["n_P92C_worse_than_B0"],
        "production":False}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",default="outputs/p92c-original-2025")
    run(Path(p.parse_args().out))
