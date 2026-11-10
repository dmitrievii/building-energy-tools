"""Freeze real Copernicus IMD2018 buffer histograms; no city-name heuristics."""
from __future__ import annotations
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import numpy as np
from ige_local.common import InputError, digest, file_hash, log, now, read_json, write_csv, write_json
from .config import sealed
from .store import Store,Lock

SERVICE="https://image.discomap.eea.europa.eu/arcgis/rest/services/GioLandPublic/HRL_ImperviousnessDensity_2018/ImageServer"
CATALOGUE="https://land.copernicus.eu/en/products/high-resolution-layer-imperviousness/imperviousness-density-2018"
SOURCES={
    'impervious':{'service':SERVICE,'catalogue':CATALOGUE},
    'tree':{'service':SERVICE.replace('HRL_ImperviousnessDensity_2018','HRL_TreeCoverDensity_2018'),'catalogue':'https://sdi.eea.europa.eu/catalogue/srv/api/records/486f77da-d605-423e-93a9-680760ab6791'},
    'water':{'service':SERVICE.replace('HRL_ImperviousnessDensity_2018','HRL_WaterWetness_2018'),'catalogue':'https://land.copernicus.eu/en/products/high-resolution-layer-water-and-wetness/water-and-wetness-status-2018'}
}

def buffer_request(lat,lon,radius,dataset='impervious'):
    phi,lam=math.radians(lat),math.radians(lon);d=radius/6371008.8;ring=[]
    for j in range(64):
        a=2*math.pi*j/64
        p=math.asin(math.sin(phi)*math.cos(d)+math.cos(phi)*math.sin(d)*math.cos(a))
        l=lam+math.atan2(math.sin(a)*math.sin(d)*math.cos(phi),math.cos(d)-math.sin(phi)*math.sin(p))
        ring.append([math.degrees(l),math.degrees(p)])
    ring.append(ring[0])
    xy=[(6378137*math.radians(x),6378137*math.log(math.tan(math.pi/4+math.radians(y)/2))) for x,y in ring]
    area=abs(sum(x*y1-x1*y for (x,y),(x1,y1) in zip(xy,xy[1:])))/2
    # The service is Web Mercator; compensate local scale to request ~10 ground m.
    pixel=10/math.cos(phi)
    q={"f":"json","geometry":json.dumps({"rings":[ring],"spatialReference":{"wkid":4326}},separators=(',',':')),
       "geometryType":"esriGeometryPolygon","pixelSize":json.dumps({"x":pixel,"y":pixel,"spatialReference":{"wkid":3857}}),
       "renderingRule":json.dumps({"rasterFunction":"None"})}
    return {"url":SOURCES[dataset]['service']+"/computeStatisticsHistograms","parameters":q,"expected_grid_cells":area/(pixel*pixel),"radius_m":radius,"lat":lat,"lon":lon,"dataset":dataset,"service_pixel_size_mercator_m":pixel}

def histogram(response,expected,minimum,dataset='impervious'):
    if "error" in response:raise InputError("Copernicus service error: "+str(response['error']))
    hist=response.get('histograms',[])
    if len(hist)!=1:raise InputError("Expected one raw IMD band, no RGB/style rendering")
    h=hist[0];counts=np.asarray(h['counts'],dtype=float);n=int(h['size'])
    if len(counts)!=n or not np.isfinite(counts).all() or (counts<0).any() or n<1:raise InputError("Malformed urban histogram")
    width=(float(h['max'])-float(h['min']))/n
    if not 0<width<=1.01:raise InputError("Urban histogram bins cannot identify original IMD codes")
    x=float(h['min'])+(np.arange(n)+.5)*width
    if dataset=='water':valid=np.isin(np.round(x).astype(int),[0,1,2,3,4,253])
    else:valid=(x>=-1e-6)&(x<=100+1e-6)
    nc=float(counts[valid].sum())
    coverage=nc/expected if expected>0 else 0
    if coverage>1.1:raise InputError("Service grid resolution/count differs from requested pixelSize")
    if dataset=='water':
        mean=float(counts[np.isin(np.round(x).astype(int),[1,2,253])].sum()/nc) if nc else None
        wet=float(counts[np.isin(np.round(x).astype(int),[3,4])].sum()/nc) if nc else None
    else:mean=float(np.sum(x[valid]*counts[valid])/nc/100) if nc else None;wet=None
    return {"fraction":mean,"wet_fraction":wet,"valid_grid_cells":nc,"total_returned_grid_cells":float(counts.sum()),"estimated_valid_fraction":min(1.,coverage),"valid":bool(nc and coverage>=minimum),"coverage_method":"valid original product codes / geodesic-buffer area on requested Web-Mercator grid; approximate raster boundary"}

def collect(c,store_path,fetch=None):
    store=Store(store_path);root=store.path/'urban';root.mkdir(exist_ok=True)
    with Lock(root/'urban.lock'):
        if (root/'features.json').exists():
            a=load_features(store,root/'features.json')
            if a['radii_m']!=c['urban']['radii_m'] or a['minimum_valid_fraction']!=c['urban']['minimum_valid_fraction']:raise InputError("Frozen urban configuration differs; use a separate results/store for changed radii or coverage")
            log("Frozen urban features verified: "+a['feature_id']);return root/'features.json'
        u=c['urban'];rows=[];errors=[];last=0.;requests=0
        for st in store.stations:
            for dataset,radius in [(d,r) for d in SOURCES for r in u['radii_m']]:
                request=buffer_request(st['lat'],st['lon'],radius,dataset);rid=digest(request);raw=root/'raw'/(rid+'.json');receipt=root/'raw'/(rid+'.receipt.json');raw.parent.mkdir(exist_ok=True)
                try:
                    if receipt.exists():
                        r=read_json(receipt)
                        if r['request']!=request or file_hash(raw)!=r['body_sha256']:raise InputError("Cached urban response changed")
                        body=raw.read_bytes()
                    else:
                        delay=u['seconds_between_requests']-(time.monotonic()-last)
                        if delay>0:time.sleep(delay)
                        if fetch is None:
                            url=request['url']+'?'+urllib.parse.urlencode(request['parameters'])
                            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'IGE-Climate-Research/0.4 (Copernicus buffer statistics)'}),timeout=u['timeout_seconds']) as f:body=f.read(2*1024**2+1)
                        else:body=fetch(request)
                        last=time.monotonic();requests+=1
                        if len(body)>2*1024**2:raise InputError("Urban response exceeds 2 MiB")
                        # Validate before freezing; errors can be retried on resume.
                        histogram(json.loads(body),request['expected_grid_cells'],u['minimum_valid_fraction'],dataset)
                        raw.write_bytes(body);r={'request':request,'body_sha256':digest(body),'retrieved_at_utc':now()};write_json(receipt,r)
                    stats=histogram(json.loads(body),request['expected_grid_cells'],u['minimum_valid_fraction'],dataset)
                    rows.append({'station':st['key'],'lat':st['lat'],'lon':st['lon'],'dataset':dataset,'radius_m':radius,'raw_relative_path':str(raw.relative_to(root)),'response_sha256':digest(body),**stats})
                    log(f"Urban {st['key']} {dataset} r={radius} m: "+str(stats['fraction']))
                except (OSError,ValueError,KeyError,TypeError,urllib.error.URLError) as exc:
                    errors.append({'station':st['key'],'dataset':dataset,'radius_m':radius,'error':str(exc)})
        summary={'store_id':store.meta['store_id'],'requests_this_invocation':requests,'responses':len(rows),'expected_responses':len(store.stations)*len(u['radii_m'])*len(SOURCES),'errors':errors}
        write_json(root/'collection_status.json',summary)
        if errors:raise InputError("Urban collection incomplete; successful frozen responses retained. Run urban again; see urban/collection_status.json")
        result={'schema':'IGE_URBAN_FEATURES_v1','store_id':store.meta['store_id'],'sources':SOURCES,'reference_year':2018,'radii_m':u['radii_m'],'minimum_valid_fraction':u['minimum_valid_fraction'],'rows':rows,'feature_contract':'8 features: impervious density, tree canopy density, permanent/temporary/sea water fraction, permanent/temporary wet fraction, each at 2 radii. Tree canopy is not total vegetation. Water codes 1/2/253; wet codes 3/4; dry 0 is valid. Unknown 254/255 never becomes zero.','temporal_contract':'Static 2018 land-cover proxy (IMD scenes 2017-2019; water occurrence 2012-2018) applied to weather years; contemporaneous station surroundings/history NOT verified; no temperature imagery used'}
        result['feature_id']=digest(result);write_json(root/'features.json',result)
        write_csv(root/'features.csv',rows,list(rows[0]) if rows else ['station','radius_m'])
        return root/'features.json'

def load_features(store,path):
    a=sealed(path,'feature_id')
    if a['store_id']!=store.meta['store_id']:raise InputError("Urban features belong to another weather store")
    expected={(s['key'],d,r) for s in store.stations for d in SOURCES for r in a['radii_m']}
    if {(r['station'],r['dataset'],r['radius_m']) for r in a['rows']}!=expected or len(a['rows'])!=len(expected):raise InputError("Urban feature rows missing or duplicated")
    st={s['key']:s for s in store.stations};root=Path(path).parent
    for r in a['rows']:
        if (r['lat'],r['lon'])!=(st[r['station']]['lat'],st[r['station']]['lon']):raise InputError("Urban station geometry changed")
        if file_hash(root/r['raw_relative_path'])!=r['response_sha256']:raise InputError("Frozen provider urban bytes changed")
        request=buffer_request(r['lat'],r['lon'],r['radius_m'],r['dataset'])
        reproduced=histogram(json.loads((root/r['raw_relative_path']).read_bytes()),request['expected_grid_cells'],a['minimum_valid_fraction'],r['dataset'])
        if any(r[k]!=v for k,v in reproduced.items()):raise InputError("Urban feature extraction does not reproduce frozen provider bytes")
        val=r['fraction']
        if val is not None and not 0<=val<=1:raise InputError("Invalid urban density")
    return a

def vectors(store,path):
    a=load_features(store,path);lookup={(r['station'],r['dataset'],r['radius_m']):r for r in a['rows']};u=np.full((len(store.stations),8),np.nan)
    for i,st in enumerate(store.stations):
        rows=[lookup[(st['key'],d,r)] for d in SOURCES for r in a['radii_m']]
        if all(r['valid'] for r in rows):u[i]=[r['fraction'] for r in rows]+[r['wet_fraction'] for r in rows if r['dataset']=='water']
    return a,u
