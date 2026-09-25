#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying COPYING.
"""Contributions begin only on BLAKE; the 83 byte rule is independent of RDTS."""
import copy
import json
import tempfile
from pathlib import Path
import native_checks as n
from settings import CANDIDATE, PARENT, RESULTS
from test_blake import decode, refresh

checks = []
def check(name, actual, expected=True):
    checks.append(dict(name=name, actual=actual, expected=expected, passed=actual == expected))
    if actual != expected:
        raise AssertionError(checks[-1])

def main():
    with tempfile.TemporaryDirectory(prefix='contribution-boundary-') as tmp:
        common = ['-testactivationheight=blake2b@101', '-blake2b_headline=Contribution boundary']
        a = n.Node('candidate', CANDIDATE, Path(tmp), common + ['-testgatewayallocationheight=1', f'-testgatewaykeys={n.G_PUB.hex()}:{n.H_PUB.hex()}'])
        old = n.Node('parent', PARENT, Path(tmp), common)
        try:
            a.rpc.generatetodescriptor(99, 'raw(51)')
            for height in range(1, 100):
                assert old.rpc.submitblock(a.rpc.getblock(a.rpc.getblockhash(height), 0)) is None
            sha_tip = a.rpc.getbestblockhash()
            def rejected(f):
                try:
                    f()
                    return False
                except n.JSONRPCException:
                    return True
            check('SHA templates retain inherited rules', 'nodecontributions' not in a.rpc.getblocktemplate({'rules': ['segwit']})['rules'])
            check('contribution RPC unavailable before BLAKE', rejected(lambda: a.rpc.getcontributionblock([], [], '')))
            check('endpoint unavailable before BLAKE', rejected(lambda: a.rpc.startminingendpoint([], '')))
            sha = n.next_block(a, legacy=True)
            sha.vtx[0].vout.append(n.CTxOut(0, n.CScript([n.OP_RETURN, bytes(81)])))
            refresh(sha)
            raw = sha.serialize().hex()
            check('SHA remains unrestricted by contribution output cap', a.rpc.submitblock(raw), None)
            check('SHA boundary parent accepts', old.rpc.submitblock(raw), None)
            check('BLAKE template requires contribution rule negotiation', rejected(lambda: a.rpc.getblocktemplate({'rules': ['segwit', 'blake2b']})))
            b = decode(a.rpc.getcontributionblock([], [], '')['hex'])
            check('first contribution template has BLAKE header', b.m_header_v2)
            check('first contribution template has correct height', b.m_height, 101)
            def proposal(block, node):
                refresh(block)
                return node.rpc.getblocktemplate({'mode': 'proposal', 'data': block.serialize().hex(), 'rules': ['segwit', 'blake2b', 'gatewayallocation', 'nodecontributions']})
            oversized = copy.deepcopy(b)
            oversized.vtx[0].vout.append(n.CTxOut(0, n.CScript([n.OP_RETURN, bytes(81)])))
            check('parent accepts84 bytes outside RDTS', proposal(oversized, old), None)
            check('contribution rule rejects84 bytes outside RDTS', proposal(oversized, a), 'n8-output-size')
            b.vtx[0].vout.append(n.CTxOut(0, n.CScript([n.OP_RETURN, bytes(80)])))
            check('83 byte script accepted outside RDTS', proposal(b, a), None)
            check('83 byte script parent compatible', proposal(b, old), None)
            check('BLAKE activation block accepted', a.rpc.submitblock(b.serialize().hex()), None)
            check('BLAKE activation block parent accepted', old.rpc.submitblock(b.serialize().hex()), None)
            a.rpc.invalidateblock(sha.hash)
            check('reorg returns to SHA tip', a.rpc.getbestblockhash(), sha_tip)
            check('reorg restores inherited template rules', 'nodecontributions' not in a.rpc.getblocktemplate({'rules': ['segwit']})['rules'])
            a.rpc.reconsiderblock(sha.hash)
            check('BLAKE contribution tip restored', a.rpc.getbestblockhash(), b.hash)
        finally:
            try:
                a.stop()
            finally:
                old.stop()

if __name__ == '__main__':
    try:
        main()
    finally:
        (RESULTS / 'boundary_results.json').write_text(json.dumps(checks, indent=2) + '\n')
    print(f'{len(checks)} activation checks passed')
