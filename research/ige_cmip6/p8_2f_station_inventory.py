#!/usr/bin/env python3
"""Full MeteoSwiss SwissMetNet metadata candidate census (NOT hourly-data availability)."""
import argparse,csv,json,math
from pathlib import Path
from p8_2e_crossyear import ROOT,POOL,TARGETS
from p8_1e_swiss_external import fetch,parse_meta,haversine
from p8_2f_donor_audit import effective_distance

def catalog(meta,sites=TARGETS,pool=POOL):
    result=[]
    for sid in sites:
        if sid not in meta:raise ValueError('Target absent from original station metadata '+sid)
        t=meta[sid];lines=[]
        for other in meta.values():
            if other['station_id']==sid:continue
            dist=float(haversine(t['lat'],t['lon'],other['lat'],other['lon']))
            dz=float(other['hoehe_m']-t['hoehe_m'])
            lines.append({'target':sid,'candidate':other['station_id'],'name':other['station'],
               'distance_km':dist,'dz_m':dz,'donor_elevation_m':other['hoehe_m'],
               'effective_altitude_distance_km':effective_distance(dist,dz),
               'in_original_12_site_pool':other['station_id'] in pool,
               'hourly_and_monthly_data_availability':'NOT_CHECKED'})
        dsorted=sorted(lines,key=lambda r:(r['distance_km'],r['candidate']))
        zsorted=sorted(lines,key=lambda r:(r['effective_altitude_distance_km'],r['candidate']))
        pos_dist={x['candidate']:i+1 for i,x in enumerate(dsorted)}
        pos_alt={x['candidate']:i+1 for i,x in enumerate(zsorted)}
        for item in lines:
            item['distance_rank_all_metadata']=pos_dist[item['candidate']]
            item['altitude_rank_all_metadata']=pos_alt[item['candidate']]
        # Top 20 nearest, top 20 terrain-penalized, all original pool sites.
        result.extend(x for x in sorted(lines,key=lambda r:(r['distance_km'],r['candidate'])) if
                      x['distance_rank_all_metadata']<=20 or x['altitude_rank_all_metadata']<=20
                      or x['in_original_12_site_pool'])
    return result

def run(out):
    dest=Path(out);dest.mkdir(parents=True,exist_ok=True)
    raw,sha=fetch(ROOT+'/ogd-smn_meta_stations.csv',max_bytes=1500000)
    sites,_=parse_meta(raw)
    rows=catalog(sites)
    with (dest/'all_swissmetnet_nearby_station_inventory.csv').open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    counts={sid:{'available_station_metadata':len(sites),
        'nearest_10':[{k:x[k] for k in ('candidate','name','distance_km','dz_m','in_original_12_site_pool')}
        for x in sorted((r for r in rows if r['target']==sid),key=lambda x:x['distance_rank_all_metadata'])[:10]],
        'original_4_distance_ranks':{r['candidate']:r['distance_rank_all_metadata'] for r in rows if r['target']==sid and r['in_original_12_site_pool']}}
        for sid in TARGETS}
    meta={'phase':'P8.2F_WIDER_SWISS_STATION_METADATA_CENSUS','source_sha256':sha,
      'station_count':len(sites),'target_count':len(TARGETS),
      'provider_hourly_data_availability':'NOT_CHECKED',
      'scientific_limit':'Metadata shortlist ONLY; nearest stations may not provide complete hourly e/RH/T/P 2018-2020',
      'stations':counts}
    (dest/'station_inventory_provenance.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    print('IGE_P8_2F_SWISS_STATION_CENSUS',json.dumps(meta,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();run(a.out)