# Work-bound transaction contributions — draft specification 0.2

Status: research specification, 2026-09-25. Implemented research format v3; not an activation proposal or frozen standard.

## Objective and scope

Make operating one's own mining node economically preferable to delegating transaction selection, while allowing miners with their own nodes to cooperate for payout smoothing. Hardware owners mining to their own nodes, including owners of many machines, are not adversaries. Ordinary operational failures and voluntary delegation remain the operator's risk.

The enforceable primitive is narrower than the objective: a settling block may credit a work-bound contribution only if it contains the contribution's named transaction X and pays the committed recipients. This does not prove who chose X, who operates a node, or who owns the hardware. A delegated service can construct the same valid contribution and name a customer's keys. The economic objective remains a hypothesis to evaluate, not a property implied by consensus validation.

This proposal introduces no second chain, extra chainwork, identity registry, share-funding transaction, evidence signature, or private-pool payment enforcement. Transaction funding and signatures needed to spend rewards remain ordinary requirements.

## Source and version boundary

Research parent: luke-jr/bitcoin `4663b7b2a73585074cb4113aaf0846efad68f6d6`.
Submission base: bitcoinknots/bitcoin `58398baf33e588779685ead478e6397bb28ed3d6`
(`29.x-knots`). This patch consolidates N1–N9 and preserves the parent's BLAKE2b
algorithm and profiles. The N8 consensus codec and N9 in-node endpoint are
implemented. The endpoint serves profile 0; consensus tests cover all four profiles.

## Provisional control parameters

| Parameter | Control fixture |
| --- | ---: |
| Combined full/weak target multiplier M | 20 |
| Maximum credited weak contributions K | 19 |
| Nominal reward slots | 20, including block finder |
| Finder skim per credited contribution | floor(slot / 20) |
| Early allocation | 50% rounded down |
| Late allocation | Remaining amount |
| Early relative lock | 6,480 blocks |
| Late relative lock | 52,560 blocks |
| Reward basis | Actual subsidy plus actual fees |
| Eligibility | Exact parent of settling block |
| Unused allocations | Unclaimed; no reserve or carryover |

These are reproducible controls, not production recommendations. The earlier thresholds of under 10% unclaimed and at least 90% proportional payout were analyst screening assumptions, not project requirements. Minimize neither metric at the expense of the actual objective.

## Consensus rules represented by the current experiment

1. All inherited block, transaction, script, monetary and resource-limit checks remain necessary. The contribution rule is an additional check in block connection after computing actual fees. Genesis is not a contribution settlement block; the current check requires a parent.
2. At an active height, parse contribution evidence only from the settling block's coinbase. Ordinary transaction data is not contribution evidence. A block with no proofs remains possible and receives only the finder slot.
3. Each certificate contains a source header, compact coinbase-hash evidence, X's transaction ID, and compressed early/late public keys. Both public keys must be fully valid. The same person may control both; ownership is not tested.
4. Source parent equals settling parent. Source nBits equals the inherited next-work requirement evaluated for that source header. Source time exceeds parent median time past and is no later than settling time. Both header modes require nVersion >= 4. At a BLAKE2b height the header must use the inherited v2 serialization, carry parent height+1, and have no reserved 0xc0 flag bits; at other heights it must use the legacy serialization.
5. For valid decoded target T, source hash h must satisfy T < h <= min(20T, 2^256 - 1). A full block solution is not also a paid weak contribution. Weak contributions do not add to chainwork or alter fork choice.
6. Within a settling block, reject duplicate source-header hashes. Distinct proofs may commit the same X and recipients. There is no enforced transaction diversity or operator identity.
7. Reconstruct the committed source coinbase leaf and fold its leftmost Merkle branch; the resulting root must equal the source header's root. The omitted source block is not supplied or validated. A valid certificate is contextual work bound to terms, not proof that its entire source was a valid block or that X appeared in that source.
8. Each credited X must appear among the settling block's non-coinbase transaction IDs. Ordinary validity ensures its inputs, signatures and dependencies work in that block. Conflicting Xs cannot both be settled. No global arrival order, oldest-first order, mandatory inclusion, or automatic punishment for omission exists.
9. Let B = subsidy + actual fees, S = floor(B/20), k = floor(S/20), and n = number of credited proofs. Finder allocation is S + n*k. Each proof receives S-k. Total authorized positive outputs are (n+1)*S. B-(n+1)*S is unclaimed, including division remainder. No recipient can take unused slots without supplying valid eligible work.
10. Split each recipient allocation A separately: early=floor(A/2), late=A-early. Pay using P2WSH scripts whose witness scripts are `<depth> OP_CHECKSEQUENCEVERIFY OP_DROP <compressed pubkey> OP_CHECKSIG`. Omit zero-valued reward outputs. Sum by script for validation, so identical recipients' scripts can be aggregated without changing per-allocation rounding. Current validation requires exact expected positive sums; it does not permit arbitrary voluntary underclaim of assigned outputs. That exactness is a restriction relative to the parent and must be explicit in review.
11. Current finder metadata is exactly one canonical zero-valued OP_RETURN push of `GWA1 || early_pubkey || late_pubkey` (70 payload bytes). Other zero-valued coinbase outputs must begin with OP_RETURN. Existing witness commitments remain required where applicable.
12. Spending rewards must satisfy BOTH inherited coinbase restrictions and the new output script. These locks do not override an inherited maturity rule. Block counts are normative; 45 days and one year are only nominal descriptions at a ten-minute cadence.
13. Eligibility is branch-relative. A proof expires on a different parent. If a reorg restores its exact parent it can be eligible again, with the orphaned payout removed by ordinary UTXO rollback. There is no permanent paid-share database.

## Implemented compact encoding (v3)

All integers below are unsigned little-endian except SHA state words. The layout is:

| Field | Bytes |
| --- | ---: |
| Certificate version, value 3 | 1 |
| Inherited source header (legacy / BLAKE2b v2) | 80 / 164 |
| Non-witness source coinbase length (106..300000) | 4 |
| SHA256 midstate, eight big-endian words | 32 |
| Branch count d, 0..12 | 1 |
| Leftmost Merkle branch | 32*d |
| X, raw uint256 wire order | 32 |
| Compressed early key | 33 |
| Compressed late key | 33 |
| Source coinbase locktime | 4 |

Certificate size is 220+32*d for legacy and 304+32*d for BLAKE2b, maximum
688 bytes. Reject trailing bytes. BLAKE2b source transaction count is 1..4096
and d must equal ceil(log2(count)). This checks structure, not the omitted
transactions. Candidate construction accepts at most 4095 non-coinbase
transactions and refreshes m_txcount after assembling them.

The source coinbase ends with two zero-valued outputs: an OP_RETURN-only script,
then OP_RETURN pushing `N8C0 || 44 zero bytes || terms_hash`.
Terms_hash = double-SHA256(`N8C0 || X || early_key || late_key`).
The scripts are 1 and 83 bytes; their serialized outputs total 102 bytes.
The known 63 bytes preceding terms_hash are:
`00 01 6a || 8 zero bytes || 53 6a 4c 50 || N8C0 || 44 zero bytes`.

Let rem=(source_length-36) mod 64 and cut=source_length-36-rem. Resume SHA256
at the supplied aligned state with byte count cut, append the final rem bytes
of that known prefix, terms_hash and locktime; finalize and SHA256 again.
Fold the resulting leaf with the leftmost branch and compare with the header
Merkle root. At cut=0 require the standard SHA initial state. For nonzero cut,
the omitted prefix is not validated or proven to exist. This is a contextual
work commitment, not a proof of source-block validity. Independent cryptographic
review of arbitrary-midstate binding remains required.

Settlement evidence body:
`count:u8 || (certificate_length:u16LE || certificate)*count`, count 1..19.
There is no additional inner magic. Maximum body size is **13,111 bytes**.
Split the body into consecutive chunks of at most 72 bytes. Each chunk occupies
a canonical zero-valued OP_RETURN output carrying
`N8PF || index:u16LE || total:u16LE || chunk`.
Maximum payload is 80 bytes, maximum script is **83 bytes**, maximum count is
183 fragments. Non-final chunks must contain 72 bytes. Require one contiguous
ordered run beginning at index zero, a consistent total and complete body;
reject gaps, repeats, noncanonical pushes, excess data and N2P1/N5P0 carriers.
Zero proofs means no evidence carrier. The active contribution rule explicitly
enforces the 83-byte bound for every coinbase OP_RETURN, even outside RDTS.
The bound is per output script, not per certificate or whole coinbase.

## Native mining and relay boundary

The node constructs the candidate, source commitment, certificates and subsequent
settlement. The ASIC/client submits nonce fields. The authenticated operator RPC
configures local transactions or uses local mempool selection. See ENDPOINT.md
for the inherited Sia-style BLAKE2b profile-0 wire mapping and its pinned source.
Ordinary submissions receive no consensus contribution allocation. Full blocks
are classified before ordinary/strong accounting caps; valid work cannot be
rejected solely because those budgets are exhausted.

The endpoint is private-regtest, loopback-only, four clients and two jobs/client,
with bounded relay to one configured peer. It is not the DATUM pool protocol and
does not inherit DATUM anti-withholding protections. SHA/BLAKE mode is selected
at startup; restart at a transition. Hardware compatibility, public binding,
peer selection, sustained multi-operator operation, portability and integration
with the normal test runner remain review/implementation work. Relay is best-effort.

## Soft-fork argument and deployment limits

Intended relation: every active-rule accepted block is also valid under the
unmodified BLAKE2b parent. The proposal restricts coinbase outputs and rewards,
uses existing P2WSH/CSV, grants no new spend permission, preserves fork choice
and stays within inherited subsidy+fees and resource limits. Fragmentation
satisfies the inherited RDTS bound without exempting proposal outputs.
Parent acceptance of tested settlements supports this relation but is not an
exhaustive proof over all blocks or deployment transitions.

Inherited maturity remains in force. The baseline constant is 100 blocks.
The reviewed parent also has a temporary long-maturity rule: mainnet-config
start/enforcement 973440 and release 979920, giving a 6480-block long depth
during its enforcement interval for the selected coinbase cohort. This is not
a permanent global 45-day maturity. New CSV scripts cannot bypass that rule.
The effective spend height must satisfy both inherited maturity and CSV.

The new activation height defaults to disabled. Only regtest can override it
with `-testgatewayallocationheight`; use a fresh chainstate. No production
activation, isolated public-testnet identity or migration is supplied. Reindex,
assumevalid, activation/reorg boundaries, inherited maturity overlaps and
resource/DoS behavior need independent review before deployment. This is a
soft-fork candidate relative to the BLAKE2b base, not a claim that changing
SHA256d Bitcoin to BLAKE2b is a soft fork.

## Economic statement permitted by this specification

Excluding a compatible foreign proof from an otherwise empty slot loses the finder its skim. When slots are full, replacement with an already-earned own-group proof can increase that group's proceeds. Replacing work requires valid work, but it need not mean purchasing new machines or newly generating a proof if eligible work already exists. Net inclusion cost also depends on fees, transaction dependencies, size and conflicts.

Directly naming a miner's keys can eliminate custody of that allocation. It does not necessarily eliminate the service's transaction control. An external service can return both allocations on the same schedule, retain a fee, or offer early payment from capital. Locks affect every credited output; the protocol does not classify local and remote ownership. Thus a universal strict own-node advantage is not currently established by any split or maturity parameter.

Conditional comparison, at matched hashpower, group size and inclusion access: net own-node value = reward present value minus own-node operating cost. Net delegated value = same-schedule rebated reward value minus service fees and any financing cost borne by the miner, adjusted for independently modeled custody/default exposure. A result depends on measured or explicitly assumed costs. Transaction-control benefits should be reported separately unless a valuation is explicitly supplied.

## Completion criteria

Independently review and freeze the implemented BLAKE encoding and source-proof contract; extend the native port and cross-node compatibility evidence; demonstrate bounded resource behavior; reproduce the economic comparison including full rebates; perform independent consensus/cryptographic review; publish the white paper and implementation with limitations. A testnet success demonstrates operation under the tested conditions, not real-money adoption or guaranteed censorship resistance.
