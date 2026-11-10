"""Immutable final store, atomic per-part preparation, bounded RAM, explicit QC."""
from __future__ import annotations
import collections
import csv
import datetime as dt
import gzip
import os
from pathlib import Path
import shutil
import time
import numpy as np
from ige_local.audit import audit
from ige_local.common import HOUR, UTC, InputError, digest, file_hash, fingerprint, iso, log, read_json, source_audit_failed, stamp, write_csv, write_json, distance
from ige_local.readers import cells, checked_metadata, relevant_parts, valid_geometry
from .config import anchor, data_config, native_configuration, sealed

DTYPE=np.dtype([("value","<f8"),("operator","<i4"),("qc","<i4"),("source","<i4"),("priority","i1"),("conflict","?")])
NAMES=("T","RH","p")

class Lock:
    def __init__(self,path): self.path=Path(path)
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        try: fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError: raise InputError("Another operation or an interrupted process owns "+str(self.path)+". If that process has ended, remove only this lock file and resume")
        with os.fdopen(fd,"w") as f: f.write(str(os.getpid()))
        return self
    def __exit__(self,*args): self.path.unlink(missing_ok=True)

def assign(stations, old, c):
    """Preserve original roles; co-located/new aliases cannot bypass old holdouts."""
    stations=sorted(stations,key=lambda s:s["key"])
    parent=list(range(len(stations)))
    def root(i):
        while parent[i]!=i: parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,a in enumerate(stations):
        for j in range(i):
            b=stations[j]
            if a["family"]==b["family"] or distance(a,b)<=c["donors"]["co_location_km"]:
                parent[root(i)]=root(j)
    groups=collections.defaultdict(list)
    for i,s in enumerate(stations): groups[root(i)].append(s)
    old_st=old["stations"]; roles={};folds={}
    for members in groups.values():
        linked={s["family"] for s in members}&set(old["family_roles"])
        for s in members:
            linked.update(o["family"] for o in old_st if o["key"]==s["key"] or distance(s,o)<=c["donors"]["co_location_km"])
        rr={old["family_roles"][f] for f in linked}
        if len(rr)>1: raise InputError("Co-located families have different original roles: "+str([s["key"] for s in members])+"; do not silently move original test sites")
        family=min(s["family"] for s in members)
        r=next(iter(rr)) if rr else None
        if r is None:
            u=int(digest([c["seed"],family])[:12],16)/16**12
            r="D" if u<c["split_fractions"]["D"] else ("V" if u<1-c["split_fractions"]["C"] else "C")
        fold=int(digest([c["seed"],"inner",family])[:12],16)%c["inner_folds"]
        roles[family]=r;folds[family]=fold
        for s in members: s["native_family"]=s["family"];s["family"]=family;s["role"]=r;s["fold"]=fold
    return stations,roles,folds

def _init_station(path, n):
    path.parent.mkdir(parents=True,exist_ok=True)
    a=np.lib.format.open_memmap(path,mode="w+",dtype=DTYPE,shape=(n,3))
    a["value"]=np.nan;a["operator"]=0;a["qc"]=0;a["source"]=0;a["priority"]=127;a["conflict"]=False;a.flush();del a

def merge(a,h,v,x,op,qid,source,priority,counters):
    old=a[h,v];x=np.nan if x is None else float(x)
    if priority>old["priority"] or (old["conflict"] and priority>=old["priority"]):return
    if priority==old["priority"] and old["source"]:
        same=(np.isnan(x) and np.isnan(old["value"]) or x==old["value"]) and op==old["operator"] and qid==old["qc"]
        if same:counters["identical_duplicate_cells"]+=1;return
        a[h,v]=(np.nan,0,qid,source,priority,True);counters["equal_priority_conflicts"]+=1;return
    a[h,v]=(x,op,qid,source,priority,False);counters["inserted_cells"]+=1

def recover_pending(root,state):
    pp=root/"pending.json"
    if not pp.exists():return
    p=read_json(pp);final=root/p["final"];backup=root/"part.backup.npy"
    if p["part"] not in state["done"]:
        if backup.exists():os.replace(backup,final)
        elif not p["existed"]:final.unlink(missing_ok=True)
    backup.unlink(missing_ok=True);(root/"part.work.npy").unlink(missing_ok=True);pp.unlink()

def _books(state,obs,country):
    op=obs["operator"];q={"country":country,"code":obs["qc"],"stratum":obs["qc_stratum"]}
    if op not in state["operators"]:state["operators"].append(op)
    if q not in state["qc"]:state["qc"].append(q)
    return state["operators"].index(op),state["qc"].index(q)

def prepare(c,rehash=False):
    out=Path(c["results"]);out.mkdir(parents=True,exist_ok=True)
    with Lock(out/"prepare.lock"):
        ap,old=anchor(c);native=native_configuration(c)
        snap,report=audit(native,out/"state/audit",rehash=rehash)
        if source_audit_failed(report) or any(v.get("unresolved_pending_jobs",v.get("pending_jobs",0)) for v in report["countries"].values()):
            raise InputError("Resolve incomplete or quarantined native jobs before full training; see state/audit/summary.json")
        if any(not report['countries'][country]['verified_jobs'] for country in c['countries']):raise InputError("A configured country has no verified downloader jobs")
        all_st={};variants=set();parts=[]
        for run in snap["runs"]:
            for s in run["stations"]:
                prev=all_st.get(s["key"])
                if prev and any(prev[k]!=s[k] for k in ("lat","lon","height_m","family","station_type")):variants.add(s["key"])
                all_st[s["key"]]=s
            for key,r,a in relevant_parts(run,native):parts.append((run,key,r,a))
        available={key for run,key,r,a in parts}
        chosen=[dict(s) for k,s in all_st.items() if k in available and k not in variants and valid_geometry(s) and s["height_m"] is not None]
        if not chosen:raise InputError("No station with compatible T/RH/p source parts and valid geometry")
        stations,roles,folds=assign(chosen,old,c)
        st_map={s["key"]:s for s in stations}
        unique={}
        for run,key,r,a in parts:
            if key in st_map:unique.setdefault((key,a["path"],a["sha256"]),(run,key,r,a))
        parts=[unique[k] for k in sorted(unique)]
        signature=digest({"selection":data_config(c),"stations":stations,"anchor_roles":old["family_roles"],"assets":[[k,a["path"],a["sha256"]] for run,k,r,a in parts]})
        root=out/"stores"/signature[:20];root.mkdir(parents=True,exist_ok=True)
        manifest=root/"manifest.json"
        if manifest.exists():
            store=Store(root,verify=True);log("Existing complete full-hour store verified: "+str(root));return root
        start=dt.datetime(min(y for ys in c["years"].values() for y in ys),1,1,tzinfo=UTC)
        end=dt.datetime(max(y for ys in c["years"].values() for y in ys)+1,1,1,tzinfo=UTC);n=int((end-start)/HOUR)
        expected_bytes=n*3*DTYPE.itemsize*len(stations)
        if not (root/'preparation.json').exists() and shutil.disk_usage(root).free<expected_bytes*1.2:raise InputError("Insufficient free disk for full-hour station arrays; estimated bytes: "+str(expected_bytes))
        state_path=root/"preparation.json"
        state=read_json(state_path) if state_path.exists() else {"signature":signature,"done":{},"station_hashes":{},"operators":["unknown"],"qc":[{"code":"missing","country":"","stratum":"missing"}],"sources":[{"status":"missing"}],"counts":{}}
        if state["signature"]!=signature:raise InputError("Store input identity differs")
        recover_pending(root,state)
        for name,sha in state["station_hashes"].items():
            if file_hash(root/name)!=sha:raise InputError("Prepared station cache changed: "+name)
        file_by_key={s["key"]:"stations/"+digest(s["key"])[:24]+".npy" for s in stations}
        write_csv(root/"stations.csv",stations,["key","name","country","lat","lon","height_m","family","native_family","role","fold","geometry_role"])
        log(f"Full-hour preparation: {len(stations)} station IDs, {n} UTC labels, {len(parts)} source parts")
        years=set(y for ys in c["years"].values() for y in ys)
        for index,(run,key,record,asset) in enumerate(parts,1):
            part=digest([key,asset["path"],asset["sha256"]])
            if part in state["done"]:continue
            if file_hash(asset["path"])!=asset["sha256"] or fingerprint(asset["path"])!=asset["fingerprint"]:raise InputError("Native part changed since audit")
            name=file_by_key[key];final=root/name;existed=final.exists();work=root/"part.work.npy";backup=root/"part.backup.npy"
            if existed:shutil.copyfile(final,work)
            else:_init_station(work,n)
            a=np.load(work,mmap_mode="r+");counters=collections.Counter();meta=checked_metadata(record);j=record["job"];country=run["country"];last=None
            book_cache={}
            source={"path":asset["path"],"sha256":asset["sha256"],"plan_id":run["plan_id"],"job_id":j["job_id"]}
            if source not in state["sources"]:state["sources"].append(source)
            source_id=state["sources"].index(source)
            priority={"historical":0,"recent":1,"now":2,"row":2}.get(j.get("type",j.get("tier")),0)
            try:
                with gzip.open(asset["path"],"rt",encoding="utf-8-sig",newline="") as f:
                    reader=csv.DictReader(f)
                    if reader.fieldnames!=asset["columns"]:raise InputError("Source CSV header changed")
                    for row in reader:
                        counters["native_rows_scanned"]+=1
                        if None in row or any(v is None for v in row.values()):raise InputError("Malformed native row")
                        if not row.get("timestamp_utc"):counters["unresolved_time_rows"]+=1;continue
                        t=stamp(row["timestamp_utc"])
                        if last is not None and t<=last:raise InputError("Duplicate/unsorted source timestamps")
                        last=t
                        sid=st_map[key]["station_id"]
                        if country=="AT" and (row.get("station_id")!=sid or not stamp(j["start"])<=t<=stamp(j["end"])):raise InputError("AT identity or period mismatch")
                        if country=="DE" and row.get("STATIONS_ID","").zfill(5)!=sid:raise InputError("DE identity mismatch")
                        if country=="CH" and row.get("station_abbr","").strip().upper()!=sid:raise InputError("CH identity mismatch")
                        if not stamp(run["start"])<=t<stamp(run["end_exclusive"]):raise InputError("Source row outside frozen plan")
                        if t.minute or t.second or t.microsecond:counters["off_hour_not_resampled"]+=1;continue
                        if t.year not in years:continue
                        h=int((t-start)/HOUR)
                        for var,obs in cells(country,run,record,row,t,meta,counters):
                            k=(obs['operator'],country,obs['qc'])
                            if k not in book_cache:book_cache[k]=_books(state,obs,country)
                            op,qid=book_cache[k]
                            merge(a,h,NAMES.index(var),obs["value"],op,qid,source_id,priority,counters)
                if fingerprint(asset["path"])!=asset["fingerprint"]:raise InputError("Source changed during parsing")
                a.flush()
            finally:del a
            new_sha=file_hash(work)
            write_json(root/"pending.json",{"part":part,"final":name,"existed":existed})
            final.parent.mkdir(exist_ok=True)
            if existed:os.replace(final,backup)
            os.replace(work,final)
            state["done"][part]=source;state["station_hashes"][name]=new_sha
            state["counts"]=dict(collections.Counter(state["counts"])+counters)
            write_json(state_path,state)
            backup.unlink(missing_ok=True);(root/"pending.json").unlink()
            log(f"  {index}/{len(parts)} {key}: {counters['inserted_cells']} inserted cells")
        meta={"schema":"IGE_FULL_CPU_STORE_v1","signature":signature,"origin":"verified_native_database_full_calendar","full_calendar_ingestion":True,"start":iso(start),"n_hours":n,"years":c["years"],"stations":stations,"files":file_by_key,"station_hashes":state["station_hashes"],"operator_codebook":state["operators"],"qc_codebook":state["qc"],"source_codebook":state["sources"],"anchor_path":str(ap),"anchor_split_id":old["split_id"],"qc_mode":c["qc_mode"],"rejected_native_qc":c["rejected_native_qc"],"data_configuration":data_config(c),"counts":state["counts"],"excluded_geometry_or_variants":sorted(available-set(st_map)),"holdout_evaluated":False,"raw_blinding_claimed":False,"historical_sensor_geometry_verified":False,"source_audit":report}
        for key,name in file_by_key.items():
            if not (root/name).exists():_init_station(root/name,n);meta["station_hashes"][name]=file_hash(root/name)
        meta["store_id"]=digest(meta);write_json(manifest,meta);write_json(out/"LATEST_STORE.json",{"path":str(root.resolve()),"store_id":meta["store_id"]})
        Store(root).availability(root/"availability.csv")
        return root

class Store:
    def __init__(self,path,verify=False):
        self.path=Path(path).resolve();self.meta=sealed(self.path/"manifest.json","store_id");self.stations=self.meta["stations"];self.start=stamp(self.meta["start"]);self.n=self.meta["n_hours"]
        if verify:self.verify()
        self.by_key={s["key"]:i for i,s in enumerate(self.stations)}
        epoch=np.datetime64(self.start.replace(tzinfo=None),"h");self.times=epoch+np.arange(self.n).astype('timedelta64[h]');self.years=self.times.astype('datetime64[Y]').astype(int)+1970
        self.month=self.times.astype('datetime64[M]').astype(int)%12+1
        self.hour=np.arange(self.n)%24
        self.qeligible=np.array([q.get("code") not in self.meta["rejected_native_qc"].get(q.get("country",""),[]) for q in self.meta["qc_codebook"]]);self.qeligible[0]=False
        self._cache=collections.OrderedDict()
    def close(self):
        for a in getattr(self,'_cache',{}).values():
            mm=getattr(a,'_mmap',None)
            if mm is not None:mm.close()
        if hasattr(self,'_cache'):self._cache.clear()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def __del__(self):self.close()
    def verify(self):
        last=time.monotonic()
        for i,(name,sha) in enumerate(self.meta['station_hashes'].items(),1):
            if file_hash(self.path/name)!=sha:raise InputError("Station cache hash differs: "+name)
            if time.monotonic()-last>=10:log(f"  verifying frozen store: {i}/{len(self.meta['station_hashes'])}");last=time.monotonic()
    def array(self,index):
        key=self.stations[index]["key"]
        if key in self._cache:self._cache.move_to_end(key);return self._cache[key]
        a=np.load(self.path/self.meta["files"][key],mmap_mode="r");self._cache[key]=a
        if len(self._cache)>80:self._cache.popitem(last=False)
        return a
    def read(self,index,hours):
        a=self.array(index)[hours];v=a['value'];eligible=np.isfinite(v)&self.qeligible[a['qc']]&~a['conflict']&(a['operator']>0)
        return v,a['operator'],eligible,a['qc']
    def hours(self,years):return np.flatnonzero(np.isin(self.years,years))
    def availability(self,path):
        def rows():
            for i,s in enumerate(self.stations):
                for role,years in self.meta['years'].items():
                    hours=self.hours(years);v,op,ok,qc=self.read(i,hours)
                    for j,var in enumerate(NAMES):
                        yield {'station':s['key'],'station_role':s['role'],'time_role':role,'variable':var,'calendar_labels':len(hours),'finite_published':int(np.isfinite(v[:,j]).sum()),'eligible_cells':int(ok[:,j].sum()),'QC_counts_on_eligible':dict(collections.Counter(map(int,qc[ok[:,j],j])))}
        write_csv(path,rows(),['station','station_role','time_role','variable','calendar_labels','finite_published','eligible_cells','QC_counts_on_eligible'])
