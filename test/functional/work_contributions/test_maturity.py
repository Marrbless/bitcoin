#!/usr/bin/env python3
# Distributed under the MIT software license, see the accompanying COPYING.
"""Actual signed reward spends at both CSV boundaries on the BLAKE2b release."""
import copy
import json
import tempfile
from pathlib import Path

import native_checks as n
from settings import CANDIDATE, PARENT, RESULTS
from test_blake import cert, decode, refresh
from test_framework.script import sign_input_unified

checks = []
def check(name, actual, expected=True):
    item = dict(name=name, actual=actual, expected=expected, passed=actual == expected)
    checks.append(item)
    if not item['passed']:
        raise AssertionError(item)

def spend(cb, index, key, depth, sequence=None, version=2, witness_depth=None):
    tx = n.CTransaction()
    tx.version = version
    tx.vin = [n.CTxIn(n.COutPoint(cb.sha256, index), nSequence=depth if sequence is None else sequence)]
    tx.vout = [n.CTxOut(cb.vout[index].nValue - 1000, n.script_to_p2wsh_script(n.CScript([n.OP_TRUE])))]
    script = n.redeem(key.get_pubkey().get_bytes(), depth if witness_depth is None else witness_depth)
    tx.wit.vtxinwit = [n.CTxInWitness()]
    tx.wit.vtxinwit[0].scriptWitness.stack = [bytes(script)]
    sign_input_unified(tx, 0, script, key, [cb.vout[index]], witness=True)
    return tx

def main():
    with tempfile.TemporaryDirectory(prefix='contribution-maturity-') as tmp:
        run = Path(tmp)
        common = ['-testactivationheight=blake2b@2', '-blake2b_headline=Contribution maturity', '-rdtsexpiry=2000000000']
        a = n.Node('candidate', CANDIDATE, run, common + ['-testgatewayallocationheight=101', f'-testgatewaykeys={n.G_PUB.hex()}:{n.H_PUB.hex()}'])
        old = n.Node('parent', PARENT, run, common)
        try:
            funding = n.next_block(a, legacy=True)
            check('funding block', a.rpc.submitblock(funding.serialize().hex()), None)
            a.rpc.generatetodescriptor(99, 'raw(51)')
            for height in range(1, 101):
                assert old.rpc.submitblock(a.rpc.getblock(a.rpc.getblockhash(height), 0)) is None
            x = n.CTransaction()
            x.vin = [n.CTxIn(n.COutPoint(funding.vtx[0].sha256, 0))]
            x.vout = [n.CTxOut(funding.vtx[0].vout[0].nValue - 1000, n.script_to_p2wsh_script(n.CScript([n.OP_TRUE])))]
            x.rehash()
            source = decode(a.rpc.getcontributionblock([x.serialize().hex()], [], x.hash)['hex'])
            refresh(source, True)
            proof = cert(source, x.hash)
            block = decode(a.rpc.getcontributionblock([x.serialize().hex()], [proof.hex()], '')['hex'])
            refresh(block)
            check('reward settlement', a.rpc.submitblock(block.serialize().hex()), None)
            check('parent reward settlement', old.rpc.submitblock(block.serialize().hex()), None)
            cb = block.vtx[0]
            def advance(height):
                while a.rpc.getblockcount() < height:
                    current = a.rpc.getblockcount()
                    for node in (a, old):
                        node.rpc.setmocktime(n.GENESIS_TIME + 60000 + current)
                    hashes = a.rpc.generatetodescriptor(min(500, height - current), 'raw(51)')
                    raws = a.rpc.batch([a.rpc.getblock.get_request(h, 0) for h in hashes])
                    accepted = old.rpc.batch([old.rpc.submitblock.get_request(b['result']) for b in raws])
                    assert all('error' not in b and b.get('result') is None for b in accepted)
                assert a.rpc.getbestblockhash() == old.rpc.getbestblockhash()
                print('Both nodes validated height', height, flush=True)
            def candidate(tx):
                # Build manually so invalid spends reach consensus, not only RPC prevalidation.
                b = decode(a.rpc.getcontributionblock([], [], '')['hex'])
                b.vtx.append(tx)
                height = a.rpc.getblockcount() + 1
                # The regtest subsidy is zero at the late boundary; fees still fund the slot.
                subsidy = 5000000000 >> (height // 150) if height // 150 < 64 else 0
                b.vtx[0].vout = n.outputs((subsidy + 1000) // 20)
                n.add_witness_commitment(b)
                refresh(b)
                return b
            def result(b, node=a):
                return node.rpc.getblocktemplate({'mode': 'proposal', 'data': b.serialize().hex(), 'rules': ['segwit', 'blake2b', 'gatewayallocation', 'nodecontributions']})
            for name, depth, indices, key in [('early', n.G_DEPTH, (0, 3), n.G_KEY), ('late', n.H_DEPTH, (1, 4), n.H_KEY)]:
                first = 101 + depth
                advance(first - 2)
                for role, index in zip(('finder', 'contributor'), indices):
                    tx = spend(cb, index, key, depth)
                    b = candidate(tx)
                    check(name + ' ' + role + ' one block early rejected', result(b) is not None)
                    check(name + ' ' + role + ' parent also rejects early spend', result(b, old) is not None)
                advance(first - 1)
                for role, index in zip(('finder', 'contributor'), indices):
                    b = candidate(spend(cb, index, key, depth))
                    check(name + ' ' + role + ' boundary accepted', result(b), None)
                    check(name + ' ' + role + ' parent boundary accepted', result(b, old), None)
                for label, kwargs in [('short sequence', {'sequence': depth - 1}), ('disabled sequence', {'sequence': 0xffffffff}), ('time sequence', {'sequence': depth | (1 << 22)}), ('old version', {'version': 1}), ('short witness lock', {'witness_depth': depth - 1})]:
                    check(name + ' ' + label + ' cannot bypass lock', result(candidate(spend(cb, indices[0], key, depth, **kwargs))) is not None)
                b = candidate(spend(cb, indices[1], key, depth))
                check(name + ' signed contribution reward actually spent', a.rpc.submitblock(b.serialize().hex()), None)
                check(name + ' spend accepted by parent', old.rpc.submitblock(b.serialize().hex()), None)
                check(name + ' spent output removed', a.rpc.gettxout(cb.hash, indices[1]), None)
            check('late spend remained valid at zero subsidy', a.rpc.getblockcount(), 52661)
        finally:
            a.stop()
            old.stop()

if __name__ == '__main__':
    try:
        main()
    finally:
        (RESULTS / 'maturity_results.json').write_text(json.dumps(checks, indent=2) + '\n')
    print(f'{len(checks)} maturity checks passed')
