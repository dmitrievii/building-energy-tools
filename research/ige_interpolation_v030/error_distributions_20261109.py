"""Frozen-V error distributions, balanced temporal profiles and diagnostic oracles.

Requires numpy, scipy and matplotlib. Never evaluates real C or refits models.
python research/ige_interpolation_v030/error_distributions_20261109.py --run PATH --out PATH
"""
import os
for _name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[_name]='1'
import argparse,csv,datetime as dt,itertools,json,math,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
CODE=next(p for p in (ROOT/'tools/ige_climate_experiments',ROOT/'artifacts/v030_restored_source') if (p/'ige_next/cases.py').is_file())
sys.path.insert(0,str(CODE))
from ige_auto.data import Cube,buck_water
from ige_auto.cases import Cases,macro_weights
from ige_hum.config import sealed,check_cohort
from ige_hum.physics import q_from_e,dewpoint_water
from ige_next.cases import Moisture,restore
from ige_local.common import file_hash,write_csv,write_json

T_NAMES={'nearest':'Ближайшая станция','idw_uncorrected':'IDW без поправки','height_idw_ols':'Постоянная по высоте','seasonal_idw_ols':'Сезонная по высоте','monthly_idw_ols':'Месячная по высоте','diurnal_height_ridge':'Высота + год/сутки','hinge_height_ridge':'Высотный spline','local_height_shrinkage':'Локальный градиент','background_residual_idw':'Фон + остатки','aux_shared':'Общая T для влажности'}
COORDS=['RH','log_e','q','Td','D'];H_NAMES={'RH':'RH напрямую','log_e':'Через ln(e)','q':'Через q','Td':'Через Td','D':'Через T−Td'}
T_ORDER=['nearest','idw_uncorrected','height_idw_ols','seasonal_idw_ols','monthly_idw_ols','diurnal_height_ridge','hinge_height_ridge','local_height_shrinkage','background_residual_idw']
COLORS={'RH':'#0072B2','log_e':'#E69F00','q':'#009E73','Td':'#D55E00','D':'#8B63AC'}
MONTHS=['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек']

def load_array(folder):
    with np.load(folder/'V_predictions.npz',allow_pickle=False) as z:return {k:z[k].copy() for k in z.files}

def quantiles(x,w,qs):
    order=np.argsort(x);xx=x[order];ww=w[order];cdf=np.cumsum(ww)/ww.sum()
    return [float(xx[min(np.searchsorted(cdf,q,side='left'),len(xx)-1)]) for q in qs]

def calculate(run,out):
    spec=sealed(run/'run_spec.sealed.json','spec_id');summary=json.loads((run/'summary.json').read_text());cube=Cube(run/'cube');check_cohort(cube,spec['anchor'])
    assert summary['holdout_opened'] is False
    c=spec['base_configuration'];d=np.flatnonzero(cube.roles=='D');v=np.flatnonzero(cube.roles=='V');vt=np.flatnonzero(cube.time_roles=='V')
    native=Moisture(cube,c,[(v,vt)],d,'distribution_V','joint');case=native.base
    assert np.all(cube.roles[case.s]=='V') and np.all(cube.time_roles[case.t]=='V')
    month=cube.month[case.t]
    utc=np.array([dt.datetime.fromisoformat(cube.times[t].replace('Z','+00:00')).hour+dt.datetime.fromisoformat(cube.times[t].replace('Z','+00:00')).minute/60 for t in case.t])
    longitude=np.array([cube.stations[s]['lon'] for s in case.s]);solar=(utc+longitude/15)%24;hbin=(solar//3).astype(int)
    frames={};results={}
    for model in T_ORDER:
        key='T/native/T/'+model;folder=run/'models'/key;r=sealed(folder/'result.sealed.json','result_id')
        assert file_hash(folder/'V_predictions.npz')==r['artifacts']['V_predictions.npz']
        a=load_array(folder);assert np.array_equal(a['station_index'],case.s) and np.array_equal(a['time_index'],case.t)
        frames['T/'+model]={'key':'T/'+model,'stage':'T','label':T_NAMES[model],'model':model,'unit':'degC','error':a['predicted']-a['observed'],'mask':a['common_mask'],'data':a};results['T/'+model]=r
    for support in ('joint','own'):
        for co in COORDS:
            chosen=summary['best_per_group']['humidity/'+support+'/'+co];folder=run/'models'/chosen['key'];r=sealed(folder/'result.sealed.json','result_id')
            assert file_hash(folder/'V_predictions.npz')==r['artifacts']['V_predictions.npz']
            a=load_array(folder);key='H/'+support+'/'+co
            assert np.array_equal(a['station_index'],case.s) and np.array_equal(a['time_index'],case.t)
            frames[key]={'key':key,'stage':'H','label':H_NAMES[co],'model':r['candidate']['model']['id'],'support':support,'coordinate':co,'unit':'RH_pp','error':a['predicted']-a['observed'],'mask':a['common_mask'],'data':a};results[key]=r
    hmask=frames['H/own/RH']['mask'].copy();tmask=frames['T/height_idw_ols']['mask'].copy()
    assert all(np.array_equal(f['mask'],hmask) for f in frames.values() if f['stage']=='H')
    assert all(np.array_equal(f['mask'],tmask) for f in frames.values() if f['stage']=='T')
    assert np.all(tmask[hmask])
    shared=frames['H/own/RH']['data']['T_aux_predicted'];actual_t=np.asarray(cube.values[case.s,case.t,0]);assert np.isfinite(shared[tmask]).all()
    frames['T/aux_shared']={'key':'T/aux_shared','stage':'T','label':T_NAMES['aux_shared'],'model':'parent_D_height_IDW','unit':'degC','error':shared-actual_t,'mask':tmask.copy(),'data':{'predicted':shared,'observed':actual_t}}
    # Fixed-structure controls: same monthly transfer regression for all moisture coordinates.
    fixed={}
    for co in COORDS:
        folder=run/'models/humidity/own'/co/'monthly_idw_ols';r=sealed(folder/'result.sealed.json','result_id');a=load_array(folder)
        assert file_hash(folder/'V_predictions.npz')==r['artifacts']['V_predictions.npz']
        assert np.array_equal(a['station_index'],case.s) and np.array_equal(a['time_index'],case.t)
        assert np.array_equal(a['common_mask'],hmask)
        fixed[co]={'key':'H/fixed_monthly/'+co,'stage':'H','label':H_NAMES[co],'model':'monthly_idw_ols','support':'own','coordinate':co,'unit':'RH_pp','error':a['predicted']-a['observed'],'mask':hmask.copy(),'data':a}
    def stats(error,mask):
        use=mask&np.isfinite(error);assert np.array_equal(mask,use)
        e=error[use];w=macro_weights(case,use,month_balance=False)[use]
        q=quantiles(abs(e),w,[.5,.75,.9,.95,.99]);median=quantiles(e,w,[.5])[0]
        threshold=q[3];tail=abs(e)>=threshold
        total_abs=float(np.sum(w*abs(e)));total_squared=float(np.sum(w*e*e))
        return {'N':int(use.sum()),'stations':len(set(case.station[use])),'countries':len(set(case.country[use])),
            'MAE_macro':float(np.sum(w*abs(e))),'MAE_pooled':float(np.mean(abs(e))),'bias_macro':float(np.sum(w*e)),
            'RMSE_macro':float(np.sqrt(np.sum(w*e*e))),'RMSE_pooled':float(np.sqrt(np.mean(e*e))),
            'median_signed_macro':median,'P50_abs_macro':q[0],'P75_abs_macro':q[1],'P90_abs_macro':q[2],'P95_abs_macro':q[3],'P99_abs_macro':q[4],
            'median_abs_pooled':float(np.median(abs(e))),'P95_abs_pooled':float(np.quantile(abs(e),.95)),
            'min_error':float(np.min(e)),'max_error':float(np.max(e)),
            'tail_ge_P95_weight_fraction':float(w[tail].sum()),'tail_ge_P95_MAE_share':float(np.sum(w[tail]*abs(e[tail]))/total_abs) if total_abs else 0.,
            'tail_ge_P95_MSE_share':float(np.sum(w[tail]*e[tail]**2)/total_squared) if total_squared else 0.}
    statistics={};thresholds=[]
    allframes={**frames,**{'H/fixed_monthly/'+co:f for co,f in fixed.items()}}
    for key,f in allframes.items():
        st=stats(f['error'],f['mask']);statistics[key]={'label':f['label'],'model':f['model'],'unit':f['unit'],**st}
        if key in results:assert abs(st['MAE_macro']-results[key]['primary_macro_MAE'])<1e-9
        e=abs(f['error'][f['mask']]);w=macro_weights(case,f['mask'],False)[f['mask']]
        for x in ([.5,1,2,3,5,10] if f['stage']=='T' else [2,5,10,15,20,30,40]):
            thresholds.append({'key':key,'threshold':x,'unit':f['unit'],'N':len(e),'fraction_pooled':float(np.mean(e<=x)),'fraction_macro':float(w[e<=x].sum())})
    write_csv(out/'distribution_metrics.csv',[{'key':k,**x} for k,x in statistics.items()],['key']+list(next(iter(statistics.values()))))
    write_csv(out/'threshold_frequencies.csv',thresholds,list(thresholds[0]))
    # Both raw observation counts and macro-standardized frequencies are retained.
    bins={}
    for stage in ('T','H'):
        mx=max(float(np.max(abs(f['error'][f['mask']]))) for f in frames.values() if f['stage']==stage)
        step=.5 if stage=='T' else 2.;bound=math.ceil(mx/step)*step
        bins[stage]={'signed':np.arange(-bound,bound+step/2,step),'absolute':np.arange(0,bound+step/2,step),'step':step,'bound':bound}
    hist_rows=[]
    for key,f in allframes.items():
        e=f['error'][f['mask']];w=macro_weights(case,f['mask'],False)[f['mask']]
        for shape in ('signed','absolute'):
            values=e if shape=='signed' else abs(e);edges=bins[f['stage']][shape]
            raw,_=np.histogram(values,edges);weighted,_=np.histogram(values,edges,weights=w)
            assert raw.sum()==len(e) and abs(weighted.sum()-1)<1e-9
            for lo,hi,n,freq in zip(edges[:-1],edges[1:],raw,weighted):hist_rows.append({'key':key,'shape':shape,'unit':f['unit'],'lower':lo,'upper':hi,'count':int(n),'frequency_pooled_pct':float(n/len(e)*100),'frequency_macro_pct':float(freq*100)})
    write_csv(out/'histogram_bins.csv',hist_rows,list(hist_rows[0]))
    # Diagnostic-only balanced station panel: at least one valid case in each month/hour cell.
    balanced_stations=[]
    for st in sorted(set(case.station[hmask])):
        ix=hmask&(case.station==st)
        if all(np.any(ix&(month==m)&(hbin==h)) for m in range(1,13) for h in range(8)):balanced_stations.append(st)
    balanced=hmask&np.isin(case.station,balanced_stations)
    assert balanced.any() and all(np.isfinite(f['error'][balanced]).all() for f in frames.values())
    temporal=[];cell_rows=[];paired=[];station_month=[]
    bootstrap_indices=np.random.default_rng(20261109).integers(0,12,(4000,12))
    for key,f in frames.items():
        for scope,mask in (('primary',f['mask']),('balanced',balanced)):
            groups=[('month',m,(month==m)) for m in range(1,13)]+[('solar_3h',h,(hbin==h)) for h in range(8)]+[('season',i,((month%12)//3==i)) for i in range(4)]
            for kind,group,gmask in groups:
                use=mask&gmask;st=stats(f['error'],use)
                temporal.append({'key':key,'scope':scope,'kind':kind,'group':group,**{k:st[k] for k in ('N','stations','countries','MAE_macro','MAE_pooled','bias_macro','P90_abs_macro')}})
        for m in range(1,13):
            for h in range(8):
                st=stats(f['error'],balanced&(month==m)&(hbin==h))
                cell_rows.append({'key':key,'month':m,'solar_3h':h,**{k:st[k] for k in ('N','MAE_macro','bias_macro')}})
        deltas=[];nights=[];afternoons=[]
        for m in range(1,13):
            use=balanced&(month==m);night=use&(solar<6);afternoon=use&(solar>=12)&(solar<18)
            an=stats(f['error'],night)['MAE_macro'];ad=stats(f['error'],afternoon)['MAE_macro'];nights.append(an);afternoons.append(ad);deltas.append(an-ad)
            for st in balanced_stations:
                n=night&(case.station==st);a=afternoon&(case.station==st)
                station_month.append({'key':key,'station':st,'month':m,'night_MAE':float(np.mean(abs(f['error'][n]))),'afternoon_MAE':float(np.mean(abs(f['error'][a]))),'delta_night_minus_afternoon':float(np.mean(abs(f['error'][n]))-np.mean(abs(f['error'][a])))})
        draws=np.array(deltas)[bootstrap_indices].mean(axis=1);interval=np.quantile(draws,[.025,.975])
        paired.append({'key':key,'night_00_06_macro_MAE':float(np.mean(nights)),'afternoon_12_18_macro_MAE':float(np.mean(afternoons)),
            'delta_night_minus_afternoon':float(np.mean(deltas)),'conditional_CI95_low':float(interval[0]),'conditional_CI95_high':float(interval[1]),
            'monthly_blocks_night_worse':int((np.array(deltas)>0).sum()),'monthly_blocks':12,
            'bootstrap_scope':'4000 resamples of the 12 common two-day month blocks, all stations move together; conditional on these V stations; exploratory',
            'clock':'mean local solar time UTC+longitude/15; not astronomical darkness'})
    write_csv(out/'temporal_profiles.csv',temporal,list(temporal[0]));write_csv(out/'month_hour_balanced.csv',cell_rows,list(cell_rows[0]));write_csv(out/'night_afternoon_paired.csv',paired,list(paired[0]));write_csv(out/'station_month_paired.csv',station_month,list(station_month[0]))
    station_rows=[]
    for key,f in frames.items():
        for station in sorted(set(case.station[f['mask']])):
            mask=f['mask']&(case.station==station);ix=np.flatnonzero(mask)[0];st=cube.stations[case.s[ix]];e=f['error'][mask]
            station_rows.append({'key':key,'station':station,'name':st.get('name',''),'country':st['country'],'height_m':st['height_m'],'N':int(mask.sum()),'MAE':float(np.mean(abs(e))),'bias':float(np.mean(e)),'P95_abs':float(np.quantile(abs(e),.95))})
    write_csv(out/'station_errors.csv',station_rows,list(station_rows[0]))
    # Retain outliers and their QC; a large prediction error is not a bad-data label.
    outliers=[]
    for key in ('T/height_idw_ols','H/own/RH'):
        f=frames[key];ii=np.flatnonzero(f['mask']);ii=ii[np.argsort(abs(f['error'][ii]))[-50:][::-1]]
        for rank,i in enumerate(ii,1):
            station=cube.stations[case.s[i]]
            row={'key':key,'rank':rank,'station':station['key'],'name':station.get('name',''),'country':station['country'],
                'timestamp_UTC':cube.times[case.t[i]],'solar_hour':float(solar[i]),'observed':float(f['data']['observed'][i]),'predicted':float(f['data']['predicted'][i]),
                'signed_error':float(f['error'][i]),'observed_T':float(native.values[i,0]),'observed_RH':float(native.values[i,1]),
                'shared_T_predicted':float(shared[i]),'target_QC_TRHp':json.dumps([cube.meta['qc_codebook'][int(k)] for k in native.target_qc[i]],ensure_ascii=False)}
            if key=='H/own/RH':
                ww=f['data']['donor_weights'][i];top=np.argsort(ww)[-3:][::-1]
                row['top_donors']=json.dumps([{'station':cube.stations[case.d[j]]['key'],'weight':float(ww[j]),
                    'T':float(native.dvalues[i,j,0]),'RH':float(native.dvalues[i,j,1])} for j in top if ww[j]>0],ensure_ascii=False)
            outliers.append(row)
    write_csv(out/'largest_errors.csv',outliers,list(dict.fromkeys(k for r in outliers for k in r)))
    # Availability/geometry diagnostics of direct RH. Associations are not causal estimates.
    rh=frames['H/own/RH'];view=native.view('RH',False);w=rh['data']['donor_weights'];assert np.max(abs(w[~view.mask]),initial=0)==0
    nearest=np.min(np.where(view.mask,view.dist,np.inf),axis=1);dz=np.sum(w*abs(view.dz),axis=1)*1000;neff=1/np.maximum(np.sum(w*w,axis=1),1e-30)
    geometry=[]
    for kind,x,edges in (('nearest_eligible_donor_km',nearest,[0,25,50,100,200,math.inf]),('weighted_abs_height_gap_m',dz,[0,100,300,700,1500,math.inf]),('effective_donors',neff,[0,1.5,2,3,5,math.inf]),('reference_RH',native.values[:,1],[0,30,60,80,95,101,math.inf])):
        for lo,hi in zip(edges[:-1],edges[1:]):
            use=hmask&(x>=lo)&(x<hi)
            if use.any():geometry.append({'quantity':kind,'lower':lo,'upper':None if not math.isfinite(hi) else hi,**{k:v for k,v in stats(rh['error'],use).items() if k in ('N','stations','countries','MAE_macro','MAE_pooled','bias_macro','P95_abs_macro')}})
    write_csv(out/'RH_geometry_and_regime.csv',geometry,list(geometry[0]))
    # Counterfactual observations used only to diagnose a frozen chain on V.
    t_true=native.values[:,0];p_true=native.values[:,2];e_true=native.e;td_true=native.td
    with np.errstate(divide='ignore',invalid='ignore'):log_e_true=np.log(e_true)
    truth={'RH':native.values[:,1],'log_e':log_e_true,'q':native.q,'Td':td_true,'D':t_true-td_true}
    oracle_rows=[];attribution={};wfull=macro_weights(case,hmask,False)[hmask]
    for co in COORDS:
        f=frames['H/own/'+co];a=f['data'];deps=['moisture'] if co=='RH' else (['T','p','moisture'] if co=='q' else ['T','moisture']);losses={};group_rows=[]
        for size in range(len(deps)+1):
            for sub in itertools.combinations(deps,size):
                known=frozenset(sub);t=t_true if 'T' in known else a['T_aux_predicted'];p=p_true if 'p' in known else a['p_aux_predicted'];nv=truth[co] if 'moisture' in known else a['native_prediction']
                pred=restore(co,nv,{'T':t,'p':p})['RH'];err=pred-native.values[:,1];st=stats(err,hmask);loss=float(np.sum(wfull*err[hmask]**2));losses[known]=loss
                row={'coordinate':co,'known_inputs':'+'.join(sub) if sub else 'none_predicted_chain','N':st['N'],'MAE_macro':st['MAE_macro'],'RMSE_macro':st['RMSE_macro'],'bias_macro':st['bias_macro'],'macro_MSE_RH_pp_squared':loss}
                oracle_rows.append(row);group_rows.append(row)
        contrib={k:0. for k in deps};perms=list(itertools.permutations(deps))
        for order in perms:
            known=frozenset()
            for part in order:
                nxt=known|{part};contrib[part]+=(losses[known]-losses[nxt])/len(perms);known=nxt
        assert abs(sum(contrib.values())-(losses[frozenset()]-losses[frozenset(deps)]))<1e-8
        attribution[co]={'base_macro_MSE':losses[frozenset()],'all_observed_macro_MSE':losses[frozenset(deps)],'shapley_reduction_pp_squared':contrib,
            'fraction_of_base_MSE':{k:v/losses[frozenset()] for k,v in contrib.items()},
            'scope':'Deterministic diagnostic substitutions; parameterization-dependent, not causal sensor-error shares; e/q/Td references derived from observed T/RH/p; negative contributions possible through error cancellation'}
    write_csv(out/'oracle_substitutions.csv',oracle_rows,list(oracle_rows[0]));write_json(out/'oracle_MSE_attribution.json',attribution)
    # First-order sensitivity of the same Buck-water curve used in the experiment.
    t=20.;rh0=70.;alpha=(18.678*257.14-(2*257.14*t+t*t)/234.5)/(257.14+t)**2
    scalar={'example_T_C':t,'example_RH_pct':rh0,'dln_es_dT_per_K':alpha,'dRH_dT_fixed_e_pp_per_K':-rh0*alpha,
        'RH_if_T_pred_plus_1K_fixed_e':rh0*float(buck_water(t)/buck_water(t+1)),
        'dRH_from_p_error_example_pp':rh0*2/1000,'note':'p derivative at fixed q; T derivative at fixed e; linearized errors can cancel or reinforce'}
    balanced_counts={co:len({st for st in balanced_stations if str(case.country[np.flatnonzero(case.station==st)[0]])==co}) for co in sorted(set(case.country[balanced]))}
    analysis={'schema':'IGE_ERROR_DISTRIBUTIONS_v1','created_date':'2026-11-09','run_spec_id':spec['spec_id'],'cube_id':cube.meta['cube_id'],
        'source_run_name':run.name,'source_commit':'c1342e06ef3c9cf544a6949bc870a8aa2c9c2ee1','holdout_evaluated':False,'model_fitting_or_selection_performed':False,
        'frequency_weighting':'equal countries then equal stations; observed cases within station have equal weights; raw counts and pooled frequencies also exported',
        'primary_N_T':int(tmask.sum()),'primary_N_RH':int(hmask.sum()),'balanced_diagnostic_N':int(balanced.sum()),'balanced_stations':balanced_stations,'balanced_country_counts':balanced_counts,
        'balanced_gate':'Diagnostic control only: at least one common case in each month x 3h cell; all partial records retained for main distributions',
        'time_definition':'mean local solar time UTC+longitude/15, no equation of time or DST; month is original UTC month',
        'sampling':'15-16th of each month, V year 2023; observed associations, not established annual climatology',
        'statistics':statistics,'thresholds':thresholds,'paired_night_afternoon':paired,'oracle_rows':oracle_rows,'oracle_attribution':attribution,'sensitivity_example':scalar,
        'station_rows':station_rows,'geometry_rows':geometry,'histogram_axes':{k:{'step':v['step'],'bound':v['bound']} for k,v in bins.items()}}
    write_json(out/'analysis.json',analysis)
    return analysis,frames,fixed,case,bins,balanced,temporal,cell_rows


def draw(out,analysis,frames,fixed,case,bins,balanced,temporal,cells):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
    note='Частоты: равные веса стран и станций. Ошибка = прогноз − наблюдение. V: выбранные дни 2023 года.'
    made=[]
    def save(fig,name):
        fig.savefig(out/(name+'.png'),dpi=180,facecolor='white');fig.savefig(out/(name+'.svg'),facecolor='white');plt.close(fig);made.append(name)
    def ecdf(ax,f,color,ls,label):
        e=abs(f['error'][f['mask']]);w=macro_weights(case,f['mask'],False)[f['mask']];order=np.argsort(e);ax.step(np.r_[0,e[order]],np.r_[0,np.cumsum(w[order])*100],where='post',color=color,ls=ls,lw=1.8,label=label)
    def freq(ax,f,color,ls,label):
        e=f['error'][f['mask']];w=macro_weights(case,f['mask'],False)[f['mask']];h,_=np.histogram(e,bins[f['stage']]['signed'],weights=w);ax.stairs(h*100,bins[f['stage']]['signed'],color=color,ls=ls,lw=1.7,label=label)
    ts=[('nearest','#7A7A7A',':'),('idw_uncorrected','#E69F00','-.'),('height_idw_ols','#0072B2','-'),('hinge_height_ridge','#009E73','--'),('local_height_shrinkage','#8B63AC',(0,(5,2,1,2)))]
    for stage,name,title,unit,items in (
        ('T','01_temperature_frequency','Температура: распределение ошибок','°C',[(frames['T/'+m],co,ls,T_NAMES[m]) for m,co,ls in ts]),
        ('H','02_humidity_frequency','Восстановленная RH: собственные необходимые входы','п.п. RH',[(frames['H/own/'+co],COLORS[co],['-','--',':','-.',(0,(5,2,1,2))][i],H_NAMES[co]) for i,co in enumerate(COORDS)])):
        fig,axs=plt.subplots(1,2,figsize=(14,5.8));handles=[]
        for f,color,ls,label in items:freq(axs[0],f,color,ls,label);ecdf(axs[1],f,color,ls,label)
        zoom=6 if stage=='T' else 30
        axs[0].axvline(0,color='#333333',lw=.8,alpha=.7);axs[0].set(xlabel='Ошибка, '+unit,ylabel='Взвешенная частота в интервале, %',xlim=(-zoom,zoom),title='Центр распределения ошибки')
        axs[1].set(xlabel='Абсолютная ошибка, '+unit,ylabel='Доля с |ошибкой| ≤ x, %',ylim=(0,101),xlim=(0,bins[stage]['bound']),title='Накопленная частота абсолютной ошибки')
        for ax in axs:ax.grid(alpha=.17);ax.set_axisbelow(True)
        fig.suptitle(title+'; N='+str(analysis['primary_N_T' if stage=='T' else 'primary_N_RH']),fontsize=15,y=.98)
        hs,ls=axs[0].get_legend_handles_labels();fig.legend(hs,ls,loc='lower center',bbox_to_anchor=(.5,.055),ncol=3,frameon=False,fontsize=10)
        fig.text(.5,.038,'Слева показан центр; справа учтен полный диапазон ошибок. Частоты не перенормированы после увеличения масштаба.',ha='center',fontsize=8.5)
        fig.text(.5,.012,note,ha='center',fontsize=9);fig.subplots_adjust(left=.075,right=.98,top=.85,bottom=.28,wspace=.27);save(fig,name)
    fig,axs=plt.subplots(3,3,figsize=(14,10),sharex=True,sharey=True)
    for ax,m in zip(axs.ravel(),T_ORDER):
        f=frames['T/'+m];e=f['error'][f['mask']];w=macro_weights(case,f['mask'],False)[f['mask']];h,_=np.histogram(e,bins['T']['signed'],weights=w);ax.stairs(h*100,bins['T']['signed'],fill=True,color='#4F85A6',alpha=.65)
        ax.axvline(0,color='#333333',lw=.7);st=analysis['statistics']['T/'+m];ax.set_title(T_NAMES[m],fontsize=11);ax.text(.98,.94,f"MAE {st['MAE_macro']:.3f} °C\nP95 |ε| {st['P95_abs_macro']:.2f} °C",transform=ax.transAxes,ha='right',va='top',fontsize=9);ax.grid(alpha=.15)
    for ax in axs[-1,:]:ax.set_xlabel('Ошибка T, °C')
    for ax in axs[:,0]:ax.set_ylabel('Взвешенная частота, %')
    fig.suptitle('Все 9 температурных вариантов; одинаковые '+str(analysis['primary_N_T'])+' случая',fontsize=15);fig.text(.5,.015,note,ha='center',fontsize=9);fig.tight_layout(rect=(0,.04,1,.96));save(fig,'03_temperature_all_methods')
    fig,axs=plt.subplots(5,2,figsize=(12.5,13),sharex=True,sharey=True)
    for i,co in enumerate(COORDS):
        for j,support in enumerate(('joint','own')):
            ax=axs[i,j];key='H/'+support+'/'+co;f=frames[key];e=f['error'][f['mask']];w=macro_weights(case,f['mask'],False)[f['mask']];h,_=np.histogram(e,bins['H']['signed'],weights=w);ax.stairs(h*100,bins['H']['signed'],fill=True,color=COLORS[co],alpha=.65);ax.axvline(0,color='#333333',lw=.7);ax.grid(alpha=.15)
            st=analysis['statistics'][key];ax.set_title(H_NAMES[co]+' · '+f['model'],fontsize=9);ax.text(.98,.92,f"MAE {st['MAE_macro']:.3f} п.п.\nP95 |ε| {st['P95_abs_macro']:.1f}",transform=ax.transAxes,ha='right',va='top',fontsize=9)
    for ax in axs[-1,:]:ax.set_xlabel('Ошибка восстановленной RH, п.п.')
    for ax in axs[:,0]:ax.set_ylabel('Частота, %')
    fig.suptitle('Влажность: совместные T/RH/p (слева) и собственные входы (справа)\nЧастоты выравнены по странам/станциям; 6672 одинаковых случая',fontsize=13);fig.tight_layout(rect=(0,.01,1,.95));save(fig,'04_humidity_joint_vs_own')
    fig,axs=plt.subplots(2,2,figsize=(14,8.8))
    tprofiles=[('T/height_idw_ols','#0072B2','-'),('T/hinge_height_ridge','#009E73','--'),('T/local_height_shrinkage','#8B63AC','-.'),('T/aux_shared','#222222',':')]
    for row,items in ((0,tprofiles),(1,[('H/own/'+co,COLORS[co],['-','--',':','-.',(0,(5,2,1,2))][i]) for i,co in enumerate(COORDS)])):
        for col,kind in ((0,'month'),(1,'solar_3h')):
            ax=axs[row,col]
            for key,color,ls in items:
                profile=sorted([r for r in temporal if r['key']==key and r['scope']=='balanced' and r['kind']==kind],key=lambda r:r['group']);xx=[r['group'] if kind=='month' else r['group']*3+1.5 for r in profile]
                ax.plot(xx,[r['MAE_macro'] for r in profile],marker='o',markersize=3.6,color=color,ls=ls,label=frames[key]['label'])
            ax.grid(alpha=.2);ax.set_ylabel('Macro MAE, '+('°C' if row==0 else 'п.п. RH'))
            if kind=='month':ax.set_xticks(range(1,13),MONTHS);ax.set_xlabel('Месяц; выбранные 15–16 числа')
            else:ax.set_xticks(range(0,25,3));ax.set_xlim(0,24);ax.set_xlabel('Среднее солнечное время, ч; интервалы по 3 ч')
            ax.set_title(('Температура' if row==0 else 'Влажность, own')+': '+('месяцы' if col==0 else 'суточный ход ошибки'));ax.legend(fontsize=8,frameon=True,ncol=2)
    fig.suptitle('Контроль состава: '+str(len(analysis['balanced_stations']))+' постоянных станций, N='+str(analysis['balanced_diagnostic_N'])+'\nПоказаны ошибки на выбранных днях V; это не климатическая норма',fontsize=14)
    fig.subplots_adjust(left=.07,right=.985,bottom=.075,top=.87,wspace=.19,hspace=.36);save(fig,'05_temporal_dependencies')
    fig,axs=plt.subplots(1,2,figsize=(14,7.4))
    for ax,key,title,cmap in ((axs[0],'T/aux_shared','T, общая для влажности; °C','YlOrBr'),(axs[1],'H/own/RH','RH напрямую / own; п.п.','YlOrRd')):
        table=np.array([[next(r['MAE_macro'] for r in cells if r['key']==key and r['month']==m and r['solar_3h']==h) for h in range(8)] for m in range(1,13)])
        im=ax.imshow(table,aspect='auto',cmap=cmap,vmin=0,vmax=table.max());ax.set_yticks(range(12),MONTHS);ax.set_xticks(range(8),[f'{h:02d}–{h+3:02d}' for h in range(0,24,3)],rotation=35,ha='right');ax.set_title(title);ax.set_xlabel('Среднее солнечное время, ч')
        for i in range(12):
            for j in range(8):ax.text(j,i,f'{table[i,j]:.1f}',ha='center',va='center',fontsize=8,color='white' if table[i,j]>table.max()*.7 else '#222222')
        fig.colorbar(im,ax=ax,fraction=.04,pad=.025,label='Macro MAE')
    fig.suptitle('Ошибка по месяцу и часу; постоянный состав '+str(len(analysis['balanced_stations']))+' станций\nКаждая ячейка — выбранное двухсуточное окно V',fontsize=14)
    fig.subplots_adjust(left=.055,right=.98,bottom=.16,top=.83,wspace=.27);save(fig,'06_month_hour_heatmap')
    fig,axs=plt.subplots(1,2,figsize=(13,5))
    for ax,co,groups in ((axs[0],'log_e',[('none_predicted_chain','Полная цепочка'),('T','Истинная T'),('moisture','Истинное e'),('T+moisture','Оба истинные')]),(axs[1],'q',[('none_predicted_chain','Полная цепочка'),('T','Истинная T'),('p','Истинное p'),('moisture','Истинное q'),('T+p+moisture','Все истинные')])):
        rr={r['known_inputs']:r['MAE_macro'] for r in analysis['oracle_rows'] if r['coordinate']==co};vals=[rr[k] for k,l in groups];xx=np.arange(len(vals));ax.bar(xx,vals,color=['#536F8C','#46A39A','#D4A05B','#927DB2','#9B9B9B'][:len(vals)])
        ax.set_xticks(xx,[l for k,l in groups],rotation=20,ha='right',fontsize=9);ax.set_ylabel('Macro MAE RH, п.п.');ax.set_title(H_NAMES[co]+' / own');ax.set_ylim(0,max(vals)*1.18);ax.grid(axis='y',alpha=.17);ax.set_axisbelow(True)
        for x,val in zip(xx,vals):ax.text(x,val+.08,f'{val:.2f}',ha='center',fontsize=10)
    fig.suptitle('Диагностические подстановки на V: где теряется точность\nИстинные входы недоступны в новой точке; это не исполнимые методы прогноза',fontsize=13);fig.tight_layout(rect=(0,0,1,.87));save(fig,'07_oracle_diagnostics')
    fig,axs=plt.subplots(1,2,figsize=(14,5.8))
    for i,co in enumerate(COORDS):
        f=fixed[co];ls=['-','--',':','-.',(0,(5,2,1,2))][i];freq(axs[0],f,COLORS[co],ls,H_NAMES[co]);ecdf(axs[1],f,COLORS[co],ls,H_NAMES[co])
    axs[0].axvline(0,color='#333333',lw=.8);axs[0].set(xlabel='Ошибка RH, п.п.',ylabel='Взвешенная частота, %',title='Распределение ошибки')
    axs[1].set(xlabel='Абсолютная ошибка RH, п.п.',ylabel='Доля с |ошибкой| ≤ x, %',ylim=(0,101),title='Накопленная частота')
    for ax in axs:ax.grid(alpha=.17)
    hs,ls=axs[0].get_legend_handles_labels();fig.legend(hs,ls,loc='lower center',bbox_to_anchor=(.5,.055),ncol=5,frameon=False,fontsize=9)
    fig.suptitle('Контроль структуры: везде месячная поправка по высоте + IDW + OLS\nМеняется координата влажности; own; одинаковые 6672 случая',fontsize=14);fig.text(.5,.012,note,ha='center',fontsize=9);fig.subplots_adjust(left=.075,right=.98,top=.80,bottom=.26,wspace=.28);save(fig,'08_humidity_fixed_structure')
    write_json(out/'figures.json',{'figures':made,'formats':['png','svg'],'weighted_frequencies':True,'signed_error':'prediction minus observation','clipping_applied':False})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);p.add_argument('--out',required=True);a=p.parse_args();run=Path(a.run).resolve();out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
    analysis,frames,fixed,case,bins,balanced,temporal,cells=calculate(run,out);draw(out,analysis,frames,fixed,case,bins,balanced,temporal,cells)
    print(json.dumps({'out':str(out),'N_T':analysis['primary_N_T'],'N_RH':analysis['primary_N_RH'],'balanced_N':analysis['balanced_diagnostic_N'],'balanced_country_counts':analysis['balanced_country_counts'],'figures':8,'C_evaluated':False},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
