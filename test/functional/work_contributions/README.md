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
| test_blake.py | 127 | Native assembly, profiles, compact codec, malformed evidence, reward checks, old/new acceptance and reorg eligibility |
| test_sha_boundary.py | 10 | SHA path and explicit 83-byte coinbase output limit outside RDTS |
| test_endpoint_blake.py | 44 | Socket work reconstruction, bounded relay, actual 19-proof cap, ordinary saturation and full-block priority |
| test_adversarial.py | 41 | Recipient attacks, all certificate truncations, random malformed corpus, admission limits, chainstate reindex and reorg |
| test_maturity.py | 36 | Optional real signed early and late reward spends, premature spends and sequence bypass attempts |
| test_stress.py | 6 | Optional hostile socket traffic with interleaved real block production and RSS sampling |

The default run includes the first four suites. Add `--extended` for the signed
maturity campaign, which validates more than 52,000 blocks on both nodes. Add
`--stress` for the socket campaign. `CONTRIBUTION_STRESS_SECONDS` selects 10 to
3,600 seconds, default 120. `CONTRIBUTION_FUZZ_CASES` selects 256 to 100,000
deterministic random certificates, default 256. These random bytes supplement
the targeted cases; this is not a coverage guided fuzzer.

`summary.json` records binary hashes and suite exit statuses. Individual JSON
files include failed assertions when reached; logs retain tracebacks. A nonzero
exit aborts the run. Outputs such as `settled_block.hex` may be replaced by a
later suite in the same run; per-suite result files and logs remain distinct.
These are recorded assertions, not independent proofs of security.

This standalone research runner is not yet integrated into `test_runner.py`.
It does not execute the full upstream functional/unit/fuzz suites, a physical
ASIC test, public-testnet trial, or economic/adoption experiment. Inherited
long-maturity overlaps, assumevalid and activation reorganisation campaigns
remain outside the signed maturity fixture.
