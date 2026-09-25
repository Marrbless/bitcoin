#!/usr/bin/env python3
# Distributed under the MIT software license, see the accompanying COPYING.
"""Offline economic experiment. Does not execute or validate consensus code."""
import argparse
import json
from pathlib import Path
import numpy as np


def choose(rng, inventory, capacity):
    """Uniform sampling without replacement, retaining operator ownership."""
    remaining = inventory.sum(axis=1)
    left = capacity.copy()
    picked = np.zeros_like(inventory)
    for j in range(inventory.shape[1]):
        good = inventory[:, j]
        active = (left > 0) & (remaining > 0)
        picked[active, j] = rng.hypergeometric(good[active], (remaining-good)[active], left[active])
        left -= picked[:, j]
        remaining -= good
    assert np.all(left == 0)
    return picked


def simulate(shares, multiplier, intervals, seed):
    rng = np.random.default_rng(seed)
    shares = np.array(shares)
    assert abs(shares.sum()-1) < 1e-12
    k = len(shares)
    totals = {p: np.zeros(k) for p in ('uniform', 'finder_first')}
    squares = {p: np.zeros(k) for p in totals}
    positive = {p: np.zeros(k) for p in totals}
    claimed_sum = claimed_squares = full = weak_sum = selected_sum = 0
    finder_counts = np.zeros(k)
    for start in range(0, intervals, 10000):
        n = min(10000, intervals-start)
        # Weak solutions exclude the terminal full solution. No target clipping.
        weak = rng.geometric(1/multiplier, n)-1
        remaining = weak.copy()
        inventory = np.zeros((n, k), dtype=np.int64)
        probability_left = 1.0
        for j in range(k-1):
            inventory[:, j] = rng.binomial(remaining, shares[j]/probability_left)
            remaining -= inventory[:, j]
            probability_left -= shares[j]
        inventory[:, -1] = remaining
        finder = rng.choice(k, n, p=shares)
        row = np.arange(n)
        capacity = np.minimum(weak, 19)
        uniform = choose(rng, inventory, capacity)
        own = np.minimum(inventory[row, finder], capacity)
        foreigners = inventory.copy()
        foreigners[row, finder] = 0
        preferred = choose(rng, foreigners, capacity-own)
        preferred[row, finder] += own
        for policy, selected in [('uniform', uniform), ('finder_first', preferred)]:
            assert np.all(selected <= inventory)
            assert np.all(selected.sum(axis=1) == capacity)
            revenue = selected.astype(float)*0.0475
            revenue[row, finder] += 0.05+capacity*0.0025
            assert np.allclose(revenue.sum(axis=1), (1+capacity)/20)
            totals[policy] += revenue.sum(axis=0)
            squares[policy] += (revenue**2).sum(axis=0)
            positive[policy] += (revenue > 0).sum(axis=0)
        claimed = (1+capacity)/20
        claimed_sum += claimed.sum()
        claimed_squares += (claimed**2).sum()
        full += (capacity == 19).sum()
        weak_sum += weak.sum()
        selected_sum += capacity.sum()
        finder_counts += np.bincount(finder, minlength=k)
    expected = sum((1-1/multiplier)**i for i in range(20))/20
    claimed_mean = claimed_sum/intervals
    claimed_se = np.sqrt((claimed_squares/intervals-claimed_mean**2)/intervals)
    assert abs(claimed_mean-expected) < 6*claimed_se
    policies = {}
    total_selected = sum((1-1/multiplier)**i for i in range(1,20))
    own_selected = np.array([sum((a*(multiplier-1)/(1+a*(multiplier-1)))**i
                                for i in range(1,20)) for a in shares])
    exact_preferred = np.zeros(k)
    for i, a in enumerate(shares):
        paid_proofs = a*own_selected[i] + sum(shares[j]*a/(1-shares[j])*
                      (total_selected-own_selected[j]) for j in range(k) if j != i)
        exact_preferred[i] = .0475*paid_proofs+a*(.05+.0025*total_selected)
    for policy in totals:
        mean = totals[policy]/intervals
        variance = np.maximum(0, squares[policy]/intervals-mean**2)
        exact = shares*expected if policy == 'uniform' else exact_preferred
        assert np.all(np.abs(mean-exact) < 6*np.sqrt(variance/intervals))
        policies[policy] = dict(revenue_per_block=mean.tolist(),
            analytic_revenue_per_hash=(exact/shares).tolist(),
            revenue_per_hash= (mean/shares).tolist(),
            fraction_of_claimed_reward=(mean/claimed_mean).tolist(),
            block_revenue_stddev=np.sqrt(variance).tolist(),
            mean_standard_error=np.sqrt(variance/intervals).tolist(),
            probability_of_payment=(positive[policy]/intervals).tolist())
        assert abs(mean.sum()-claimed_mean) < 1e-10
    return dict(hash_fractions=shares.tolist(), multiplier=multiplier, intervals=intervals,
        mean_weak_proofs=float(weak_sum/intervals), expected_weak_proofs=multiplier-1,
        claimed_fraction=float(claimed_mean), analytic_claimed_fraction=expected,
        full_probability=float(full/intervals), analytic_full_probability=(1-1/multiplier)**19,
        fraction_of_weak_proofs_settled=float(selected_sum/weak_sum),
        finder_counts=finder_counts.tolist(), policies=policies)


def maturity():
    rows = []
    # Steady production of 100,000 sats/day; costs of 70,000 sats/day.
    # Exact deterministic fluid cash flow, not a stochastic mining reserve.
    for inherited in (100, 6480):
        for name, allocation in [('one_inherited', [(1, 0)]),
                                 ('one_delayed', [(1, 6480)]),
                                 ('two_current', [(.5, 6480), (.5, 52560)])]:
            schedule = [(weight, max(inherited, delay)) for weight, delay in allocation]
            times = sorted({0, *(delay/144 for _, delay in schedule)})
            reserve = max(70000*t-sum(weight*100000*max(0,t-delay/144)
                          for weight, delay in schedule) for t in times)
            pv = sum(weight/1.1**(delay/52560) for weight, delay in schedule)
            baseline = 1/1.1**(inherited/52560)
            rows.append(dict(case=name, assumed_inherited_depth=inherited,
                schedule=schedule, reserve_sats=reserve,
                pv_loss_vs_inherited_at_10_percent=1-pv/baseline,
                full_reward_advance_receivables_sats=sum(weight*100000*delay/144 for weight,delay in schedule),
                delegated_direct_payment_has_same_schedule=True))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--intervals', type=int, default=1000000)
    args = parser.parse_args()
    assert args.intervals >= 10000
    scenarios = []
    for i, (name, shares) in enumerate([('concentrated', [.5,.2,.1,.1,.09,.01]),
                                       ('equal', [.01]*100)]):
        for multiplier in (20, 40):
            scenarios.append(dict(name=name, **simulate(shares, multiplier, args.intervals, 20260925+i*100+multiplier)))
    # At zero subsidy, with all 19 foreign slots, marginal finder fee retention.
    fees = [dict(shared_fraction=s, finder_marginal_fraction=1-s+s*.0975,
                 foreign_contributor_fraction=s*.9025) for s in (0,.25,.5,1)]
    result = dict(source_commit='006502597f495a2c4814e3a45dd10a4af5d07b17',
        scope='Offline model, not native consensus or transport testing. Constant reward; independent stationary hash; unclipped target; compatible X; perfect relay; no withholding, costs, fee substitution, mempool congestion or stale blocks. Revenue normalized to one available shared budget per block. Float arithmetic omits satoshi rounding; existing compare_fee_rules.py tests rounding separately. Equal group runs are symmetry controls, not adoption forecasts.',
        numpy_version=np.__version__, scenarios=scenarios, maturity=maturity(), fee_policies=fees)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    for r in scenarios:
        print(r['name'], r['multiplier'], 'claimed', round(r['claimed_fraction'],6),
              'preferred revenue/hash first,last',
              [round(r['policies']['finder_first']['revenue_per_hash'][j],6) for j in (0,-1)])
    print('maturity', result['maturity'][:3])


if __name__ == '__main__':
    main()
