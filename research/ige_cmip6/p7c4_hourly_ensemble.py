#!/usr/bin/env python3
"""IGE P7C.4: full source-audited per-GCM hourly EPW, research only.

Never substitute P7C.3 ensemble percentile into a GCM hourly series.
Never synthesize missing huss for IPSL-CM6A-LR.
All proprietary EPW inputs/derived hourly data remain in local user-controlled artifacts.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,statistics,sys
from pathlib import Path
from collections import defaultdict
import numpy as np
import p7c1_epw_morphing as morph
import p7c1b_humidity_closure as moist
import p7c1c_hourly_humidity_coherence as coherent
import p7c3_ensemble as ensemble

MODELS=ensemble.MODELS
WINDOWS=ensemble.WINDOWS
HIST=ensemble.HIST
P7C4_FIELDS=(6,7,8,12,13,14,15,21,33)
MISSING_HUSS='IPSL-CM6A-LR'

def validate_baseline(baseline,provenance):
    provided=json.loads(Path(provenance).read_text())
    if (provided.get('provider','').lower().find('meteonorm')<0
        or provided.get('original_filename')!=Path(baseline).name
        or provided.get('sha256')!=morph.sha(baseline)
        or not provided.get('user_authorized_research_use')):
        raise ValueError('Authenticated source EPW provenance mismatch; fail closed')
    h,rows,meta=morph.read_epw(baseline)
    if meta['baseline_missing_wind_direction_hours']!=0:raise ValueError('No complete wind direction in authentic baseline')
    return h,rows,meta

def verify_daily_sources(root,expected_csv,monthly_csv):
    root=Path(root)
    expected=json.loads(Path(expected_csv).read_text())['source_sha256']
    if len(expected)!=40:raise ValueError('Missing original 8 GCM × five 20-y windows source SHA')
    baseline_index={}
    sources={}
    for model in MODELS:
        for window in (HIST,*WINDOWS):
            src=ensemble.archive_path(root,model,window)
            data,prov=ensemble.read_source(src,model,window)
            key=model+'_'+window
            if prov['daily_csv_sha256']!=expected[key]:raise ValueError('Registered source SHA discrepancy: '+key)
            if len({d['year'] for d in data})!=20:raise ValueError('Wrong model years')
            sources[key]=(data,prov)
            if window==HIST:baseline_index[model]=data
    with open(monthly_csv,newline='') as f: entries=list(csv.DictReader(f))
    if len(entries)!=384:raise ValueError('P7C3 published monthly signals incomplete')
    registered={}
    for x in entries:
        key=(x['model'],x['window'],int(x['month']))
        if key in registered or not (x['model'] in MODELS and x['window'] in WINDOWS and key[2] in range(1,13)):
            raise ValueError('Duplicated or unregistered climate delta')
        registered[key]=x
    for model in MODELS:
        hist=baseline_index[model]
        for w in WINDOWS:
            f=sources[model+'_'+w][0]
            calc=ensemble.monthly_signals(hist,f,model,w)
            for row in calc:
                reg=registered[(model,w,row['month'])]
                for a,b in (('tas_delta_C','tas_delta_C'),('dtr_ratio','dtr_ratio'),('huss_ratio','huss_ratio'),('pr_ratio','pr_ratio'),('ghi_ratio','ghi_ratio'),('rlds_ratio','rlds_ratio'),('wind_ratio','wind_ratio')):
                    actual=float(reg[a]) if reg[a] not in ('',None) else None
                    if (actual is None)!=(row[b] is None) or (actual is not None and abs(actual-row[b])>1e-9):
                        raise ValueError('P7C.3 to P7C.4 monthly signal parity failed: '+str((model,w,row['month'],a)))
    return sources,registered

def preflight(baseline,provenance,root,expected_csv,monthly_csv):
    original=validate_baseline(baseline,provenance)
    sources,registered=verify_daily_sources(root,expected_csv,monthly_csv)
    return original,sources,registered

def build_signal(model,win,source,reg):
    hist,fu=source[model+'_'+HIST][0],source[model+'_'+win][0]
    hh=defaultdict(list);ff=defaultdict(list)
    for row in hist:hh[row['month']].append(row['tas_c'])
    for row in fu:ff[row['month']].append(row['tas_c'])
    sig={}
    for m in range(1,13):
        x=reg[(model,win,m)]
        if x['huss_ratio'] in ('',None):raise ValueError('Cannot produce complete EPW without native GCM huss')
        sig[m]={
            'T_mean_delta_c':float(x['tas_delta_C']),
            'T_daily_range_ratio':float(x['dtr_ratio']),
            'specific_humidity_ratio':float(x['huss_ratio']),
            'rainfall_amount_ratio':float(x['pr_ratio']),
            'solar_ghi_ratio':float(x['ghi_ratio']),
            'wind_speed_ratio':float(x['wind_ratio']),
            'longwave_ratio':float(x['rlds_ratio']),
            'historical_daily_tas_sorted':sorted(hh[m]),
            'future_daily_tas_sorted':sorted(ff[m]),
        }
        for k,prefix in [('T_daily_range_ratio','dtr_ratio'),('specific_humidity_ratio','q_ratio'),('solar_ghi_ratio','solar_ratio'),('rainfall_amount_ratio','rain_ratio'),('wind_speed_ratio','wind_ratio'),('longwave_ratio','longwave_ratio')]:
            lower,upper=morph.SOURCE_THRESHOLDS[prefix]
            if not lower<=sig[m][k]<=upper:raise ValueError('Unregistered climate signal range: '+str((model,win,m,k,sig[m][k])))
        if abs(sig[m]['T_mean_delta_c'])>morph.SOURCE_THRESHOLDS['T_delta_abs_c']:raise ValueError('Temperature delta out of bounds')
    return sig

def climate_ratio(sig):return {m:float(sig[m]['specific_humidity_ratio']) for m in sig}

def can_morph_moisture(sources,model,win):
    # Require both original historical and future daily GCM huss; no surrogate.
    return all(x['huss'] is not None
               for key in (model+'_'+HIST,model+'_'+win)
               for x in sources[key][0])

def verify_hourly(base,stage_a,stage_b,final,signal,baseline_meta,model,win):
    if len(stage_a)!=8760 or len(stage_b)!=8760 or len(final)!=8760:raise ValueError('Incomplete EPW member')
    if any(row[:5]!=old[:5] or stage_a[i][:5]!=old[:5] or stage_b[i][:5]!=old[:5] for i,(row,old) in enumerate(zip(final,base))):raise ValueError('Time anchor drift')
    for i,(old,a,b,c) in enumerate(zip(base,stage_a,stage_b,final)):
        for j in range(35):
            if j not in P7C4_FIELDS and (old[j]!=a[j] or old[j]!=b[j] or old[j]!=c[j]):
                raise ValueError(f'Immutable field changed: {model} {win} i={i} field={j}')
            if j not in (7,8) and (a[j]!=b[j] or a[j]!=c[j]):
                raise ValueError('Humidity refinement modified other fields')
        t,td,rh,p=map(float,(c[6],c[7],c[8],c[9]))
        if not -70<t<70 or not (-80<td<=t+.00005) or not (1-1e-6<=rh<=100+1e-6) or not 30000<p<120000:raise ValueError('Psychrometric physical closure')
        if float(c[21])<0 or float(c[33])<0:raise ValueError('Negative wind/precipitation')
        # The original wind-direction sequence MUST remain identical for future morphs.
        if c[20]!=old[20]:raise ValueError('Original wind directions altered')
        if (float(c[33])>1e-10)!=(float(old[33])>1e-10):raise ValueError('Rain event occurrence changed')
    max_q_err=0.;months=[]
    for month in range(1,13):
        idx=[i for i,r in enumerate(base) if int(r[1])==month]
        qt=statistics.fmean(morph.q_from_rh(float(base[i][6]),float(base[i][8]),float(base[i][9])) for i in idx)*signal[month]['specific_humidity_ratio']
        qn=statistics.fmean(morph.q_from_rh(float(final[i][6]),float(final[i][8]),float(final[i][9])) for i in idx)
        err=abs(qn-qt)
        if err>1e-9:raise ValueError('Serialized monthly humidity mass closure lost')
        max_q_err=max(max_q_err,err)
        months.append({'model':model,'window':win,'month':month,'q_target_kg_kg':qt,'q_serialized_kg_kg':qn,'abs_q_error_kg_kg':err})
    byday=[];max_balance=0.;max_identity=0.;
    from datetime import date
    for i in range(0,8760,24):
        dt=date(int(final[i][0]),int(final[i][1]),int(final[i][2]));geometry=morph.solar_geometry(dt,baseline_meta['epw_lat'],baseline_meta['epw_lon'],baseline_meta['epw_tz']);month=dt.month
        solar_baseline=sum(float(r[13])/1000. for r in base[i:i+24]);solar_target=solar_baseline*signal[month]['solar_ghi_ratio'];solar_final=sum(float(r[13])/1000. for r in final[i:i+24]);max_balance=max(max_balance,abs(solar_final-solar_target))
        for h,row in enumerate(final[i:i+24]):
            ghi,dni,dhi=(float(row[x])/1000. for x in (13,14,15));cos,toa=geometry[h]
            if ghi<-1e-10 or dni<-1e-10 or dhi<-1e-10 or ghi>toa+1e-7:raise ValueError('Solar physical/TOA bound violated')
            max_identity=max(max_identity,abs(ghi-(dhi+dni*cos)))
    if max_balance>1e-7 or max_identity>1e-7:raise ValueError('Radiometric closure failed')
    f_rh=np.array([float(r[8]) for r in final]);b_rh=np.array([float(r[8]) for r in base]);a_rh=np.array([float(r[8]) for r in stage_b]);orig=np.abs(np.diff(b_rh));new=np.abs(np.diff(f_rh));parent=np.abs(np.diff(a_rh))
    intro=lambda v:int(np.sum((v>20.000001)&(orig<=20.000001)))
    info={'model':model,'window':win,'member':'r1i1p1f1', 'status':'RESEARCH_CLOSURE_PASS' if intro(new)==0 else 'RESEARCH_CLOSURE_WITH_HUMIDITY_DISCONTINUITY',
          'max_serialized_monthly_q_error_kg_kg':max_q_err,'max_daily_GHI_balance_kwh_m2':max_balance,'max_hourly_GHI_DNI_DHI_residual_kwh_m2':max_identity,
          'original_wind_direction_hours_inherited':8760,'original_precipitation_occurrence_hours_inherited':8760,
          'introduced_RH_gt20_pp_h_stage_b':intro(parent),'introduced_RH_gt20_pp_h_stage_c':intro(new),
          'RH_100_hours':int(np.sum(np.isclose(f_rh,100.,atol=1e-5))),'max_RH_hour_jump_pp':float(np.max(new)),
          'annual_mean_T_delta_C':statistics.fmean(float(c[6])-float(b[6]) for c,b in zip(final,base)),
          'annual_GHI_base_kwh_m2':sum(float(x[13]) for x in base)/1000.,'annual_GHI_future_kwh_m2':sum(float(x[13]) for x in final)/1000.,
          'authentic_source_graz_epw_reused':True,'production_epw_ready':False}
    return info,months

def run(baseline,provenance,zip_root,expected_sha,monthly_csv,out,model_subset=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    (h,base,meta),sources,reg=preflight(baseline,provenance,zip_root,expected_sha,monthly_csv)
    result=[];month_info=[];missing=[];generated={};method={'stage':'IGE_P7C4_EIGHT_GCM_HOURLY_EPW_ENSEMBLE','research_only':True,'production_epw_ready':False,'baseline_sha256':morph.sha(baseline),
     'baseline_is_meteonorm_contemporary':True,'GCM_grid':[46.875,15.375],'original_source_windows':{},'calendar':'native 20-y Gregorian/noleap climate distributions mapped to source fixed 365-day EPW; no event-day pairing',
     'source_monthly_signal_csv_sha256':morph.sha(monthly_csv),'missing_huss_is_not_imputed':True,
     'no_EnergyPlus_simulation':True,'limitations':['One member (r1i1p1f1) per GCM: not full internal climate-model variability',
       'Future EPW retains Meteonorm historical hourly weather event sequence', 'Unknown cloud/opaque cover/visibility/precipitable-water EPW columns are inherited as-is; not GCM-morphed',
       'Empirical Erbs DNI/DHI split is not validated against direct/diffuse measurements',
       'Preserving rain-event timing and wind directions is an assumption, not a future-wind/precipitation forecast',
       'No future GCM changes to atmospheric pressure, clouds or event chronology',
       'Daily humidity is softly preferred but not conserved; monthly specific humidity conservation is exact to serialized precision',
       'No independent EPW weather-model benchmark or EnergyPlus validation of these 28 hourly outputs']}
    for key,(x,prov) in sources.items():
        method['original_source_windows'][key]={'source_daily_csv_sha256':prov['daily_csv_sha256'],'source_zip_sha256':prov['source_zip_sha256'],'calendar':prov['calendar'],'source_day_count':len(x),'source_anomalies':prov['original_variable_census']}
    for model in MODELS:
        if model_subset and model not in model_subset:continue
        for win in WINDOWS:
            source_id=model+'_'+win
            if not can_morph_moisture(sources,model,win):
                missing.append({'model':model,'window':win,'status':'BLOCKED_MISSING_SOURCE_HUSS','complete_EPW_generated':False,'reason':'Original P6 historical and future huss absent; no surrogate, no imputation, no uncontrolled RH morphing'})
                continue
            sig=build_signal(model,win,sources,reg)
            head,a,daily,firstdiag=morph.morph_epw(h,base,sig,win.split('-')[0],win,meta)
            head[5]=['COMMENTS 1',f'IGE P7C.4 model={model} member=r1i1p1f1 {win}; input Meteonorm Graz Contemporary, research only']
            head[6]=['COMMENTS 2','Source station hourly patterns inherited; monthly GCM climate signals; RH monthly q-closure and temporal optimization; not observed future weather']
            b,months_b,days_b,second=moist.hourly_redistribution(base,a,climate_ratio(sig))
            mon,t,p,ref,target,lo,hi,prior=coherent.arrays_for_moisture(base,b,climate_ratio(sig))
            sol,opt=coherent.minimize_humidity(target,lo,hi,mon,t,p,ref,prior)
            c,third=coherent.evaluate_epw(base,b,sol,target,mon,t,p,ref)
            fname=f'Graz_{model}_{win}_P7C4_HOURLY_ENSEMBLE_RESEARCH_ONLY.epw'
            path=out/fname
            morph.write_epw(path,head,c)
            hh,rows,newmeta=morph.read_epw(path)
            info,mlist=verify_hourly(base,a,b,rows,sig,meta,model,win)
            info.update({'EPW_filename':fname,'EPW_sha256':morph.sha(path),'source_historical_daily_csv_sha256':method['original_source_windows'][model+'_'+HIST]['source_daily_csv_sha256'],
                'source_future_daily_csv_sha256':method['original_source_windows'][source_id]['source_daily_csv_sha256'],
                'optimizer_objective_before':opt['objective_before'],'optimizer_objective_after':opt['objective_after'],
                'optimizer_converged_by_delta':opt['converged_by_delta'],'optim_iterations_accepted':opt['iterations_accepted']})
            result.append(info);month_info.extend(mlist);generated[fname]=info['EPW_sha256']
            print('P7C4',model,win,info['status'],'added jumps',info['introduced_RH_gt20_pp_h_stage_b'],'->',info['introduced_RH_gt20_pp_h_stage_c'],flush=True)
    if not model_subset and (len(result)!=28 or len(missing)!=4 or len(month_info)!=336):raise ValueError('Expected 28 complete + 4 blocked + 336 monthly validations')
    def writecsv(name,values):
        if values:
            with (out/name).open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(values[0]));w.writeheader();w.writerows(values)
    writecsv('p7c4_model_hourly_closure_summary.csv',result)
    writecsv('p7c4_model_monthly_humidity_balance.csv',month_info)
    writecsv('p7c4_blocked_source_windows.csv',missing)
    report={**method,'n_models':8,'n_windows':4,'n_full_epws':len(result),'n_blocked_missing_huss':len(missing),'n_monthly_humidity_closures':len(month_info),
        'blocked':missing,'results':result,'derived_epw_file_sha256':generated}
    (out/'p7c4_hourly_science_audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('baseline','provenance','zip-root','expected-sha','monthly-csv','out'):p.add_argument('--'+k,required=True)
    p.add_argument('--model-subset',nargs='*',default=None)
    q=p.parse_args();r=run(q.baseline,q.provenance,q.zip_root,q.expected_sha,q.monthly_csv,q.out,q.model_subset)
    print(json.dumps({'n_full_epws':r['n_full_epws'],'blocked':r['n_blocked_missing_huss'],'production_epw_ready':False},indent=2))