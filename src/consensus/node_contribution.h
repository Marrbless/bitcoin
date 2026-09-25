// Experimental private-regtest N8. Distributed under the MIT license.
#ifndef BITCOIN_CONSENSUS_NODE_CONTRIBUTION_H
#define BITCOIN_CONSENSUS_NODE_CONTRIBUTION_H
#include <consensus/gateway_allocation.h>
#include <primitives/block.h>
class CBlockIndex;
namespace Consensus {
struct Params;
static constexpr size_t NODE_CONTRIBUTION_CAP{19};
static constexpr size_t NODE_CONTRIBUTION_MAX_BYTES{688};
// v3 work-bound certificate (inherited legacy or BLAKE2b header); not evidence of validity of an omitted source.
std::vector<unsigned char> EncodeNodeContribution(const CBlock& block, const uint256& x,
                                                 const CPubKey& early, const CPubKey& late);
CScript NodeContributionCommitment(const uint256& x, const CPubKey& early, const CPubKey& late);
std::vector<CTxOut> NodeContributionOutputs(CAmount budget, const CPubKey& early, const CPubKey& late,
                                          const std::vector<std::vector<unsigned char>>& proofs);
bool CheckNodeContributions(const CBlock& block, const CBlockIndex* parent, const Params& params,
                            CAmount budget, BlockValidationState& state);
}
#endif
