"""Export publication figures from frozen pilot evidence. No model calls.

Run: python analysis/plot_dashboard.py
Requires matplotlib. Exports PNG (2400 x 1500) and SVG alongside the UI.
"""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'frontend/public/pilot.json').read_text())
DEST = ROOT / 'frontend/public/graphs'
DEST.mkdir(exist_ok=True)
BG, INK, MUTED, RULE = '#15191e', '#f1f3f5', '#b2bbc6', '#343e4a'
BASE, SFT, AMBER = '#75b8ee', '#617f9a', '#f4bf62'
plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':12, 'text.color':INK, 'axes.labelcolor':MUTED, 'xtick.color':MUTED, 'ytick.color':INK, 'figure.facecolor':BG, 'axes.facecolor':BG, 'axes.edgecolor':RULE, 'svg.hashsalt':'checkpoint-gate-seed7', 'savefig.facecolor':BG})

def frame(title, subtitle):
    fig = plt.figure(figsize=(12,7.5), dpi=200)
    fig.text(.07,.93,title,fontsize=23,weight='bold',va='top')
    fig.text(.07,.865,subtitle,fontsize=12,color=MUTED,va='top')
    fig.text(.07,.055,'CheckpointGate / Qwen3.6-35B-A3B / rank-8 LoRA / 12 SFT updates',fontsize=10,color=MUTED)
    fig.text(.07,.03,'Single-seed synthetic pilot. Source: frozen pilot.json; not an across-seed estimate.',fontsize=9,color=MUTED)
    return fig

def style(ax, limit=100):
    ax.set_xlim(0,limit); ax.set_axisbelow(True); ax.grid(axis='x',color=RULE,linewidth=.7)
    for side in ['top','right','left']: ax.spines[side].set_visible(False)
    ax.tick_params(axis='both',length=0,pad=10)

def save(fig,name):
    fig.savefig(DEST/f'{name}.png',dpi=200)
    fig.savefig(DEST/f'{name}.svg',metadata={'Date':None})
    plt.close(fig)

families = [('latest_window','Latest row per group'),('anti_null','NULL-safe anti-join'),('distinct_pairs','Distinct pairs'),('relational_division','Relational division')]
fig=frame('The regression is concentrated in two query families.','Held-out SQL accuracy (%) / 50 tasks per family / identical task instances')
ax=fig.add_axes([.255,.20,.61,.57]); style(ax)
y=np.arange(4)
for arm,offset,color,label in [('base',-.16,BASE,'Base'),('sft',.16,SFT,'After SFT')]:
    values=[]; counts=[]
    for family,_ in families:
        rows=[r for r in DATA['rows'][arm] if r['family']==family]
        correct=sum(r['correct'] for r in rows); counts.append(correct); values.append(100*correct/len(rows))
    ax.barh(y+offset,values,height=.25,color=color,label=label)
    for yy,v,n in zip(y+offset,values,counts): ax.text(103,yy,f'{v:g}%  ({n}/50)',va='center',fontsize=10,color=INK)
ax.set_yticks(y,[name for _,name in families]);ax.invert_yaxis();ax.set_xticks([0,25,50,75,100]);ax.set_xlabel('Correct answers (%)',labelpad=13)
ax.legend(loc='lower left',bbox_to_anchor=(0,1.01),frameon=False,ncol=2,labelcolor=INK,fontsize=11)
save(fig,'query-families')

fig=frame('The accuracy decline survives a tool-fault split.','Held-out SQL accuracy (%) / 100 tasks per condition / one recoverable first-call error')
ax=fig.add_axes([.23,.24,.635,.49]);style(ax);y=np.arange(2)
for arm,offset,color,label in [('base',-.16,BASE,'Base'),('sft',.16,SFT,'After SFT')]:
    vals=[DATA['results']['conditions'][arm]['by_fault'][f]['correct'] for f in ['none','transient_first_call']]
    ax.barh(y+offset,vals,height=.26,color=color,label=label)
    for yy,v in zip(y+offset,vals): ax.text(103,yy,f'{v}%  ({v}/100)',va='center',fontsize=10,color=INK)
ax.set_yticks(y,['No tool fault','Transient tool fault']);ax.invert_yaxis();ax.set_xticks([0,25,50,75,100]);ax.set_xlabel('Correct answers (%)',labelpad=13)
ax.legend(loc='lower left',bbox_to_anchor=(0,1.03),frameon=False,ncol=2,labelcolor=INK)
save(fig,'tool-faults')

fig=frame('Perfect formatting did not preserve SQL correctness.','Same 200 held-out tasks / format-violation counts and verified answer accuracy')
for index,(metric,title,limit) in enumerate([('strict_format_violations','Strict-format violations (count)',320),('accuracy','Correct answers (%)',100)]):
    ax=fig.add_axes([.10+index*.46,.25,.34,.48]); ax.set_axisbelow(True); ax.grid(axis='y',color=RULE,linewidth=.7)
    vals=[DATA['results']['conditions'][arm][metric]*(100 if metric=='accuracy' else 1) for arm in ['base','sft']]
    ax.bar([0,1],vals,color=[BASE,SFT],width=.50)
    ax.set_xticks([0,1],['Base','After SFT']); ax.set_ylim(0,limit);ax.set_title(title,fontsize=12,loc='left',color=INK,pad=24)
    for side in ['top','right','left']: ax.spines[side].set_visible(False)
    ax.tick_params(length=0,pad=10)
    for x,v in enumerate(vals): ax.text(x,v+limit*.035,f'{v:g}'+('%' if metric=='accuracy' else ''),ha='center',fontsize=18,color=INK)
    if vals[1]==0: ax.hlines(0,.75,1.25,color=SFT,linewidth=4)
fig.text(.10,.14,'A task can incur multiple format violations. Both axes begin at zero.',fontsize=10,color=MUTED)
save(fig,'format-reliability')
print('Exported 3 PNG and 3 SVG figures from the frozen pilot evidence.')
