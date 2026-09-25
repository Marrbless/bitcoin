# Fixed v4 validation

Executed 25 September 2026 on Linux x86_64 with GCC 13. Candidate and unmodified
parent use release commit `58398baf33e588779685ead478e6397bb28ed3d6` as the base.
Wallet and GUI are disabled. The normal binary is Release; the instrumented
binary uses RelWithDebInfo with address and undefined behavior sanitizers.

Version 4 uses the fixed 263 byte header commitment proof. Historical v3
results are retained in [VALIDATION_V3.md](VALIDATION_V3.md), [evidence/](evidence/)
and [review/](review/). They are not counted as passes for the new format.

## Current campaign

| Suite | Recorded checks | What it exercises |
| --- | ---: | --- |
| Native BLAKE2b | 70 | Independent Python commitment, all four profiles, fixed size, maximum evidence, changed terms, legacy rejection, exact payouts and parent acceptance |
| Activation boundary | 17 | Inherited SHA behavior, BLAKE activation, template negotiation, explicit 83 byte limit with RDTS inactive, reorganisation |
| Native socket endpoint | 44 | Work reconstruction, two node settlement, relay, inventory caps, full block priority and expiry |
| Adversarial | 41 | All 263 strict certificate prefixes, malformed inputs, changed recipients, reward redirection, admission budget, reindex and activation reorganisation |
| Signed maturity | 36 | Actual spends at both CSV boundaries through height 52,661 on both implementations |
| Socket stress | 6 | Two minutes of hostile sequential connections with honest block production |
| Fee and header review | 54 | Native marginal fee deltas, specific missing X rejection and inherited header commitment on all profiles |
| Temporary maturity overlap | 16 | Inherited restriction, release and reorganisation composed with CSV rewards |

The Release default run contains 172 recorded checks. The additional four
suites contain 112, giving 284 distinct checks. A final default run added the
legacy header rejection case after an earlier 171 check development run;
repeated checks are not added to the total.

The address and undefined behavior campaign passes the same 172 default
checks with 10,000 malformed certificates instead of the Release corpus of
256. Half of the instrumented corpus mutates a valid proof's committed terms,
and half uses bounded random bytes. This is deterministic adversarial input,
not coverage guided fuzzing. Leak detection is disabled because LeakSanitizer
fails under this runtime's process tracing. No leak check pass is claimed.

The inherited `feature_powchange.py` and `mining_basic.py` also pass against the
new Release binary. This is not the full upstream test suite.

## Scope of the observations

The independent Python encoder agrees with native commitments and certificate
encoding. Altering X, a recipient or the header commitment invalidates the
claim. Contextual checks reject wrong parent, target, height, reserved flags,
time and full block solutions presented as weak work. The proof does not
claim validity of an omitted source block.

Maximum inventory produces a 4,998 byte evidence body in 70 fragments.
The measured fixture coinbase is 8,335 bytes and its complete block 8,594
bytes, including payouts and ordinary block structure. These larger sizes
make clear that 83 bytes limits each OP_RETURN script, not a whole proof,
coinbase or block. Extra unrelated block contents can increase total size.

Signed rewards remain subject to both ordinary inherited restrictions and
CSV. Tests reject premature, disabled, short and time based sequences, an old
transaction version and a shortened witness script. The late spend uses actual
fees after regtest subsidy has reached zero. The temporary maturity test shows
that CSV eligibility cannot bypass an inherited longer restriction.

Socket observations and raw timings are in [v4/stress_metrics.json](v4/stress_metrics.json).
The honest miner remains connected while hostile connections are sequential.
The result is not a fairness guarantee under occupied client slots, slow
readers, network saturation or a public peer network.

## Design comparisons are separate from consensus tests

[DESIGN_CHOICES.md](DESIGN_CHOICES.md) compares three fee policies, twelve slot
and multiplier cases and three maturity schedules. The exact arithmetic checks
3,840 allocations including rounding boundaries, zero subsidy and large fees.
The comparison is analytic, without target clipping, delivery losses or
strategic behavior. It does not establish a recommended production setting.

Only sharing subsidy plus fees and the existing long locks are implemented.
Fee alternatives and shorter schedules have not been validated as native
consensus variants. The model never treats node parameter selection as a vote.

## Evidence and reproduction

[v4/campaign.json](v4/campaign.json) records source and binary hashes, counts,
settings and the development correction. [v4/](v4/) contains individual results,
runner summaries, measured sizes and the comparison data. Binary hashes identify
these executables; they do not promise identical builds on other systems.

Use the [test instructions](../../test/functional/work_contributions/README.md)
with fresh regtest state. Add `--extended --stress --review` for the additional
suites. Use `CONTRIBUTION_FUZZ_CASES=10000` for the larger adversarial corpus.
The supported instrumented run sets
`ASAN_OPTIONS=detect_leaks=0:halt_on_error=1` and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`.

Version 4 supersedes the experimental v3 format. No migration of an already
active v3 chain is implemented. Parent compatibility refers to the unmodified
pinned release. Activation stays disabled outside explicit regtest settings.

## Remaining gates

Independent commitment and consensus review, coverage guided fuzzing, complete
upstream suites, platform builds, assumevalid and crash recovery, realistic
multi operator networking and physical ASIC testing remain. Fee and maturity
choices still need strategic economic evaluation. The current proposal does
not establish a universal economic preference for running one's own node.

These results support review of a disabled research implementation. They do
not establish deployment readiness or exhaustive security.
