# Reward funding, maturity and operator incentives

25 September 2026

I want contributions to remain useful when the subsidy ends. That means they
need a share of transaction fees. Giving every fee to the finder is useful as
a control, but it cannot be the final funding rule for this proposal.

Activation will use a block height. The height remains unspecified. The
allocation does not expire with RDTS.

## What was tested

This is an economic comparison against source commit
`006502597f495a2c4814e3a45dd10a4af5d07b17`. It does not change consensus code.
Alternative maturity and proof frequency values have not been tested through
native block validation in this comparison.

The simulation runs one million block intervals for each of four cases:
two operator distributions at multipliers 20 and 40. Each case compares
uniform proof selection against every finder selecting its own proofs first.
Foreign proofs fill any remaining space uniformly. Both policies use the same
work inventory and finder for each interval.

The concentrated case has hash fractions of 50%, 20%, 10%, 10%, 9% and 1%.
The symmetry control has one hundred equal operators. All work is independent,
every X is compatible, relay is immediate, reward is constant and targets do
not clip. There are nineteen contribution slots and a 5% inclusion skim.
There is no withholding, fee substitution, congestion, delivery loss or
operating cost in this simulation. These are scenarios, not network forecasts.

The simulator checks reward conservation and inventory bounds. Independent
analytic expectations check utilization and every operator's mean revenue
within six estimated standard errors. This tolerance checks the simulation;
it does not bound the model's economic assumptions. The separate existing fee
comparison also passed 3,840 integer allocation checks, including zero subsidy.

## Choosing your own proofs

There is nothing invalid about a finder choosing its own work. In that sense,
yes, this is solo mining. It still produces the extra qualifying proofs and
includes their X transactions. A block solution cannot be reused as nineteen
additional weak proofs.

The question is whether grouping hashpower changes revenue per unit of work.
For a slot worth 10,000 sats, a foreign proof gives the finder a 500 sat skim
and its recipient 9,500 sats. An owned proof gives the same operator all
10,000 sats. The operator gains 9,500 sats by substituting its own eligible
proof when the transaction costs are otherwise equal.

Small miners can make this choice too. Large operators find full blocks more
often and have more of their own proofs ready when they do. No identity rule
is involved: an operator can control many recipient keys.

The measured revenue below is divided by the operator's hash fraction, with
the available shared reward per block normalized to one.

| Selection | Multiplier | Operator with 50% hash | Operator with 1% hash |
| :--- | ---: | ---: | ---: |
| Uniform | 20 | 0.6416 | 0.6376 |
| Own proofs first | 20 | 0.7174 | 0.5118 |
| Uniform | 40 | 0.7947 | 0.7947 |
| Own proofs first | 40 | 0.9259 | 0.5091 |

Uniform selection has equal expected revenue per hash; the measured difference
is sampling noise. Under ownership preference, the difference is structural.
The equal operator control remains symmetric. This is not evidence of a
universal centralization outcome, but it is a concrete incentive to analyze.

## Proof frequency

| Quantity | Multiplier 20 | Multiplier 40 |
| :--- | ---: | ---: |
| Expected weak proofs per interval | 19 | 39 |
| Analytic shared reward claimed | 64.15% | 79.46% |
| Analytic probability all slots fill | 37.74% | 61.81% |
| Measured fraction of proofs settled, concentrated case | 62.28% | 38.21% |

Multiplier 40 increases utilization and approximately doubles proof arrivals.
It leaves the maximum block evidence unchanged, but more proofs compete for
the same slots. The smallest operator does not gain meaningful revenue in the
ownership preference scenario. The larger operator benefits substantially.

Keep 20 as the control. Do not recommend 40 solely because fewer rewards go
unclaimed. Current easy regtest targets can clip both multipliers, so native
acceptance at those targets would not test this economic difference.

For the analytic cross check, let a be an operator's hash fraction and M the
target multiplier. Its weak proof count before a full block has geometric
tail ratio r = a(M minus 1)/(1 + a(M minus 1)). Its expected owned inventory
that fits is the sum of r to powers 1 through 19. Condition on each possible
finder, reserve its owned inventory first, and distribute remaining selections
among other operators in proportion to their hash fractions. The script uses
that expectation independently of its sampled inventory and selection path.

## Recipients and maturity

Assume 100,000 sats of reward per day, 70,000 sats of operating expense per
day, ten minute blocks and inherited maturity of 100 blocks. This deterministic
cash flow calculation excludes equipment, price changes and mining variance.

| Reward schedule | Operating reserve | Present value loss versus inherited maturity at 10% annually |
| :--- | ---: | ---: |
| One recipient, inherited maturity | 48,611 sats | 0% |
| One recipient, 6,480 block delay | 3,150,000 sats | 1.15% |
| Two recipients, half at 6,480 and half at 52,560 | 9,550,000 sats | 5.11% |

The reserve is the maximum cumulative expense less matured receipts. It is
not a recommended cash buffer. Real small miners also face payout variance.
The model separately checks an assumed inherited depth of 6,480 blocks as a
sensitivity case; it is not a claim about the chain's current maturity rule.
Inherited restrictions always apply, taking the later applicable maturity.

A template provider paying directly to the miner's keys has the same schedule
as independent mining. A provider advancing money sooner needs financing.
These delays target advances, not control of transaction selection.

One recipient with inherited maturity is the recommended next implementation
candidate. A single delayed recipient is a control for financing costs. The
two recipient split has not demonstrated a compensating benefit. Removing a
key would require a versioned commitment and new signed spend tests. The
estimated 230 byte certificate and twenty allocation outputs remain design
estimates, not implemented results.

## Fee funding

At zero subsidy, a positive shared fee fraction can fund contributions. It
does not guarantee economically worthwhile payments: fees can be small,
proofs can be excluded and compensation can move outside transaction fees.

With all nineteen proofs owned by other miners, the finder retains 100% minus
90.25% times the shared fee fraction of an additional transaction fee.

| Shared fee fraction | Finder retains | Contribution recipients receive |
| :--- | ---: | ---: |
| 25% | 77.4375% | 22.5625% |
| 50% | 54.875% | 45.125% |
| 100% | 9.75% | 90.25% |

Partial fee sharing reduces the finder's dilution and the size of the shared
budget at the same time. It does not remove ownership preference inside that
budget. The simulation uses a fully shared budget; with zero subsidy and a
constant fee budget, a shared fraction s scales these contribution revenues
by s and adds an expected direct finder return of 1 minus s per unit of hash.
This linear transformation does not model miners changing transaction fees.

No fraction is selected as a final default. Keep 100% as the implemented
control, and compare 25% and 50% with direct payment and congestion scenarios.
Zero sharing no longer satisfies the intended design.

## Template construction and delivery

The existing RPC manually assembles supplied transactions and validates the
result. The endpoint calls that RPC and decodes the returned block. The next
implementation should expose one internal candidate construction function to
both callers, using the existing block assembler.

Selected contributions impose required X transactions and their ancestors.
Resolve conflicts before construction, reserve exact coinbase weight and
sigop costs, add required packages once in dependency order, then use ordinary
package selection for remaining space. Recalculate fees and payouts from the
final transaction set and run full candidate validation. Required inclusion
must not bypass script, maturity, sequence lock or resource checks. If a
contribution cannot fit, exclude it before promising its reward.

Delivery stays optional and outside consensus. For the next experiment use
several explicitly configured peers with bounded queues, duplicate suppression,
cheap context checks before work checks, a shared validation budget and expiry
on parent change. Transaction dependencies should use available mempool data,
with bounded requests for missing data. Separate peer delivery from ASIC job
handling. Imported proofs must be eligible for bounded onward relay; merely
configuring more destinations is not a complete propagation design.

This is a design direction. The current endpoint still has one loopback peer.
Peer selection, eclipse resistance and honest admission during saturation need
network experiments. Consensus cannot reject a block just because the finder
failed to include a proof it may never have received.

## Reproduction and next implementation

Run `python3 test/functional/work_contributions/compare_operator_incentives.py
--output doc/work-contributions/operator_comparison.json` with NumPy installed.
The recorded run used NumPy 2.3.5 and fixed seeds. Raw results include per
operator means, variance, standard errors, payment probabilities and analytic
expectations.

Next implement one recipient with inherited maturity as an explicit experiment,
then exercise signed spending, activation boundaries, reorganisations and
parent acceptance. Test multipliers with targets that do not clip. Keep the
fee funding and ownership incentives visible while refactoring the assembler.
Activation by height also needs height H minus 1, H and H plus 1 tests and
reorganisations across H. The mechanism is settled; the production height is
not selected here.
