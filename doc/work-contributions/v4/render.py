#!/usr/bin/env python3
"""Render the v4 design comparison from recorded data."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

root = Path(__file__).resolve().parent
j = json.loads((root/'comparison.json').read_text())
plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':11, 'axes.spines.top':False,
                     'axes.spines.right':False, 'axes.spines.left':False, 'axes.spines.bottom':False})
fig, axes = plt.subplots(1, 3, figsize=(15, 5.4), gridspec_kw={'width_ratios':[.9,1.1,1]})
fig.patch.set_facecolor('#faf9f5')
for ax in axes:
    ax.set_facecolor('#faf9f5'); ax.set_axisbelow(True); ax.grid(axis='x', color='#e0e1df')
colors = ['#54756a','#387aa0','#bd7456']
ax=axes[0]
ax.barh(['Previous maximum', 'Previous sample', 'Fixed v4'], [688,336,263], color=['#c2c4c1','#c2c4c1',colors[0]],height=.5)
ax.invert_yaxis(); ax.set_xlim(0,780); ax.set_xlabel('Certificate bytes'); ax.set_title('A smaller proof',loc='left',weight='bold',pad=18)
for i,v in enumerate([688,336,263]): ax.text(v+12,i,str(v),va='center',weight='bold')
ax=axes[1]
rows=[x for x in j['marginal_fee_rows'] if x['foreign_proofs']==19]
vals=[r['finder_sats']/400000*100 for r in rows]
ax.barh(['Fees to finder', 'Share 25% of fees', 'Share all fees'],vals,color=colors,height=.5)
ax.invert_yaxis();ax.set_xlim(0,115);ax.set_xlabel('Finder keeps from an added fee');ax.xaxis.set_major_formatter(PercentFormatter())
ax.set_title('Transaction selection incentive',loc='left',weight='bold',pad=18)
for i,v in enumerate(vals):ax.text(v+2,i,f'{v:.2f}%',va='center',weight='bold')
ax=axes[2]
rows=[x for x in j['slot_rows'] if x['slots']==20]
vals=[r['expected_paid_fraction']*100 for r in rows]
ax.barh(['Multiplier 20', 'Multiplier 40', 'Multiplier 100'],vals,color=['#54756a','#387aa0','#c2c4c1'],height=.5)
ax.invert_yaxis();ax.set_xlim(0,110);ax.set_xlabel('Average shared budget claimed');ax.xaxis.set_major_formatter(PercentFormatter())
ax.set_title('Same 20 slots, more proofs',loc='left',weight='bold',pad=18)
for i,v in enumerate(vals):ax.text(v+2,i,f'{v:.2f}%',va='center',weight='bold')
fig.suptitle('Keep the proof simple. Choose incentives with evidence.',x=.06,y=.97,ha='left',fontsize=20,weight='bold')
fig.text(.06,.14,'Fee comparison: all 19 contributions belong to others. The current code shares all fees.',fontsize=11)
fig.text(.06,.095,'Slot comparison: ideal analytic model with complete relay, compatible transactions and no target clipping.',fontsize=10,color='#555555')
fig.text(.06,.05,'Maturity: long locks delay both independent miners and customers receiving full rebates. No production default selected.',fontsize=10,color='#555555')
fig.subplots_adjust(left=.16,right=.97,top=.79,bottom=.31,wspace=.9)
fig.savefig(root.parent.parent/'ContributionChoices.png',dpi=160,facecolor=fig.get_facecolor())
