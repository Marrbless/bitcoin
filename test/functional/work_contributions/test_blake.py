#!/usr/bin/env python3
"""Native C++ N8 settlement tests; independent Python certificates and genuine CPU PoW."""
# Copyright (c) 2026 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.
from pathlib import Path
import copy,io,json,struct,sys,tempfile
from settings import CANDIDATE, PARENT, RESULTS
R=Path(__file__).resolve().parent
import native_checks as n
from hash_state import midstate,hash256
from compact_codec import branch
from test_framework.messages import CBlock,CBlockHeader,uint256_from_compact
checks=[]
def check(name,actual,expected=True):
 checks.append(dict(name=name,actual=actual,expected=expected,passed=actual==expected))
 if actual!=expected:raise AssertionError(checks[-1])
def decode(raw):
 b=CBlock();b.deserialize(io.BytesIO(bytes.fromhex(raw)));b.rehash()
 for t in b.vtx:t.rehash()
 return b
def refresh(b,weak=False):
 for t in b.vtx:t.rehash()
 b.hashMerkleRoot=b.calc_merkle_root();b.m_txcount=len(b.vtx) if b.m_header_v2 else 0
 target=uint256_from_compact(b.nBits)
 while True:
  h=b.rehash()
  if (target<h<=min(target*20,2**256-1)) if weak else h<=target:return b
  b.nNonce+=1

def cert(b,x):
 cb=b.vtx[0].serialize_without_witness();cut=(len(cb)-36)//64*64
 known=b'\0\1\x6a'+bytes(8)+bytes([83,0x6a,0x4c,80])+b'N8C0'+bytes(44)
 assert cb[-99:-36]==known
 assert cb[-36:-4]==hash256(b'N8C0'+bytes.fromhex(x)[::-1]+n.G_PUB+n.H_PUB)
 br=branch(b.vtx)
 return b'\3'+CBlockHeader(b).serialize()+struct.pack('<I',len(cb))+midstate(cb[:cut])+bytes([len(br)])+b''.join(br)+bytes.fromhex(x)[::-1]+n.G_PUB+n.H_PUB+cb[-4:]
def fragment(o):return b'N8PF' in bytes(o.scriptPubKey)[:10]
def fragment_data(o):return next(x for x in n.CScript(o.scriptPubKey) if isinstance(x,bytes))
def setdata(o,data):o.scriptPubKey=n.CScript([n.OP_RETURN,data])
def main():
 with tempfile.TemporaryDirectory(prefix='n8-native-') as tmp:
  run=Path(tmp);common=['-testactivationheight=blake2b@2','-blake2b_headline=N8 test','-rdtsexpiry=2000000000']
  a=n.Node('A',CANDIDATE,run,common+['-testgatewayallocationheight=101',f'-testgatewaykeys={n.G_PUB.hex()}:{n.H_PUB.hex()}'])
  old=n.Node('parent',PARENT,run,common)
  try:
   funding=n.next_block(a,legacy=True);funding.vtx[0].vout=[n.CTxOut(2500000000,n.CScript([n.OP_TRUE])) for _ in range(2)];n.add_witness_commitment(funding);refresh(funding)
   check('funding accepted',a.rpc.submitblock(funding.serialize().hex()),None)
   a.rpc.generatetodescriptor(99,'raw(51)')
   for height in range(1,101):
    raw=a.rpc.getblock(a.rpc.getblockhash(height),0)
    assert old.rpc.submitblock(raw) is None
   check('parent and candidate at same BLAKE tip',old.rpc.getbestblockhash(),a.rpc.getbestblockhash())
   tx=n.CTransaction();tx.vin=[n.CTxIn(n.COutPoint(funding.vtx[0].sha256,0))];tx.vout=[n.CTxOut(2499999000,n.script_to_p2wsh_script(n.CScript([n.OP_TRUE])))];tx.rehash()
   def assemble(proofs=(),x=tx.hash,txs=None):
    result=a.rpc.getcontributionblock([t.serialize().hex() for t in ([tx] if txs is None else txs)],[p.hex() for p in proofs],x)
    block=decode(result['hex'])
    if x:assert bytes.fromhex(result['candidateproof'])==cert(block,x), 'native/Python encoder mismatch'
    return block
   def proposal(b,node=a):
    refresh(b)
    return node.rpc.getblocktemplate({'mode':'proposal','data':b.serialize().hex(),'rules':['segwit','blake2b','gatewayallocation','nodecontributions']})
   def rejected(f):
    try:f();return False
    except n.JSONRPCException:return True
   source=assemble();check('native candidate BLAKE header',source.m_header_v2);check('native txcount refreshed',source.m_txcount,len(source.vtx))
   check('source scripts <=83',max(len(o.scriptPubKey) for o in source.vtx[0].vout),83)
   proofs=[]
   for profile in range(4):
    b=copy.deepcopy(source);b.m_flags=profile|4;b.m_time_offset=13;b.m_nonce2=17;b.m_nonce3=23;b.m_extranonce=12345+profile;b.m_xor_key=98765;b.m_xor_key_mask_clear_bits=[0,7,128,255][profile];b.m_mm_rhs=45678
    refresh(b,True);p=cert(b,tx.hash);proofs.append(p);settled=assemble([p]);check(f'profile {profile} certificate length',len(p),336)
    check(f'profile {profile} C++ accepts contribution',proposal(settled),None);check(f'profile {profile} parent accepts settlement',proposal(copy.deepcopy(settled),old),None)
   residues=set()
   for length in range(64):
    b=copy.deepcopy(source);b.vtx[0].vin[0].scriptSig=n.CScript([101,bytes(length)]);refresh(b,True);p=cert(b,tx.hash);residues.add((len(b.vtx[0].serialize_without_witness())-36)%64)
    check(f'midstate remainder fixture {length}',proposal(assemble([p])),None)
   check('all 64 SHA block remainders tested',len(residues),64)
   # Distinct actually earned work, including same-X reuse allowed by the rule.
   while len(proofs)<19:
    b=copy.deepcopy(source);b.m_extranonce=len(proofs)+100;refresh(b,True);proofs.append(cert(b,tx.hash))
   cap=assemble(proofs);check('cap source outputs within83',all(len(o.scriptPubKey)<=83 for o in cap.vtx[0].vout))
   check('19 real BLAKE contributions accepted',proposal(copy.deepcopy(cap)),None)
   check('19 proof block parent-compatible',proposal(copy.deepcopy(cap),old),None)
   # Maximum-length contextual certificates: omitted source validity is not claimed.
   maximum=[]
   for i in range(19):
    b=copy.deepcopy(source);b.m_txcount=4096;b.m_extranonce=10000+i
    siblings=[hash256(bytes([j,i])) for j in range(12)]
    root=hash256(b.vtx[0].serialize_without_witness())
    for sibling in siblings:root=hash256(root+sibling)
    b.hashMerkleRoot=int.from_bytes(root,'little');target=uint256_from_compact(b.nBits)
    while not target<b.rehash()<=min(20*target,2**256-1):b.nNonce+=1
    base=cert(source,tx.hash)
    p=b'\3'+CBlockHeader(b).serialize()+base[165:201]+b'\x0c'+b''.join(siblings)+base[-102:]
    assert len(p)==688
    maximum.append(p)
   maxblock=assemble(maximum)
   check('maximum certificates use 183 fragments',sum(fragment(o) for o in maxblock.vtx[0].vout),183)
   check('19 maximum-length certificates accepted',proposal(copy.deepcopy(maxblock)),None)
   check('maximum evidence parent-compatible under RDTS',proposal(copy.deepcopy(maxblock),old),None)
   check('maximum evidence output scripts <=83',all(len(o.scriptPubKey)<=83 for o in maxblock.vtx[0].vout))
   for label,txcount in [('zero',0),('too many',4097),('wrong depth',1)]:
    q=bytearray(proofs[0]);q[109:111]=struct.pack('<H',txcount)
    check('invalid source txcount '+label+' rejected',rejected(lambda:assemble([bytes(q)])))
   check('20 proofs rejected',rejected(lambda:assemble(proofs+[proofs[0]])))
   check('duplicate proof rejected',rejected(lambda:assemble([proofs[0],proofs[0]])))
   check('budget exact including fees',sum(o.nValue for o in cap.vtx[0].vout),20*((5000000000+1000)//20))
   one=assemble([proofs[0]]);positions=[i for i,o in enumerate(one.vtx[0].vout) if fragment(o)]
   check('one proof spans multiple legal fragments',len(positions)>1)
   mutations=[('missing fragment',lambda b:b.vtx[0].vout.pop(positions[0])),
    ('duplicate fragment',lambda b:b.vtx[0].vout.insert(positions[0],copy.deepcopy(b.vtx[0].vout[positions[0]]))),
    ('noncontiguous fragments',lambda b:b.vtx[0].vout.insert(positions[0]+1,n.CTxOut(0,n.CScript([n.OP_RETURN])))),
    ('wrong payout',lambda b:setattr(b.vtx[0].vout[0],'nValue',b.vtx[0].vout[0].nValue-1)),
    ('oversize return',lambda b:b.vtx[0].vout.append(n.CTxOut(0,n.CScript([n.OP_RETURN,bytes(81)])))),
    ('missing X',lambda b:b.vtx.pop())]
   for name,mutate in mutations:
    b=copy.deepcopy(one);mutate(b);check(name+' rejected',proposal(b) is not None)
   for name,mutate in [('reordered',lambda d:d[:4]+b'\1\0'+d[6:]),('zero count',lambda d:d[:6]+b'\0\0'+d[8:]),('oversized count',lambda d:d[:6]+b'\xff\xff'+d[8:]),('short nonfinal',lambda d:d[:-1]),('extra byte final',lambda d:d+b'\0')]:
    b=copy.deepcopy(one);pos=positions[-1] if name=='extra byte final' else positions[0];o=b.vtx[0].vout[pos];setdata(o,mutate(fragment_data(o)));check(name+' fragment rejected',proposal(b) is not None)
   for name,offset in [('version',0),('header parent',5),('merkle root',37),('bits',73),('header height',129),('state',169),('X',-102),('recipient',-70)]:
    q=bytearray(proofs[0]);q[offset]^=1;check('tampered '+name+' rejected',rejected(lambda:assemble([bytes(q)])))
   for name,mutate in [('height',lambda b:setattr(b,'m_height',102)),('reserved flags',lambda b:setattr(b,'m_flags',0xc0)),('past timestamp',lambda b:setattr(b,'nTime',1))]:
    b=copy.deepcopy(source);mutate(b);refresh(b,True);check('fresh work on invalid '+name+' rejected',rejected(lambda:assemble([cert(b,tx.hash)])))
   b=copy.deepcopy(source);refresh(b);check('full block proof not credited as weak',rejected(lambda:assemble([cert(b,tx.hash)])))
   for label,q in [('truncated',proofs[0][:-1]),('trailing',proofs[0]+b'\0')]:check(label+' certificate rejected',rejected(lambda:assemble([q])))
   # Active code enforces 83 even with inherited RDTS inactive in a separate lane (below).
   refresh(cap);raw=cap.serialize().hex();check('actual settlement accepted by C++',a.rpc.submitblock(raw),None);check('actual settlement accepted by parent',old.rpc.submitblock(raw),None);check('tips agree',a.rpc.getbestblockhash(),old.rpc.getbestblockhash())
   check('old-parent proof expires',rejected(lambda:assemble([proofs[0]],x='',txs=[])))
   a.rpc.invalidateblock(cap.hash);check('proof eligible after exact-parent restoration',proposal(assemble([proofs[0]])),None)
   a.rpc.reconsiderblock(cap.hash);check('settlement restored',a.rpc.getbestblockhash(),cap.hash)
   (RESULTS/'settled_block.hex').write_text(raw+'\n');(RESULTS/'example_proof.hex').write_text(proofs[0].hex()+'\n')
   (RESULTS/'sizes.json').write_text(json.dumps({'certificate_bytes':len(proofs[0]),'nineteen_proof_block_bytes':len(cap.serialize()),'coinbase_bytes':len(cap.vtx[0].serialize()),'proof_fragments':sum(fragment(o) for o in cap.vtx[0].vout),'max_output_script_bytes':max(len(o.scriptPubKey) for o in cap.vtx[0].vout)},indent=2)+'\n')
  finally:a.stop();old.stop()
if __name__=='__main__':
 try:main()
 finally:(RESULTS/'results.json').write_text(json.dumps(checks,indent=2)+'\n')
 print(f'{len(checks)} native BLAKE checks passed')
