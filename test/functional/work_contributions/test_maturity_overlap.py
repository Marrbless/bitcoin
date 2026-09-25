#!/usr/bin/env python3
# Distributed under the MIT software license, see the accompanying COPYING.
"""CSV eligibility cannot bypass the inherited temporary coinbase restriction."""
import json
import tempfile
from pathlib import Path

import native_checks as n
from settings import CANDIDATE, PARENT, RESULTS
from test_blake import decode, refresh
from test_maturity import spend

checks = []
def check(name, actual, expected=True):
    item = dict(name=name, actual=actual, expected=expected, passed=actual == expected)
    checks.append(item)
    if not item['passed']:
        raise AssertionError(item)

def main():
    with tempfile.TemporaryDirectory(prefix='contribution-overlap-') as tmp:
        common = ['-testactivationheight=blake2b@2', '-blake2b_headline=Contribution overlap',
                  '-rdtsexpiry=2000000000', '-testcoinbasematuritylong=101:201:7101']
        a = n.Node('candidate', CANDIDATE, Path(tmp), common + ['-testgatewayallocationheight=201', f'-testgatewaykeys={n.G_PUB.hex()}:{n.H_PUB.hex()}'])
        old = n.Node('parent', PARENT, Path(tmp), common)
        try:
            def advance(height):
                while a.rpc.getblockcount() < height:
                    current = a.rpc.getblockcount()
                    for node in (a, old):
                        node.rpc.setmocktime(n.GENESIS_TIME + 60000 + current)
                    hashes = a.rpc.generatetodescriptor(min(500, height - current), 'raw(51)')
                    raws = a.rpc.batch([a.rpc.getblock.get_request(h, 0) for h in hashes])
                    replies = old.rpc.batch([old.rpc.submitblock.get_request(b['result']) for b in raws])
                    assert all('error' not in b and b.get('result') is None for b in replies)
                check('nodes agree at height ' + str(height), a.rpc.getbestblockhash(), old.rpc.getbestblockhash())
            advance(201)
            block = decode(a.rpc.getblock(a.rpc.getbestblockhash(), 0))
            cb = block.vtx[0]
            # One finder reward is sufficient to exercise the shared CSV script.
            tx = spend(cb, 0, n.G_KEY, n.G_DEPTH)
            def candidate():
                b = decode(a.rpc.getcontributionblock([], [], '')['hex'])
                b.vtx.append(tx)
                b.vtx[0].vout = n.outputs(1000 // 20)
                n.add_witness_commitment(b)
                refresh(b)
                return b
            def proposal(b, node):
                return node.rpc.getblocktemplate({'mode': 'proposal', 'data': b.serialize().hex(),
                    'rules': ['segwit', 'blake2b', 'gatewayallocation', 'nodecontributions', 'long_coinbase_maturity']})
            for tip in [6680, 7099]:
                advance(tip)
                b = candidate()
                for name, node in [('candidate', a), ('parent', old)]:
                    check(f'{name} inherited maturity blocks CSV eligible spend at {tip + 1}',
                          proposal(b, node), 'bad-txns-premature-spend-of-coinbase')
            advance(7100)
            b = candidate()
            for name, node in [('candidate', a), ('parent', old)]:
                check(name + ' accepts signed spend at inherited release', proposal(b, node), None)
                check(name + ' connects release spend', node.rpc.submitblock(b.serialize().hex()), None)
            check('release spend is below unreleased long depth', 7101 - 201 < 7000)
            for node in (a, old):
                node.rpc.invalidateblock(node.rpc.getblockhash(7100))
            check('reorg crosses inherited release boundary', a.rpc.getblockcount(), 7099)
            b = candidate()
            for name, node in [('candidate', a), ('parent', old)]:
                check(name + ' restores inherited lock after reorg', proposal(b, node), 'bad-txns-premature-spend-of-coinbase')
        finally:
            try:
                a.stop()
            finally:
                old.stop()

if __name__ == '__main__':
    try:
        main()
    finally:
        (RESULTS / 'maturity_overlap_results.json').write_text(json.dumps(checks, indent=2) + '\n')
    print(f'{len(checks)} maturity overlap checks passed')
