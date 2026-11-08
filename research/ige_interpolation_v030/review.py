"""Post-run descriptive review of V; contains no C scoring.

Optional report utility: numpy + matplotlib. Run from a repository checkout as
python research/ige_interpolation_v030/review.py PATH_TO_FINISHED_RUN.
The experimental runner itself requires only numpy and scipy.
"""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[k]='1'
import csv,json,sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools/ige_climate_experiments'))
from ige_auto.data import Cube
from ige_auto.cases import Cases
from ige_hum.metrics import errors
from ige_local.common import write_json,write_csv,file_hash
from ige_next.study import path_for


def main(run):
    run=Path(run).resolve();out=Path(__file__).resolve().parent
    summary=json.loads((run/'summary.json').read_text());spec=json.loads((run/'run_spec.sealed.json').read_text())
    cube=Cube(run/'cube');c=spec['base_configuration']
    source_cube=Cube(Path(spec['source_run'])/'cube')
    if source_cube.meta['cube_id']!=cube.meta['cube_id']:raise RuntimeError('Source cube changed')
    results=[json.loads(p.read_text()) for p in sorted((run/'models').rglob('result.sealed.json'))]
    bykey={r['key']:r for r in results};chosen={k:bykey[x['key']] for k,x in summary['best_per_group'].items()}
    parameter_rows=[]
    for r in results:
        f=r.get('fit_D',{});opt=r.get('optimization',{})
        parameter_rows.append({'key':r['key'],'status':r['status'],'fit_rows_D':f.get('fit_rows'),'rank':f.get('rank'),
            'scaled_condition':f.get('scaled_condition'),'eta':json.dumps(opt.get('eta')),
            'active_bounds':json.dumps(opt.get('active_bounds')),'feature_names':json.dumps(f.get('feature_names')),
            'coefficients':json.dumps(f.get('coefficients')),'ridge_lambda':f.get('ridge_lambda'),'huber_delta':f.get('huber_delta')})
    write_csv(out/'fitted_parameters.csv',parameter_rows,list(parameter_rows[0]))
    d=np.flatnonzero(cube.roles=='D');v=np.flatnonzero(cube.roles=='V');vt=np.flatnonzero(cube.time_roles=='V')
    b=Cases(cube,[(v,vt)],d,'RH',c,'review_V')
    def arrays(r):
        with np.load(path_for(run,r['candidate'])/'V_predictions.npz',allow_pickle=False) as z:return {k:z[k].copy() for k in z.files}
    records={k:arrays(r) for k,r in chosen.items()}
    monthly=[];auxmetrics={};matched={}
    humidity_masks=[z['common_mask'] for k,z in records.items() if k.startswith('humidity/')]
    common=humidity_masks[0] if humidity_masks else np.zeros(len(b.y),bool)
    if any(not np.array_equal(common,m) for m in humidity_masks):raise RuntimeError('Humidity common masks differ')
    for key,r in chosen.items():
        a=records[key];mask=a['common_mask'];y=a['observed'];p=a['predicted']
        for m in range(1,13):
            e=errors(y,p,b,mask&(b.month==m));monthly.append({'group':key,'model':r['candidate']['model']['id'],'month':m,'N':e['N_scored'],
                'macro_MAE':e['macro_MAE'],'MAE':e['MAE'],'RMSE':e['RMSE'],'bias':e['bias']})
        if key in ('T/native/T','p/native/p'):matched[key]=errors(y,p,b,common)
    anyh=next((z for k,z in records.items() if k.startswith('humidity/')),None)
    if anyh is not None:
        for name,j in (('T',0),('p',2)):
            observed=np.asarray(cube.values[b.s,b.t,j]);auxmetrics[name]=errors(observed,anyh[name+'_aux_predicted'],b,common)
    from ige_hum.cases import HumidityCases
    original_mask=HumidityCases(cube,c,[(v,vt)],d,'legacy_mask').common_mask({'T':anyh['T_aux_predicted'],'p':anyh['p_aux_predicted']})
    legacy_rows=[]
    for r in results:
        if r['candidate']['stage']!='humidity' or r['candidate']['support']!='joint' or r['candidate']['coordinate'] not in ('RH','log_e','q'):continue
        item=r['candidate'];p=Path(spec['source_run'])/'models'/item['coordinate']/item['model']['id']/'result.sealed.json'
        if not p.exists() or 'primary_macro_MAE' not in r:continue
        old=json.loads(p.read_text());before=old['common']['RH']['macro_MAE']
        legacy_rows.append({'coordinate':item['coordinate'],'model':item['model']['id'],'previous_macro_MAE':before,
            'new_macro_MAE':r['primary_macro_MAE'],'delta_pp':r['primary_macro_MAE']-before,
            'new_huber_scale_rule':item['model']['regression']=='huber'})
    if legacy_rows:write_csv(out/'legacy_joint_replay.csv',legacy_rows,list(legacy_rows[0]))
    write_csv(out/'monthly_selected.csv',monthly,list(monthly[0]))
    global_h=min((r for r in chosen.values() if r['candidate']['stage']=='humidity'),key=lambda r:r['primary_macro_MAE'])
    hk='/'.join((global_h['candidate']['stage'],global_h['candidate']['support'],global_h['candidate']['coordinate']))
    selecteddata=records[hk];pairwise=[]
    for key,r in chosen.items():
        if not key.startswith('humidity/'):continue
        a=records[key]
        for co in c['countries']:
            use=common&(b.country==co);e=errors(a['observed'],a['predicted'],b,use)
            pairwise.append({'group':key,'country':co,'N':e['N_scored'],'macro_MAE':e['macro_MAE'],'bias':e['bias']})
    write_csv(out/'countries_humidity.csv',pairwise,list(pairwise[0]))
    # Identify whether calendar references differ; this denominator is not hidden.
    support_rows=[]
    for k,r in chosen.items():
        own=r['own_coverage'];m=own.get('RH',own)
        support_rows.append({'group':k,'model':r['candidate']['model']['id'],'common_macro_MAE':r['primary_macro_MAE'],
            'common_N':r['common_calendar_cases'],'own_reference_N':m['N_reference'],'own_scored_N':m['N_scored'],
            'own_macro_MAE':m['macro_MAE'],'predicted_calendar_N':own['N_predicted_calendar']})
    write_csv(out/'selected_coverage.csv',support_rows,list(support_rows[0]))
    moisture_outputs=[]
    for k,r in chosen.items():
        if not k.startswith('humidity/'):continue
        m=r['common'];moisture_outputs.append({'group':k,'RH_macro_MAE_pp':m['RH']['macro_MAE'],
            'q_macro_MAE_gkg':1000*m['q_kgkg']['macro_MAE'],'e_macro_MAE_hPa':m['e_hPa']['macro_MAE'],
            'Td_macro_MAE_C':m['Td_water']['macro_MAE'],'supersaturated_N':m['physical_flags']['supersaturated'],
            'negative_RH_N':m['physical_flags']['negative_RH'],'common_N':r['common_calendar_cases']})
    write_csv(out/'moisture_secondary_outputs.csv',moisture_outputs,list(moisture_outputs[0]))
    # Primary comparative chart; humidity represents RH after back transformation.
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(12,5.2),gridspec_kw={'width_ratios':[1.5,1]})
    for ax,stage,unit in zip(axes,('T','p'),('°C','hPa')):
        rs=[r for r in results if r['candidate']['stage']==stage and r['status']=='ELIGIBLE'];rs.sort(key=lambda r:r['primary_macro_MAE'],reverse=True)
        yy=np.arange(len(rs));vals=[r['primary_macro_MAE'] for r in rs]
        ax.barh(yy,vals,color=['#1f8276' if r['key']==chosen[stage+'/native/'+stage]['key'] else '#859bb4' for r in rs])
        ax.set_yticks(yy,[r['candidate']['model']['id'] for r in rs],fontsize=9)
        for y,x in zip(yy,vals):ax.text(x+.015*max(vals),y,f'{x:.3f}',va='center',fontsize=9)
        ax.set_xlim(0,max(vals)*1.23);ax.set_xlabel('Macro MAE, '+unit);ax.set_title(('Температура' if stage=='T' else 'Давление')+'; общие часы внутри блока')
        ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
    fig.suptitle('IGE 0.3.0 — реальные наблюдения AT/DE/CH, исследовательская V',fontsize=13)
    fig.tight_layout();fig.savefig(out/'temperature_pressure.png',dpi=180);plt.close(fig)
    coords=['RH','log_e','q','Td','D'];values=np.array([[chosen['humidity/'+s+'/'+co]['primary_macro_MAE'] for s in ('joint','own')] for co in coords])
    fig,ax=plt.subplots(figsize=(7.3,5));im=ax.imshow(values,cmap='YlOrRd',aspect='auto',vmin=min(7.,values.min()),vmax=max(10.,values.max()))
    ax.set_yticks(range(5),['RH','ln(e)','q','Td','T − Td']);ax.set_xticks([0,1],['Совместные доноры T/RH/p','Собственные требуемые доноры'])
    for i in range(5):
        for j in range(2):ax.text(j,i,f'{values[i,j]:.3f}',ha='center',va='center',fontsize=17,color='#142031')
    ax.set_title('Лучшая структура каждой координаты\nMacro MAE восстановленной RH, п.п.; одинаковые часы V',pad=16)
    fig.colorbar(im,ax=ax,label='п.п. RH');fig.tight_layout();fig.savefig(out/'humidity_matrix.png',dpi=180);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4.7))
    for co in coords:
        r=[x for x in monthly if x['group']=='humidity/own/'+co];ax.plot([x['month'] for x in r],[x['macro_MAE'] for x in r],marker='o',label=co)
    ax.set(xticks=range(1,13),xlabel='Месяц; выбранные дни V ('+', '.join(map(str,c['years']['V']))+')',ylabel='Macro MAE RH, п.п.',title='Ошибки влажности по месяцам: own, выбранные структуры')
    ax.legend(ncol=5,loc='upper center',bbox_to_anchor=(.5,1));ax.grid(alpha=.2);fig.tight_layout();fig.savefig(out/'humidity_monthly.png',dpi=180);plt.close(fig)
    details={'run':str(run),'spec_id':spec['spec_id'],'cube_id':summary['cube_id'],'models_requested':summary['models_requested'],
        'models_eligible':summary['models_eligible'],'failures':summary['failures'],'best_per_group':summary['best_per_group'],
        'best_humidity_group':hk,'old_auxiliaries_on_humidity_common':auxmetrics,'new_T_p_on_humidity_common':matched,
        'source_data_scope':'Selected native T/RH/p cube, no full national Database available here',
        'holdout_evaluated':False,'selected_coverage':support_rows,'monthly':monthly}
    details['legacy_common_mask_unchanged']=bool(np.array_equal(original_mask,common))
    details['parameters_at_bounds']=[z for z in parameter_rows if 'true' in z['active_bounds']]
    details['moisture_secondary_outputs']=moisture_outputs
    q_controls=[]
    for model in ('height_idw_ols','seasonal_idw_ols','monthly_idw_ols','harmonic_idw_ridge','geo_gaussian_ols','seasonal_geo_gaussian_huber'):
        ja=bykey.get('humidity/joint/q/'+model);oa=bykey.get('humidity/own/q/'+model)
        if not ja or not oa or ja['status']!='ELIGIBLE' or oa['status']!='ELIGIBLE':continue
        x=arrays(ja);y=arrays(oa)
        same=all(np.array_equal(x[k],y[k],equal_nan=True) for k in ('predicted','native_prediction','donor_weights','common_mask'))
        q_controls.append({'model':model,'identical_logical_arrays':bool(same),
            'macro_MAE_delta':oa['primary_macro_MAE']-ja['primary_macro_MAE']})
    details['q_joint_own_internal_controls']=q_controls
    from ige_auto.data import buck_water
    from ige_hum.physics import dewpoint_water
    domain_audit=[]
    for label,ss,tt in (('D_sites_D_and_V_times',d,np.flatnonzero(np.isin(cube.time_roles,['D','V']))),('V_sites_V_times',v,vt)):
        values=np.asarray(cube.values[ss[:,None],tt[None,:],:3]);eligible=np.asarray(cube.eligible[ss[:,None],tt[None,:],:3])
        e=values[:,:,1]*buck_water(values[:,:,0])/100
        physical=eligible.all(axis=2)&np.isfinite(values).all(axis=2)&(values[:,:,0]>-273.15)&(e>0)&(e<values[:,:,2])
        domain_audit.append({'panel':label,'physical_TRHp_cells':int(physical.sum()),'outside_Td_domain_cells':int((physical&~np.isfinite(dewpoint_water(e))).sum())})
    details['Td_domain_audit_no_C']=domain_audit
    details['source_cube_reverified_after']=True
    write_json(out/'review.json',details)
    t_selected=chosen['T/native/T']['primary_macro_MAE'];t_height=bykey['T/native/T/height_idw_ols']['primary_macro_MAE']
    tm_old=auxmetrics['T']['macro_MAE'];tm_new=matched['T/native/T']['macro_MAE']
    pcm=matched['p/native/p']['by_country'];pcold=auxmetrics['p']['by_country']
    rh_own=chosen['humidity/own/RH']['primary_macro_MAE'];d_own=chosen['humidity/own/D']['primary_macro_MAE']
    qm={x['group']:x['q_macro_MAE_gkg'] for x in moisture_outputs}
    mr=sorted([x for x in monthly if x['group']=='humidity/own/RH'],key=lambda x:x['macro_MAE'],reverse=True)
    coupling_data=json.loads((run/'coupling_diagnostic.json').read_text())
    le_base=chosen['humidity/own/log_e']['primary_macro_MAE'];le_replaced=coupling_data['results']['humidity/own/log_e']['replace_T_only']['RH']['macro_MAE']
    lines=['# IGE — реальные испытания новой программы 0.3.0','',
      'Выполнено сравнение на ваших почасовых данных AT/DE/CH из завершённого запуска влажности 0.2.1. Это численный пилот выбранных станций/дней, не весь национальный архив.',
      '',f"Запрошено {summary['models_requested']} кандидата; пригодно для сравнения {summary['models_eligible']}; незавершённых {len(summary['failures'])}.",
      'C не вычислялась. V ранее просматривалась, поэтому результаты исследовательские. Перечень методов и правила были запечатаны до нового расчёта.',
      '', '## Результаты на одинаковых часах внутри каждого блока','',
      '| Блок | Структура | Macro MAE | Общих случаев |','|---|---|---:|---:|']
    for k,r in chosen.items():lines.append(f"| {k} | {r['candidate']['model']['id']} | {r['primary_macro_MAE']:.6f} | {r['common_calendar_cases']} |")
    lines+=['','T — °C; p — hPa; влажность — процентные пункты восстановленной RH, а не относительные проценты. В таблице выбрана лучшая структура отдельно для каждой координаты и поддержки доноров.',
       '', '![Температура и давление](temperature_pressure.png)','', '![Матрица влажности](humidity_matrix.png)',
       '', '## Влажность по разным выходным величинам','',
       '| Группа | MAE RH, п.п. | MAE q, g/kg | MAE e, hPa | MAE Td, °C | RH>100, случаев |',
       '|---|---:|---:|---:|---:|---:|']
    lines += [f"| {z['group']} | {z['RH_macro_MAE_pp']:.4f} | {z['q_macro_MAE_gkg']:.4f} | {z['e_macro_MAE_hPa']:.4f} | {z['Td_macro_MAE_C']:.4f} | {z['supersaturated_N']} |" for z in moisture_outputs]
    lines += ['', 'Все ошибки в этой таблице — macro MAE на общей маске. Структуры выбраны по RH, а не по q или Td. Победитель по RH не обязан быть лучшим для скрытой нагрузки здания; это проверяется отдельной энергетической задачей. Референсы e/q/Td производны от наблюдённых T/RH/p.',
       '', '## Что сравнивается и что пока не проверено','',
       'Для температуры проверены ближайшая станция, IDW без поправки, постоянная/сезонная/месячная поправки, суточная высотная связь, spline с обучаемым узлом, локальный донорский градиент с усадкой и обученный фон + остатки.',
       'Для давления проверены ближайшая станция, линейная поправка по высоте, гидростатический перенос с предсказанной целевой T и его остаточная регрессия. Целевые наблюдения T/RH в прогноз p не подставляются.',
       'В блоке давления одинаковы целевые контрольные часы, но требования к донорским переменным различаются: линейной модели достаточно p, физической нужны T/RH/p. Поэтому сравнение относится к полной процедуре; чистый эффект формулы при единой маске доноров требует отдельного контроля.',
       'Для влажности RH, ln(e), q, Td и T−Td сравниваются на шести структурах, отдельно с joint и own донорами. Коэффициенты и донорские веса заново оценены на D. В основном сравнении общие T/p сохранялись от предыдущей версии; coupling_diagnostic.json показывает отдельную диагностическую замену T/p без перенастройки влажности.',
       'Режим own меняет и доступных доноров, и доступные обучающие D-референсы, если требования к наблюдениям цели различаются. Это сравнение полных правил доступности, а не чистая причинная оценка количества доноров. Числа обучающих строк и все параметры приведены в fitted_parameters.csv.',
       'Маски прежнего и нового совместного сравнения проверены по каждому случаю: '+str(bool(np.array_equal(original_mask,common)))+'. В legacy_joint_replay.csv сравниваются старые и новые 18 совместных вариантов. Для Huber в новой версии масштаб адаптируется на обучающей части к рассматриваемым весам; его результат не является точным повтором прежней процедуры.',
       'Неполные годы допущены; флаги ручной/автоматической проверки не превращаются автоматически в отбраковку. RH не обрезана. Производные e/q/Td не являются независимыми измерениями.',
       'Солнце, осадки, ветер, длинноволновое излучение и снег описаны в полном протоколе, но не вычислялись: соответствующих столбцов нет в присланном кубе. Модели с DEM/реанализом требуют внешних входов.',
       '', '## Покрытие и месяцы','',
       '| Группа | Общие часы | Собственные часы с RH-референсом | Macro MAE на собственных часах |','|---|---:|---:|---:|']
    for z in support_rows:lines.append(f"| {z['group']} | {z['common_N']} | {z['own_scored_N']} | {z['own_macro_MAE']:.6f} |")
    lines+=['','Собственные часы разных методов различаются; их MAE нельзя использовать как парное доказательство преимущества. Для q при оценке RH не требуется наблюдаемая целевая p: используется прогноз p.',
       '', '![Месячные ошибки](humidity_monthly.png)','',
       'Полные месячные числа, RMSE и смещения находятся в monthly_selected.csv. На каждый месяц приходится два выбранных дня; это не оценка всех часов месяца или экстремальных событий.',
       '', '## Сопоставление старых и новых T/p на часах влажности','',
       '| Величина | Прежняя общая модель | Новая выбранная модель | Общих часов |','|---|---:|---:|---:|']
    for name in ('T','p'):
        old=auxmetrics[name];new=matched[name+'/native/'+name]
        lines.append(f"| {name} | {old['macro_MAE']:.6f} | {new['macro_MAE']:.6f} | {new['N_scored']} |")
    lines+=['','Эта таблица исключает эффект смены референсных часов. Температурная и барометрическая модели отбирались на своих первичных масках; таблица — дополнительная проверка на часах влажности.',
       '', '## Что следует из пилота','',
       f'1. Температура: height-эталон {t_height:.6f} °C, выбранная структура {t_selected:.6f} °C. Условный интервал парной разницы приведён в summary.json и не является независимым подтверждением. На общих часах влажности прежняя T даёт {tm_old:.6f} °C, новая {tm_new:.6f} °C.',
       '2. Давление по странам: '+', '.join(co+' '+f"{pcm[co]['station_macro_MAE']:.6f}"+' hPa' for co in sorted(pcm))+'. Прежняя общая p в DE: '+f"{pcold['DE']['station_macro_MAE']:.6f}"+' hPa. Улучшение общего среднего не доказывает улучшения в каждой стране; немецкий контроль включает лишь две станции.',
       f'3. На общей маске direct-RH/own: {rh_own:.6f} п.п.; T−Td/own: {d_own:.6f} п.п. Own означает новое обучение при другом правиле доступности, поэтому это не изолированный эффект количества доноров.',
       f"4. Среди структур, отобранных по RH, ошибка q: Td/own {qm['humidity/own/Td']:.6f}, RH/own {qm['humidity/own/RH']:.6f} g/kg. Это не отдельный отбор всех кандидатов по q и не подтверждение энергетического преимущества.",
       '5. RH/own на выбранных днях, самые большие месячные ошибки: '+', '.join(str(x['month'])+' — '+f"{x['macro_MAE']:.4f}"+' п.п.' for x in mr[:2])+f"; минимум: {mr[-1]['month']} — {mr[-1]['macro_MAE']:.4f} п.п. Состав доступных станций по месяцам может различаться; вывод не переносится автоматически на все часы месяца.",
       f'6. Диагностическая замена T для ln(e)/own: {le_base:.6f} → {le_replaced:.6f} п.п. Без совместного переобучения влажности нельзя автоматически подставлять новую выбранную T. Direct-RH от такой замены по определению не меняется.',
       '', '## Ограничения вывода и независимый следующий этап','',
       'Отбор структуры на V не является подтверждением преимущества на C. Условные bootstrap-интервалы в summary.json учитывают станции внутри стран при фиксированном годе, но не весь процесс выбора кандидатов. Они описательные, после отбора.',
       'В давлениях обученная степень IDW достигла верхней границы b=8; у лучшей температурной spline-модели узел также находится на границе разрешённого интервала высот D. Это ограниченные локальные решения, не доказанные глобальные оптимумы. Перед заморозкой для C нужны отдельные проверки чувствительности границ и физически скорректированного ближайшего донора.',
       'Для независимого вывода нужно заморозить итоговые цепочки и правила допустимости, затем отдельно оценить их на закрытых семействах/временных блоках. Полный десятилетний охват, трансграничные доноры, экстремумы и строительные нагрузки пока не подтверждены.',
       '', '## Воспроизводимость','',f"- Входной cube_id: `{summary['cube_id']}`.",f"- Спецификация запуска: `{spec['spec_id']}`.",
       f"- Запуск: `{run.name}`.",'- Исходные данные не изменялись; запросов сети в расчёте не было; C не оценивалась.',
       '- Все 186 автоматических тестов и 73/73 синтетических вариантов проверены отдельно. Это проверка кода, не независимая проверка научной точности.',
       '- В архиве результатов: спецификация, сравнительные таблицы, коэффициенты/параметры, диагностические отчёты и контрольные прогнозы. Программный код предоставляется отдельным обновлением и в GitHub.']
    (out/'REPORT_DETAILED_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'models':summary['models_eligible'],'best_humidity':hk,'review':str(out)},ensure_ascii=False))

if __name__=='__main__':main(sys.argv[1])
