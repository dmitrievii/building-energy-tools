"""Explicit sparse-cube replay for engineering checks, never called full weather."""
import collections
import datetime as dt
from pathlib import Path
import numpy as np
from ige_auto.data import Cube
from ige_local.common import HOUR,UTC,InputError,digest,file_hash,iso,write_json
from .config import data_config,sealed
from .store import DTYPE,NAMES,Store,_init_station,assign

def import_cube(c,source):
    source=Path(source);cube=Cube(source/'cube');old=sealed(source/'cube/split.sealed.json','split_id')
    summary=source/'summary.json'
    if summary.exists():
        import json
        if json.loads(summary.read_text()).get('holdout_opened'):raise InputError("Source C already evaluated")
    if (source/'C_OPENED.json').exists():raise InputError("Source C exposure marker exists")
    if c['anchor_cube_id'] and cube.meta['cube_id']!=c['anchor_cube_id']:raise InputError("Unexpected original cube")
    for r in ('V','C'):
        if set(cube.years[cube.time_roles==r])&set(c['years']['D']):raise InputError("Source V/C years cannot enter D")
    stations,roles,folds=assign([dict(s) for s in cube.stations],old,c)
    start=dt.datetime(min(y for ys in c['years'].values() for y in ys),1,1,tzinfo=UTC);end=dt.datetime(max(y for ys in c['years'].values() for y in ys)+1,1,1,tzinfo=UTC);n=int((end-start)/HOUR)
    sig=digest(['sparse_replay',cube.meta['cube_id'],data_config(c)]);root=Path(c['results'])/'stores'/sig[:20];root.mkdir(parents=True,exist_ok=True)
    if (root/'manifest.json').exists():Store(root,verify=True);return root
    from ige_local.common import stamp
    hours=np.array([int((stamp(t)-start)/HOUR) for t in cube.times]);valid=(hours>=0)&(hours<n);qbook=cube.meta['qc_codebook'];oldmap={s['key']:i for i,s in enumerate(cube.stations)};files={};hashes={}
    for s in stations:
        i=oldmap[s['key']];name='stations/'+digest(s['key'])[:24]+'.npy';files[s['key']]=name;_init_station(root/name,n);a=np.load(root/name,mmap_mode='r+')
        for j,var in enumerate(NAMES):
            k=cube.meta['variables'].index(var);a['value'][hours[valid],j]=cube.values[i,valid,k];a['operator'][hours[valid],j]=cube.operators[i,valid,k];a['qc'][hours[valid],j]=cube.qc[i,valid,k];a['source'][hours[valid],j]=1;a['priority'][hours[valid],j]=0
        a.flush();del a;hashes[name]=file_hash(root/name)
    meta={'schema':'IGE_FULL_CPU_STORE_v1','signature':sig,'origin':'provided_pilot_cube_sparse_replay','full_calendar_ingestion':False,'source_calendar_hours':hours[valid].tolist(),'start':iso(start),'n_hours':n,'years':c['years'],'stations':stations,'files':files,'station_hashes':hashes,'operator_codebook':cube.meta['operator_codebook'],'qc_codebook':qbook,'source_codebook':[{'status':'none'},{'original_cube_id':cube.meta['cube_id'],'source_arrays_sha256':cube.meta['array_hashes']}],'anchor_split_id':old['split_id'],'qc_mode':c['qc_mode'],'rejected_native_qc':c['rejected_native_qc'],'data_configuration':data_config(c),'holdout_evaluated':False,'raw_blinding_claimed':False,'counts':{'source_cube_labels':len(cube.times),'populated_source_hours':int(valid.sum())},'historical_sensor_geometry_verified':False}
    meta['store_id']=digest(meta);write_json(root/'manifest.json',meta);write_json(Path(c['results'])/'LATEST_STORE.json',{'path':str(root.resolve()),'store_id':meta['store_id']});Store(root).availability(root/'availability.csv');return root
