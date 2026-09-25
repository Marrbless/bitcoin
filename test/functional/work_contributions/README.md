# Standalone contribution research tests

Run `python3 test/functional/work_contributions/run.py --help` from a checkout.
Supply explicit candidate and unmodified-parent bitcoind binaries and an empty
results directory. Build commands and the pinned parent are in
`doc/work-contributions/README.md`.

The suites import this checkout's ordinary `test_framework`; they require no
research archive, wallet, external DATUM process or funded account. Python
performs actual easy-regtest work. Fixtures use publicly known test-only keys
1 and 2, never suitable for real funds.

| Suite | Expected recorded checks | Coverage |
| --- | ---: | --- |
| test_blake.py | 70 | Native assembly, profiles, fixed v4 codec, malformed evidence, reward checks, old/new acceptance and reorg eligibility |
| test_activation_boundary.py | 17 | BLAKE activation, inherited SHA behavior and explicit 83-byte limit outside RDTS |
| test_endpoint_blake.py | 44 | Socket work reconstruction, bounded relay, actual 19-proof cap, ordinary saturation and full-block priority |
| test_adversarial.py | 41 | Recipient attacks, all certificate truncations, random malformed corpus, admission limits, chainstate reindex and reorg |
| test_maturity.py | 36 | Optional real signed early and late reward spends, premature spends and sequence bypass attempts |
| test_stress.py | 6 | Optional hostile socket traffic with interleaved real block production and RSS sampling |
| test_review.py | 54 | Optional native fee deltas, precise missing X rejection and inherited header commitment |
| test_maturity_overlap.py | 16 | Optional inherited temporary maturity restriction, release and reorganisation with CSV rewards |

The default run includes the first four suites. Add `--extended` for the signed
maturity campaign, which validates more than 52,000 blocks on both nodes. Add
`--stress` for the socket campaign. `CONTRIBUTION_STRESS_SECONDS` selects 10 to
3,600 seconds, default 120. `CONTRIBUTION_FUZZ_CASES` selects 256 to 100,000
deterministic random certificates, default 256. These random bytes supplement
the targeted cases; this is not a coverage guided fuzzer.

Add `--review` to execute both new review suites. Version 4 is the implemented fixed 263 byte format. The
separate `review_economics.py --output PATH` script runs an analytic and seeded
one million interval model. It uses no live network data and is not an adoption
test. The reviewed model output is in `doc/work-contributions/review/`.

`summary.json` records binary hashes and suite exit statuses. Individual JSON
files include failed assertions when reached; logs retain tracebacks. A nonzero
exit aborts the run. Outputs such as `settled_block.hex` may be replaced by a
later suite in the same run; per-suite result files and logs remain distinct.
These are recorded assertions, not independent proofs of security.

This standalone research runner is not yet integrated into `test_runner.py`.
It does not execute the full upstream functional/unit/fuzz suites, a physical
ASIC test, public-testnet trial, or economic/adoption experiment. A temporary
long-maturity overlap is exercised by the review suite. Assumevalid, crash
recovery and a broader matrix of activation interactions remain outstanding.

`compare_fee_rules.py --output PATH` compares three fee policies, twelve slot
and multiplier cases, and three maturity schedules. It checks integer reward
conservation and reports analytic expectations. Alternative fees, caps and
locks are model cases, not additional consensus settings. Only the existing
combined fee policy and long lock control are implemented. Current comparison
output is in `doc/work-contributions/v4/`.
