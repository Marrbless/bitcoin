// Bounded Linux/private-regtest Stratum subset. MIT license. Not production networking.
#include <node/native_stratum.h>

#ifdef __linux__
#include <arith_uint256.h>
#include <chainparams.h>
#include <common/args.h>
#include <consensus/merkle.h>
#include <consensus/node_contribution.h>
#include <core_io.h>
#include <hash.h>
#include <node/context.h>
#include <rpc/server.h>
#include <rpc/server_util.h>
#include <rpc/util.h>
#include <streams.h>
#include <util/strencodings.h>
#include <validation.h>
#include <univalue.h>
#include <algorithm>
#include <any>
#include <atomic>
#include <chrono>
#include <cerrno>
#include <stdexcept>
#include <deque>
#include <memory>
#include <mutex>
#include <set>
#include <thread>
#include <arpa/inet.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

namespace {
using Bytes=std::vector<unsigned char>;
using Clock=std::chrono::steady_clock;
struct Job { CBlock block; std::string id,x; };
struct Client {
    int fd{-1}; bool subscribed{false},authorized{false}; std::string user,in,out,extra;
    std::deque<Job> jobs; Clock::time_point last{Clock::now()};
};
// Delivery is best-effort, bounded, and tied to one parent. It changes no consensus rules.
struct Publication {
    std::string raw, reply, parent; int port{0}, attempts{0}; size_t sent{0};
    Clock::time_point due{Clock::now()}, deadline{};
};
struct Endpoint {
    std::atomic<int> peer_port{0}; uint64_t imported{0}, transport_failures{0};
    std::deque<Publication> outbox; int outgoing{-1}; bool connecting{false};
    std::any context; UniValue transactions{UniValue::VARR}; std::string x,anchor;
    std::vector<Bytes> proofs; std::set<uint256> seen;
    std::atomic<bool> stopping{false}; std::thread thread; int listener{-1},port{0};
    bool blake{false};
    uint64_t epoch_ordinary{0};
    // Local admission policy, not a consensus rule. Shared across connections.
    Clock::time_point contribution_epoch{Clock::now()};
    unsigned contribution_attempts{0};
    uint64_t next_client{0},next_job{0},ordinary{0},strong{0},blocks{0},rejected{0};
    std::string last_block,error; std::mutex mutex;
    ~Endpoint(){stop();}
    UniValue call(const std::string& method,UniValue args=UniValue(UniValue::VARR)) {
        JSONRPCRequest req;req.context=context;req.strMethod=method;req.params=std::move(args);
        return tableRPC.execute(req);
    }
    void stop(){stopping=true;if(thread.joinable())thread.join();if(listener>=0){close(listener);listener=-1;}}
    void queue(Client& c,const UniValue& value){c.out+=value.write()+"\n";if(c.out.size()>131072)throw std::runtime_error("slow client");}
    void reply(Client& c,const UniValue& id,UniValue result,const std::string& error="") {
        UniValue value(UniValue::VOBJ);value.pushKV("id",id);value.pushKV("result",result);
        if(error.empty())value.pushKV("error",NullUniValue);
        else {UniValue e(UniValue::VARR);e.push_back(20);e.push_back(error);e.push_back(NullUniValue);value.pushKV("error",e);}
        queue(c,value);
    }
    static std::string hex32(uint32_t x){unsigned char b[4]={static_cast<unsigned char>(x>>24),static_cast<unsigned char>(x>>16),static_cast<unsigned char>(x>>8),static_cast<unsigned char>(x)};return HexStr(b);}
    static uint32_t number(const UniValue& val){const auto s=val.get_str();if(s.size()!=8||!IsHex(s))throw std::runtime_error("need 8 hex digits");return static_cast<uint32_t>(std::stoul(s,nullptr,16));}
    static std::pair<uint32_t,uint32_t> sia_words(const UniValue& val) {
        const auto hex=val.get_str();
        if(hex.size()==8)return {number(val),0};
        if(hex.size()!=16||!IsHex(hex))throw std::runtime_error("need 8 or 16 hex digits");
        DataStream ds{ParseHex(hex)};uint32_t low,high;ds>>low>>high;return {low,high};
    }
    std::vector<uint256> branch(const CBlock& b) {
        std::vector<uint256> hashes,result;for(const auto& tx:b.vtx)hashes.push_back(tx->GetHash().ToUint256());
        while(hashes.size()>1){if(hashes.size()%2)hashes.push_back(hashes.back());result.push_back(hashes[1]);std::vector<uint256> next;for(size_t i=0;i<hashes.size();i+=2)next.push_back(Hash(hashes[i],hashes[i+1]));hashes=std::move(next);}return result;
    }
    Job makejob() {
        UniValue args(UniValue::VARR),ps(UniValue::VARR);{std::lock_guard lock(mutex);for(const auto& p:proofs)ps.push_back(HexStr(p));}
        args.push_back(transactions);args.push_back(ps);args.push_back(x);
        const auto result=call("getcontributionblock",args);Job job;
        if(!DecodeHexBlk(job.block,result["hex"].get_str()))throw std::runtime_error("native candidate decode");
        if(job.block.m_header_v2) {
            // Sia work-header mapping: profile 0, fixed consensus time, unmasked work.
            if(job.block.m_flags||!job.block.m_xor_key.IsNull()||job.block.m_xor_key_mask_clear_bits)throw std::runtime_error("unsupported BLAKE job profile");
        } else {
            CMutableTransaction cb{*job.block.vtx[0]};cb.vin[0].scriptSig<<Bytes(8,0);
            if(cb.vin[0].scriptSig.size()>100)throw std::runtime_error("coinbase script limit");
            job.block.vtx[0]=MakeTransactionRef(std::move(cb));job.block.hashMerkleRoot=BlockMerkleRoot(job.block);
        }
        job.id=std::to_string(++next_job);job.x=x;return job;
    }
    void notify(Client& c,bool clean) {
        Job job=makejob();
        if(job.block.m_header_v2!=blake)throw std::runtime_error("PoW mode changed; restart endpoint");
        UniValue p(UniValue::VARR);p.push_back(job.id);
        if(blake) {
            auto hidden=(TaggedHash("Bitcoin prevblock header, hashed")<<job.block.hashPrevBlock.ReversedBytes()).GetSHA256();
            std::fill_n(hidden.begin(),6,uint8_t{0});p.push_back(HexStr(hidden));
            const auto commitment=job.block.GetMiningCommitment();Bytes first(3,0);
            first.insert(first.end(),commitment.begin(),commitment.end());first.resize(39,0);
            p.push_back(HexStr(first));p.push_back("");p.push_back(UniValue(UniValue::VARR));
            p.push_back(hex32(job.block.nVersion));p.push_back(hex32(job.block.nBits));
            DataStream time;time<<uint32_t{0}<<job.block.nTime;p.push_back(HexStr(time));p.push_back(clean);
        } else {
            const auto& cb=*job.block.vtx[0];DataStream stream;stream<<TX_NO_WITNESS(cb);
            Bytes raw(stream.size());std::transform(stream.begin(),stream.end(),raw.begin(),[](std::byte b){return std::to_integer<unsigned char>(b);});
            const size_t offset=4+1+36+GetSizeOfCompactSize(cb.vin[0].scriptSig.size())+cb.vin[0].scriptSig.size()-8;
            Bytes prev(job.block.hashPrevBlock.begin(),job.block.hashPrevBlock.end());
            for(size_t i=0;i<32;i+=4)std::reverse(prev.begin()+i,prev.begin()+i+4);
            UniValue branches(UniValue::VARR);for(const auto& h:branch(job.block))branches.push_back(HexStr(h));
            p.push_back(HexStr(prev));p.push_back(HexStr(Span{raw}.first(offset)));p.push_back(HexStr(Span{raw}.subspan(offset+8)));
            p.push_back(branches);p.push_back(hex32(job.block.nVersion));p.push_back(hex32(job.block.nBits));p.push_back(hex32(job.block.nTime));p.push_back(clean);
        }
        UniValue msg(UniValue::VOBJ);msg.pushKV("id",NullUniValue);msg.pushKV("method","mining.notify");msg.pushKV("params",p);queue(c,msg);
        if(clean){c.jobs.clear();}
        c.jobs.push_back(std::move(job));while(c.jobs.size()>2)c.jobs.pop_front();
    }
    Bytes proof(const Job& job,const CBlock& block) {
        CPubKey early,late; bool found=false;
        for(const auto& out:block.vtx[0]->vout){auto pc=out.scriptPubKey.begin();opcodetype op;Bytes data;
            if(out.scriptPubKey.GetOp(pc,op)&&op==OP_RETURN&&out.scriptPubKey.GetOp(pc,op,data)&&data.size()==70&&std::equal(data.begin(),data.begin()+4,"GWA1")){
                early.Set(data.begin()+4,data.begin()+37);late.Set(data.begin()+37,data.end());found=true;break;}}
        if(!found)throw std::runtime_error("missing native keys");
        return Consensus::EncodeNodeContribution(block,*uint256::FromHex(job.x),early,late);
    }

    void close_outgoing() { if(outgoing>=0){close(outgoing);outgoing=-1;}connecting=false; }
    void publication_failed() {
        close_outgoing();{std::lock_guard lock(mutex);++transport_failures;}
        if(outbox.front().attempts>=3)outbox.pop_front();
        else {auto& p=outbox.front();p.sent=0;p.reply.clear();p.due=Clock::now()+std::chrono::milliseconds(250*p.attempts);}
    }
    void publish(const Bytes& proof) {
        const int port=peer_port.load();if(!port)return;
        UniValue message(UniValue::VOBJ),params(UniValue::VARR);
        params.push_back(HexStr(proof));params.push_back(transactions);
        message.pushKV("id",1);message.pushKV("method","mining.contribute");message.pushKV("params",params);
        auto raw=message.write()+"\n";
        // No unlimited messages, memory, retries, or work across parent changes.
        if(outbox.size()>=19||raw.size()>131072){std::lock_guard lock(mutex);++transport_failures;return;}
        Publication p;p.raw=std::move(raw);p.parent=anchor;p.port=port;outbox.push_back(std::move(p));
    }
    void service_publications() {
        while(!outbox.empty()&&(outbox.front().parent!=anchor||outbox.front().port!=peer_port.load())){close_outgoing();outbox.pop_front();}
        if(outbox.empty())return;
        auto& p=outbox.front();const auto now=Clock::now();
        if(outgoing<0){
            if(now<p.due)return;
            ++p.attempts;p.deadline=now+std::chrono::milliseconds(750);
            outgoing=socket(AF_INET,SOCK_STREAM,0);
            if(outgoing<0){publication_failed();return;}
            if(fcntl(outgoing,F_SETFL,O_NONBLOCK)<0){publication_failed();return;}
            sockaddr_in addr{};addr.sin_family=AF_INET;addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);addr.sin_port=htons(p.port);
            const auto result=connect(outgoing,reinterpret_cast<sockaddr*>(&addr),sizeof(addr));
            if(result!=0&&errno!=EINPROGRESS){publication_failed();return;}
            connecting=result!=0;
        }
        if(now>=p.deadline){publication_failed();return;}
        pollfd fd{outgoing,static_cast<short>(POLLIN|((connecting||p.sent<p.raw.size())?POLLOUT:0)),0};
        const auto ready=poll(&fd,1,0);if(ready<0){if(errno!=EINTR)publication_failed();return;}if(ready==0)return;
        if(connecting){
            if(!(fd.revents&(POLLOUT|POLLERR|POLLHUP)))return;
            int error=0;socklen_t size=sizeof(error);
            if(getsockopt(outgoing,SOL_SOCKET,SO_ERROR,&error,&size)!=0||error){publication_failed();return;}
            connecting=false;
        }
        if((fd.revents&POLLOUT)&&p.sent<p.raw.size()){
            const auto n=send(outgoing,p.raw.data()+p.sent,p.raw.size()-p.sent,MSG_NOSIGNAL);
            if(n>0)p.sent+=n;else if(n==0||(errno!=EAGAIN&&errno!=EINTR)){publication_failed();return;}
        }
        // TCP is a byte stream: accumulate a bounded reply until its newline arrives.
        if(fd.revents&POLLIN){
            char buffer[1024];const auto n=recv(outgoing,buffer,sizeof(buffer),0);
            if(n>0){p.reply.append(buffer,n);if(p.reply.size()>8192){publication_failed();return;}
                const auto end=p.reply.find('\n');if(end!=std::string::npos){UniValue response;
                    const bool ok=p.sent==p.raw.size()&&response.read(p.reply.substr(0,end))&&response.isObject()&&response["id"].isNum()&&response["id"].write()=="1"&&response["result"].isTrue()&&response["error"].isNull();
                    if(ok){close_outgoing();outbox.pop_front();}else publication_failed();return;}}
            else if(n==0||(errno!=EAGAIN&&errno!=EINTR)){publication_failed();return;}
        }
        if(fd.revents&(POLLERR|POLLHUP|POLLNVAL))publication_failed();
    }
    bool receive_contribution(const UniValue& p) {
        if(!p.isArray()||p.size()!=2||!p[1].isArray()||p[1].size()>128)throw std::runtime_error("bad contribution envelope");
        const auto hex=p[0].get_str();if(hex.size()<440||hex.size()>2*Consensus::NODE_CONTRIBUTION_MAX_BYTES||!IsHex(hex))throw std::runtime_error("bad proof length");
        const auto raw=ParseHex(hex);DataStream proof_header{raw};uint8_t version;CBlockHeader header;
        proof_header>>version>>header;if(version!=3)throw std::runtime_error("bad certificate version");
        const auto id=header.GetHash();
        // Lost ACK retries acknowledge the exact currently retained proof, without new credit.
        if(anchor!=call("getbestblockhash").get_str())throw std::runtime_error("parent changed");
        {std::lock_guard lock(mutex);
            if(std::find(proofs.begin(),proofs.end(),raw)!=proofs.end())return false;
            if(seen.count(id)||proofs.size()>=19)throw std::runtime_error("duplicate or full inbox");}
        const auto now=Clock::now();
        if(now-contribution_epoch>=std::chrono::seconds(1)){contribution_epoch=now;contribution_attempts=0;}
        if(contribution_attempts>=32)throw std::runtime_error("contribution validation rate limit");
        ++contribution_attempts;
        const auto prior=transactions;auto proposed=transactions;
        std::set<Txid> ids;
        for(const auto& t:transactions.getValues()){CMutableTransaction tx;if(!DecodeHexTx(tx,t.get_str()))throw std::runtime_error("configured tx decode");ids.insert(tx.GetHash());}
        for(const auto& t:p[1].getValues()){CMutableTransaction tx;if(!DecodeHexTx(tx,t.get_str())||CTransaction{tx}.IsCoinBase())throw std::runtime_error("incoming tx decode");if(ids.insert(tx.GetHash()).second)proposed.push_back(t);}
        transactions=proposed;
        {std::lock_guard lock(mutex);proofs.push_back(raw);}
        try {makejob();} catch(...) {{std::lock_guard lock(mutex);proofs.pop_back();}transactions=prior;throw;}
        {std::lock_guard lock(mutex);seen.insert(id);++imported;}return true;
    }
    bool submit(Client& c,const UniValue& params) {
        if(!c.authorized||!c.subscribed||params.size()!=5)throw std::runtime_error("unauthorized or bad submit");
        if(params[0].get_str()!=c.user)throw std::runtime_error("wrong worker");
        auto it=std::find_if(c.jobs.begin(),c.jobs.end(),[&](const Job& j){return j.id==params[1].get_str();});
        if(it==c.jobs.end())throw std::runtime_error("unknown job");
        const auto extra=params[2].get_str();if(extra.size()!=(blake?16:8)||!IsHex(extra))throw std::runtime_error("bad extranonce2");
        CBlock block=it->block;
        if(block.hashPrevBlock.GetHex()!=call("getbestblockhash").get_str())throw std::runtime_error("stale parent");
        if(blake) {
            const auto nonce=sia_words(params[4]),time=sia_words(params[3]);
            block.nNonce=nonce.first;block.m_nonce2=nonce.second;
            block.m_time_offset=time.first;block.m_nonce3=time.second;
            const auto en=ParseHex("00000000"+c.extra+extra);
            std::copy(en.begin(),en.end(),block.m_extranonce.begin());
        } else {
            if(number(params[3])!=block.nTime)throw std::runtime_error("time rolling unsupported in fixture");
            block.nNonce=number(params[4]);CMutableTransaction cb{*block.vtx[0]};const auto nonce=ParseHex(c.extra+extra);
            std::copy(nonce.begin(),nonce.end(),cb.vin[0].scriptSig.end()-8);block.vtx[0]=MakeTransactionRef(std::move(cb));block.hashMerkleRoot=BlockMerkleRoot(block);
        }
        const auto id=block.GetHash();
        arith_uint256 target;target.SetCompact(block.nBits);const auto value=UintToArith256(id);
        if(value<=target){DataStream ds;ds<<TX_WITH_WITNESS(block);UniValue args(UniValue::VARR);args.push_back(HexStr(ds));const auto result=call("submitblock",args);if(!result.isNull())throw std::runtime_error(result.write());std::lock_guard lock(mutex);++blocks;last_block=id.GetHex();return false;}
        // A complete block never depends on the local ordinary-share accounting budget.
        {std::lock_guard lock(mutex);if(seen.count(id))throw std::runtime_error("duplicate work");}
        const auto max=~arith_uint256{};const auto weak=target>max/20?max:target*20;
        if(!it->x.empty()&&value<=weak){auto p=proof(*it,block);
            if(p.size()>Consensus::NODE_CONTRIBUTION_MAX_BYTES)throw std::runtime_error("certificate too large");
            {std::lock_guard lock(mutex);if(proofs.size()>=19)throw std::runtime_error("contribution queue full");proofs.push_back(p);}
            try{makejob();}catch(...){std::lock_guard lock(mutex);proofs.pop_back();throw;}
            {std::lock_guard lock(mutex);seen.insert(id);++strong;}publish(p);return true;}
        // Strong contributions have their own 19-proof cap; ordinary traffic cannot fill it.
        {std::lock_guard lock(mutex);if(epoch_ordinary>=4096)throw std::runtime_error("epoch ordinary work limit");seen.insert(id);++epoch_ordinary;++ordinary;}return false;
    }
    bool handle(Client& c,const std::string& line) {
        UniValue req;if(!req.read(line)||!req.isObject())throw std::runtime_error("invalid JSON");
        const auto id=req["id"];const auto method=req["method"].get_str();const auto& p=req["params"];
        try {
            if(method=="mining.contribute"){const bool changed=receive_contribution(p);reply(c,id,UniValue(true));return changed;}
            if(method=="mining.subscribe"){
                if(c.subscribed){throw std::runtime_error("already subscribed");}
                c.subscribed=true;
                UniValue result(UniValue::VARR),subs(UniValue::VARR),sub(UniValue::VARR);sub.push_back("mining.notify");sub.push_back(c.extra);subs.push_back(sub);result.push_back(subs);result.push_back(c.extra);result.push_back(blake?8:4);reply(c,id,result);
                UniValue msg(UniValue::VOBJ),diff(UniValue::VARR);diff.push_back(0.0000000002328270909401909);msg.pushKV("id",NullUniValue);msg.pushKV("method","mining.set_difficulty");msg.pushKV("params",diff);queue(c,msg);
                if(c.authorized){notify(c,true);}
                return false;
            }
            if(method=="mining.authorize"){
                if(c.authorized)throw std::runtime_error("already authorized");
                if(!p.isArray()||p.size()!=2||p[0].get_str().empty()||p[0].get_str().size()>128)throw std::runtime_error("bad worker");
                c.authorized=true;c.user=p[0].get_str();reply(c,id,UniValue(true));if(c.subscribed)notify(c,true);return false;
            }
            if(method=="mining.configure"){UniValue result(UniValue::VOBJ);result.pushKV("version-rolling",false);reply(c,id,result);return false;}
            if(method=="mining.submit"){const bool refresh=submit(c,p);reply(c,id,UniValue(true));return refresh;}
            throw std::runtime_error("unsupported method");
        }catch(const UniValue& e){reply(c,id,UniValue(false),e.write());}
        catch(const std::exception& e){reply(c,id,UniValue(false),e.what());}
        {std::lock_guard lock(mutex);++rejected;}return false;
    }
    bool select_local_transactions() {
        // The existing node assembler supplies dependency order and local mempool policy.
        UniValue args(UniValue::VARR),options(UniValue::VOBJ),rules(UniValue::VARR);
        rules.push_back("segwit");rules.push_back("blake2b");rules.push_back("gatewayallocation");rules.push_back("nodecontributions");options.pushKV("rules",rules);args.push_back(options);
        const auto candidate=call("getblocktemplate",args);UniValue selected(UniValue::VARR);std::string selected_x;size_t bytes=0;
        for(const auto& entry:candidate["transactions"].getValues()){
            const auto raw=entry["data"].get_str();bytes+=raw.size();if(bytes>60000||selected.size()>=128)break;
            selected.push_back(raw);if(selected_x.empty())selected_x=entry["txid"].get_str();
        }
        if(selected.write()==transactions.write()&&selected_x==x)return false;
        const auto previous=transactions;const auto old_x=x;transactions=selected;x=selected_x;
        try{makejob();}catch(...){transactions=previous;x=old_x;throw;}
        return true;
    }
    void run() {
        std::vector<Client> clients;auto next_tip=Clock::now();auto next_selection=Clock::now()+std::chrono::seconds(1);
        try {anchor=call("getbestblockhash").get_str();
            while(!stopping){
                bool refresh=false,clean=false;
                if(Clock::now()>=next_tip){next_tip=Clock::now()+std::chrono::milliseconds(250);const auto tip=call("getbestblockhash").get_str();
                    if(tip!=anchor){anchor=tip;{std::lock_guard lock(mutex);proofs.clear();seen.clear();epoch_ordinary=0;}transactions=UniValue(UniValue::VARR);x.clear();refresh=true;clean=true;}}
                if(Clock::now()>=next_selection){next_selection=Clock::now()+std::chrono::seconds(1);bool can_select;{std::lock_guard lock(mutex);can_select=x.empty()&&proofs.empty();}if(can_select){refresh=select_local_transactions()||refresh;}}
                service_publications();
                std::vector<pollfd> fds{{listener,POLLIN,0}};for(const auto& c:clients)fds.push_back({c.fd,static_cast<short>(POLLIN|(c.out.empty()?0:POLLOUT)),0});
                poll(fds.data(),fds.size(),50);
                for(size_t i=0;i<clients.size();++i){auto& c=clients[i];
                    try{
                        if(Clock::now()-c.last>std::chrono::seconds(30))throw std::runtime_error("idle");
                        if(fds[i+1].revents&(POLLERR|POLLHUP|POLLNVAL))throw std::runtime_error("closed");
                        if(fds[i+1].revents&POLLIN){char data[2048];auto got=recv(c.fd,data,sizeof(data),0);if(got<=0)throw std::runtime_error("read");c.last=Clock::now();c.in.append(data,got);if(c.in.size()>131072)throw std::runtime_error("frame limit");}
                        // Drain already buffered frames even when no more socket bytes arrive.
                        for(int processed=0;processed<16;++processed){auto end=c.in.find('\n');if(end==std::string::npos)break;auto line=c.in.substr(0,end);c.in.erase(0,end+1);refresh=handle(c,line)||refresh;}
                        if((fds[i+1].revents&POLLOUT)&&!c.out.empty()){auto sent=send(c.fd,c.out.data(),c.out.size(),MSG_NOSIGNAL);if(sent>0)c.out.erase(0,sent);else if(errno!=EAGAIN)throw std::runtime_error("write");}
                    }catch(...){close(c.fd);c.fd=-1;}}
                clients.erase(std::remove_if(clients.begin(),clients.end(),[](const Client& c){return c.fd<0;}),clients.end());
                if(fds[0].revents&POLLIN){const int fd=accept(listener,nullptr,nullptr);if(fd>=0){if(clients.size()>=4)close(fd);else{fcntl(fd,F_SETFL,O_NONBLOCK);Client c;c.fd=fd;c.extra=hex32(++next_client);clients.push_back(std::move(c));}}}
                if(refresh){for(auto& c:clients)if(c.authorized&&c.subscribed){try{notify(c,clean);}catch(...){close(c.fd);c.fd=-1;}}clients.erase(std::remove_if(clients.begin(),clients.end(),[](const Client& c){return c.fd<0;}),clients.end());}
            }
        }catch(const UniValue& e){std::lock_guard lock(mutex);error=e.write();}
        catch(const std::exception& e){std::lock_guard lock(mutex);error=e.what();}
        close_outgoing();outbox.clear();for(auto& c:clients)close(c.fd);
    }
};
std::mutex control;
std::unique_ptr<Endpoint> endpoint;

RPCHelpMan startminingendpoint(){return RPCHelpMan{"startminingendpoint","Start bounded in-process loopback Stratum test endpoint (regtest only).",{
    {"transactions",RPCArg::Type::ARR,RPCArg::Optional::NO,"Operator-selected ordered raw transactions",{{"raw",RPCArg::Type::STR_HEX,RPCArg::Optional::OMITTED,""}}},
    {"x",RPCArg::Type::STR,RPCArg::Optional::NO,"Operator-selected X txid or empty"}},

    RPCResult{RPCResult::Type::NUM,"","Loopback TCP port"},RPCExamples{""},
    [&](const RPCHelpMan&,const JSONRPCRequest& request)->UniValue{
        auto& chainman=EnsureChainman(EnsureAnyNodeContext(request.context));if(chainman.GetParams().GetChainType()!=ChainType::REGTEST)throw JSONRPCError(RPC_INVALID_PARAMETER,"regtest only");
        std::lock_guard lock(control);if(endpoint)throw JSONRPCError(RPC_INVALID_PARAMETER,"already running");
        auto e=std::make_unique<Endpoint>();e->context=request.context;e->transactions=request.params[0];e->x=request.params[1].get_str();
        e->blake=e->makejob().block.m_header_v2; // Validate before opening the listener.
        e->listener=socket(AF_INET,SOCK_STREAM,0);if(e->listener<0)throw JSONRPCError(RPC_MISC_ERROR,"socket failed");
        sockaddr_in addr{};addr.sin_family=AF_INET;addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);addr.sin_port=0;
        if(bind(e->listener,reinterpret_cast<sockaddr*>(&addr),sizeof(addr))||listen(e->listener,4))throw JSONRPCError(RPC_MISC_ERROR,"bind failed");
        socklen_t size=sizeof(addr);getsockname(e->listener,reinterpret_cast<sockaddr*>(&addr),&size);e->port=ntohs(addr.sin_port);fcntl(e->listener,F_SETFL,O_NONBLOCK);
        const int port=e->port;endpoint=std::move(e);endpoint->thread=std::thread([p=endpoint.get()]{p->run();});return port;
    }};}
RPCHelpMan setcontributionpeer(){return RPCHelpMan{"setcontributionpeer","Private loopback contribution peer port; zero disables.",{{"port",RPCArg::Type::NUM,RPCArg::Optional::NO,"TCP port"}},RPCResult{RPCResult::Type::BOOL,"","Configured"},RPCExamples{""},
    [&](const RPCHelpMan&,const JSONRPCRequest& request)->UniValue{const int port=request.params[0].getInt<int>();if(port<0||port>65535)throw JSONRPCError(RPC_INVALID_PARAMETER,"port range");std::lock_guard guard(control);if(!endpoint)throw JSONRPCError(RPC_MISC_ERROR,"endpoint stopped");endpoint->peer_port=port;return true;}};}
RPCHelpMan stopminingendpoint(){return RPCHelpMan{"stopminingendpoint","Stop the native test endpoint.",{},RPCResult{RPCResult::Type::BOOL,"","Stopped"},RPCExamples{""},
    [&](const RPCHelpMan&,const JSONRPCRequest&)->UniValue{StopNativeStratum();return true;}};}
RPCHelpMan getminingendpointinfo(){return RPCHelpMan{"getminingendpointinfo","Native endpoint experiment counters and queued proofs.",{},RPCResult{RPCResult::Type::OBJ,"","Status",{{RPCResult::Type::BOOL,"running","Listener exists"},{RPCResult::Type::NUM,"imported",true,"Imported contributions"},{RPCResult::Type::NUM,"transport_failures",true,"Failed sends"},{RPCResult::Type::NUM,"ordinary",true,"Ordinary submissions"},{RPCResult::Type::NUM,"strong",true,"Strong submissions"},{RPCResult::Type::NUM,"blocks",true,"Accepted blocks"},{RPCResult::Type::NUM,"rejected",true,"Rejected submissions"},{RPCResult::Type::STR,"last_block",true,"Last accepted block"},{RPCResult::Type::STR,"error",true,"Worker error"},{RPCResult::Type::ARR,"proofs",true,"Queued proofs",{{RPCResult::Type::STR_HEX,"","Proof"}}}}},RPCExamples{""},
    [&](const RPCHelpMan&,const JSONRPCRequest&)->UniValue{std::lock_guard guard(control);UniValue result(UniValue::VOBJ);result.pushKV("running",bool(endpoint));if(!endpoint)return result;
        std::lock_guard lock(endpoint->mutex);result.pushKV("imported",endpoint->imported);result.pushKV("transport_failures",endpoint->transport_failures);result.pushKV("ordinary",endpoint->ordinary);result.pushKV("strong",endpoint->strong);result.pushKV("blocks",endpoint->blocks);result.pushKV("rejected",endpoint->rejected);result.pushKV("last_block",endpoint->last_block);result.pushKV("error",endpoint->error);UniValue p(UniValue::VARR);for(const auto& proof:endpoint->proofs)p.push_back(HexStr(proof));result.pushKV("proofs",p);return result;
    }};}
}
void StopNativeStratum(){std::lock_guard lock(control);endpoint.reset();}
void RegisterNativeStratumRPC(CRPCTable& table){static const CRPCCommand commands[]{{"hidden",&setcontributionpeer},{"hidden",&startminingendpoint},{"hidden",&stopminingendpoint},{"hidden",&getminingendpointinfo}};for(const auto& c:commands)table.appendCommand(c.name,&c);}

#else
// The private endpoint is Linux-only; consensus validation remains portable.
void StopNativeStratum() {}
void RegisterNativeStratumRPC(CRPCTable&) {}
#endif // __linux__
