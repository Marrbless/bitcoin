// Experimental private-regtest N8. Distributed under the MIT license.
// A proof certifies contextual work bound to X and recipients, not source validity.
#include <consensus/node_contribution.h>
#include <arith_uint256.h>
#include <chain.h>
#include <consensus/params.h>
#include <consensus/consensus.h>
#include <consensus/validation.h>
#include <crypto/sha256.h>
#include <hash.h>
#include <pow.h>
#include <streams.h>
#include <algorithm>
#include <array>
#include <map>
#include <set>
#include <stdexcept>

namespace Consensus {
namespace {
using Bytes=std::vector<unsigned char>;
constexpr uint32_t MAX_SOURCE_BYTES{300000};
struct Proof { CBlockHeader header; uint256 leaf,x; CPubKey early,late; std::vector<uint256> branch; };
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
uint256 Terms(const uint256& x,const CPubKey& early,const CPubKey& late) {
    Bytes t{'N','8','C','0'};t.insert(t.end(),x.begin(),x.end());
    t.insert(t.end(),early.begin(),early.end());t.insert(t.end(),late.begin(),late.end());return Hash(t);
}
Bytes KnownPrefix() {
    // Last three bytes of the empty OP_RETURN output, then the 60-byte
    // prefix of the final output. Both output scripts fit the 83-byte limit.
    Bytes p{0,1,OP_RETURN};p.resize(11,0);p.insert(p.end(),{83,OP_RETURN,OP_PUSHDATA1,80,'N','8','C','0'});p.resize(63,0);return p;
}
Proof Decode(const Bytes& raw) {
    if(raw.size()>NODE_CONTRIBUTION_MAX_BYTES)throw std::runtime_error("proof-size");
    DataStream ds{raw};Proof p;uint8_t version,count;uint32_t size,locktime;std::array<unsigned char,32> state;
    ds>>version;if(version!=3)throw std::runtime_error("proof-version");
    ds>>p.header;
    ds>>size;if(size<106 || size>MAX_SOURCE_BYTES)throw std::runtime_error("source-length");
    ds.read(MakeWritableByteSpan(state));ds>>count;if(count>12)throw std::runtime_error("branch-size");
    if(p.header.m_header_v2) {
        if(!p.header.m_txcount || p.header.m_txcount>4096)throw std::runtime_error("source-txcount");
        unsigned depth=0;for(unsigned n=p.header.m_txcount-1;n;n>>=1)++depth;
        if(count!=depth)throw std::runtime_error("source-branch-depth");
    }
    for(uint8_t i=0;i<count;++i){uint256 h;ds>>h;p.branch.push_back(h);}
    ds>>p.x;Bytes g(33),h(33);ds.read(MakeWritableByteSpan(g));ds.read(MakeWritableByteSpan(h));ds>>locktime;
    p.early=CPubKey{g};p.late=CPubKey{h};
    if(!ds.empty() || !p.early.IsCompressed() || !p.early.IsFullyValid() || !p.late.IsCompressed() || !p.late.IsFullyValid())throw std::runtime_error("proof-encoding");
    const uint32_t remainder=(size-36)%64,cut=size-36-remainder;
    CSHA256 sha;std::array<unsigned char,32> initial;
    if(!sha.GetMidstateAligned(initial.data()))throw std::runtime_error("initial-state");
    if(cut==0 && state!=initial)throw std::runtime_error("initial-state");
    if(!sha.SetMidstateAligned(state.data(),cut))throw std::runtime_error("state-alignment");
    const auto prefix=KnownPrefix();const auto digest=Terms(p.x,p.early,p.late);
    DataStream tail;tail.write(MakeByteSpan(prefix).last(remainder));tail<<digest<<locktime;
    const auto bytes=Raw(tail);std::array<unsigned char,32> first;
    sha.Write(bytes.data(),bytes.size()).Finalize(first.data());
    CSHA256{}.Write(first.data(),first.size()).Finalize(p.leaf.begin());
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
constexpr size_t MAX_EVIDENCE_BYTES{1+NODE_CONTRIBUTION_CAP*(2+NODE_CONTRIBUTION_MAX_BYTES)};
constexpr size_t MAX_FRAGMENTS{(MAX_EVIDENCE_BYTES+FRAGMENT_DATA_BYTES-1)/FRAGMENT_DATA_BYTES};
std::vector<Bytes> ReadProofs(const CTransaction& cb) {
    Bytes evidence;uint16_t total=0,next=0;bool ended=false;
    for(const auto& o:cb.vout){Bytes data;
        const bool parsed=Data(o.scriptPubKey,data);
        if(parsed&&(Prefix(data,"N2P1")||Prefix(data,"N5P0")))throw std::runtime_error("legacy-proof-format");
        if(!parsed||!Prefix(data,"N8PF")){if(next)ended=true;continue;}
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
    std::vector<Bytes> result;
    for(uint8_t i=0;i<count;++i){uint16_t len;ds>>len;
        if(!len||len>NODE_CONTRIBUTION_MAX_BYTES||len>ds.size())throw std::runtime_error("proof-length");
        Bytes proof(len);ds.read(MakeWritableByteSpan(proof));result.push_back(std::move(proof));
    }
    if(!ds.empty())throw std::runtime_error("proof-trailing");
    return result;
}
}
CScript NodeContributionCommitment(const uint256& x,const CPubKey& early,const CPubKey& late) {
    Bytes data{'N','8','C','0'};data.resize(48,0);const auto h=Terms(x,early,late);data.insert(data.end(),h.begin(),h.end());
    return CScript{}<<OP_RETURN<<data;
}
std::vector<unsigned char> EncodeNodeContribution(const CBlock& block,const uint256& x,const CPubKey& early,const CPubKey& late) {
    if(block.vtx.empty())throw std::runtime_error("proof-source");
    const auto& cb=*block.vtx[0];
    if(cb.vout.size()<2||cb.vout[cb.vout.size()-2].nValue||cb.vout[cb.vout.size()-2].scriptPubKey!=(CScript{}<<OP_RETURN)||cb.vout.back().nValue||cb.vout.back().scriptPubKey!=NodeContributionCommitment(x,early,late))throw std::runtime_error("proof-ending");
    DataStream source;source<<TX_NO_WITNESS(cb);const auto raw=Raw(source);
    if(raw.size()<106||raw.size()>MAX_SOURCE_BYTES)throw std::runtime_error("source-length");
    const size_t cut=(raw.size()-36)/64*64;std::array<unsigned char,32> state;
    if(!CSHA256{}.Write(raw.data(),cut).GetMidstateAligned(state.data()))throw std::runtime_error("state-alignment");
    std::vector<uint256> hashes,branch;for(const auto& tx:block.vtx)hashes.push_back(tx->GetHash().ToUint256());
    while(hashes.size()>1){if(hashes.size()%2)hashes.push_back(hashes.back());branch.push_back(hashes[1]);
        std::vector<uint256> next;for(size_t i=0;i<hashes.size();i+=2)next.push_back(Hash(hashes[i],hashes[i+1]));hashes=std::move(next);}
    if(block.m_header_v2&&block.m_txcount!=block.vtx.size())throw std::runtime_error("source-txcount");
    if(branch.size()>12)throw std::runtime_error("branch-size");
    DataStream ds;ds<<uint8_t{3}<<block.GetBlockHeader()<<static_cast<uint32_t>(raw.size());ds.write(MakeByteSpan(state));
    ds<<static_cast<uint8_t>(branch.size());for(const auto& h:branch)ds<<h;
    ds<<x;ds.write(MakeByteSpan(early));ds.write(MakeByteSpan(late));ds<<cb.nLockTime;
    const auto result=Raw(ds);if(result.size()>NODE_CONTRIBUTION_MAX_BYTES)throw std::runtime_error("proof-size");return result;
}
std::vector<CTxOut> NodeContributionOutputs(CAmount budget,const CPubKey& early,const CPubKey& late,const std::vector<Bytes>& proofs) {
    if(!MoneyRange(budget)||proofs.size()>NODE_CONTRIBUTION_CAP)throw std::runtime_error("contribution-budget");
    const CAmount slot=budget/20,skim=slot/20;auto outputs=GatewayAllocationOutputs(slot+skim*proofs.size(),early,late);
    DataStream evidence;evidence<<uint8_t(proofs.size());
    for(const auto& raw:proofs){const auto p=Decode(raw);
        for(const auto& o:GatewayAllocationOutputs(slot-skim,p.early,p.late))if(o.nValue)outputs.push_back(o);
        evidence<<static_cast<uint16_t>(raw.size());evidence.write(MakeByteSpan(raw));
    }
    if(!proofs.empty()){
        const auto raw=Raw(evidence);const uint16_t count=(raw.size()+FRAGMENT_DATA_BYTES-1)/FRAGMENT_DATA_BYTES;
        for(uint16_t i=0;i<count;++i){DataStream fragment;fragment<<i<<count;Bytes data{'N','8','P','F'};
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
        auto root=p.leaf;for(const auto& sibling:p.branch)root=Hash(root,sibling);
        if(root!=p.header.hashMerkleRoot)return fail("n5-share-merkle");
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
