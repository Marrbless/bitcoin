// Copyright (c) 2026 The experimental gateway-allocation contributors
// Distributed under the MIT software license, see the accompanying COPYING.
#ifndef BITCOIN_CONSENSUS_GATEWAY_ALLOCATION_H
#define BITCOIN_CONSENSUS_GATEWAY_ALLOCATION_H

#include <consensus/amount.h>
#include <primitives/transaction.h>
#include <pubkey.h>
#include <script/script.h>

#include <vector>

class BlockValidationState;

namespace Consensus {
// Experimental regtest-only allocation. These are block depths, not wall time.
static constexpr int GATEWAY_ALLOCATION_DEPTH{6480};
static constexpr int HASHER_ALLOCATION_DEPTH{52560};
static constexpr int GATEWAY_ALLOCATION_BPS{5000};

CScript GatewayAllocationScript(const CPubKey& key, int depth);
std::vector<CTxOut> GatewayAllocationOutputs(CAmount claimed, const CPubKey& gateway, const CPubKey& hasher);
} // namespace Consensus

#endif // BITCOIN_CONSENSUS_GATEWAY_ALLOCATION_H
