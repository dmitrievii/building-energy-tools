"""Compact, immutable numerical cache from verified native downloader parts."""
from __future__ import annotations

import calendar
import collections
import csv
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from ige_local.common import HOUR, InputError, digest, file_hash, fingerprint, iso, log, stamp, write_json
from ige_local.readers import cells, checked_metadata, qc_allowed, relevant_parts, timestamps, valid_geometry
from .config import data_signature, native_config

NATIVE = ["T","RH","p"]
ALL_VARIABLES = ["T","RH","p","log_e_water"]


def rank_key(seed, *parts):
    return hashlib.sha256((str(seed)+"|"+"|".join(map(str,parts))).encode()).hexdigest()


def choose_and_split(stations, available, c):
    selected, role, folds, notes = [], {}, {}, []
    for country in c["countries"]:
        groups = collections.defaultdict(list)
        for key in sorted(available):
            s = stations[key]
            if s["country"]==country and valid_geometry(s) and s["height_m"] is not None:
                groups[s["family"]].append(key)
        families = sorted(groups, key=lambda f:(np.mean([stations[k]["height_m"] for k in groups[f]]),f))
        limit = c["sites_per_country"] or len(families)
        if len(families)>limit:
            ix = np.linspace(0,len(families)-1,limit).round().astype(int)
            families = [families[i] for i in ix]
        if len(families)<9:
            notes.append({"country":country,"status":"INSUFFICIENT_FAMILIES","families":len(families),"minimum":9})
            continue
        families.sort(key=lambda f:rank_key(c["split_seed"],country,f))
        n=len(families); nv=max(1,round(n*c["split_fractions"]["V"])); nc=max(1,round(n*c["split_fractions"]["C"]))
        nd=n-nv-nc
        if nd<6 or nd<=c["inner_folds"]:
            notes.append({"country":country,"status":"INSUFFICIENT_D_FAMILIES","families":n})
            continue
        for i,f in enumerate(families):
            role[f] = "D" if i<nd else "V" if i<nd+nv else "C"
            if i<nd: folds[f]=i%c["inner_folds"]
            selected.extend(groups[f])
    return sorted(set(selected)),role,folds,notes


def buck_water(t):
    t=np.asarray(t,dtype=float)
    with np.errstate(over="ignore",invalid="ignore",divide="ignore"):
        return 6.1121*np.exp((18.678-t/234.5)*t/(257.14+t))


def build(snapshot, c, output, audit_summary=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if snapshot.get("snapshot_id")!=digest({k:v for k,v in snapshot.items() if k!="snapshot_id"}):
        raise InputError("E0 snapshot identity mismatch")
    native=native_config(c)
    if snapshot["config_sha256"]!=digest(native):
        raise InputError("E0 snapshot belongs to a different automatic-regression data selection")
    stations,variants={},set(); parts=[]
    for run in snapshot["runs"]:
        for s in run["stations"]:
            old=stations.get(s["key"])
            if old and any(old[k]!=s[k] for k in ("lat","lon","height_m","family","station_type")):
                variants.add(s["key"])
            stations[s["key"]]=s
        parts.extend((run,key,rec,a) for key,rec,a in relevant_parts(run,native))
    available={x[1] for x in parts}-variants
    keys,roles,folds,notes=choose_and_split(stations,available,c)
    if variants:
        notes.append({"status":"CONFLICTING_STATION_METADATA_EXCLUDED","station_keys":sorted(variants)})
    if not keys:
        raise InputError("No country has enough independent completed station families for D/V/C and inner validation; see source readiness")
    times=timestamps(native);si={k:i for i,k in enumerate(keys)};ti={t:i for i,t in enumerate(times)}
    shape=(len(keys),len(times),len(ALL_VARIABLES))
    bytes_estimate=int(np.prod(shape))*26
    if bytes_estimate>c["memory_budget_bytes"]//2:
        raise InputError("Numerical cache exceeds half the configured memory budget; reduce sites/years/sample days")
    split={"schema":"IGE_AUTO_SPLIT_v1","data_signature":data_signature(c),"source_snapshot_id":snapshot["snapshot_id"],
           "stations":[stations[k] for k in keys],"family_roles":roles,"inner_folds":folds,"times":times,
           "time_roles":[next(r for r,ys in c["years"].items() if stamp(t).year in ys) for t in times],
           "selection":"metadata-only height quantiles and seeded family split; no weather/error-based selection",
           "notes":notes,"geometry":"published_station_geometry_proxy_not_verified_historical_sensor_heights"}
    split["split_id"]=digest(split);write_json(output/"split.sealed.json",split)
    values=np.full(shape,np.nan);operators=np.zeros(shape,dtype=np.int32);qc=np.zeros(shape,dtype=np.int32)
    sources=np.zeros(shape,dtype=np.int32);eligible=np.zeros(shape,dtype=bool)
    priority=np.full(shape,127,dtype=np.int8);conflict=np.zeros(shape,dtype=bool)
    op_book=["unknown"];op_lookup={"unknown":0};qc_book=[{"code":"unknown","stratum":"unknown","eligible":False}];qc_lookup={}
    source_book=[{"status":"no_source"}];derived_source_lookup={};seen=set();counts=collections.Counter();errors=[]
    qc_cfg={"rejected_native_qc":c["rejected_native_qc"]}
    for run,key,rec,a in parts:
        if key not in si or (a["path"],a["sha256"]) in seen:continue
        seen.add((a["path"],a["sha256"]));log("Regression input: "+key+" / "+Path(a["path"]).name)
        try:
            if fingerprint(a["path"])!=a["fingerprint"] or file_hash(a["path"])!=a["sha256"]:
                raise InputError("CSV changed since audit")
            meta=checked_metadata(rec);j=rec["job"];pending=[];previous=None
            with gzip.open(a["path"],"rt",encoding="utf-8-sig",newline="") as f:
                reader=csv.DictReader(f)
                if reader.fieldnames!=a["columns"]:raise InputError("CSV header changed")
                for row in reader:
                    counts["native_rows_scanned"]+=1
                    if None in row or any(v is None for v in row.values()):raise InputError("Malformed CSV row")
                    if not row.get("timestamp_utc"):
                        counts["unresolved_time_rows"]+=1;continue
                    t=stamp(row["timestamp_utc"])
                    if previous is not None and t<=previous:raise InputError("Duplicate/unsorted native timestamps")
                    previous=t
                    country=run["country"];sid=stations[key]["station_id"]
                    if country=="AT" and (row.get("station_id")!=sid or not stamp(j["start"])<=t<=stamp(j["end"])):
                        raise InputError("AT row identity/period mismatch")
                    if country=="DE" and row.get("STATIONS_ID","").zfill(5)!=sid:raise InputError("DWD station mismatch")
                    if country=="CH" and row.get("station_abbr","").strip().upper()!=sid:raise InputError("CH station mismatch")
                    if not stamp(run["start"])<=t<stamp(run["end_exclusive"]):raise InputError("Row outside plan")
                    time_key=iso(t)
                    if time_key not in ti:continue
                    for variable,obs in cells(country,run,rec,row,t,meta,counts):
                        qkey=(country,obs["qc"])
                        if qkey not in qc_lookup:
                            qc_lookup[qkey]=len(qc_book);qc_book.append({"country":country,"code":obs["qc"],"stratum":obs["qc_stratum"],
                                "eligible":qc_allowed(country,obs["qc"],c["qc_mode"],qc_cfg)})
                        op=op_lookup.get(obs["operator"])
                        if op is None:op=len(op_book);op_lookup[obs["operator"]]=op;op_book.append(obs["operator"])
                        pending.append((ti[time_key],NATIVE.index(variable),obs["value"],op,qc_lookup[qkey]))
            if fingerprint(a["path"])!=a["fingerprint"]:raise InputError("CSV changed during parsing")
            source_id=len(source_book);source_book.append({"path":a["path"],"sha256":a["sha256"],"plan_id":run["plan_id"],
                "job_id":j["job_id"],"exposure":"AUTOMATED_READ_NATIVE_CONTAINER; no blind-raw claim"})
            pri={"historical":0,"recent":1,"now":2,"row":2}.get(j.get("type",j.get("tier")),0)
            for tid,v,value,op,qid in pending:
                slot=(si[key],tid,v);x=np.nan if value is None else value
                if pri>priority[slot] or (conflict[slot] and pri>=priority[slot]):continue
                if pri==priority[slot] and sources[slot]:
                    same=(np.isnan(x) and np.isnan(values[slot]) or x==values[slot]) and operators[slot]==op and qc[slot]==qid
                    if same:counts["identical_duplicate_cells"]+=1;continue
                    values[slot]=np.nan;operators[slot]=0;eligible[slot]=False;conflict[slot]=True;counts["conflicting_cells"]+=1;continue
                values[slot]=x;operators[slot]=op;qc[slot]=qid;sources[slot]=source_id;priority[slot]=pri;conflict[slot]=False
                eligible[slot]=np.isfinite(x) and qc_book[qid]["eligible"]
        except (OSError,ValueError,KeyError,TypeError,EOFError,csv.Error) as exc:
            errors.append({"source":a["path"],"error":str(exc)})
    if "log_e_water" in c["variables"]:
        # This is an explicitly derived quantity, never named independently observed e.
        for s in range(len(keys)):
            t,rh=values[s,:,0],values[s,:,1];es=buck_water(t);e=rh*es/100
            valid=eligible[s,:,0]&eligible[s,:,1]&(e>0)&np.isfinite(e)&np.isfinite(es)
            with np.errstate(invalid="ignore",divide="ignore"):values[s,:,3]=np.where(valid,np.log(e),np.nan)
            eligible[s,:,3]=valid
            for h in range(len(times)):
                if operators[s,h,0]==0 or operators[s,h,1]==0:continue
                opname="DERIVED_WATER:"+str(operators[s,h,0])+":"+str(operators[s,h,1])
                if opname not in op_lookup:op_lookup[opname]=len(op_book);op_book.append(opname)
                operators[s,h,3]=op_lookup[opname]
                qkey=(int(qc[s,h,0]),int(qc[s,h,1]))
                if qkey not in qc_lookup:
                    qc_lookup[qkey]=len(qc_book);qc_book.append({"code":"derived_T_RH", "stratum":"derived("+qc_book[qkey[0]]["stratum"]+","+qc_book[qkey[1]]["stratum"]+")","eligible":bool(qc_book[qkey[0]]["eligible"] and qc_book[qkey[1]]["eligible"])})
                qc[s,h,3]=qc_lookup[qkey]
                pair=(int(sources[s,h,0]), int(sources[s,h,1]))
                if pair not in derived_source_lookup:
                    # Separate provenance book: both input artifacts survive derivation.
                    derived_source_lookup[pair]=len(source_book)
                    source_book.append({"status":"DERIVED_T_RH","input_source_ids":list(pair)})
                sources[s,h,3]=derived_source_lookup[pair]
    arrays={"values":values,"operators":operators,"qc":qc,"sources":sources,"eligible":eligible}
    hashes={}
    for name,array in arrays.items():
        np.save(output/(name+".npy"),array,allow_pickle=False);hashes[name+".npy"]=file_hash(output/(name+".npy"))
    metadata=split|{"schema":"IGE_AUTO_CUBE_v1","variables":ALL_VARIABLES,"array_shape":list(shape),"array_hashes":hashes,
        "operator_codebook":op_book,"qc_codebook":qc_book,"source_codebook":source_book,"source_errors":errors,
        "read_counts":dict(counts),"derived_variable_contract":"log_e_water=ln(RH*Buck_water(T)/100), hPa reference; T/RH QC jointly required; not independent measured vapour",
        "estimated_array_bytes":bytes_estimate,
        "source_audit":{k:audit_summary[k] for k in ("countries","plan_errors","discovery_notes")} if audit_summary else None}
    metadata["cube_id"]=digest(metadata);write_json(output/"metadata.json",metadata)
    return output


class Cube:
    def __init__(self,path,verify=True):
        self.path=Path(path).resolve();self.meta=json.loads((self.path/"metadata.json").read_bytes())
        if self.meta.get("cube_id")!=digest({k:v for k,v in self.meta.items() if k!="cube_id"}):raise InputError("Cube metadata hash mismatch")
        if verify:
            for name,sha in self.meta["array_hashes"].items():
                if file_hash(self.path/name)!=sha:raise InputError("Cube array hash mismatch: "+name)
        for name in ("values","operators","qc","sources","eligible"):
            setattr(self,name,np.load(self.path/(name+".npy"),mmap_mode="r",allow_pickle=False))
            if list(getattr(self,name).shape) != self.meta["array_shape"]:
                raise InputError("Cube array shape mismatch: " + name)
        self.stations=self.meta["stations"];self.times=self.meta["times"]
        self.month=np.array([stamp(t).month for t in self.times]);self.years=np.array([stamp(t).year for t in self.times])
        self.phase=np.array([2*np.pi*(stamp(t).timetuple().tm_yday-1)/(366 if calendar.isleap(stamp(t).year) else 365) for t in self.times])
        self.roles=np.array([self.meta["family_roles"][s["family"]] for s in self.stations])
        self.time_roles=np.array(self.meta["time_roles"])
        self.folds=np.array([self.meta["inner_folds"].get(s["family"],-1) for s in self.stations])
