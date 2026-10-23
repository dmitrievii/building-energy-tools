"""Plot measured CD2 diagnostics; no model or acceptance parameter fitting."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def plot(audit_json, output):
    data=json.loads(Path(audit_json).read_text())
    variants=list(data['summary']['variants'])
    labels=['Frozen C2','Scaled x','Scaled x,c','COBYQA']
    colors=['#536477','#247ba0','#168b6a','#ba5b35']
    fig,axes=plt.subplots(1,3,figsize=(12.6,4.8))
    for i,name in enumerate(variants):
        rows=[r for r in data['selected_trials'] if r['variant']==name]
        x=i+np.linspace(-.14,.14,len(rows))
        axes[0].scatter(x,[r['delta_F_vs_control'] for r in rows],color=colors[i],s=17,alpha=.72)
        axes[1].scatter(x,[max(1e-16,r['stationarity_Linf_by_tolerance']['1e-06']) for r in rows],color=colors[i],s=17,alpha=.72)
    axes[0].set_yscale('symlog',linthresh=1e-10)
    axes[0].axhline(0,color='#777777',linewidth=.8)
    axes[0].set_ylabel('F - F(frozen), original objective')
    axes[0].set_title('Selected-state objective change',fontsize=11)
    axes[1].set_yscale('log')
    axes[1].set_ylabel('Dimensionless stationarity residual, Linf')
    axes[1].set_title('First-order fit at active tolerance 1e-6',fontsize=11)
    values=[data['summary']['variants'][v]['optimizer_CPU_seconds'] for v in variants]
    axes[2].bar(range(4),values,color=colors,width=.58)
    axes[2].set_yscale('log')
    axes[2].set_ylabel('CPU seconds, all captured optimizer calls')
    axes[2].set_title('Measured optimizer cost',fontsize=11)
    axes[2].set_ylim(max(.01,min(values)/2),max(values)*3)
    for i,v in enumerate(values):axes[2].text(i,v*1.13,f'{v:.1f} s',ha='center',va='bottom',fontsize=9)
    for ax in axes:
        ax.set_xticks(range(4),labels,rotation=18,ha='right',fontsize=9)
        ax.set_xlim(-.5,3.5)
        ax.grid(axis='y',alpha=.18)
        ax.set_axisbelow(True)
        ax.spines[['top','right']].set_visible(False)
    fig.suptitle('IGE CD2: the same objective and physical constraints, four numerical variants',fontsize=13,y=.98)
    fig.text(.02,.075,'33 modified cases per variant; 30 exact strict witnesses per variant are preserved without optimization.',fontsize=9)
    fig.text(.02,.035,'Revealed controls/sensitivity at fixed p. Residuals do not certify a minimum; independent accuracy remains unqualified.',fontsize=9)
    fig.tight_layout(rect=[0,.13,1,.94])
    path=Path(output)
    if path.exists():raise FileExistsError(path)
    fig.savefig(path,dpi=180,facecolor='white')
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();plot(a.audit,a.out)
