# N9: in-node BLAKE2b Sia-style mining endpoint

Native C++ continuation of N8, pinned to the same Knots source. The endpoint now
serves profile-0 BLAKE2b work using the established Sia-style Stratum wire layout.
No external DATUM process is needed in the demonstrated path. This does not
implement the DATUM pool protocol or claim its anti-withholding protections.

## Wire contract

The endpoint is still private-regtest, loopback-only, with four clients, two
retained jobs per client and the existing bounded one-peer contribution relay.
Start it with the existing startminingendpoint operator RPC. It selects the
current candidate's PoW mode at startup. A transition between SHA256d and BLAKE2b
requires restarting the endpoint; mixing hardware modes on one listener is not
supported. SHA256d's prior 4-byte extranonce2 layout is preserved.

For BLAKE2b, subscribe returns four bytes of extranonce1 and an eight-byte
extranonce2 size. Notify uses the ordinary nine-element array:

- job ID;
- 32-byte tagged hidden previous-block value with first six bytes zero;
- coinb1 = three zero bytes + 32-byte inherited h2 commitment + four zero bytes;
- empty coinb2;
- empty merkle array;
- version;
- nBits;
- eight raw little-endian time-word bytes (initially zero low word and the
  template timestamp as high word);
- clean flag.

The work root is BLAKE2b-256 of one zero byte + coinb1 + extranonce1 + extranonce2.
The ASIC input is hidden previous value (32) + nonce words (8) + time words (8)
+ work root (32), 80 bytes total. Work hash byte order matches inherited GetHash.
The node alone retains the actual coinbase, transactions and header commitment.

Submit remains worker, job ID, extranonce2, time, nonce. Extranonce2 is exactly
16 hex digits. Time and nonce each accept either 16 raw hex digits encoding two
little-endian uint32 words, or an eight-digit numeric uint32 with high word zero.
Hex and length checks precede conversion. Nonce words map to nNonce/m_nonce2;
time words map to m_time_offset/m_nonce3. Header extranonce is four zero bytes +
assigned extranonce1 + submitted extranonce2. With the time-offset flag disabled,
these are PoW grinding words and do not change consensus nTime.

This first hardware dialect uses profile 0, zero XOR key/mask and fixed consensus
time. It rejects unsupported generated profiles instead of silently translating
them. Consensus still supports all four inherited profiles; their N8 tests were
rerun after the hashing-helper refactor. Fixed easy-regtest share difficulty is
retained, with no production vardiff or mining-profitability claim. The job nBits
is the block target, not DATUM's synthetic hidden block-target mechanism.

## Implementation boundary

Admission policy limits new contribution validation attempts to 32 per one
second interval across all connections. Retries of already retained proofs
are acknowledged without repeating candidate validation. Repeated authorization
on one connection is rejected without regenerating a job. These are local
resource policies, not consensus limits. Attackers can exhaust this shared
budget, and the policy does not establish public network fairness or safety.
Full block submissions do not consume the contribution budget.

The N9 endpoint increment changed three C++ files relative to N8 (this PR also contains the earlier consensus work):

- primitives/block.h / block.cpp expose the existing h2 calculation as
  GetMiningCommitment and call it from GetHash and the endpoint. The calculation
  and inherited final hash remain unchanged.
- node/native_stratum.cpp builds and reconstructs Sia work, retains SHA work,
  advertises blake2b support to local template selection, and reads the complete
  source header when identifying relayed certificates.

No contribution consensus, reward, maturity, certificate encoding, 83-byte
output bound, fork-choice or network parameter changed. N8 remains preserved.

Wire reference: CONVOYMining/datum_gateway commit
b9ea7dc3eb91352565ab487ec55ed6ee5964a440, src/datum_stratum.c and src/datum_pow.c.
The reference is not a runtime dependency. This is a wire-format implementation, not a full gateway
port. The primary source can be inspected at:
https://github.com/CONVOYMining/datum_gateway/tree/b9ea7dc3eb91352565ab487ec55ed6ee5964a440

## Reproduce

See README.md and test/functional/work_contributions/README.md in this repository.
The standalone runner builds on the repository's own functional test framework;
no nested research archives or external gateway process are required.

## What the tests establish

A socket-only Python client computes work from notifications and submits only
nonce fields. Two native nodes produce and exchange contributions; a block found
through the endpoint settles both Xs. The unmodified parent validates the chain.
Tests include 8-/16-digit time/nonce fields, extended nonce words, commitment
agreement, replay/mutation rejection, actual 19-proof saturation, 4,096 ordinary
submissions and overflow, full-block priority, expiry and node mempool selection.
The 127 N8 native and 10 SHA/boundary checks also pass on this binary.

This is not a physical ASIC test or a public testnet release. LAN binding,
operator configuration, sustained multi-operator network trials, robust peer
selection/dissemination and deployment review remain. The endpoint is Linux-only;
on other platforms it registers no RPCs. Real hardware must verify
firmware treatment of job fields and difficulty; do not advertise universal ASIC
compatibility based on a software miner. The proposed economic advantage of
self-operated nodes remains a separate, unproven claim.
