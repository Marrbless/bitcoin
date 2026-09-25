# Security review and open design work

This is a proposal with a private regtest implementation. Passing these tests
does not establish that the new consensus rules or mining interface are safe
to deploy. The review distinguishes demonstrated behavior from design claims.

## Finding fixed in this revision

An inbound peer could repeatedly submit an invalid contribution and cause the
endpoint to construct and validate a candidate each time. The proof inventory
cap did not bound rejected work. A batch of 96 poisoned contributions reproduced
the missing admission limit before the fix.

The endpoint now admits at most 32 new contribution validation attempts per
one second interval, shared across connections. Exact retries of retained
proofs are acknowledged before this budget. Repeated authorization on an
already authorized connection is rejected without rebuilding its job.

These are local resource policies, not consensus changes. The fixed interval
permits a burst across an interval boundary. It is not a CPU time limit, fair
scheduling, peer authentication or a public network denial of service solution.
A hostile peer can consume the shared budget and delay honest contributions.
Full block submissions do not use this contribution budget.

The regression test first failed on the missing limit, then passed after the
fix. It also accepted an honest contribution after budget replenishment and a
full block afterward. See the retained before and after evidence.

## Attack surface and evidence

| Surface | Exercised here | Remaining exposure |
| --- | --- | --- |
| Certificate parser | All strict prefixes of a valid certificate, bounded random bytes, targeted field mutations, maximum evidence | Coverage guided fuzzing, independent parser and cryptographic review |
| Work and recipients | Work reuse with altered X, keys or locktime rejected; all four inherited BLAKE2b profiles | Independent review of the arbitrary midstate construction |
| Reward settlement | Wrong scripts, redirection, underpayment, duplicate metadata, aggregate and split recipient outputs | Broad arithmetic and fee boundary fuzzing |
| Persistence | Settlement reproduced by chainstate reindex, then invalidate and reconsider; activation crossed on an alternate branch | Assumevalid, broader activation interactions, crash and interrupted reindex campaigns |
| Endpoint resources | Rejected contribution budget, repeated authorization, malformed frames, connection churn with real block production | Sustained multi peer contention, slow readers, network partitions and recovery, production scheduling |
| Compatibility | Parent accepts tested valid settlements and signed spends; inherited mining and PoW transition tests | Complete upstream test suite, platform builds and independent soft fork review |

The random certificate corpus is not coverage guided fuzzing. The socket
stress test is a local, sequential connection fixture with a legitimate miner
kept connected. It does not establish fairness when attackers occupy all four
connections or saturate the network.

## A smaller commitment may be possible

The inherited BLAKE2b header already contains `m_mm_rhs`, a 32 byte input to
the tagged merge mining hook included in the work hash. The inherited
`feature_powchange.py` test accepts a block with this field nonzero.

A possible alternative is to place a domain separated hash of X and the two
reward keys in that field. A certificate could then contain only a version,
the 164 byte header, X and the two 33 byte keys: 263 bytes before settlement
framing. This could remove the source coinbase length, imported SHA256 state,
Merkle branch and locktime from contribution evidence.

This alternative is not implemented or selected by this revision. It needs
analysis of compatibility with the field's existing merge mining purpose,
domain separation, hardware and gateway behavior, and whether the proposal
should support contributions on the historical SHA256d path at all. The
83 byte per script limit would still require fragmented settlement evidence.
Changing this design would require a new encoding and a fresh validation run.

## Economic limits are design limits

An external gateway can use the miner's keys for both allocations. The
resulting payment schedule can match independent operation while the gateway
still selects transactions. No additional parser testing can distinguish two
arrangements with identical on chain evidence.

The rules enforce inclusion of X when its contribution is credited. They do
not require selection of every eligible contribution, prove node ownership,
or impose a universal cost on exclusion. Slot competition and transaction
conflicts remain material. Longer locks affect independent miners too, and
do not prevent a mature rolling reserve.

The proposal should therefore be reviewed as conditional transaction inclusion
with shared rewards. An economic preference for operating one's own node is
the research objective, not a demonstrated consensus guarantee.

## Gates before a deployment proposal

1. Decide whether the proof format can be reduced before hardening it further.
2. Independently review the exact consensus specification and binding argument.
3. Add coverage guided parser fuzzing, sanitizer campaigns and arithmetic tests
   to normal upstream test infrastructure.
4. Test inherited maturity overlaps, additional activation and reorganisation boundaries,
   assumevalid and interrupted persistence operations.
5. Specify resource and peer delivery policies, then test realistic latency,
   adversarial contention and recovery with independent node operators.
6. Verify real ASIC and firmware behavior on an isolated BLAKE2b testnet.
7. Measure matched economic arrangements and publish counterexamples as well
   as favorable settings. Do not infer adoption from protocol acceptance.

Each gate needs a reproducible result and an explicit failure criterion.
Discussion of this proposal can start before those gates are complete;
production activation cannot be justified by this private fixture.
