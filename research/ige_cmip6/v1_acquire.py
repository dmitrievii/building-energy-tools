"""V1 bounded original-source acquisition, with published registration/seal gates."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import io,json,re,subprocess,time
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request,build_opener
import zipfile
from a13_acquire import NoRedirect
from v1_prepare import (ROOT,R,REG,ADMISSION,EXPOSURE,META,INPUTS,CONTROLS,
    PREDICTIONS,LEDGER,SEAL,CODE,FROZEN_CORE,registered,code_hashes)
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
BRANCH='research/ige-v1-time-admission-preregistration-20261026'
PART_BYTES=5_500_000


def publication_gate(phase,commit):
    if phase not in ('registration','predictions') or not re.fullmatch('[0-9a-f]{40}',commit or ''):
        raise ValueError('V1_EXACT_PUBLISHED_COMMIT_REQUIRED')
    subprocess.run(['git','merge-base','--is-ancestor',commit,'refs/remotes/origin/'+BRANCH],cwd=ROOT,check=True,capture_output=True)
    def original(name):return subprocess.check_output(['git','show',commit+':'+name],cwd=ROOT)
    for name in [*CODE,*FROZEN_CORE,*['research/ige_cmip6/'+n for n in (REG,ADMISSION,EXPOSURE,META)]]:
        if original(name)!=(ROOT/name).read_bytes():raise ValueError('V1_PUBLISHED_AND_CURRENT_PROTOCOL_CODE_DIFFER:'+name)
    if phase=='predictions':
        raw=original('research/ige_cmip6/'+SEAL)
        if raw!=(R/SEAL).read_bytes():raise ValueError('V1_PUBLISHED_AND_LOCAL_SEAL_DIFFER')
        seal=json.loads(raw)
        if seal['control_bodies_opened'] is not False or seal['code_sha256']!=code_hashes():
            raise ValueError('V1_METHOD_CHANGED_AFTER_SEAL_OR_NOT_PRECONTROL')
        for name,digest in seal['frozen_files_sha256'].items():
            body=original('research/ige_cmip6/'+name)
            if body!=(R/name).read_bytes() or sha256(body).hexdigest()!=digest:
                raise ValueError('V1_SEALED_INPUT_OR_PREDICTION_CHANGED:'+name)
    return {'commit':commit,'remote_tracking_branch_ancestry_verified':True,
        'published_bytes_equal_current':True,'phase':phase,
        'GitHub_API_publication_checked_separately_by_orchestrator':True,
        'trusted_external_timestamp_claimed':False}


def store_packet(raw,directory,name):
    parts=[]
    for i,offset in enumerate(range(0,len(raw),PART_BYTES),1):
        member=name+f'.part{i:03d}';body=raw[offset:offset+PART_BYTES]
        write_exclusive(directory/member,body);parts.append({'name':member,'bytes':len(body),'sha256':sha256(body).hexdigest()})
    info={'schema':'IGE_V1_BITWISE_ORIGINAL_PACKET_PARTS_v1','packet_name':name,
        'bytes':len(raw),'sha256':sha256(raw).hexdigest(),'parts':parts}
    write_exclusive(directory/(name+'.storage.json'),json_bytes(info));return info


def read_packet(directory,name,*,phase):
    info=json.loads((directory/(name+'.storage.json')).read_text());pieces=[]
    if info['schema']!='IGE_V1_BITWISE_ORIGINAL_PACKET_PARTS_v1' or info['packet_name']!=name:
        raise ValueError('V1_PACKET_STORAGE_SCHEMA')
    if not 1<=len(info['parts'])<=200:raise ValueError('V1_PACKET_PART_CENSUS')
    for i,p in enumerate(info['parts'],1):
        if p['name']!=name+f'.part{i:03d}' or not 0<p['bytes']<=PART_BYTES:raise ValueError('V1_PACKET_PART_NAME_OR_SIZE')
        body=(directory/p['name']).read_bytes()
        if len(body)!=p['bytes'] or sha256(body).hexdigest()!=p['sha256']:raise ValueError('V1_PACKET_PART_HASH')
        pieces.append(body)
    raw=b''.join(pieces)
    if len(raw)!=info['bytes'] or sha256(raw).hexdigest()!=info['sha256'] or len(raw)>900_000_000:
        raise ValueError('V1_ORIGINAL_PACKET_HASH_OR_BUDGET')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        entries=z.infolist();names=z.namelist()
        if len(names)>60 or len(set(names))!=len(names) or any(Path(n).name!=n or '\\' in n for n in names) or sum(e.file_size for e in entries)>905_000_000:
            raise ValueError('V1_PACKET_MEMBER_BUDGET_OR_NAMES')
        m=json.loads(z.read('manifest.json'))
        if m['phase']!=phase or set(names)!=set(m['original_body_sha256'])|{'manifest.json'}:
            raise ValueError('V1_SOURCE_PHASE_OR_MEMBER_CENSUS')
        bodies={n:z.read(n) for n in m['original_body_sha256']}
        if any(sha256(bodies[n]).hexdigest()!=h for n,h in m['original_body_sha256'].items()):raise ValueError('V1_ORIGINAL_BODY_HASH')
    return bodies,m,info


def allowed_spec(spec,phase,plan):
    if phase not in ('inputs','controls') or spec not in plan[phase]:raise ValueError('V1_UNREGISTERED_OR_WRONG_PHASE_SOURCE')
    targets=set(plan['target_keys'])
    if phase=='inputs' and (spec['role']=='control' or spec['kind'].startswith('station_') and spec['station_key'] in targets):
        raise ValueError('V1_TARGET_OBSERVATION_IN_PREDICTORS')


def collect(phase,output,commit,*,opener=None,pause=time.sleep):
    plan=registered();gate=publication_gate('registration' if phase=='inputs' else 'predictions',commit)
    if phase not in ('inputs','controls'):raise ValueError('V1_UNKNOWN_SOURCE_PHASE')
    used=0
    if phase=='controls':
        _,m,_=read_packet(R,INPUTS,phase='inputs');used=m['decoded_body_bytes_read_all_attempts']
    output.mkdir(parents=True,exist_ok=False);opener=opener or build_opener(NoRedirect).open
    bodies={};receipts=[];budget=plan['source_budget']['max_decoded_body_bytes_all_attempts_inputs_plus_controls']
    for spec in plan[phase]:
        allowed_spec(spec,phase,plan)
        receipt={k:spec[k] for k in ('id','station_key','kind','role','url','member')}
        receipt.update(status='SOURCE_BLOCKED',attempts=[])
        for attempt in range(plan['source_budget']['attempts_per_asset']):
            note={'number':attempt+1,'started_UTC':datetime.now(timezone.utc).isoformat(),'body_bytes_read':0}
            receipt['attempts'].append(note);start=time.monotonic()
            try:
                if used>=budget:raise ValueError('V1_CUMULATIVE_SOURCE_BYTE_BUDGET')
                req=Request(spec['url'],headers={'User-Agent':'IGE-V1-registered-temperature-validation/1','Accept-Encoding':'identity'})
                with opener(req,timeout=plan['source_budget']['timeout_seconds']) as response:
                    if response.status!=200 or response.geturl()!=spec['url']:raise ValueError('V1_ORIGINAL_200_ENDPOINT_REQUIRED')
                    if response.headers.get('Content-Encoding','identity')!='identity':raise ValueError('V1_UNREGISTERED_CONTENT_ENCODING')
                    length=int(response.headers.get('Content-Length','0'))
                    if length>min(spec['max_body_bytes'],budget-used):raise ValueError('V1_SOURCE_HEADER_BYTE_BUDGET')
                    note['headers']={k:response.headers.get(k) for k in ('Content-Type','Content-Length','ETag','Last-Modified')}
                    chunks=[];n=0
                    while True:
                        chunk=response.read(min(65536,spec['max_body_bytes']-n+1,budget-used+1))
                        if not chunk:break
                        n+=len(chunk);used+=len(chunk);note['body_bytes_read']+=len(chunk)
                        if n>spec['max_body_bytes'] or used>budget:raise ValueError('V1_SOURCE_STREAM_BYTE_BUDGET')
                        chunks.append(chunk)
                    raw=b''.join(chunks)
                    if not raw or length and len(raw)!=length:raise ValueError('V1_EMPTY_OR_TRUNCATED_SOURCE')
                receipt.update(status='ORIGINAL_BODY_RECEIVED',bytes=len(raw),sha256=sha256(raw).hexdigest(),retrieved_UTC=datetime.now(timezone.utc).isoformat())
                bodies[spec['member']]=raw;note['status']='RECEIVED';break
            except (HTTPError,URLError,OSError,ValueError) as exc:
                note['status']='FAILED';note['error']=type(exc).__name__+':'+str(exc)[:220]
                retry=isinstance(exc,(URLError,TimeoutError,ConnectionError)) or isinstance(exc,HTTPError) and exc.code in (429,500,502,503,504)
                if not retry or attempt+1>=plan['source_budget']['attempts_per_asset']:break
                pause(2**(attempt+1))
            finally:note['wall_seconds']=time.monotonic()-start
        receipts.append(receipt);write_exclusive(output/(spec['id']+'_receipt.json'),json_bytes(receipt))
        print(spec['id'],receipt['status'],receipt.get('bytes',0),flush=True)
    manifest={'schema':'IGE_V1_ORIGINAL_SOURCE_PACKET_v1','phase':phase,'publication_gate':gate,
        'registration_sha256':sha256((R/REG).read_bytes()).hexdigest(),'sources':receipts,
        'original_body_sha256':{n:sha256(b).hexdigest() for n,b in bodies.items()},
        'status':'COMPLETE' if all(r['status']=='ORIGINAL_BODY_RECEIVED' for r in receipts) else 'PARTIAL_WITH_RETAINED_SOURCE_BLOCKS',
        'HTTP_attempts_this_phase':sum(len(r['attempts']) for r in receipts),
        'decoded_body_bytes_read_this_phase':sum(a['body_bytes_read'] for r in receipts for a in r['attempts']),
        'decoded_body_bytes_read_all_attempts':used,'control_bodies_opened_this_phase':phase=='controls',
        'original_bodies_preserved':True,'attribution':'GeoSphere Austria; DWD CDC; MeteoSwiss OGD; Open-Meteo / Copernicus ECMWF ERA5; original URLs in receipts'}
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:
        for n,b in sorted({**bodies,'manifest.json':json_bytes(manifest)}.items()):
            info=zipfile.ZipInfo(n,(2000,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,b)
    name=INPUTS if phase=='inputs' else CONTROLS
    storage=store_packet(raw.getvalue(),output,name);write_exclusive(output/'manifest.json',json_bytes(manifest))
    print(json.dumps({'packet':name,'bytes':storage['bytes'],'sha256':storage['sha256'],
        'HTTP_attempts':manifest['HTTP_attempts_this_phase'],'decoded_bytes':used,'status':manifest['status']}),flush=True)
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=('inputs','controls'),required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--published-commit',required=True)
    a=p.parse_args();collect(a.phase,a.out,a.published_commit)
