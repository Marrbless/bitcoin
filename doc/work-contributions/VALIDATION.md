# Proposal validation

Executed 25 September 2026 on Linux x86_64 with GCC 13. Candidate and
unmodified parent were built from release commit
`58398baf33e588779685ead478e6397bb28ed3d6`. Wallet and GUI were disabled.
The normal binary used Release; the instrumented binary used RelWithDebInfo
with address and undefined behavior sanitizers.

| Campaign | Result |
| --- | --- |
| Native BLAKE2b consensus suite | 127 recorded checks passed |
| SHA and 83 byte boundary suite | 10 recorded checks passed |
| BLAKE2b socket endpoint suite | 44 recorded checks passed |
| Adversarial suite | 41 recorded checks passed |
| Signed reward maturity campaign | 36 recorded checks passed |
| Sustained socket fixture | 6 recorded checks passed |
| Inherited feature_powchange.py and mining_basic.py | Both passed |
| Address and undefined behavior sanitizer campaign | 222 checks passed, including 10,000 malformed certificates; leak detection disabled |
| LeakSanitizer | Blocked by the runtime tracing environment; not a pass |

The default suite records 222 checks. The additional maturity and socket
campaigns bring the Release total to 264. Counts describe assertions in these
fixtures, not independent attacks or proofs of safety.

## Findings and adversarial coverage

A batch of poisoned contributions reproduced an absent admission limit before
its correction. The new shared budget and repeated authorization check passed
regression tests. Honest contribution processing resumed after replenishment,
and a full block was accepted afterward. The before fix failure is retained in
[evidence/admission_before_fix.json](evidence/admission_before_fix.json).

Adversarial cases cover all 336 strict prefixes of the sample certificate,
256 deterministic malformed certificates in the Release run, work reuse with
changed recipients, X or locktime, reward redirection, underpayment and duplicate
metadata. Maximum evidence and all four BLAKE2b profiles are also exercised.
Chainstate reindex reproduced the settlement tip. A reorganisation crossed the
activation height, accepted an ordinary reward below activation, and reapplied
restrictions on the alternate branch above it.

The signed maturity campaign validated the same chain through height 52,661 on
both implementations. Finder and contributor spends were rejected one block
before each relative maturity boundary and accepted at the boundary. Actual
signed contributor spends were connected at both boundaries. Short, disabled
and time based sequence values, version 1 and a shortened witness script did
not bypass the locks. The late spend also exercised settlement funded by fees
with zero regtest subsidy. This does not cover inherited temporary long
maturity overlaps or their release.

The final 120 second socket fixture opened 7,552 hostile connections while
accepting 472 real regtest blocks. Sampled resident memory grew from 52,539,392
to 54,337,536 bytes. The largest observed block response was 301.680 ms.
These are local observations with a connected honest client, sequential hostile
connections and easy work. They are not public network throughput, fairness or
denial of service guarantees.

## Evidence and reproduction

[evidence/summary.json](evidence/summary.json) records Release binary hashes,
suite exit statuses and counts. Maturity results and campaign metadata are
separate files. Individual JSON records retain observations; the source manifest
identifies the reviewed C++ and test files. Binary hashes provide provenance,
not reproducible build guarantees across environments.

The initial upstream functional attempt lacked bitcoin-cli. Both tests passed
after building that required executable. The activation fixture initially
reused a stopped RPC connection after reindex; correcting the helper made the
case execute successfully. These were harness issues, not protocol findings.

The shutdown check now treats a nonzero node exit as a test failure. This
exposed LeakSanitizer's fatal error under runtime process tracing. The supported
sanitizer run uses `ASAN_OPTIONS=detect_leaks=0:halt_on_error=1` and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`. Leak testing must be rerun
outside this environment. Earlier instrumented assertion passes that ignored
shutdown status are not counted as successful sanitizer runs.

See the [test instructions](../../test/functional/work_contributions/README.md).
Use `--extended` for maturity and `--stress` for the socket fixture. Sanitizer
builds can use `-DSANITIZERS=address,undefined` and
`-DCMAKE_CXX_FLAGS=-fno-sanitize-recover=all`. The instrumented adversarial run
sets `CONTRIBUTION_FUZZ_CASES=10000`. Random malformed input is not coverage
guided fuzzing.

## Outstanding gates

The [security review](SECURITY_REVIEW.md) describes the open design questions
and attack surface. Independent cryptographic and consensus review, coverage
guided fuzzing, inherited maturity overlap tests, assumevalid and crash recovery,
the full upstream suites, platform builds, realistic multi operator networking
and physical ASIC tests remain. Neither a public testnet nor an empirical
adoption experiment has been completed. The economic advantage of operating
one's own node remains unproved.

These results support review of a disabled research proposal. They do not
establish production readiness, exhaustive compatibility or censorship
resistance. No production activation is included.
