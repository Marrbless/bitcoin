#!/usr/bin/env python3
"""Render the review figure from the saved analytic result."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root = Path(__file__).resolve().parent
r = json.loads((root / 'economics.json').read_text())
plt.rcParams.update({'font.family': 'DejaVu Serif', 'font.size': 12, 'axes.spines.top': False, 'axes.spines.right': False})
fig, axes = plt.subplots(3, 1, figsize=(10, 9), gridspec_kw={'height_ratios': [1, 1, 1.7]})
fig.patch.set_facecolor('white')
ink, grey = '#222222', '#cccccc'
fig.suptitle('Three questions before fixing the design', fontsize=20, y=.98)
for ax in axes[:2]:
    ax.set_xlim(0, 100)
    ax.set_ylim(-.65, .65)
    ax.set_yticks([])
    ax.set_xticks([0, 25, 50, 75, 100], ['0%', '25%', '50%', '75%', '100%'])
    ax.spines[['left', 'top', 'right']].set_visible(False)
p = r['analytic']['expected_paid_fraction'] * 100
axes[0].barh(0, p, color=ink, height=.6)
axes[0].barh(0, 100-p, left=p, color=grey, height=.6)
axes[0].text(p/2, 0, f'Paid {p:.2f}%', ha='center', va='center', color='white', fontsize=13)
axes[0].text((100+p)/2, 0, f'Unclaimed {100-p:.2f}%', ha='center', va='center', fontsize=13)
axes[0].set_title('1. Ideal cooperation still leaves empty reward slots', loc='left', fontsize=14, pad=16)
axes[1].barh(0, 9.75, color=ink, height=.6)
axes[1].barh(0, 90.25, left=9.75, color=grey, height=.6)
axes[1].text(4.875, 0, '9.75%', ha='center', va='center', color='white', fontsize=10)
axes[1].text(54.875, 0, 'Other contributors 90.25%', ha='center', va='center', fontsize=13)
axes[1].set_title('2. Finder receives 9.75% of marginal fees with 19 foreign proofs', loc='left', fontsize=14, pad=16)
axes[2].barh([2, 1, 0], [688, 336, 263], color=[grey, ink, 'white'], edgecolor=ink, height=.58)
axes[2].set_yticks([2, 1, 0], ['Current maximum', 'Current sample', 'Header alternative'])
axes[2].set_xlim(0, 760)
axes[2].set_xlabel('Certificate bytes before settlement framing')
for y, v in zip([2, 1, 0], [688, 336, 263]):
    axes[2].text(v+9, y, str(v), va='center')
axes[2].set_title('3. Existing header commitment may reduce proof complexity', loc='left', fontsize=14, pad=18)
fig.text(.07, .03, 'Model: independent work, complete immediate relay, compatible Xs, constant budget.\nThe header alternative is exploratory. Current consensus remains v3. Per script limit remains 83 bytes.', fontsize=10)
fig.subplots_adjust(left=.21, right=.96, top=.85, bottom=.16, hspace=.85)
fig.savefig(root.parent.parent / 'ContributionReview.png', dpi=170, bbox_inches='tight')
