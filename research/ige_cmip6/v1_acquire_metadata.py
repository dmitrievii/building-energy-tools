"""V1 metadata snapshot/reacquisition; weather products are forbidden here.

The initial metadata exploration is retained, including unused/wrong-identity
WMDR downloads. Only v1_prepare.AT_WSI and checked dated geometry admit a row.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import io,json
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
import zipfile
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive


def metadata_url(url):
    p=urlsplit(url)
    if p.scheme!='https':return False
    if p.netloc=='oscar.wmo.int':
        return p.path.startswith('/surface/rest/api/wmd/download/') or p.path=='/surface/rest/api/stations/approvedStations/names'
    if p.netloc=='opendata.dwd.de':
        return '/climate/10_minutes/air_temperature/' in p.path and (
            '/meta_data/Meta_Daten_' in p.path or p.path.endswith(('Beschreibung_Stationen.txt','air_temperature_en.pdf','historical/')))
    if p.netloc=='data.geo.admin.ch':
        return p.path.startswith('/api/stac/v1/collections/ch.meteoschweiz.ogd-smn/items/')
    return False


def snapshot(directory,output):
    bodies={};receipts=[]
    for receipt_file in sorted(directory.glob('*.receipt.json')):
        note=json.loads(receipt_file.read_text());name=receipt_file.name.removesuffix('.receipt.json')
        if not metadata_url(note['url']) or note['observational_values_requested'] is not False:
            raise ValueError('V1_ONLY_METADATA_URLS_ALLOWED')
        raw=(directory/name).read_bytes()
        if len(raw)!=note['bytes'] or sha256(raw).hexdigest()!=note['sha256']:
            raise ValueError('V1_METADATA_SOURCE_RECEIPT_HASH')
        if note['final_url']!=note['url']:raise ValueError('V1_METADATA_SOURCE_REDIRECT')
        bodies[name]=raw;bodies[receipt_file.name]=receipt_file.read_bytes();receipts.append(note)
    failures=[{'url':'https://oscar.wmo.int/surface/rest/api/wmd/download/0-20000-0-11217',
        'status':404,'body_bytes_read':0,'observation_values_requested':False,
        'reason':'wrong exploratory WSI typed before lookup result was read; no body retained; corrected 11278 separately archived'}]
    manifest={'schema':'IGE_V1_METADATA_ONLY_SNAPSHOT_v1',
        'source_receipts':receipts,'source_requests_with_retained_original_body':len(receipts),
        'exploration_failures':failures,'total_HTTP_attempts':len(receipts)+len(failures),
        'received_original_body_bytes':sum(r['bytes'] for r in receipts),
        'member_sha256':{n:sha256(b).hexdigest() for n,b in bodies.items()},
        'station_observation_bodies_opened':False,'model_background_bodies_opened':False,
        'unused_exploration':'AT_WMDR_3702.xml is WSI11051, not Jauerling11024. It is retained but never admitted. Correct source has WSI in filename; 11217 lookup failed before body.'}
    bodies['manifest.json']=json_bytes(manifest)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for n,b in sorted(bodies.items()):
            info=zipfile.ZipInfo(n,(2000,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,b)
    write_exclusive(output,out.getvalue())
    print(json.dumps({'metadata_packet_bytes':len(out.getvalue()),'sha256':sha256(out.getvalue()).hexdigest(),
        'metadata_requests':manifest['total_HTTP_attempts'],'observation_requests':0}))


def reacquire(packet,output):
    """Explicit fresh snapshot, never silently overwrite a frozen evidence packet."""
    with zipfile.ZipFile(packet) as z:m=json.loads(z.read('manifest.json'))
    output.mkdir(parents=True,exist_ok=False)
    for i,note in enumerate(m['source_receipts']):
        url=note['url']
        if not metadata_url(url):raise ValueError('V1_ONLY_METADATA_URLS_ALLOWED')
        # Reacquisition names are independent from the frozen snapshot. A new
        # provider version is evidence of drift, not permission to update V1.
        with urlopen(Request(url,headers={'User-Agent':'IGE-V1-metadata-reacquisition/1','Accept-Encoding':'identity'}),timeout=35) as r:
            raw=r.read(6_000_001)
            if r.status!=200 or r.geturl()!=url or len(raw)>6_000_000:raise ValueError('V1_METADATA_FETCH_CONTRACT')
        name=f'{i:03d}.body';write_exclusive(output/name,raw)
        write_exclusive(output/(name+'.json'),json_bytes({'url':url,'sha256':sha256(raw).hexdigest(),
            'matches_frozen':sha256(raw).hexdigest()==note['sha256'],'observations_read':False}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--snapshot-directory',type=Path);p.add_argument('--reacquire-packet',type=Path)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if bool(a.snapshot_directory)==bool(a.reacquire_packet):p.error('Choose exactly one metadata mode')
    if a.snapshot_directory:snapshot(a.snapshot_directory,a.out)
    else:reacquire(a.reacquire_packet,a.out)
