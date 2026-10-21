"""One frozen AT/DE/CH source preflight -> sealed predictions -> scoring.

Private source/cache files are never artifacts. Only aggregate scores and hashes
are public. An unavailable source/cell stays in the preregistered denominator.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request
import zipfile

import numpy as np

from p9_3b3_generator import from_legacy_day,generate
from p9_3b3_joint_solver import SolverPolicy
from p9_3b3_pressure_reference import station_pressure
from p9_3b3_source_semantics import DailyTarget,SourceSemantics
from p9_3b3_thermodynamics import saturation,q_from_e,relative_humidity

PERIODS=(("winter","2021-02-01","2021-02-14"),("summer","2021-08-01","2021-08-14"))
SITES={"AT":{"id":"30","lat":47.0707,"lon":15.4395},
       "DE":{"id":"00399","lat":52.5198,"lon":13.4057},
       "CH":{"id":"DAV","lat":46.801,"lon":9.830}}
SEEDS=(7313,7314,7315,7316,7317)
ALLOWED_HOSTS={"opendata.dwd.de","dataset.api.hub.geosphere.at","data.geo.admin.ch",
               "archive-api.open-meteo.com"}


def protocol_guard():
    path=Path(__file__).with_name("p9_3b3_frozen_protocol.json")
    raw=path.read_bytes();p=json.loads(raw)
    if p["countries"]!=["AT","DE","CH"] or p["validation_windows_UTC"]!=[[s,e] for _,s,e in PERIODS]:
        raise ValueError("P93B3_PROTOCOL_COHORT_DRIFT")
    if p["training_years"]!=[2019,2020] or (p["primary_seed"],*p["diagnostic_seeds"])!=SEEDS:
        raise ValueError("P93B3_PROTOCOL_DONOR_OR_SEED_DRIFT")
    relevant={"T","p","q","RH","e"}
    for exposure in p["exposure_registry"]:
        if not relevant.intersection(exposure["variables"]):continue
        if 2021 in exposure.get("years",[]) and "windows" not in exposure:
            raise ValueError("P93B3_RELEVANT_YEAR_ALREADY_EXPOSED")
        for start,end in exposure.get("windows",[]):
            if any(not (e<start or s>end) for _,s,e in PERIODS):
                raise ValueError("P93B3_RELEVANT_HOLDOUT_WINDOW_ALREADY_EXPOSED")
    return hashlib.sha256(raw).hexdigest()


def repair_protocol_guard():
    raw=Path(__file__).with_name("p9_3b3_repair_protocol.json").read_bytes();p=json.loads(raw)
    if (p["countries"]!=["AT","DE","CH"] or p["windows"]!=[[s,e] for _,s,e in PERIODS] or
            p["baseline_run"]!=39493440318 or p["pressure_B4_qualified"] or p["production_epw_ready"] or
            p["MSL_candidate_constants"]!={"gravity_m_s2":9.80665,"Rd_J_kg_K":287.05,"lapse_K_m":.0065} or
            p["window_status"]!="REVEALED_IN_BASELINE_RUN_REGRESSION_ONLY_NO_RENEWED_HOLDOUT"):
        raise ValueError("P93B3_REPAIR_PROTOCOL_DRIFT")
    return hashlib.sha256(raw).hexdigest()


def sha_file(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_sealed(path,digest):
    if sha_file(path)!=digest:raise ValueError("P93B3_SEALED_INPUT_DIGEST_CHANGED")
    return json.loads(Path(path).read_text())


class SourceCache:
    def __init__(self,path):
        self.root=Path(path);self.root.mkdir(parents=True,exist_ok=True)
        self.downloaded=0

    def fetch(self,url,limit=160_000_000):
        if urllib.parse.urlsplit(url).hostname not in ALLOWED_HOSTS or not url.startswith("https://"):
            raise ValueError("P93B3_SOURCE_HOST_NOT_ALLOWED")
        p=self.root/(hashlib.sha256(url.encode()).hexdigest()+".bin")
        if p.exists():return p.read_bytes()
        errors=[]
        for _ in range(2):
            try:
                request=urllib.request.Request(url,headers={"User-Agent":"IGE-P9.3B3-source-preflight"})
                with urllib.request.urlopen(request,timeout=20) as response:
                    if urllib.parse.urlsplit(response.geturl()).hostname not in ALLOWED_HOSTS:
                        raise ValueError("P93B3_SOURCE_REDIRECT_NOT_ALLOWED")
                    b=response.read(limit+1)
                if len(b)>limit or self.downloaded+len(b)>500_000_000:
                    raise ValueError("P93B3_SOURCE_DOWNLOAD_BUDGET_EXCEEDED")
                self.downloaded+=len(b);p.write_bytes(b)
                return b
            except (OSError,ValueError) as exc:errors.append(str(exc))
        raise OSError("P93B3_SOURCE_BLOCKED_"+" | ".join(errors))


def timestamps(start,end):
    s=dt.datetime.fromisoformat(start);e=dt.datetime.fromisoformat(end)+dt.timedelta(days=1)
    return [(s+dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(int((e-s).total_seconds()/3600))]


def _period(stamp):
    return next((name for name,start,end in PERIODS if start<=stamp[:10]<=end),None)


def empty_observations(country,reason=None):
    return {"country":country,"site":dict(SITES[country]),"status":"SOURCE_BLOCKED" if reason else "SOURCE_READ",
            "reason":reason,"cells":{name:{"T2m":{},"RH2m":{},"p_hPa":{}} for name,_,_ in PERIODS},
            "provenance":[],"native_qc":{},"time_support":"UNKNOWN"}


def observations_AT(cache):
    base="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h"
    raw=cache.fetch(base+"/metadata",14_000_000);meta=json.loads(raw)
    site=next(s for s in meta["stations"] if int(s["id"])==30)
    fields={p["name"]:p for p in meta["parameters"]}
    if fields.get("tl",{}).get("unit") not in ("°C","degC") or fields.get("p",{}).get("unit")!="hPa":
        raise ValueError("P93B3_AT_NATIVE_UNIT_CHANGED")
    if fields.get("rf",{}).get("unit")!="%":raise ValueError("P93B3_AT_RH_UNIT_CHANGED")
    out=empty_observations("AT")
    out["site"].update(lat=float(site["lat"]),lon=float(site["lon"]),height_m=float(site["altitude"]))
    out["time_support"]="PROVIDER_1H_NATIVE_SUPPORT_NOT_INDEPENDENTLY_CERTIFIED"
    out["provenance"].append({"url":base+"/metadata","sha256":hashlib.sha256(raw).hexdigest()})
    good={10,11,12,20,21,22}
    for period,start,end in PERIODS:
        params={"station_ids":"30","parameters":"tl,tl_flag,rf,rf_flag,p,p_flag", "output_format":"geojson",
                "start":start+"T00:00Z","end":end+"T23:00Z"}
        url=base+"?"+urllib.parse.urlencode(params);raw=cache.fetch(url,14_000_000);obj=json.loads(raw)
        if len(obj["features"])!=1:raise ValueError("P93B3_AT_STATION_COUNT_CHANGED")
        obs=obj["features"][0]["properties"]["parameters"]
        stamps=[dt.datetime.fromisoformat(t.replace("Z","+00:00")).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M") for t in obj["timestamps"]]
        if stamps!=timestamps(start,end):raise ValueError("P93B3_AT_SOURCE_TIME_AXIS")
        for field,key in (("tl","T2m"),("rf","RH2m"),("p","p_hPa")):
            values=obs[field]["data"];qc=obs[field+"_flag"]["data"]
            if len(values)!=len(stamps) or len(qc)!=len(stamps):raise ValueError("P93B3_AT_ARRAY_LENGTH")
            out["native_qc"][period+"_"+key]=dict(Counter(map(str,qc)))
            for ts,v,flag in zip(stamps,values,qc):
                if v is None or flag not in good:continue
                v=float(v)
                valid=math.isfinite(v) and (-95<v<65 if key=="T2m" else (0<=v<=105 if key=="RH2m" else 450<v<1100))
                if valid:out["cells"][period][key][ts]=v
        out["provenance"].append({"url":url,"sha256":hashlib.sha256(raw).hexdigest()})
    out["qc_tier"]="GEOSPHERE_NATIVE_VARIABLE_GOOD_FLAGS"
    return out


def _dwd_archive(cache,product,pattern):
    root="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate_urban/10_minutes/"+product+"/historical/"
    raw=cache.fetch(root,2_000_000)
    names=sorted(set(re.findall(pattern,raw.decode("utf8","replace"))))
    eligible=[n for n in names if re.search(r"_(\d{8})_(\d{8})_hist",n).group(1)<= "20210201"
              and re.search(r"_(\d{8})_(\d{8})_hist",n).group(2)>= "20210814"]
    if len(eligible)!=1:raise ValueError("P93B3_DWD_FROZEN_00399_ARCHIVE_NOT_UNIQUE")
    url=root+eligible[0];b=cache.fetch(url,30_000_000)
    z=zipfile.ZipFile(io.BytesIO(b))
    if z.testzip() is not None:raise ValueError("P93B3_DWD_CRC_ERROR")
    members=[n for n in z.namelist() if Path(n).name.startswith("produkt") and n.endswith(".txt")]
    if len(members)!=1:raise ValueError("P93B3_DWD_PRODUCT_AMBIGUOUS")
    reader=csv.DictReader(io.TextIOWrapper(z.open(members[0]),encoding="latin1"),delimiter=";")
    # Materialize selected-window rows only, never emit raw values in artifacts.
    selected=[]
    cols=[s.strip() for s in (reader.fieldnames or [])]
    for row in reader:
        row={k.strip():v.strip() for k,v in row.items() if k is not None}
        stamp=row.get("MESS_DATUM","")
        if len(stamp)!=12 or not stamp.endswith("00"):continue
        when=dt.datetime.strptime(stamp,"%Y%m%d%H%M").strftime("%Y-%m-%dT%H:%M")
        if _period(when):
            if int(row["STATIONS_ID"])!=399:raise ValueError("P93B3_DWD_OTHER_STATION")
            selected.append((when,row))
    return selected,{"url":url,"sha256":hashlib.sha256(b).hexdigest(),"native_columns":cols}


def observations_DE(cache):
    out=empty_observations("DE")
    out["time_support"]="ORIGINAL_10MIN_HH00_INSTANT_NO_LAG_SELECTION"
    out["qc_tier"]="DWD_NATIVE_QN_PRESERVED_EMPTY_IS_NOT_FINAL_QC"
    # Station geometry is source metadata only, never inferred from measured p.
    url=("https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
         "climate_urban/10_minutes/pressure/historical/zehn_st_min_p0_Beschreibung_Stationen.txt")
    try:
        from p9_3b2d_original_DWD_urban_2023_pressure_holdout import parse_station_metadata
        raw=cache.fetch(url,1_000_000);meta=parse_station_metadata(raw)
        out["site"].update(lat=meta["lat"],lon=meta["lon"],height_m=meta["station_height_m"])
        out["provenance"].append({"url":url,"sha256":hashlib.sha256(raw).hexdigest()})
    except (OSError,ValueError) as exc:
        out["metadata_blocker"]=str(exc)
    products=(("pressure",r"10minutenwerte_P0_STADT_00399_\d{8}_\d{8}_hist\.zip"),
              ("air_temperature",r"10minutenwerte_TU_STADT_00399_\d{8}_\d{8}_hist\.zip"))
    for product,pattern in products:
        try:
            rows,prov=_dwd_archive(cache,product,pattern)
            required=("P0_ST_10","PP_ST_10","QN") if product=="pressure" else ("TT_ST_10","RF_ST_10","QN")
            if not set(required)<=set(prov["native_columns"]):
                raise ValueError("P93B3_DWD_SOURCE_SCHEMA_NOT_CERTIFIED_"+product)
            for ts,row in rows:
                period=_period(ts)
                out["native_qc"].setdefault(period+"_"+product,Counter())[row.get("QN","")]+=1
                if product=="pressure":
                    v,_=station_pressure(row,"DWD_URBAN_10MIN")
                    values={"p_hPa":None if v is None else v/100}
                else:
                    values={}
                    for key,field in (("T2m","TT_ST_10"),("RH2m","RF_ST_10")):
                        try:v=float(row[field])
                        except ValueError:continue
                        if math.isfinite(v) and (-95<v<65 if key=="T2m" else 0<=v<=105):values[key]=v
                for key,v in values.items():
                    if v is None:continue
                    if ts in out["cells"][period][key]:raise ValueError("P93B3_DWD_DUPLICATE_HOUR")
                    out["cells"][period][key][ts]=v
            out["provenance"].append(prov)
        except (OSError,ValueError,zipfile.BadZipFile) as exc:
            out.setdefault("source_blockers",[]).append({"product":product,"reason":str(exc)})
    return out


def observations_CH(cache):
    import p8_1e_swiss_external as ch
    md="https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/ogd-smn_meta_stations.csv"
    raw=cache.fetch(md,12_000_000);sites,_=ch.parse_meta(raw);site=sites["DAV"]
    url="https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/dav/ogd-smn_dav_h_historical_2020-2029.csv"
    b=cache.fetch(url,160_000_000)
    out=empty_observations("CH");out["site"].update(lat=site["lat"],lon=site["lon"],height_m=site["hoehe_m"])
    out["time_support"]="PRECEDING_HOUR_MEAN_END_STAMP"
    out["qc_tier"]="PUBLISHED_SOURCE_NO_COMPARABLE_PER_SAMPLE_QC"
    out["provenance"]=[{"url":md,"sha256":hashlib.sha256(raw).hexdigest()},
                       {"url":url,"sha256":hashlib.sha256(b).hexdigest()}]
    reader=csv.DictReader(io.StringIO(b.decode("utf-8-sig")),delimiter=";")
    cols={c.strip():c for c in (reader.fieldnames or [])}
    needed={"reference_timestamp","tre200h0","ure200h0","prestah0","station_abbr"}
    if not needed<=set(cols):raise ValueError("P93B3_CH_NATIVE_VARIABLES_MISSING")
    for row in reader:
        row={k.strip():v.strip() for k,v in row.items() if k is not None}
        try:ts=dt.datetime.strptime(row["reference_timestamp"],"%d.%m.%Y %H:%M").strftime("%Y-%m-%dT%H:%M")
        except ValueError:continue
        period=_period(ts)
        if not period:continue
        if row["station_abbr"].upper()!="DAV":raise ValueError("P93B3_CH_OTHER_STATION")
        for key,field in (("T2m","tre200h0"),("RH2m","ure200h0"),("p_hPa","prestah0")):
            try:v=float(row[field])
            except ValueError:continue
            if not math.isfinite(v) or not (-95<v<65 if key=="T2m" else (0<=v<=105 if key=="RH2m" else 450<v<1100)):continue
            if ts in out["cells"][period][key]:raise ValueError("P93B3_CH_DUPLICATE_HOUR")
            out["cells"][period][key][ts]=v
    return out


def preflight(cache,out):
    """Schema/coverage/QC only; no model errors or observation values exported."""
    protocol_sha=protocol_guard()
    repair_sha=repair_protocol_guard()
    private={};summary={}
    for country,fn in (("AT",observations_AT),("DE",observations_DE),("CH",observations_CH)):
        try:o=fn(cache)
        except (OSError,ValueError,KeyError,zipfile.BadZipFile) as exc:o=empty_observations(country,str(exc))
        private[country]=o
        summary[country]={k:v for k,v in o.items() if k!="cells"}
        summary[country]["coverage"]={name:{key:len(a) for key,a in values.items()} for name,values in o["cells"].items()}
    path=cache.root/"observations_PRIVATE_DO_NOT_PUBLISH.json"
    path.write_text(json.dumps(private,sort_keys=True,allow_nan=False))
    report={"stage":"SOURCE_ONLY_PREFLIGHT_NO_MODEL_SCORING","periods":PERIODS,"protocol_sha256":protocol_sha,
            "repair_protocol_sha256":repair_sha,"previously_revealed_2021_windows":True,
            "expected_site_hours":2016,"cells":summary,"countries":["AT","DE","CH"],
            "pressure_model_qualified":False,"production_epw_ready":False}
    Path(out).write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    return path,report


def _era5(cache,lat,lon,start,end):
    import p9_1a_global_historical_backbone as era
    from p9_2a_joint_weather_regimes import canonical_days
    url=era.request_url(lat,lon,start,end);raw=cache.fetch(url,12_000_000)
    obj,arrays,meta=era.parse_source(raw,lat,lon,start,end)
    return canonical_days([s+"Z" for s in obj["hourly"]["time"]],arrays,
                           meta["raw_original_response_sha256"]),meta


def coherent_target(day):
    T=np.array([v["temperature_2m"]+273.15 for v in day.vectors])
    P=np.array([v["surface_pressure"]*100 for v in day.vectors])
    q=q_from_e(saturation([v["dew_point_2m"]+273.15 for v in day.vectors]),P)
    R=relative_humidity(T,P,q)
    if np.max(R)>100+1e-6:raise ValueError("P93B3_REFERENCE_NODES_WATER_SUPERSATURATED")
    sem=SourceSemantics("TIME_MEAN_TAS","WATER",calendar="gregorian",
                        time_support="DECLARED_NODE_QUADRATURE_COHERENT_TEST",verified=True,
                        source="ERA5_DERIVED_COHERENT_NODE_DIAGNOSTICS_NOT_NATIVE_NEX")
    return DailyTarget(day.date.isoformat(),float(T.min()),float(T.max()),float(T.mean()),
                       float(q.mean()),float(np.mean(R)),sem)


def _hour_predictions(days):
    result={}
    for d in days:
        if "T_K" not in d:continue
        if len(d["T_K"])!=24:raise ValueError("P93B3_HOURLY_SCORER_REQUIRES_24_NODES")
        for hour in range(len(d["T_K"])):
            stamp=d["date"]+f"T{hour:02d}:00"
            result[stamp]={"T2m":d["T_K"][hour]-273.15,
                           "RH2m":d["diagnostics"]["RH_source_pct"][hour],"p_hPa":d["p_Pa"][hour]/100,
                           "e_hPa":d["diagnostics"]["e_Pa"][hour]/100,"q_gkg":d["q_kgkg"][hour]*1000}
    return result


def _assert_pressure_alignment(hourly,references):
    if references is None:return
    for stamp,row in hourly.items():
        day=stamp[:10];hour=int(stamp[11:13])
        if day not in references or abs(row["p_hPa"]*100-references[day].values_Pa[hour])>1e-7:
            raise AssertionError("P93B3_MODEL_OR_CONTROL_DID_NOT_USE_IDENTICAL_TARGET_DAY_PRESSURE")


def score_frozen(manifest):
    """Only sealed files. No network or generator access during scoring."""
    if not manifest.get("frozen_before_scoring") or manifest.get("countries")!=["AT","DE","CH"]:
        raise ValueError("P93B3_UNFROZEN_OR_OUT_OF_SCOPE_VALIDATION")
    if not re.fullmatch(r"[0-9a-f]{40}",manifest.get("algorithm_commit","")):
        raise ValueError("P93B3_ALGORITHM_COMMIT_NOT_FROZEN")
    preds=read_sealed(manifest["predictions_path"],manifest["predictions_sha256"])
    obs=read_sealed(manifest["observations_path"],manifest["observations_sha256"])
    cells=[];daily=defaultdict(dict);paired=defaultdict(dict);structure=[]
    members={(m["country"],m["period"],m["method"],m["seed"]):m for m in preds["members"]}
    if len(members)!=len(preds["members"]):raise ValueError("P93B3_DUPLICATE_SCORING_MEMBER")
    expected_members=[]
    for c in ("AT","DE","CH"):
        for period,_,_ in PERIODS:
            for method in ("B3_STRICT","B3_RECONCILED_RESEARCH","P93A_DAILY_CONTROL","FULL_HOURLY_ERA5_RICH_REFERENCE"):
                for seed in ((7313,) if method.startswith("FULL_") else SEEDS):
                    expected_members.append(members.get((c,period,method,seed),{
                        "country":c,"period":period,"method":method,"seed":seed,"hourly":{}}))
    for member in expected_members:
        country,period=member["country"],member["period"]
        source=obs[country];expected=336
        ordered=sorted(member["hourly"])
        if ordered:
            a=np.array([[member["hourly"][ts][k] for k in ("T2m","RH2m","e_hPa","q_gkg")] for ts in ordered])
            spells=[];length=0;previous=None;seams=[]
            for ts,row in zip(ordered,a):
                current=dt.datetime.fromisoformat(ts)
                if previous is not None and current-previous!=dt.timedelta(hours=1):
                    if length:spells.append(length)
                    length=0
                if row[1]>=90:length+=1
                elif length:spells.append(length);length=0
                if previous and current-previous==dt.timedelta(hours=1) and current.hour==0:
                    seams.append(abs(member["hourly"][ts]["T2m"]-member["hourly"][previous.strftime("%Y-%m-%dT%H:%M")]["T2m"]))
                previous=current
            if length:spells.append(length)
            corr=lambda col:float(np.corrcoef(a[:,0],a[:,col])[0,1]) if np.std(a[:,0])>0 and np.std(a[:,col])>0 else None
            structure.append({"country":country,"period":period,"method":member["method"],"seed":member["seed"],
                "n_generated_nodes":len(a),"water_saturated_fraction":float(np.mean(a[:,1]>=99.995)),
                "RH_ge90_spell_lengths_hours":spells,"T_e_correlation":corr(2),"T_RH_correlation":corr(1),
                "temperature_seam_max_K":max(seams) if seams else None,
                "T_p05_p50_p95_C":np.quantile(a[:,0],[.05,.5,.95]).tolist(),
                "q_p05_p50_p95_gkg":np.quantile(a[:,3],[.05,.5,.95]).tolist(),
                "source_modified_days":member.get("n_source_modified",0)})
        for key in ("T2m","RH2m","p_hPa","e_hPa","q_gkg"):
            original=dict(source["cells"][period].get(key,{}))
            if key in ("e_hPa","q_gkg"):
                common=set(source["cells"][period]["T2m"])&set(source["cells"][period]["RH2m"])
                if key=="q_gkg":common&=set(source["cells"][period]["p_hPa"])
                for ts in common:
                    e=float(saturation(source["cells"][period]["T2m"][ts]+273.15))*source["cells"][period]["RH2m"][ts]/100
                    original[ts]=e/100 if key=="e_hPa" else float(q_from_e(e,source["cells"][period]["p_hPa"][ts]*100))*1000
            errors=[];group=defaultdict(list);error_by_hour={}
            for ts,true in original.items():
                pred=member["hourly"].get(ts)
                if pred is None:continue
                val=pred[key]
                if source["time_support"]=="PRECEDING_HOUR_MEAN_END_STAMP":
                    prev=(dt.datetime.fromisoformat(ts)-dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
                    if prev not in member["hourly"]:continue
                    val=(val+member["hourly"][prev][key])/2
                err=val-true;errors.append(err);group[ts[:10]].append(abs(err));error_by_hour[ts]=abs(err)
            r={"country":country,"period":period,"method":member["method"],"seed":member["seed"],
               "variable":key,"expected_hours":expected,"source_hours":len(original),"matched_hours":len(errors),
               "qc_tier":source.get("qc_tier","UNKNOWN"),"time_support":source["time_support"],
               "derived_from_station_T_RH_p_not_independent_q_sensor":key in ("e_hPa","q_gkg"),
               "status":"SCORED_LIMITED_SOURCE_SUPPORT" if len(errors)>=.9*expected else "SOURCE_OR_GENERATION_COVERAGE_BLOCKED"}
            if errors:
                a=np.asarray(errors)
                r.update(MAE=float(np.mean(abs(a))),RMSE=float(np.sqrt(np.mean(a*a))),bias=float(np.mean(a)))
            if key=="p_hPa":
                r["pressure_MAE_gate_hPa"]=2.0
                r["pressure_accuracy_gate"]=("INCONCLUSIVE_COVERAGE" if len(errors)<.9*expected
                    else "PASS_THIS_CELL_ONLY" if r["MAE"]<=2.0 else "FAIL_THIS_CELL")
            cells.append(r)
            if member["seed"]==7313:
                paired[(country,period,key)][member["method"]]=error_by_hour
    for (country,period,key),methods in paired.items():
        b3=methods.get("B3_STRICT",{});old=methods.get("P93A_DAILY_CONTROL",{})
        common=set(b3)&set(old)
        for method,values in (("B3_STRICT",b3),("P93A_DAILY_CONTROL",old)):
            byday=defaultdict(list)
            for ts in sorted(common):byday[ts[:10]].append(values[ts])
            for day,vals in byday.items():daily[(country,period,key,day)][method]=float(np.mean(vals))
    comparisons=[]
    for country in ("AT","DE","CH"):
        for key,margin in (("T2m",.1),("RH2m",.5),("q_gkg",.05)):
            delta=[v["B3_STRICT"]-v["P93A_DAILY_CONTROL"] for (c,_,k,_),v in daily.items()
                   if c==country and k==key and {"B3_STRICT","P93A_DAILY_CONTROL"}<=set(v)]
            if len(delta)<14:
                comparisons.append({"country":country,"variable":key,"status":"INCONCLUSIVE_INSUFFICIENT_PAIRED_DAYS"});continue
            rng=np.random.default_rng(20261020);a=np.asarray(delta)
            boot=np.mean(a[rng.integers(0,len(a),(2000,len(a)))],axis=1)
            ci=np.quantile(boot,[.025,.975]).tolist()
            comparisons.append({"country":country,"variable":key,"n_days":len(a),"delta_MAE":float(a.mean()),
                "CI95":ci,"margin":margin,"status":"NONINFERIOR_LIMITED_DIAGNOSTIC" if ci[1]<margin else "FAIL_OR_INCONCLUSIVE"})
    return {"stage":"ONE_FROZEN_AT_DE_CH_2021_COMPARISON","cells":cells,"comparisons":comparisons,"generated_structure":structure,
            "expected_site_hours":2016,"independent_accuracy":"INCONCLUSIVE_SOURCE_SUPPORT_AND_LIMITED_COHORT",
            "station_RH_phase_for_derived_e_q":"DECLARED_WATER_NOT_PROVIDER_CERTIFIED_ALL_SITES",
            "station_e_q_from_hourly_means_are_nonlinear_proxies_not_native_mean_q_measurements":True,
            "hourly_accuracy_is_reconstruction_not_weather_forecast":True,
            "pressure_model_qualified":False,"operational_ready":False,"production_epw_ready":False}


def _generate_days(targets,donors,seed,wet_by_date,policy,reconcile=False,pressure_by_date=None):
    if pressure_by_date is None:
        return generate(targets,donors,seed=seed,wet_by_date=wet_by_date,policy=policy,reconcile=reconcile)
    # Equal conditioning for the unchanged control adapter: each day is an
    # independent reconstruction, with no previous-day selection for either.
    rows=[];summary=None
    for t in targets:
        r,summary=generate([t],donors,seed=seed,wet_by_date=wet_by_date,policy=policy,reconcile=reconcile,
                           pressure_by_date={t.date:pressure_by_date[t.date]})
        rows.extend(r)
    return rows,{**summary,"total":len(rows),"counts":dict(Counter(r["status"] for r in rows)),
                 "selection_conditioning":"INDEPENDENT_DAYS_NO_PREVIOUS_DAY_SELECTION"}


def run(cache_dir,out,pressure_mode="TARGET_DAY_GRID"):
    if pressure_mode not in ("TARGET_DAY_GRID","DONOR_GRID_LEGACY"):
        raise ValueError("P93B3_UNREGISTERED_PRESSURE_ALIGNMENT_MODE")
    from p9_3b3_pressure_diagnostics import (target_day_references,with_legacy_pressure,
        source_msl,pressure_candidates,score_pressure_diagnostics)
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    cache=SourceCache(cache_dir)
    obs_path,pre=preflight(cache,out/"source_preflight.json")
    predictions={"members":[],"blocked":[],"pressure_diagnostics":[],"pressure_diagnostic_blockers":[]}
    # Observations are never arguments of the generator; only original metadata
    # site coordinates and source availability summaries enter this stage.
    for country in ("AT","DE","CH"):
        site=pre["cells"][country]["site"]
        for name,start,end in PERIODS:
            try:
                donors=[];legacy_donors=[]
                for yr in (2019,2020):
                    ds,_=_era5(cache,site["lat"],site["lon"],str(yr)+start[4:],str(yr)+end[4:])
                    legacy_donors.extend(ds);donors.extend(from_legacy_day(d,frame=f"ERA5_GRID_{country}") for d in ds)
                reference,meta=_era5(cache,site["lat"],site["lon"],start,end)
                targets=[coherent_target(d) for d in reference]
                pressure_refs=target_day_references(reference,meta,country) if pressure_mode=="TARGET_DAY_GRID" else None
                try:
                    msl,msmeta=source_msl(cache,site["lat"],site["lon"],start,end,meta)
                    candidate=pressure_candidates(reference,site,msl,msmeta)
                    predictions["pressure_diagnostics"].append({"country":country,"period":name,**candidate})
                except (OSError,ValueError,KeyError) as exc:
                    predictions["pressure_diagnostic_blockers"].append({"country":country,"period":name,"reason":str(exc)})
                wet={d.date.isoformat():any(v["precipitation"]>0 for v in d.vectors) for d in reference}
                for seed in SEEDS:
                    generated,summary=_generate_days(targets,donors,seed,wet,SolverPolicy(lower_bound_seconds=.25),
                                                     pressure_by_date=pressure_refs)
                    _assert_pressure_alignment(_hour_predictions(generated),pressure_refs)
                    predictions["members"].append({"country":country,"period":name,"method":"B3_STRICT",
                        "seed":seed,"summary":summary,"hourly":_hour_predictions(generated),
                        "source_canonical_sha256":meta["canonical_hourly_weather_and_selected_cell_sha256"]})
                    reconciled=[]
                    for t,r in zip(targets,generated):
                        if r["status"]=="EXACT_DEFINED_OPERATORS":reconciled.append(r)
                        else:
                            rr,_=_generate_days([t],donors,seed,wet,SolverPolicy(lower_bound_seconds=.25),reconcile=True,
                                                pressure_by_date=pressure_refs)
                            reconciled.extend(rr)
                    predictions["members"].append({"country":country,"period":name,"method":"B3_RECONCILED_RESEARCH",
                        "seed":seed,"hourly":_hour_predictions(reconciled),
                        "n_source_modified":sum(bool(r.get("source_modified")) for r in reconciled),
                        "reconciliation_science_qualified":False})
                    # Baseline is deliberately richer than an unconstrained analogue,
                    # but receives the same daily diagnostics and 2019/20 donor pool.
                    from p9_3a_pressure_temperature_q_joint import generate as old_generate
                    from p9_3b3_thermodynamics import e_from_q
                    old_targets=[]
                    for d,t in zip(reference,targets):
                        v=d.vectors
                        old_targets.append({"date":d.date,"tas_c":t.tas_K-273.15,"tasmin_c":t.Tmin_K-273.15,
                            "tasmax_c":t.Tmax_K-273.15,"huss":t.q_mean_kgkg,"hurs":t.RH_mean_pct,
                            "pr_mm_day":sum(x["precipitation"] for x in v),
                            "rsds_kwh_m2_day":sum(x["shortwave_radiation"] for x in v)/1000,
                            "rlds_kwh_m2_day":float(np.mean([.8*5.670374419e-8*(x["temperature_2m"]+273.15)**4 for x in v]))*.024,
                            "sfcWind":float(np.mean([x["wind_speed_10m"] for x in v]))})
                    if pressure_refs is None:
                        good,bad=old_generate(old_targets,legacy_donors,site["lat"],site["lon"],seed)
                    else:
                        good=[];bad=[]
                        for t,old_target in zip(targets,old_targets):
                            ds=[with_legacy_pressure(d,pressure_refs[t.date]) for d in legacy_donors]
                            g,b=old_generate([old_target],ds,site["lat"],site["lon"],seed)
                            good.extend(g);bad.extend(b)
                    converted=[]
                    for day,lw,info in good:
                        td=from_legacy_day(day)
                        T=np.asarray(td.T_K);P=np.asarray(td.pressure.values_Pa);q=np.asarray(td.q_kgkg)
                        converted.append({"date":td.date,"T_K":list(td.T_K),"p_Pa":list(td.pressure.values_Pa),"q_kgkg":q.tolist(),
                            "diagnostics":{"RH_source_pct":[x["relative_humidity_2m"] for x in day.vectors],"e_Pa":e_from_q(q,P).tolist()}})
                    _assert_pressure_alignment(_hour_predictions(converted),pressure_refs)
                    predictions["members"].append({"country":country,"period":name,"method":"P93A_DAILY_CONTROL",
                        "seed":seed,"hourly":_hour_predictions(converted),"blocked":len(bad),"LW_proxy_not_qualified":True})
                rich=[]
                for day,t in zip(reference,targets):
                    d=from_legacy_day(day);T=np.asarray(d.T_K);p=np.asarray(d.pressure.values_Pa);q=np.asarray(d.q_kgkg)
                    rich.append({"date":d.date,"T_K":T.tolist(),"p_Pa":p.tolist(),"q_kgkg":q.tolist(),
                        "diagnostics":{"RH_source_pct":[x["relative_humidity_2m"] for x in day.vectors],"e_Pa":e_from_q(q,p).tolist()}})
                predictions["members"].append({"country":country,"period":name,"method":"FULL_HOURLY_ERA5_RICH_REFERENCE",
                                               "seed":7313,"hourly":_hour_predictions(rich)})
            except (OSError,ValueError,KeyError) as exc:
                predictions["blocked"].append({"country":country,"period":name,"reason":str(exc)})
    pp=cache.root/"predictions_PRIVATE_DO_NOT_PUBLISH.json"
    pp.write_text(json.dumps(predictions,sort_keys=True,allow_nan=False))
    algorithm=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    manifest={"frozen_before_scoring":True,"algorithm_commit":algorithm,"countries":["AT","DE","CH"],
        "periods":PERIODS,"seeds":SEEDS,"observations_path":str(obs_path.resolve()),"observations_sha256":sha_file(obs_path),
        "predictions_path":str(pp.resolve()),"predictions_sha256":sha_file(pp),
        "policy_sha256":SolverPolicy(lower_bound_seconds=.25).fingerprint,
        "protocol_sha256":pre["protocol_sha256"],"repair_protocol_sha256":pre.get("repair_protocol_sha256"),"pressure_mode":pressure_mode,
        "evaluation_role":"PREVIOUSLY_REVEALED_2021_REGRESSION_AFTER_REPAIR"}
    # Write seal before scorer opens the private observations.
    seal=cache.root/"frozen_scoring_manifest.json";seal.write_text(json.dumps(manifest,sort_keys=True))
    score=score_frozen(manifest)
    score["pressure_diagnostics"]=score_pressure_diagnostics(predictions["pressure_diagnostics"],
        read_sealed(manifest["observations_path"],manifest["observations_sha256"]))
    score["pressure_diagnostic_blockers"]=predictions["pressure_diagnostic_blockers"]
    score["pressure_source_provenance"]=[{k:v for k,v in x.items() if k!="hourly"}
                                        for x in predictions["pressure_diagnostics"]]
    score["pressure_mode"]=pressure_mode
    score["previously_revealed_2021_windows"]=True
    score["evaluation_role"]=manifest["evaluation_role"]
    score["independent_accuracy"]="NOT_REESTABLISHED_AFTER_REPAIR_REVEALED_COHORT"
    for comparison in score["comparisons"]:
        comparison["evidence_role"]="REVEALED_REGRESSION_DIAGNOSTIC_NO_RENEWED_HOLDOUT"
    score["daily_selection_conditioning"]=("INDEPENDENT_DAYS_BOTH_METHODS" if pressure_mode=="TARGET_DAY_GRID" else "LEGACY_SEQUENTIAL_DAYS")
    score["blocked_generation_cells"]=predictions["blocked"]
    score["sealed_manifest_sha256"]=sha_file(seal)
    score["algorithm_commit"]=algorithm
    (out/"independent_station_aggregate.json").write_text(json.dumps(score,indent=2,allow_nan=False)+"\n")
    return score


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--cache",required=True);ap.add_argument("--out",required=True)
    ap.add_argument("--pressure-mode",choices=("TARGET_DAY_GRID","DONOR_GRID_LEGACY"),default="TARGET_DAY_GRID")
    a=ap.parse_args();result=run(a.cache,a.out,a.pressure_mode)
    print("P93B3_AT_DE_CH",json.dumps({"cells":len(result["cells"]),"independent_accuracy":result["independent_accuracy"]}))
