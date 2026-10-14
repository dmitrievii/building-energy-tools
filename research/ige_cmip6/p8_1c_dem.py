#!/usr/bin/env python3
"""Independent Mapzen/Tilezen DEM sampler for IGE P8.1C (not NASA/Copernicus DEM).

Source: https://registry.opendata.aws/terrain-tiles/
https://github.com/tilezen/joerd/blob/master/docs/attribution.md
Terrarium elevations in metres, Web Mercator EPSG:3857. Tile bytes stay local
in the CI runner cache. Public derived terrain features retain tile SHA256.
Never infer atmospheric observations from this terrain dataset.
"""
from __future__ import annotations
import argparse,collections,concurrent.futures,hashlib,io,json,math,time
from pathlib import Path
from urllib.request import Request,urlopen
import numpy as np
from PIL import Image

ROOT='https://s3.amazonaws.com/elevation-tiles-prod/terrarium'
RINGS=(250.,1500.,5000.,10000.)
BEARINGS=tuple(range(0,360,30))
ZOOM=11

def tile_point(lat,lon,zoom=ZOOM):
    if not -85.05112878 < lat < 85.05112878 or not -180 <= lon <= 180:raise ValueError('Out of EPSG:3857 bounds')
    scale=2**zoom
    xf=(lon+180)/360*scale
    yf=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*scale
    xt=int(math.floor(xf))%scale;yt=int(math.floor(yf))
    px=min(255,max(0,int((xf-math.floor(xf))*256)))
    py=min(255,max(0,int((yf-math.floor(yf))*256)))
    return (zoom,xt,yt),px,py

def radial(lat,lon,dist_m,bearing_deg):
    # Great-circle destination, includes longitude correction at mountain latitudes.
    r=6371008.8;a=dist_m/r;b=math.radians(bearing_deg)
    p1,l1=math.radians(lat),math.radians(lon)
    p2=math.asin(math.sin(p1)*math.cos(a)+math.cos(p1)*math.sin(a)*math.cos(b))
    l2=l1+math.atan2(math.sin(b)*math.sin(a)*math.cos(p1),math.cos(a)-math.sin(p1)*math.sin(p2))
    return math.degrees(p2),(math.degrees(l2)+540)%360-180

def decode_tile(blob, key=None, stats=None):
    with Image.open(io.BytesIO(blob)) as im:
        v=np.asarray(im.convert('RGB'),dtype=np.float64)
    if v.shape!=(256,256,3):raise ValueError('Wrong Terrarium tile shape')
    h=256*v[:,:,0]+v[:,:,1]+v[:,:,2]/256-32768
    # The upstream joerd Terrarium writer sets R=0 for NoData, deliberately
    # encoding a physically impossible elevation below -32512 m. Do not
    # reject the *whole tile* if only unvisited pixels are NoData.
    # https://github.com/tilezen/joerd/blob/master/joerd/output/terrarium.py
    nodata=v[:,:,0]==0
    bad=(~np.isfinite(h) | (h < -12000) | (h > 10000)) & ~nodata
    # A physically impossible pixel is unusable, not grounds to discard
    # otherwise valid DEM terrain. Never interpolate, clip or substitute it.
    # Requested terrain points are checked separately by TileCache.point().
    if stats is not None:
        stats['nodata_pixels']=int(np.count_nonzero(nodata))
        stats['implausible_pixels']=int(np.count_nonzero(bad))
        if np.any(bad):
            row,col=np.argwhere(bad)[0]
            stats['first_implausible']={'row':int(row),'col':int(col),
                'rgb':[int(vv) for vv in v[row,col]],
                'decoded_m':float(h[row,col])}
    h[nodata | bad]=np.nan
    if not np.isfinite(h).any():
        raise ValueError('Terrarium tile contains no valid elevation pixels')
    return h

class TileCache:
    def __init__(self,cache,zoom=ZOOM):
        self.path=Path(cache);self.path.mkdir(parents=True,exist_ok=True)
        self.zoom=zoom;self.arrays={};self.sha={};self.tile_stats={}
    def load(self,key):
        z,x,y=key
        path=self.path/f'{z}_{x}_{y}.png'
        if path.exists():blob=path.read_bytes()
        else:
            url=f'{ROOT}/{z}/{x}/{y}.png';issues=[]
            for i in range(3):
                try:
                    with urlopen(Request(url,headers={'User-Agent':'IGE-independent-P8.1C-GeoResearch'}),timeout=35) as f:
                        blob=f.read(2000000)
                    if len(blob)<500:raise RuntimeError('DEM tile too short')
                    break
                except Exception as e:
                    issues.append(str(e));time.sleep(.35*(i+1))
            else:raise RuntimeError(f'Missing DEM tile {key}: {issues}')
            # Validate before retaining.
            decode_tile(blob,key)
            path.write_bytes(blob)
        tile_stats={}
        a=decode_tile(blob,key,stats=tile_stats)
        return key,a,hashlib.sha256(blob).hexdigest(),tile_stats
    def prefetch(self,keys,workers=12):
        unique=sorted(set(keys));missing=[key for key in unique if key not in self.arrays]
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for k,a,sha,stats in pool.map(self.load,missing):
                self.arrays[k]=a;self.sha[str(k)]=sha
                self.tile_stats[str(k)]=stats
    def point(self,lat,lon):
        k,x,y=tile_point(lat,lon,self.zoom)
        if k not in self.arrays:raise KeyError('DEM_TILE_UNFETCHED '+str(k))
        elevation=float(self.arrays[k][y,x])
        if not math.isfinite(elevation):
            raise ValueError(f'DEM_NODATA_AT_SAMPLE tile={k} pixel=({x},{y}) lat={lat:.6f} lon={lon:.6f}')
        return elevation

def sample_locations(station):
    pts=[(station['lat'],station['lon'])]
    for d in RINGS:
        pts.extend(radial(station['lat'],station['lon'],d,b) for b in BEARINGS)
    return pts

def sample_stations(stations,cache,workers=12):
    valid=sorted([s for s in stations if s.get('periode')=='1991–2020'],key=lambda s:s['station_id'])
    pts={s['station_id']:sample_locations(s) for s in valid}
    needed={tile_point(lat,lon,cache.zoom)[0] for sites in pts.values() for lat,lon in sites}
    cache.prefetch(needed,workers=workers)
    records=[]
    for s in valid:
        h=np.array([cache.point(lat,lon) for lat,lon in pts[s['station_id']]],float)
        rings=[h[1+i*len(BEARINGS):1+(i+1)*len(BEARINGS)] for i in range(len(RINGS))]
        center=float(h[0]);r250,r1500,r5000,r10000=rings
        slope_dir=np.array([(r250[j]-r250[(j+6)%12])/(2*250.) for j in range(6)])
        rec={'station_id':int(s['station_id']),'station':s['station'],'lat':s['lat'],'lon':s['lon'],
             'station_height_m':float(s['hoehe_m']),'dem_height_m':center,
             'dem_minus_station_m':center-float(s['hoehe_m']),
             'tpi_1500_m':center-float(np.mean(r1500)),
             'tpi_5000_m':center-float(np.mean(r5000)),
             'tpi_10000_m':center-float(np.mean(r10000)),
             'rugged_1500_m':float(np.std(r1500)),
             'slope_250m_proxy':float(np.max(np.abs(slope_dir))),
             'dem_height_min_1500_m':float(np.min(r1500)),
             'dem_height_max_1500_m':float(np.max(r1500)),
             'dem_source':'Mapzen Terrain Tiles, AWS Open Data','dem_zoom':cache.zoom,
             'dem_sampling':'nearest pixel; 12 great-circle bearings for each ring 250m,1500m,5000m,10000m',
             'elevation_warning':abs(center-float(s['hoehe_m']))>200}
        records.append(rec)
    return records

def run(reference,out,cache_dir,zoom=ZOOM,workers=12):
    blob=Path(reference).read_bytes();data=json.loads(blob);stations=data['stationen']
    cache=TileCache(cache_dir,zoom);features=sample_stations(stations,cache,workers)
    if len(features)<150:raise RuntimeError('DEM coverage too small')
    provenance={'source':'Mapzen Terrain Tiles (Tilezen/Joerd) AWS Open Data','source_reference':'https://registry.opendata.aws/terrain-tiles/',
        'attribution':'https://github.com/tilezen/joerd/blob/master/docs/attribution.md',
        'source_kind':'multi-provider mosaicked bare-earth DEM, not single Copernicus or NASA source',
        'zoom':zoom,'pixel_interpretation':'Web Mercator Terrarium, nearest pixel; resolution depends on latitude',
        'nodata_pixel_count':sum(x['nodata_pixels'] for x in cache.tile_stats.values()),
        'implausible_pixel_count':sum(x['implausible_pixels'] for x in cache.tile_stats.values()),
        'tile_invalid_pixel_diagnostics':{k:v for k,v in cache.tile_stats.items() if v['implausible_pixels']>0},
        'invalid_pixel_policy':'NoData and physically impossible pixels are NaN; never interpolated or replaced; fail closed if sampled point is NaN',
        'rings_m':RINGS,'bearings_degrees':BEARINGS,'n_tile_hashes':len(cache.sha),'tile_sha256':cache.sha,
        'input_station_reference_sha256':hashlib.sha256(blob).hexdigest(),'n_stations':len(features),
        'n_station_dem_disagreements_gt200m':sum(x['elevation_warning'] for x in features),
        'source_data_policy':'Only derived terrain point features and tile hash manifest published; original DEM PNG files remain on CI runner.'}
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    (out/'terrain_features.json').write_text(json.dumps({'provenance':provenance,'stations':features},indent=2,ensure_ascii=False)+'\n')
    (out/'terrain_summary.json').write_text(json.dumps({k:v for k,v in provenance.items() if k!='tile_sha256'},indent=2,ensure_ascii=False)+'\n')
    print('DEM',len(features),'stations',len(cache.sha),'unique tiles','elev>200m',sum(x['elevation_warning'] for x in features),flush=True)
    return features

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--station-normals',required=True);p.add_argument('--out',required=True)
    p.add_argument('--cache',required=True);p.add_argument('--zoom',type=int,default=ZOOM);p.add_argument('--workers',type=int,default=12)
    a=p.parse_args();run(a.station_normals,a.out,a.cache,a.zoom,a.workers)