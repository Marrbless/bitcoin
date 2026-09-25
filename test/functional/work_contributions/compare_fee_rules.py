#!/usr/bin/env python3
# Distributed under the MIT software license, see the accompanying COPYING.
"""Exact reward arithmetic and analytic parameter comparisons, not an adoption test."""
import argparse
from fractions import Fraction
import json
import math
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()

def allocate(subsidy, fees, proofs, fee_share, slots=20):
    shared = subsidy + fees * fee_share.numerator // fee_share.denominator
    direct = subsidy + fees - shared
    slot = shared // slots
    skim = slot // 20
    finder = direct + slot + proofs * skim
    contributors = proofs * (slot - skim)
    return {'finder_sats': finder, 'contributors_sats': contributors,
            'unclaimed_sats': subsidy + fees - finder - contributors}

def utilization(slots, multiplier):
    r = Fraction(multiplier - 1, multiplier)
    return sum(r ** k for k in range(slots)) / slots

policies = [('finder_fees', Fraction(0)), ('quarter_shared_fees', Fraction(1, 4)), ('all_shared_fees', Fraction(1))]
checks = 0
for subsidy in [0, 1, 19, 20, 399, 400, 312500000, 5000000000]:
    for fees in [0, 1, 19, 20, 399, 400, 10000000, 2099995000000000]:
        if subsidy + fees > 2100000000000000:
            continue
        for name, share in policies:
            for count in range(20):
                row = allocate(subsidy, fees, count, share)
                assert min(row.values()) >= 0 and sum(row.values()) == subsidy + fees
                # Independent per-recipient construction checks total and rounding.
                shared = subsidy + math.floor(Fraction(fees) * share)
                slot = shared // 20
                expected = [subsidy + fees - shared + slot + count * (slot // 20)] + [slot - slot // 20] * count
                assert sum(expected) == subsidy + fees - row['unclaimed_sats']
                checks += 1
fee_rows = []
for name, share in policies:
    for count in [0, 1, 10, 19]:
        delta = allocate(0, 400000, count, share)
        fee_rows.append(dict(policy=name, shared_fee_fraction=float(share), foreign_proofs=count,
                             added_fee_sats=400000, **delta))
slot_rows = []
for slots in [5, 10, 20, 40]:
    for multiple in [1, 2, 5]:
        multiplier = slots * multiple
        paid = utilization(slots, multiplier)
        # Independent finite expectation plus exact geometric tail.
        r = Fraction(multiplier - 1, multiplier)
        direct_sum = sum((1-r)*r**k*Fraction(k+1, slots) for k in range(slots-1)) + r**(slots-1)
        assert paid == direct_sum
        body = 1 + (slots - 1) * 263
        fragments = (body + 71) // 72
        # Serialized zero-valued carrier outputs, including framing and push opcodes.
        carrier_bytes = sum(8 + 1 + (1 + (1 if min(72, body-offset)+8 <= 75 else 2) + min(72, body-offset)+8)
                            for offset in range(0, body, 72))
        slot_rows.append(dict(slots=slots, max_contributions=slots-1, multiplier=multiplier,
            expected_weak_per_block=multiplier-1, expected_paid_fraction=float(paid),
            full_inventory_probability=float(r**(slots-1)), max_certificate_body_bytes=body,
            max_fragments=fragments, serialized_carrier_outputs_bytes=carrier_bytes))
locks = []
for label, early, late in [('inherited_baseline', 100, 100), ('short_comparison', 100, 1008), ('current_control', 6480, 52560)]:
    for rate in [0, .05, .10, .20]:
        pv = .5 / (1+rate)**(early/52560) + .5 / (1+rate)**(late/52560)
        baseline = 1 / (1+rate)**(100/52560)
        locks.append(dict(case=label, early_blocks=early, late_blocks=late, assumed_annual_discount_rate=rate,
                          present_value_fraction=pv, loss_vs_100_block_baseline=1-pv/baseline,
                          own_node_pv=pv, full_rebate_delegated_pv=pv))
fee_mix = []
util = float(utilization(20, 20))
for name, share in policies:
    for fee_fraction in [0, .1, .5, .9, 1]:
        shared_fraction = 1-fee_fraction + fee_fraction*float(share)
        fee_mix.append(dict(policy=name, fees_fraction_of_total_reward=fee_fraction,
            expected_claimed_fraction=shared_fraction*util + fee_fraction*(1-float(share)),
            expected_contributor_fraction=shared_fraction*(util-.05)*.95))
output = dict(scope='Offline comparison. Only all_shared_fees and current_control maturity are implemented. Independent work; instantaneous full relay; compatible X; constant rewards; no target clipping, strategic withholding, congestion or adoption model. Same reward scripts and maturity held constant between fee policies. Each policy has one global split, not node voting.',
    rounding_checks=checks, marginal_fee_rows=fee_rows, slot_rows=slot_rows,
    maturity_rows=locks, fee_mix_rows=fee_mix,
    invariants={'v4_certificate_bytes':263, 'current_max_container_bytes':4998, 'current_max_fragments':70,
                'current_expected_paid_fraction':util, 'direct_rebate_has_same_consensus_maturity':True})
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(output, indent=2)+'\n')
print(json.dumps({'rounding_checks':checks, 'parameter_cases':len(slot_rows), **output['invariants']}))
