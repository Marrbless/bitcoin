// Experimental regtest mining contributions. Distributed under the MIT license.
#ifndef BITCOIN_CONSENSUS_NODE_CONTRIBUTION_H
#define BITCOIN_CONSENSUS_NODE_CONTRIBUTION_H
#include <consensus/gateway_allocation.h>
#include <primitives/block.h>
class CBlockIndex;
namespace Consensus {
struct Params;
static constexpr size_t NODE_CONTRIBUTION_CAP{19};
static constexpr size_t NODE_CONTRIBUTION_MAX_BYTES{263};
// Fixed v4 certificate: BLAKE2b header, X and reward keys. Source validity is not claimed.
std::vector<unsigned char> EncodeNodeContribution(const CBlockHeader& header, const uint256& x,
                                                 const CPubKey& early, const CPubKey& late);
uint256 NodeContributionCommitment(const uint256& x, const CPubKey& early, const CPubKey& late);
std::vector<CTxOut> NodeContributionOutputs(CAmount budget, const CPubKey& early, const CPubKey& late,
                                          const std::vector<std::vector<unsigned char>>& proofs);
bool CheckNodeContributions(const CBlock& block, const CBlockIndex* parent, const Params& params,
                            CAmount budget, BlockValidationState& state);
}
#endif
