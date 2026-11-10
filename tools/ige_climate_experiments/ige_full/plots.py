"""Plots from streamed metrics/histograms, without loading all hourly errors."""
import csv
from pathlib import Path
import numpy as np
from ige_local.common import read_json

def create(run):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    root=Path(run);summary=read_json(root/'summary.json');made=[]
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
    for panel in ('all','urban_common'):
        rr=[r for r in summary['results'] if r['panel']==panel and r['status']=='COMPLETE']
        groups=[('T',[r for r in rr if r['model']['coordinate']=='T']),('p',[r for r in rr if r['model']['coordinate']=='p'])]
        if panel=='all':groups.append(('RH_routes',[r for r in rr if r['model']['coordinate'] not in ('T','p')]))
        else:
            for co in ('RH','log_e','q','Td','D'):groups.append(('RH_via_'+co,[r for r in rr if r['model']['coordinate']==co]))
        for group,items in groups:
            if not items:continue
            fig,axs=plt.subplots(1,2,figsize=(13,5));styles=['-','--',':','-.']
            for j,r in enumerate(items):
                model=root/'models'/panel/r['model']['id'];rows=list(csv.DictReader((model/'histogram.csv').open(encoding='utf-8-sig')))
                good=[z for z in rows if z['lower'] and z['upper']];x=[(float(z['lower'])+float(z['upper']))/2 for z in good];y=[float(z['macro_frequency_pct']) for z in good]
                color=plt.get_cmap('tab10')(j%10);label=r['model']['id']+f" (MAE {r['primary_macro_MAE']:.3f})"
                axs[0].plot(x,y,ls=styles[j%4],color=color,label=label)
                metrics=read_json(model/'metrics.json');months=range(1,13);axs[1].plot(months,[metrics['by_month'][str(m)]['MAE'] for m in months],ls=styles[j%4],color=color,marker='o',markersize=3)
            unit='°C' if group=='T' else ('hPa' if group=='p' else 'п.п. RH');bound=6 if group=='T' else (12 if group=='p' else 30)
            axs[0].set(xlim=(-bound,bound),xlabel='Прогноз − наблюдение, '+unit,ylabel='Взвешенная частота интервала, %');axs[0].axvline(0,color='gray',lw=.7)
            axs[1].set(xticks=range(1,13),xlabel='Месяц UTC',ylabel='Macro MAE, '+unit)
            for ax in axs:ax.grid(alpha=.2)
            fig.suptitle(group+' · '+panel+' · V · '+('полная база' if summary['full_calendar_ingestion'] else 'разреженный инженерный replay'))
            hs,labels=axs[0].get_legend_handles_labels();fig.legend(hs,labels,loc='lower center',bbox_to_anchor=(.5,.06),ncol=2,fontsize=8,frameon=False)
            fig.text(.5,.015,'Частоты: равные веса стран/станций. Хвосты сохранены в CSV. Состав месячных выборок может различаться.',ha='center',fontsize=8)
            fig.subplots_adjust(left=.07,right=.98,top=.85,bottom=.30,wspace=.25)
            name=group+'_'+panel
            for ext in ('png','svg'):fig.savefig(root/(name+'.'+ext),dpi=160,facecolor='white')
            plt.close(fig);made.append(name)
    return made
