# Work-bound contribution research draft

This draft pairs a white paper with a native C++ private-regtest implementation.
It is disabled by default and supplies no mainnet activation. Target base:
`bitcoinknots/bitcoin`, `29.x-knots`, commit
`58398baf33e588779685ead478e6397bb28ed3d6`.

- [White paper](WHITE_PAPER.md): motivation, mechanism, economic limits and evidence.
- [Specification](SPECIFICATION.md): exact reward rules and v3 encoding.
- [Endpoint](ENDPOINT.md): Linux-only Sia-style BLAKE2b profile-0 mining interface.
- [Validation](VALIDATION.md): tests run on this submission and outstanding gates.
- [Security review](SECURITY_REVIEW.md): the reproduced finding, attack surface and open design work.
- [System review](SYSTEM_REVIEW.md): slot utilization, fee incentives, financing and the inherited header experiment.
- [Test runner](../../test/functional/work_contributions/README.md): reproducible commands.

## Review map

| Area | Implementation |
| --- | --- |
| Reward scripts and split | `src/consensus/gateway_allocation.*` |
| Certificate parsing, work, inclusion and payout checks | `src/consensus/node_contribution.*` |
| Aligned hash-state access | `src/crypto/sha256.*` |
| Inherited hash commitment factoring | `src/primitives/block.*` |
| Opt-in activation and block connection | `src/chainparams.cpp`, `src/kernel/chainparams.*`, `src/validation.cpp` |
| Candidate construction and template negotiation | `src/node/miner.cpp`, `src/rpc/mining.cpp` |
| Private mining and contribution relay | `src/node/native_stratum.*` |

Proofs bind X and keys but do not establish who selected X or validate the omitted
source block. An external service can return both reward portions directly to
miner keys. A universal economic advantage for self-operation is not demonstrated.

## Build and reproduce

Follow the repository's build/dependency documentation. On a Linux host with its
build dependencies installed:

```sh
cmake -S . -B build-contributions -DENABLE_WALLET=OFF -DBUILD_GUI=OFF -DBUILD_TESTS=OFF
cmake --build build-contributions --target bitcoind -j4
git worktree add --detach ../knots-contribution-parent 58398baf33e588779685ead478e6397bb28ed3d6
cmake -S ../knots-contribution-parent -B ../knots-contribution-parent-build -DENABLE_WALLET=OFF -DBUILD_GUI=OFF -DBUILD_TESTS=OFF
cmake --build ../knots-contribution-parent-build --target bitcoind -j4
python3 test/functional/work_contributions/run.py \
  --bitcoind build-contributions/bin/bitcoind \
  --parent-bitcoind ../knots-contribution-parent-build/bin/bitcoind \
  --results ../contribution-results
```

Use an empty results directory. The suites create temporary regtest datadirs,
use loopback connections, and stop their nodes. They do not connect to public
peers. The endpoint is not available on other platforms; non-Linux code registers
no endpoint RPCs. The portable consensus portion still needs cross-platform CI.
No production-grade mining interface, public network setup or ASIC compatibility
is implied by these fixtures.
