// Copyright (c) 2026 The experimental gateway-allocation contributors
// Distributed under the MIT software license, see the accompanying COPYING.
#include <consensus/gateway_allocation.h>

#include <crypto/sha256.h>

#include <algorithm>
#include <array>
#include <cassert>

namespace Consensus {
namespace {
constexpr std::array<unsigned char, 4> MAGIC{'G', 'W', 'A', '1'};

CAmount EarlyAmount(CAmount amount)
{
    // Avoid overflowing CAmount even when all existing coins become block fees.
    return (amount / 10000) * GATEWAY_ALLOCATION_BPS
        + (amount % 10000) * GATEWAY_ALLOCATION_BPS / 10000;
}

CScript Commitment(const CPubKey& gateway, const CPubKey& hasher)
{
    std::vector<unsigned char> data{MAGIC.begin(), MAGIC.end()};
    data.insert(data.end(), gateway.begin(), gateway.end());
    data.insert(data.end(), hasher.begin(), hasher.end());
    return CScript{} << OP_RETURN << data;
}
} // namespace

CScript GatewayAllocationScript(const CPubKey& key, int depth)
{
    const CScript redeem{CScript{} << depth << OP_CHECKSEQUENCEVERIFY << OP_DROP
        << std::vector<unsigned char>(key.begin(), key.end()) << OP_CHECKSIG};
    std::array<unsigned char, 32> hash;
    CSHA256{}.Write(redeem.data(), redeem.size()).Finalize(hash.data());
    return CScript{} << OP_0 << std::vector<unsigned char>(hash.begin(), hash.end());
}

std::vector<CTxOut> GatewayAllocationOutputs(CAmount claimed, const CPubKey& gateway, const CPubKey& hasher)
{
    assert(MoneyRange(claimed));
    assert(gateway.IsCompressed() && hasher.IsCompressed());
    const CAmount early{EarlyAmount(claimed)};
    const CAmount late{claimed - early};
    std::vector<CTxOut> out;
    if (early) out.emplace_back(early, GatewayAllocationScript(gateway, GATEWAY_ALLOCATION_DEPTH));
    if (late) out.emplace_back(late, GatewayAllocationScript(hasher, HASHER_ALLOCATION_DEPTH));
    out.emplace_back(0, Commitment(gateway, hasher));
    return out;
}

} // namespace Consensus
