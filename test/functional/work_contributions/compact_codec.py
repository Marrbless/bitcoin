# Copyright (c) 2026 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.
from hash_state import hash256

def branch(txs):
 hs=[hash256(t.serialize_without_witness()) for t in txs];result=[]
 while len(hs)>1:
  if len(hs)%2:hs.append(hs[-1])
  result.append(hs[1]);hs=[hash256(hs[i]+hs[i+1]) for i in range(0,len(hs),2)]
 return result
