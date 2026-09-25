#!/usr/bin/env python3
# Distributed under the MIT software license, see the accompanying COPYING.
"""Analytic checks and a seeded model; not a live network or adoption test."""
import argparse
import json
import math
import random
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--samples', type=int, default=1000000)
args = parser.parse_args()
if args.samples < 10000:
    parser.error('Use at least 10000 independent block intervals')
rng = random.Random(20260925)
# Independent weak and full successes, no clipping, all work eligible and relayed.
p = 1 / 20
r = 1 - p
paid_sum = paid_sq = weak_sum = full = 0
for _ in range(args.samples):
    weak = math.floor(math.log1p(-rng.random()) / math.log(r))
    paid = (1 + min(weak, 19)) / 20
    weak_sum += weak
    paid_sum += paid
    paid_sq += paid * paid
    full += weak >= 19
mean = paid_sum / args.samples
variance = max(0, paid_sq / args.samples - mean * mean)
se = math.sqrt(variance / args.samples)
expected = 1 - r ** 20
assert abs(mean - expected) < 6 * se
# Independent numerical sum of the geometric distribution.
series = sum(p * r ** k * (1 + min(k, 19)) / 20 for k in range(2000))
assert abs(series - expected) < 1e-12

def paid_fraction(multiplier):
    ratio = 1 - 1 / multiplier
    return (1 + sum(ratio ** k for k in range(1, 20))) / 20

rows = [{'effective_multiplier': m, 'expected_paid_fraction': paid_fraction(m),
         'probability_all_slots_filled': (1 - 1 / m) ** 19}
        for m in [2, 5, 10, 20, 40, 100, 200]]
# Marginal increments chosen so all integer allocation divisions are exact.
fee_delta = 400000
fee_rows = []
for n in [0, 1, 10, 19]:
    slot = fee_delta // 20
    finder = slot + n * (slot // 20)
    contributors = n * (slot - slot // 20)
    assert finder + contributors == (n + 1) * slot
    fee_rows.append({'credited_foreign_proofs': n, 'fee_delta_sats': fee_delta,
                     'finder_sats': finder, 'contributors_sats': contributors,
                     'unclaimed_sats': fee_delta - finder - contributors,
                     'finder_fraction': finder / fee_delta})
locks = []
for rate in [0, .05, .10, .20]:
    pv = .5 / (1 + rate) ** (6480 / 52560) + .5 / (1 + rate)
    baseline = 1 / (1 + rate) ** (100 / 52560)
    locks.append({'assumed_annual_rate': rate, 'allocation_present_value': pv,
                  'baseline_100_block_present_value': baseline})
output = {'scope': 'Constant budget, independent work, unbounded time horizon, instantaneous full relay, compatible Xs, no target clipping unless stated. No strategic withholding, latency, price or adoption forecast.',
          'seed': 20260925, 'samples': args.samples,
          'analytic': {'expected_weak_before_block': 19, 'variance_weak_before_block': 380,
                       'expected_paid_fraction': expected, 'expected_unclaimed_fraction': 1 - expected,
                       'probability_all_slots_filled': r ** 19},
          'simulation': {'mean_weak': weak_sum / args.samples, 'mean_paid_fraction': mean,
                         'paid_standard_error': se, 'all_slots_fraction': full / args.samples},
          'multiplier_sweep_fixed_twenty_slots': rows,
          'marginal_fee_allocation': fee_rows, 'illustrative_discount_rates': locks}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(output, indent=2) + '\n')
print(json.dumps(output['analytic']))
print(json.dumps(output['simulation']))
