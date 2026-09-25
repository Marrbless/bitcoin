// Experimental regtest mining contributions. Distributed under the MIT license.
// A proof certifies contextual work bound to X and recipients, not source validity.
#include <consensus/node_contribution.h>
#include <arith_uint256.h>
#include <chain.h>
#include <consensus/params.h>
#include <consensus/consensus.h>
#include <consensus/validation.h>
#include <hash.h>
#include <pow.h>
#include <streams.h>
#include <algorithm>
#include <map>
#include <set>
#include <stdexcept>

namespace Consensus {
namespace {
using Bytes=std::vector<unsigned char>;
struct Proof { CBlockHeader header; uint256 x; CPubKey early,late; };
Bytes Raw(const DataStream& ds) {
    Bytes result(ds.size());
    std::transform(ds.begin(),ds.end(),result.begin(),[](std::byte b){return std::to_integer<unsigned char>(b);});
    return result;
}
bool Prefix(const Bytes& b,const char* tag) { return b.size()>=4 && std::equal(b.begin(),b.begin()+4,tag); }
bool Data(const CScript& script,Bytes& data) {
    auto pc=script.begin();opcodetype op;
    return script.GetOp(pc,op) && op==OP_RETURN && script.GetOp(pc,op,data);
}
Proof Decode(const Bytes& raw)
{
    if (raw.size() != NODE_CONTRIBUTION_MAX_BYTES) throw std::runtime_error("proof-size");
    DataStream ds{raw};
    Proof p;
    uint8_t version;
    ds >> version;
    if (version != 4) throw std::runtime_error("proof-version");
    ds >> p.header;
    if (!p.header.m_header_v2) throw std::runtime_error("proof-header-type");
    ds >> p.x;
    Bytes early(33), late(33);
    ds.read(MakeWritableByteSpan(early));
    ds.read(MakeWritableByteSpan(late));
    p.early = CPubKey{early};
    p.late = CPubKey{late};
    if (!ds.empty() || !p.early.IsCompressed() || !p.early.IsFullyValid() ||
        !p.late.IsCompressed() || !p.late.IsFullyValid()) {
        throw std::runtime_error("proof-encoding");
    }
    if (p.header.m_mm_rhs != NodeContributionCommitment(p.x, p.early, p.late)) {
        throw std::runtime_error("proof-commitment");
    }
    return p;
}
void Credit(std::map<CScript,CAmount>& expected,CAmount value,const CPubKey& early,const CPubKey& late) {
    for(const auto& o:GatewayAllocationOutputs(value,early,late))if(o.nValue)expected[o.scriptPubKey]+=o.nValue;
}
bool FinderKeys(const CTransaction& cb,CPubKey& early,CPubKey& late) {
    bool found=false;
    for(const auto& o:cb.vout){Bytes data;
        if(!Data(o.scriptPubKey,data)||!Prefix(data,"GWA1"))continue;
        if(found||data.size()!=70||o.nValue||o.scriptPubKey!=(CScript{}<<OP_RETURN<<data))return false;
        early.Set(data.begin()+4,data.begin()+37);late.Set(data.begin()+37,data.end());found=true;
    }
    return found&&early.IsCompressed()&&early.IsFullyValid()&&late.IsCompressed()&&late.IsFullyValid();
}
constexpr size_t FRAGMENT_DATA_BYTES{72};
constexpr size_t MAX_EVIDENCE_BYTES{1+NODE_CONTRIBUTION_CAP*NODE_CONTRIBUTION_MAX_BYTES};
constexpr size_t MAX_FRAGMENTS{(MAX_EVIDENCE_BYTES+FRAGMENT_DATA_BYTES-1)/FRAGMENT_DATA_BYTES};
std::vector<Bytes> ReadProofs(const CTransaction& cb) {
    Bytes evidence;uint16_t total=0,next=0;bool ended=false;
    for(const auto& o:cb.vout){Bytes data;
        const bool parsed=Data(o.scriptPubKey,data);
        if(parsed&&(Prefix(data,"N2P1")||Prefix(data,"N5P0")||Prefix(data,"N8PF")))throw std::runtime_error("legacy-proof-format");
        if(!parsed||!Prefix(data,"N4PF")){if(next)ended=true;continue;}
        if(ended||o.nValue||data.size()<9||data.size()>80||o.scriptPubKey!=(CScript{}<<OP_RETURN<<data))throw std::runtime_error("proof-fragment");
        DataStream ds{Span{data}.subspan(4)};uint16_t index,count;ds>>index>>count;
        if(!count||count>MAX_FRAGMENTS||index!=next||index>=count||(next&&count!=total))throw std::runtime_error("proof-fragment-order");
        total=count;
        if(index+1<count&&ds.size()!=FRAGMENT_DATA_BYTES)throw std::runtime_error("proof-fragment-size");
        const auto part=Raw(ds);evidence.insert(evidence.end(),part.begin(),part.end());++next;
        if(evidence.size()>MAX_EVIDENCE_BYTES)throw std::runtime_error("proof-container-size");
    }
    if(!next)return {};
    if(next!=total)throw std::runtime_error("proof-fragment-missing");
    DataStream ds{evidence};uint8_t count;ds>>count;
    if(!count||count>NODE_CONTRIBUTION_CAP)throw std::runtime_error("proof-count");
    if (ds.size() != count * NODE_CONTRIBUTION_MAX_BYTES) throw std::runtime_error("proof-container-size");
    std::vector<Bytes> result;
    for (uint8_t i = 0; i < count; ++i) {
        Bytes proof(NODE_CONTRIBUTION_MAX_BYTES);
        ds.read(MakeWritableByteSpan(proof));
        result.push_back(std::move(proof));
    }
    return result;
}
}
uint256 NodeContributionCommitment(const uint256& x, const CPubKey& early, const CPubKey& late)
{
    auto hash = TaggedHash("Bitcoin mining contribution v4");
    hash << x;
    hash.write(MakeByteSpan(early));
    hash.write(MakeByteSpan(late));
    return hash.GetSHA256();
}

std::vector<unsigned char> EncodeNodeContribution(const CBlockHeader& header, const uint256& x,
                                                 const CPubKey& early, const CPubKey& late)
{
    if (!header.m_header_v2 || header.m_mm_rhs != NodeContributionCommitment(x, early, late)) {
        throw std::runtime_error("proof-commitment");
    }
    DataStream ds;
    ds << uint8_t{4} << header << x;
    ds.write(MakeByteSpan(early));
    ds.write(MakeByteSpan(late));
    const auto result = Raw(ds);
    Decode(result); // Keep encoder and consensus encoding checks identical.
    return result;
}
std::vector<CTxOut> NodeContributionOutputs(CAmount budget,const CPubKey& early,const CPubKey& late,const std::vector<Bytes>& proofs) {
    if(!MoneyRange(budget)||proofs.size()>NODE_CONTRIBUTION_CAP)throw std::runtime_error("contribution-budget");
    const CAmount slot=budget/20,skim=slot/20;auto outputs=GatewayAllocationOutputs(slot+skim*proofs.size(),early,late);
    DataStream evidence;evidence<<uint8_t(proofs.size());
    for(const auto& raw:proofs){const auto p=Decode(raw);
        for(const auto& o:GatewayAllocationOutputs(slot-skim,p.early,p.late))if(o.nValue)outputs.push_back(o);
        evidence.write(MakeByteSpan(raw));
    }
    if(!proofs.empty()){
        const auto raw=Raw(evidence);const uint16_t count=(raw.size()+FRAGMENT_DATA_BYTES-1)/FRAGMENT_DATA_BYTES;
        for(uint16_t i=0;i<count;++i){DataStream fragment;fragment<<i<<count;Bytes data{'N','4','P','F'};
            const auto prefix=Raw(fragment);data.insert(data.end(),prefix.begin(),prefix.end());
            const size_t start=i*FRAGMENT_DATA_BYTES,end=std::min(start+FRAGMENT_DATA_BYTES,raw.size());
            data.insert(data.end(),raw.begin()+start,raw.begin()+end);outputs.emplace_back(0,CScript{}<<OP_RETURN<<data);
        }
    }
    return outputs;
}
bool CheckNodeContributions(const CBlock& block,const CBlockIndex* parent,const Params& params,CAmount budget,BlockValidationState& state) {
    auto fail=[&](const char* reason){return state.Invalid(BlockValidationResult::BLOCK_CONSENSUS,reason);};
    if(!parent)return fail("n8-missing-parent");
    // This bound is part of our rule even outside the inherited RDTS epoch.
    for(const auto& o:block.vtx[0]->vout)if(!o.scriptPubKey.empty()&&o.scriptPubKey.front()==OP_RETURN&&o.scriptPubKey.size()>MAX_OUTPUT_DATA_SIZE)return fail("n8-output-size");
    CPubKey early,late;if(!FinderKeys(*block.vtx[0],early,late))return fail("n5-finder-keys");
    std::vector<Bytes> proofs;
    // Only coinbase evidence is credited; ordinary transaction data is not parsed as evidence.
    try{proofs=ReadProofs(*block.vtx[0]);
    }catch(const std::exception&){return fail("n5-proof-encoding");}
    const CAmount slot=budget/20,skim=slot/20;std::map<CScript,CAmount> expected;Credit(expected,slot+skim*proofs.size(),early,late);
    std::set<uint256> ids,txids;for(size_t i=1;i<block.vtx.size();++i)txids.insert(block.vtx[i]->GetHash().ToUint256());
    for(const auto& raw:proofs){Proof p;try{p=Decode(raw);}catch(const std::exception&){return fail("n5-proof-encoding");}
        if(p.header.m_header_v2!=params.IsBlake2bHeight(parent->nHeight+1))return fail("n8-share-header-type");
        if(p.header.m_header_v2&&(p.header.m_height!=parent->nHeight+1||(p.header.m_flags&0xc0)))return fail("n8-share-header-context");
        if(p.header.nVersion<4)return fail("n5-share-version");
        if(p.header.hashPrevBlock!=block.hashPrevBlock)return fail("n5-share-parent");
        if(p.header.nBits!=GetNextWorkRequired(parent,&p.header,params))return fail("n5-share-bits");
        if(p.header.GetBlockTime()<=parent->GetMedianTimePast()||p.header.nTime>block.nTime)return fail("n5-share-time");
        bool negative,overflow;arith_uint256 target;target.SetCompact(p.header.nBits,&negative,&overflow);
        if(negative||overflow||target==0)return fail("n5-share-target");
        const auto max=~arith_uint256{};const auto weak=target>max/20?max:target*20;
        const auto id=p.header.GetHash();const auto work=UintToArith256(id);
        if(work<=target||work>weak)return fail("n5-share-work");
        if(!ids.insert(id).second)return fail("n5-share-duplicate");
        if(!txids.count(p.x))return fail("n5-missing-x");
        Credit(expected,slot-skim,p.early,p.late);
    }
    std::map<CScript,CAmount> actual;
    for(const auto& o:block.vtx[0]->vout){if(o.nValue)actual[o.scriptPubKey]+=o.nValue;
        else if(o.scriptPubKey.empty()||o.scriptPubKey.front()!=OP_RETURN)return fail("n5-payout-script");}
    if(actual!=expected)return fail("n5-payout-amount");
    return true;
}
}
