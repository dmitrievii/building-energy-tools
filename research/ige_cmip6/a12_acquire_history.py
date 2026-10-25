"""A1.2 historical metadata only; measurement products are never read.

Frozen station IDs and source discovery are separate from eligibility. No
replacement is made when a station lacks an unambiguous OSCAR identity.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from hashlib import sha256
import io,json,re
from pathlib import Path
from urllib.request import Request,urlopen
import zipfile

from a12_metadata_zip import MetadataArchive

ROOT=Path(__file__).resolve().parents[2]
R=ROOT/'research/ige_cmip6'
AT_WSI={'3202':'0-20000-0-11060','5000':'0-20000-0-11010','6305':'0-20000-0-11350',
    '6415':'0-20000-0-11152','6512':'0-20000-0-11153'}


def fetch_wmdr(item, discovery=None):
    key,wsi=item
    url='https://oscar.wmo.int/surface/rest/api/wmd/download/'+wsi
    filename=key.replace(':','_')+'_WMDR.xml'
    try:
        if key=='AT:3202' and discovery is not None:
            raw=(discovery/'AT_Linz_WMDR.xml').read_bytes()
            receipt=json.loads((discovery/'AT_Linz_WMDR.xml.receipt.json').read_text())
            assert receipt['sha256']==sha256(raw).hexdigest() and receipt['url']==url
            cached=True
        else:
            with urlopen(Request(url,headers={'User-Agent':'IGE-A1.2-WMDR-metadata-only'}),timeout=30) as response:
                if response.geturl()!=url:raise ValueError('A12_WMDR_REDIRECT')
                raw=response.read(3_000_001)
            if len(raw)>3_000_000:raise ValueError('A12_WMDR_SIZE')
            cached=False
        if b'WIGOSMetadataRecord' not in raw:raise ValueError('A12_EXPECTED_WMDR_XML')
        return {filename:raw},{'station':key,'WSI':wsi,'url':url,'status':'ORIGINAL_METADATA_RECEIVED',
            'member':filename,'bytes':len(raw),'sha256':sha256(raw).hexdigest(),'reused_discovery_body':cached}
    except Exception as exc:
        return {},{'station':key,'WSI':wsi,'url':url,'status':'SOURCE_BLOCKED','error':type(exc).__name__+': '+str(exc)}


def fetch_dwd(item, first_dwd=None):
    sid,name=item;url='https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/'+name
    files={}
    try:
        if sid=='02928' and first_dwd is not None:
            proof=json.loads((first_dwd/'range_proof.json').read_text())
            assert proof['url']==url
            files={f'DE_{sid}__'+p.name:p.read_bytes() for p in first_dwd.glob('*.txt')}
            reused=True
        else:
            source=MetadataArchive(url);entries=source.directory()
            for row in entries:
                member=row['name']
                if (member.startswith(('Metadaten_Parameter','Metadaten_Geographie','Metadaten_Geraete'))
                        and member.endswith('.txt')):
                    files[f'DE_{sid}__'+member]=source.read_metadata(member)
            proof=source.proof();reused=False
        files['DE_'+sid+'__range_proof.json']=(json.dumps(proof,indent=2)+'\n').encode()
        return files,{'station':'DE:'+sid,'url':url,'status':'ORIGINAL_METADATA_RECEIVED','reused_discovery_body':reused,
            'metadata_members':{n:{'bytes':len(b),'sha256':sha256(b).hexdigest()} for n,b in files.items()},
            'range_requests':len(proof['requests']),'range_body_bytes':sum(x['bytes'] for x in proof['requests']),
            'observation_product_members_requested':False,'whole_archive_body_read':False}
    except Exception as exc:
        return files,{'station':'DE:'+sid,'url':url,'status':'SOURCE_BLOCKED','error':type(exc).__name__+': '+str(exc)}


def acquire(output, discovery=None, first_dwd=None):
    output.mkdir(parents=True,exist_ok=False)
    protocol=json.loads((R/'a1_1_protocol_20261025.json').read_text());refs={}
    for group in protocol['targets']:
        for station in [group['target'],*group['donors']]:refs[station['country']+':'+station['station_id']]=station
    if discovery is not None:listing=(discovery/'dwd_tu_index.html').read_bytes()
    else:
        url='https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/'
        with urlopen(Request(url,headers={'User-Agent':'IGE-A1.2-metadata-index-only'}),timeout=25) as response:
            if response.geturl()!=url:raise ValueError('A12_INDEX_REDIRECT')
            listing=response.read(300001)
        if len(listing)>300000:raise ValueError('A12_INDEX_SIZE')
    dwd=[];wmo=[];missing=[]
    for key,station in sorted(refs.items()):
        country,sid=key.split(':')
        if country=='DE':
            matches=sorted(set(re.findall(r'stundenwerte_TU_'+sid+r'_(\d{8})_(\d{8})_hist.zip',listing.decode())))
            matches=[(a,b) for a,b in matches if a<='20250110' and b>='20251016']
            if len(matches)!=1:raise ValueError('A12_AMBIGUOUS_DWD_METADATA_ARCHIVE_'+sid)
            a,b=matches[0];dwd.append((sid,f'stundenwerte_TU_{sid}_{a}_{b}_hist.zip'))
        elif country=='CH':wmo.append((key,station['identity_group'].removeprefix('CH_WIGOS:')))
        elif sid in AT_WSI:wmo.append((key,AT_WSI[sid]))
        else:missing.append({'station':key,'status':'SOURCE_BLOCKED','reason':'NO_UNAMBIGUOUS_OSCAR_NAME_IDENTITY_MATCH; wrong Reichenau/Ennstal stations not substituted'})
    plan={'schema':'IGE_A12_METADATA_REQUEST_PLAN_v1','parent_protocol_sha256':sha256((R/'a1_1_protocol_20261025.json').read_bytes()).hexdigest(),
        'frozen_station_ids':sorted(refs),'DWD_archives':[name for _,name in dwd],'WMDR_identities':dict(wmo),
        'metadata_scope':'parameter/device/geography TXT members and WMDR deployments; no products',
        'max_range_requests_per_archive':20,'max_WMDR_body_bytes':3000000,'max_workers':3,
        'global_validation_or_new_target_measurements':False,'prior_discovery_included':discovery is not None}
    (output/'request_plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    bodies={'request_plan.json':(output/'request_plan.json').read_bytes(),'DWD_TU_archive_index.html':listing}
    receipts=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for files,receipt in pool.map(lambda item:fetch_dwd(item,first_dwd),dwd):
            for name,body in files.items():
                with (output/name).open('xb') as stream:stream.write(body)
            bodies.update(files);receipts.append(receipt);print(receipt['station'],receipt['status'],flush=True)
        for files,receipt in pool.map(lambda item:fetch_wmdr(item,discovery),wmo):
            for name,body in files.items():
                with (output/name).open('xb') as stream:stream.write(body)
            bodies.update(files);receipts.append(receipt);print(receipt['station'],receipt['status'],flush=True)
    if discovery is not None:
        for p in discovery.glob('oscar_names_*.json'):
            bodies['discovery_'+p.name]=p.read_bytes()
    receipts.extend(missing)
    manifest={'schema':'IGE_A12_HISTORICAL_METADATA_v1','retrieved_utc':datetime.now(timezone.utc).isoformat(),
        'stations':receipts,'member_sha256':{n:sha256(b).hexdigest() for n,b in bodies.items()},
        'raw_2025_measurement_values_opened':False,'IV1_observation_values_opened':False,
        'DWD_product_members_requested':False,'observation_or_ERA5_requests':0,
        'range_requests':sum(r.get('range_requests',0) for r in receipts),
        'range_body_bytes':sum(r.get('range_body_bytes',0) for r in receipts)}
    bodies['manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    for name,body in bodies.items():
        if (output/name).exists():
            if (output/name).read_bytes()!=body:raise ValueError('A12_EXISTING_METADATA_DIFFERS_'+name)
            continue
        with (output/name).open('xb') as stream:stream.write(body)
    packet=io.BytesIO()
    with zipfile.ZipFile(packet,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,body in sorted(bodies.items()):
            info=zipfile.ZipInfo(name,(2000,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,body)
    with (output/'history_sources.zip').open('xb') as stream:stream.write(packet.getvalue())
    print(json.dumps({'packet_bytes':len(packet.getvalue()),'packet_sha256':sha256(packet.getvalue()).hexdigest(),
        'range_requests':manifest['range_requests'],'range_body_bytes':manifest['range_body_bytes'],'station_records':len(receipts)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--discovery-dir',type=Path);parser.add_argument('--reuse-first-dwd',type=Path)
    args=parser.parse_args();acquire(args.out,args.discovery_dir,args.reuse_first_dwd)
