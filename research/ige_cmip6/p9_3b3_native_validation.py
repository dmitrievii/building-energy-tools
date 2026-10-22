"""Sealed, paired PRESSURE-ONLY development comparison on revealed 2021 days.

No observation is an input to source-column admission, geometry, or prediction.
Country/season/method cells remain in the denominator when sources are blocked.
"""
from __future__ import annotations
from collections import Counter
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import urllib.parse
import zipfile

import numpy as np

from p9_3b3_compare_vertical_frame import SourceBlocked
from p9_3b3_pressure_reference import station_pressure
from p9_3b3_reference_sources import AT,DE


def target_hours(protocol):
    return [day+'T'+str(hour).zfill(2)+':00' for day in protocol['development_days'] for hour in range(24)]


def sealed_read(path,sha):
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('P93N_SEALED_PREDICTIONS_CHANGED')
    return json.loads(raw)


def observation_pressure(cache,country,protocol):
    wanted=set(target_hours(protocol));values={};qc=Counter();sources=[]
    def fetch(url,limit=None):
        b=cache.fetch(url,limit=limit);sources.append({'url':url,'sha256':hashlib.sha256(b).hexdigest()});return b
    if country=='AT':
        meta=json.loads(fetch(AT));fields={p['name']:p for p in meta['parameters']}
        if fields['p']['unit']!='hPa':raise ValueError('P93N_AT_PRESSURE_UNIT')
        base=AT.rsplit('/metadata',1)[0];identity=[]
        for day in protocol['development_days']:
            series={}
            for station_id in (30,16412):
                params={'station_ids':str(station_id),'parameters':'p,p_flag','output_format':'geojson',
                    'start':day+'T00:00Z','end':day+'T23:00Z'}
                obj=json.loads(fetch(base+'?'+urllib.parse.urlencode(params)))
                if len(obj['features'])!=1:raise ValueError('P93N_AT_STATION_COUNT')
                data=obj['features'][0]['properties']['parameters']
                stamps=[dt.datetime.fromisoformat(t.replace('Z','+00:00')).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M') for t in obj['timestamps']]
                if stamps!=[day+'T'+str(h).zfill(2)+':00' for h in range(24)]:raise ValueError('P93N_AT_TIME_AXIS')
                series[station_id]=(stamps,data['p']['data'],data['p_flag']['data'])
            if series[30]!=series[16412]:raise SourceBlocked('P93N_AT_COMBINED_INDIVIDUAL_PRESSURE_IDENTITY_NOT_EXACT')
            identity.append({'day':day,'combined_30_equals_individual_16412':'EXACT_PRESSURE_VALUES_FLAGS_AND_TIMES'})
            stamps,pressure,flags=series[30]
            for stamp,p,flag in zip(stamps,pressure,flags):
                qc[str(flag)]+=1
                if p is not None and flag in (10,11,12,20,21,22) and math.isfinite(float(p)) and 450<float(p)<1100:values[stamp]=float(p)*100
        detail={'historical_combined_member_identity':identity,'QC':'GEOSPHERE_NATIVE_GOOD_FLAGS',
            'time_support':'PROVIDER_1H_NODE_PROXY_INTERVAL_UNRESOLVED_PREDECLARED'}
    elif country=='DE':
        with zipfile.ZipFile(io.BytesIO(fetch(DE))) as z:
            products=[n for n in z.namelist() if n.startswith('produkt') and n.endswith('.txt')]
            if len(products)!=1:raise ValueError('P93N_DWD_PRESSURE_PRODUCT_AMBIGUOUS')
            with z.open(products[0]) as stream:
                reader=csv.DictReader(io.TextIOWrapper(stream,encoding='latin1'),delimiter=';')
                for raw in reader:
                    row={k.strip():v.strip() for k,v in raw.items() if k is not None};t=row.get('MESS_DATUM','')
                    if len(t)!=12 or not t.endswith('00'):continue
                    stamp=dt.datetime.strptime(t,'%Y%m%d%H%M').strftime('%Y-%m-%dT%H:%M')
                    if stamp not in wanted:continue
                    if int(row['STATIONS_ID'])!=399:raise ValueError('P93N_DWD_OTHER_STATION')
                    qc[row.get('QN','')]+=1;p,_=station_pressure(row,'DWD_URBAN_10MIN')
                    if p is not None:
                        if stamp in values:raise ValueError('P93N_DWD_DUPLICATE_STATION_HOUR')
                        values[stamp]=p
        detail={'field':'P0_ST_10','sea_level_field_forbidden':'PP_ST_10',
            'QC':'NATIVE_QN_RETAINED_EMPTY_IS_NOT_FINAL_QC','time_support':'ORIGINAL_HH00_INSTANTANEOUS'}
    elif country=='CH':
        url='https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/dav/ogd-smn_dav_h_historical_2020-2029.csv'
        reader=csv.DictReader(io.StringIO(fetch(url).decode('utf-8-sig')),delimiter=';')
        if not {'station_abbr','reference_timestamp','prestah0'}<=set(reader.fieldnames or []):raise ValueError('P93N_CH_QFE_SCHEMA')
        for row in reader:
            try:stamp=dt.datetime.strptime(row['reference_timestamp'],'%d.%m.%Y %H:%M').strftime('%Y-%m-%dT%H:%M')
            except ValueError:continue
            if stamp not in wanted:continue
            if row['station_abbr'].strip().upper()!='DAV':raise ValueError('P93N_CH_OTHER_STATION')
            try:p=float(row['prestah0'])
            except ValueError:continue
            if math.isfinite(p) and 450<p<1100:
                if stamp in values:raise ValueError('P93N_CH_DUPLICATE_STATION_HOUR')
                values[stamp]=p*100
        detail={'field':'prestah0','QC':'PUBLISHED_SOURCE_NO_COMPARABLE_SAMPLE_QC',
            'time_support':'PRECEDING_HOUR_MEAN_END_STAMP_TRAPEZOID_PREDICTION_PROXY'}
    else:raise ValueError('P93N_COUNTRY_OUTSIDE_AT_DE_CH')
    return values,{'country':country,'status':'SOURCE_READ','valid_hours':len(values),'expected_hours':48,
        'native_qc':dict(qc),'sources':sources,**detail}


def predicted_pressure(predictions,country,method,stamp):
    value=predictions.get(stamp,{}).get(country,{}).get('methods',{}).get(method,{})
    p=value.get('pressure_Pa')
    if p is None:return None
    if country=='CH':
        previous=(dt.datetime.fromisoformat(stamp)-dt.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')
        earlier=predictions.get(previous,{}).get(country,{}).get('methods',{}).get(method,{}).get('pressure_Pa')
        if earlier is None:return None
        return .5*(p+earlier)
    return p


def score_pressure(predictions,observed,protocol):
    cells=[];paired=[]
    for country in protocol['countries']:
        for day in protocol['development_days']:
            stamps=[t for t in target_hours(protocol) if t.startswith(day)]
            baseline='P2_NATIVE_SINGLE_COLUMN'
            for method in protocol['methods']:
                errors=[];common=[]
                for t in stamps:
                    p=predicted_pressure(predictions,country,method,t);truth=observed.get(country,{}).get(t)
                    if p is None or truth is None:continue
                    error=(p-truth)/100;errors.append(error)
                    b=predicted_pressure(predictions,country,baseline,t)
                    if b is not None:common.append((error,(b-truth)/100))
                row={'country':country,'day':day,'method':method,'expected_hours':24,'matched_hours':len(errors),
                    'coverage':len(errors)/24,'scope':'REVEALED_TWO_DAY_DEVELOPMENT_DIAGNOSTIC_NOT_NEW_INDEPENDENT_VALIDATION'}
                if errors:
                    e=np.array(errors);row.update(MAE_hPa=float(np.mean(abs(e))),bias_hPa=float(np.mean(e)),RMSE_hPa=float(np.sqrt(np.mean(e*e))),max_abs_error_hPa=float(np.max(abs(e))))
                row['accuracy_gate']=('INCONCLUSIVE_COVERAGE' if len(errors)<24*protocol['minimum_cell_coverage'] else
                    'PASS_THIS_REVEALED_CELL' if row['MAE_hPa']<=protocol['pressure_MAE_gate_hPa'] else 'FAIL_THIS_REVEALED_CELL')
                row['independently_qualified']=False;cells.append(row)
                if common:
                    a,b=np.array(common).T;paired.append({'country':country,'day':day,'method':method,'baseline':baseline,
                        'paired_hours':len(common),'delta_MAE_hPa':float(np.mean(abs(a))-np.mean(abs(b))),
                        'delta_RMSE_hPa':float(np.sqrt(np.mean(a*a))-np.sqrt(np.mean(b*b)))})
    return {'cells':cells,'paired_comparisons':paired,'expected_score_cells':len(protocol['countries'])*len(protocol['development_days'])*len(protocol['methods']),
        'independent_accuracy':'NOT_QUALIFIED_PREVIOUSLY_REVEALED_DAYS_SMALL_PILOT',
        'all_AT_DE_CH_qualified':False,'B4_qualified':False,'production_epw_ready':False}


def score_sealed(path,digest,cache,protocol,eligible_countries=None):
    pred=sealed_read(path,digest);observed={};sources={}
    for country in protocol['countries']:
        if eligible_countries is not None and country not in eligible_countries:
            observed[country]={};sources[country]={'status':'OBSERVATIONS_NOT_OPENED_HISTORICAL_REFERENCE_BLOCKED'};continue
        try:observed[country],sources[country]=observation_pressure(cache,country,protocol)
        except (OSError,ValueError,KeyError,zipfile.BadZipFile) as exc:
            observed[country]={};sources[country]={'status':'SOURCE_BLOCKED','reason':type(exc).__name__+':'+str(exc)}
    # Recheck after I/O as well; source access cannot silently replace predictions.
    sealed_read(path,digest)
    return {**score_pressure(pred['hourly'],observed,protocol),'sealed_prediction_sha256':digest,'observation_provenance':sources}
