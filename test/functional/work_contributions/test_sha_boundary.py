#!/usr/bin/env python3
"""Retained SHA endpoint regression and new 83-byte rule with RDTS inactive."""
# Copyright (c) 2026 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.
from pathlib import Path
import copy,io,json,sys,tempfile
from settings import CANDIDATE, PARENT, RESULTS
R=Path(__file__).resolve().parent
from socket_miner import Miner,n
from test_blake import decode,refresh,cert
checks=[]
def check(name,actual,expected=True):
 checks.append(dict(name=name,actual=actual,expected=expected,passed=actual==expected))
 if actual!=expected:raise AssertionError(checks[-1])
def main():
 with tempfile.TemporaryDirectory(prefix='n8-sha-') as tmp:
  a=n.Node('candidate',CANDIDATE,Path(tmp),['-testgatewayallocationheight=101',f'-testgatewaykeys={n.G_PUB.hex()}:{n.H_PUB.hex()}'])
  old=n.Node('parent',PARENT,Path(tmp));m=None
  try:
   funding=n.next_block(a,legacy=True);check('SHA funding',a.rpc.submitblock(funding.serialize().hex()),None);a.rpc.generatetodescriptor(99,'raw(51)')
   for i in range(1,101):assert old.rpc.submitblock(a.rpc.getblock(a.rpc.getblockhash(i),0)) is None
   x=n.CTransaction();x.vin=[n.CTxIn(n.COutPoint(funding.vtx[0].sha256,0))];x.vout=[n.CTxOut(funding.vtx[0].vout[0].nValue-1000,n.script_to_p2wsh_script(n.CScript([n.OP_TRUE])))];x.rehash()
   r=a.rpc.getcontributionblock([x.serialize().hex()],[],x.hash);b=decode(r['hex'])
   check('SHA native/Python candidate codec agrees',r['candidateproof'],cert(b,x.hash).hex())
   oversized=copy.deepcopy(b);oversized.vtx[0].vout.append(n.CTxOut(0,n.CScript([n.OP_RETURN,bytes(81)])));refresh(oversized)
   opts={'mode':'proposal','data':oversized.serialize().hex(),'rules':['segwit','gatewayallocation','nodecontributions']}
   check('parent accepts oversized output outside RDTS',old.rpc.getblocktemplate(opts),None)
   check('new consensus rejects oversized output outside RDTS',a.rpc.getblocktemplate(opts),'n8-output-size')
   m=Miner(a.rpc.startminingendpoint([x.serialize().hex()],x.hash));m.login();job=m.job[0];params,digest,_=m.find(False)
   check('native encoder strong work accepted',m.request('mining.submit',params)['result']);m.nextjob(job)
   ps=a.rpc.getminingendpointinfo()['proofs'];check('native encoder queued one proof',len(ps),1);check('certificate version3',bytes.fromhex(ps[0])[0],3)
   settlement=decode(a.rpc.getcontributionblock([x.serialize().hex()],ps,'')['hex']);refresh(settlement)
   check('all settlement scripts <=83',all(len(o.scriptPubKey)<=83 for o in settlement.vtx[0].vout))
   check('SHA settlement accepted',a.rpc.submitblock(settlement.serialize().hex()),None)
   check('SHA settlement parent compatible',old.rpc.submitblock(settlement.serialize().hex()),None)
  finally:
   if m:m.close()
   a.stop();old.stop()
if __name__=='__main__':
 try:main()
 finally:(RESULTS/'sha_results.json').write_text(json.dumps(checks,indent=2)+'\n')
 print(f'{len(checks)} SHA/boundary checks passed')
