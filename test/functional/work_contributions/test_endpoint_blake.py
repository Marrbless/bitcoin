#!/usr/bin/env python3
"""Socket-only Sia work client. No full template/header/proof supplied by miner."""
# Copyright (c) 2026 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.
from pathlib import Path
import copy,hashlib,io,json,socket,struct,sys,tempfile,time
from settings import CANDIDATE, PARENT, RESULTS
R=Path(__file__).resolve().parent
import native_checks as n
from socket_miner import Miner
from test_blake import decode,refresh
from test_framework.messages import CBlockHeader,uint256_from_compact,blake2b_header_hash_components
checks=[]
def check(name,actual,expected=True):
 checks.append(dict(name=name,actual=actual,expected=expected,passed=actual==expected))
 if actual!=expected:raise AssertionError(checks[-1])
def wait(f,seconds=12):
 end=time.monotonic()+seconds
 while not f():
  if time.monotonic()>end:raise RuntimeError('condition timed out')
  time.sleep(.02)
class SiaMiner(Miner):
 def login(self):
  r=self.request('mining.subscribe',[],True);self.extra=r['result'][1]
  assert r['result'][2]==8 and len(self.extra)==8
  assert self.request('mining.authorize',['fixture.worker',''])['result']
  while self.job is None:self.receive()
 def find(self,full=False,seed=0,short=False):
  j=self.job;extra2=seed.to_bytes(8,'little').hex();tm=j[7] if short else struct.pack('<II',seed+17,0x12345678).hex()
  if short:tm=f'{seed+17:08x}'
  raw=b'\0'+bytes.fromhex(j[2]+self.extra+extra2+j[3]);assert len(raw)==52 and j[4]==[]
  root=hashlib.blake2b(raw,digest_size=32).digest();target=uint256_from_compact(int(j[6],16))
  timebytes=(struct.pack('<I',int(tm,16))+bytes(4)) if short else bytes.fromhex(tm)
  for nonce in range(10000):
   noncebytes=struct.pack('<II',nonce,0 if short else 0x87654321)
   work=bytes.fromhex(j[1])+noncebytes+timebytes+root;assert len(work)==80
   digest=hashlib.blake2b(work,digest_size=32).digest();value=int.from_bytes(digest,'big')
   if (value<=target)==full:
    param_nonce=f'{nonce:08x}' if short else noncebytes.hex()
    return ['fixture.worker',j[0],extra2,tm,param_nonce],digest.hex()
  raise AssertionError('easy work exhausted')
def header(proof):
 h=CBlockHeader();h.deserialize(io.BytesIO(bytes.fromhex(proof)[1:]));h.rehash();return h

def main():
 clients=[];nodes=[]
 with tempfile.TemporaryDirectory(prefix='n9-endpoint-') as tmp:
  run=Path(tmp);common=['-testactivationheight=blake2b@2','-blake2b_headline=N9 test','-rdtsexpiry=2000000000']
  keys=f'-testgatewaykeys={n.G_PUB.hex()}:{n.H_PUB.hex()}'
  try:
   a=n.Node('A',CANDIDATE,run,common+['-testgatewayallocationheight=101',keys]);nodes.append(a)
   b=n.Node('B',CANDIDATE,run,common+['-testgatewayallocationheight=101',keys]);nodes.append(b)
   old=n.Node('parent',PARENT,run,common);nodes.append(old)
   funding=n.next_block(a,legacy=True);funding.vtx[0].vout=[n.CTxOut(1000000000,n.script_to_p2wsh_script(n.CScript([n.OP_TRUE]))) for _ in range(3)];n.add_witness_commitment(funding);refresh(funding)
   check('funding',a.rpc.submitblock(funding.serialize().hex()),None);a.rpc.generatetodescriptor(99,'raw(51)')
   for node in [b,old]:node.rpc.addnode(f'127.0.0.1:{a.p2pport}','onetry')
   wait(lambda:all(node.rpc.getblockcount()==100 for node in nodes))
   txs=[]
   for i in range(3):
    t=n.CTransaction();t.vin=[n.CTxIn(n.COutPoint(funding.vtx[0].sha256,i))];t.vout=[n.CTxOut(999999000,n.script_to_p2wsh_script(n.CScript([n.OP_TRUE])))];wit=n.CTxInWitness();wit.scriptWitness.stack=[bytes(n.CScript([n.OP_TRUE]))];t.wit.vtxinwit=[wit];t.rehash();txs.append(t)
   x,y,z=txs
   pa=a.rpc.startminingendpoint([x.serialize().hex()],x.hash);pb=b.rpc.startminingendpoint([y.serialize().hex()],y.hash)
   a.rpc.setcontributionpeer(pb);b.rpc.setcontributionpeer(pa)
   ma=SiaMiner(pa);mb=SiaMiner(pb);clients=[ma,mb];ma.login();mb.login()
   check('BLAKE coinb1 is39 bytes',len(bytes.fromhex(ma.job[2])),39)
   check('BLAKE has empty coinb2',ma.job[3],'');check('BLAKE no Bitcoin merkle branch',ma.job[4],[])
   check('BLAKE notification time is8 bytes',len(bytes.fromhex(ma.job[7])),8)
   job=copy.deepcopy(ma.job);params,digest=ma.find(False,seed=3)
   for field,bad in [(2,'0'*8),(2,'g'*16),(3,'123'),(3,'z'*16),(4,'0'*24),(4,'z'*16),(0,'wrong.worker'),(1,'unknown-job')]:
    q=list(params);q[field]=bad;check('reject invalid submit field '+str(field)+' '+bad,ma.request('mining.submit',q)['result'],False)
   check('long-form strong submission',ma.request('mining.submit',params)['result'])
   wait(lambda:b.rpc.getminingendpointinfo()['imported']==1)
   ap=a.rpc.getminingendpointinfo()['proofs'][0];h=header(ap)
   check('socket work equals native certificate hash',h.hash,digest)
   check('native nonce2 matches Sia high word',h.m_nonce2,0x87654321)
   check('native time offset matches Sia low word',h.m_time_offset,20)
   check('native nonce3 matches Sia time high word',h.m_nonce3,0x12345678)
   check('fixed consensus time despite grinding words',h.nTime,int.from_bytes(bytes.fromhex(job[7])[4:],'little'))
   check('shared commitment equals independent Python',job[2][6:70],blake2b_header_hash_components(h)['h2'].hex())
   check('header extranonce matches assigned bytes',h.m_extranonce.to_bytes(16,'little').hex(),'00000000'+ma.extra+params[2])
   before=b.rpc.getminingendpointinfo()['imported'];check('exact proof retry ACK',mb.request('mining.contribute',[ap,[x.serialize().hex()]])['result']);check('retry has no duplicate credit',b.rpc.getminingendpointinfo()['imported'],before)
   q=bytearray.fromhex(ap);q[-1]^=1;check('same header changed certificate rejected',mb.request('mining.contribute',[q.hex(),[x.serialize().hex()]])['result'],False)
   # Reconnect for latest aggregate jobs; certificate publication itself is native.
   ma.close();mb.close();ma=SiaMiner(pa);mb=SiaMiner(pb);clients=[ma,mb];ma.login();mb.login()
   params2,digest2=mb.find(False,seed=9,short=True)
   check('short-form nonce/time accepted',mb.request('mining.submit',params2)['result'])
   wait(lambda:a.rpc.getminingendpointinfo()['imported']==1)
   proofs=a.rpc.getminingendpointinfo()['proofs'];check('two independently earned proofs present',len(proofs),2)
   bh=next(header(p) for p in proofs if header(p).hash==digest2)
   check('short nonce high word zero',bh.m_nonce2,0);check('short time high word zero',bh.m_nonce3,0)
   # Reconnect A then fill its independent contribution budget with genuine work.
   a.rpc.setcontributionpeer(0);b.rpc.setcontributionpeer(0);ma.close();ma=SiaMiner(pa);clients=[ma,mb];ma.login()
   for i in range(17):
    oldjob=ma.job[0];p,d=ma.find(False,seed=100+i);assert ma.request('mining.submit',p)['result'];ma.nextjob(oldjob)
   check('19 proof inbox reached',len(a.rpc.getminingendpointinfo()['proofs']),19)
   p,d=ma.find(False,seed=999);check('20th strong rejected',ma.request('mining.submit',p)['result'],False)
   stale=list(p);p,blockhash=ma.find(True,seed=1000);check('full block accepted at strong cap',ma.request('mining.submit',p)['result'])
   wait(lambda:all(node.rpc.getblockcount()==101 for node in nodes))
   check('socket blockhash matches node tip',a.rpc.getbestblockhash(),blockhash)
   check('all native nodes and parent agree',len({node.rpc.getbestblockhash() for node in nodes}),1)
   settled=decode(a.rpc.getblock(blockhash,0));check('block includes both node selections',set([x.hash,y.hash]).issubset({t.hash for t in settled.vtx}))
   check('all coinbase scripts within83',all(len(o.scriptPubKey)<=83 for o in settled.vtx[0].vout))
   check('block at cap claims full slots incl fees',sum(o.nValue for o in settled.vtx[0].vout),20*((5000000000+2000)//20))
   check('old-parent job rejected',ma.request('mining.submit',stale)['result'],False)
   a.rpc.stopminingendpoint();b.rpc.stopminingendpoint();ma.close();mb.close();clients=[]
   # Ordinary accounting saturation must not reject a block.
   pa=a.rpc.startminingendpoint([],'');ma=SiaMiner(pa);clients=[ma];ma.login()
   for i in range(4096):
    p,_=ma.find(False,seed=10000+i);assert ma.request('mining.submit',p)['result']
    if i%256==0:ma.trace.clear()
   check('4096 ordinary accounted',a.rpc.getminingendpointinfo()['ordinary'],4096)
   p,_=ma.find(False,seed=20000);check('ordinary overflow rejected',ma.request('mining.submit',p)['result'],False)
   p,secondhash=ma.find(True,seed=20001);check('block accepted after ordinary saturation',ma.request('mining.submit',p)['result'])
   wait(lambda:all(node.rpc.getblockcount()==102 for node in nodes));check('post-saturation chain agreement',a.rpc.getbestblockhash(),old.rpc.getbestblockhash())
   # Node's normal mempool selection works with BLAKE rule negotiation.
   a.rpc.sendrawtransaction(z.serialize().hex());wait(lambda:a.rpc.getminingendpointinfo()['ordinary']==4096)
   time.sleep(1.2);check('endpoint remains healthy after local selection',a.rpc.getminingendpointinfo()['error'],'')
   ma.close();ma=SiaMiner(pa);clients=[ma];ma.login();p,_=ma.find(False,seed=30000);check('local mempool X earns strong proof',ma.request('mining.submit',p)['result'])
   wait(lambda:len(a.rpc.getminingendpointinfo()['proofs'])==1)
   p=bytes.fromhex(a.rpc.getminingendpointinfo()['proofs'][0]);check('native selection commits local txid',p[-98:-66].hex(),bytes.fromhex(z.hash)[::-1].hex())
   (RESULTS/'settled_block.hex').write_text(settled.serialize().hex()+'\n');(RESULTS/'wire_trace.json').write_text(json.dumps(ma.trace,indent=2)+'\n')
  finally:
   for c in clients:
    try:c.close()
    except Exception:pass
   for node in reversed(nodes):node.stop()
if __name__=='__main__':
 try:main()
 finally:(RESULTS/'endpoint_results.json').write_text(json.dumps(checks,indent=2)+'\n')
 print(f'{len(checks)} BLAKE socket endpoint checks passed')
