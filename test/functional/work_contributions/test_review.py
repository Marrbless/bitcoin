#!/usr/bin/env python3
# Distributed under the MIT software license, see the accompanying COPYING.
"""Review experiments: inherited header commitment and marginal fee allocation.

The inherited header hook is the v4 contribution commitment.
"""
import copy
import hashlib
import json
import tempfile
from pathlib import Path

import native_checks as n
from settings import CANDIDATE, PARENT, RESULTS
from test_blake import cert, decode, refresh
from test_framework.messages import CBlockHeader

checks = []
def check(name, actual, expected=True):
    item = dict(name=name, actual=actual, expected=expected, passed=actual == expected)
    checks.append(item)
    if not item['passed']:
        raise AssertionError(item)

def terms(x, early, late):
    tag = hashlib.sha256(b'Bitcoin mining contribution v4').digest()
    return hashlib.sha256(tag + tag + x + early + late).digest()

def main():
    with tempfile.TemporaryDirectory(prefix='contribution-review-') as tmp:
        common = ['-testactivationheight=blake2b@2', '-blake2b_headline=Contribution review', '-rdtsexpiry=2000000000']
        a = n.Node('candidate', CANDIDATE, Path(tmp), common + ['-testgatewayallocationheight=101', f'-testgatewaykeys={n.G_PUB.hex()}:{n.H_PUB.hex()}'])
        old = n.Node('parent', PARENT, Path(tmp), common)
        try:
            funding = n.next_block(a, legacy=True)
            funding.vtx[0].vout = [n.CTxOut(2500000000, n.CScript([n.OP_TRUE])) for _ in range(2)]
            n.add_witness_commitment(funding)
            refresh(funding)
            check('funding accepted', a.rpc.submitblock(funding.serialize().hex()), None)
            a.rpc.generatetodescriptor(99, 'raw(51)')
            for h in range(1, 101):
                assert old.rpc.submitblock(a.rpc.getblock(a.rpc.getblockhash(h), 0)) is None
            def spend(index, fee):
                tx = n.CTransaction()
                tx.vin = [n.CTxIn(n.COutPoint(funding.vtx[0].sha256, index))]
                tx.vout = [n.CTxOut(2500000000 - fee, n.script_to_p2wsh_script(n.CScript([n.OP_TRUE])))]
                tx.rehash()
                return tx
            x = spend(0, 1000)
            source = decode(a.rpc.getcontributionblock([x.serialize().hex()], [], x.hash)['hex'])
            proofs = []
            for i in range(19):
                b = copy.deepcopy(source)
                b.m_extranonce = i + 1
                refresh(b, True)
                proofs.append(cert(b, x.hash).hex())
            fee_delta = 400000
            for count in [0, 1, 10, 19]:
                blocks = []
                for fee in [400000, 800000]:
                    y = spend(1, fee)
                    block = decode(a.rpc.getcontributionblock([x.serialize().hex(), y.serialize().hex()], proofs[:count], '')['hex'])
                    refresh(block)
                    options = {'mode': 'proposal', 'data': block.serialize().hex(), 'rules': ['segwit', 'blake2b', 'gatewayallocation', 'nodecontributions']}
                    check(f'{count} proof fee {fee} accepted by candidate', a.rpc.getblocktemplate(options), None)
                    check(f'{count} proof fee {fee} accepted by parent', old.rpc.getblocktemplate(options), None)
                    blocks.append(block)
                finder_delta = sum(o.nValue for o in blocks[1].vtx[0].vout[:2]) - sum(o.nValue for o in blocks[0].vtx[0].vout[:2])
                total_delta = sum(o.nValue for o in blocks[1].vtx[0].vout) - sum(o.nValue for o in blocks[0].vtx[0].vout)
                check(f'{count} proof finder marginal fees', finder_delta, 20000 + 1000 * count)
                check(f'{count} proof total marginal fees', total_delta, 20000 * (count + 1))
            omitted = decode(a.rpc.getcontributionblock([x.serialize().hex()], proofs[:1], '')['hex'])
            omitted.vtx.pop()
            # Preserve inherited witness validity so this reaches the X inclusion rule.
            n.add_witness_commitment(omitted)
            refresh(omitted)
            options = {'mode': 'proposal', 'data': omitted.serialize().hex(), 'rules': ['segwit', 'blake2b', 'gatewayallocation', 'nodecontributions']}
            check('missing X control remains valid under inherited rules', old.rpc.getblocktemplate(options), None)
            check('missing X reaches contribution rejection', a.rpc.getblocktemplate(options), 'n5-missing-x')
            # The inherited node must accept actual work using the hook on all profiles.
            xraw = bytes.fromhex(x.hash)[::-1]
            commitment = terms(xraw, n.G_PUB, n.H_PUB)
            for profile in range(4):
                b = decode(a.rpc.getcontributionblock([], [], '')['hex'])
                b.m_flags = profile
                b.m_mm_rhs = int.from_bytes(commitment, 'little')
                refresh(b)
                expected_hash = b.hash
                check(f'profile {profile} hook block accepted by candidate', a.rpc.submitblock(b.serialize().hex()), None)
                check(f'profile {profile} hook block accepted by parent', old.rpc.submitblock(b.serialize().hex()), None)
                check(f'profile {profile} native work hash agrees', a.rpc.getbestblockhash(), expected_hash)
                check(f'profile {profile} inherited hook unchanged', old.rpc.getblockheader(expected_hash)['mm_rhs'], commitment.hex())
                raw = bytes([4]) + CBlockHeader(b).serialize() + xraw + n.G_PUB + n.H_PUB
                check(f'profile {profile} alternative certificate size', len(raw), 263)
                changed = copy.deepcopy(b)
                changed.m_mm_rhs ^= 1
                check(f'profile {profile} hook mutation changes work hash', changed.rehash() != b.sha256)
            for label, values in [('X', (bytes(32), n.G_PUB, n.H_PUB)),
                                  ('early key', (xraw, n.H_PUB, n.H_PUB)),
                                  ('late key', (xraw, n.G_PUB, n.G_PUB))]:
                check('alternate terms change hook: ' + label, terms(*values) != commitment)
        finally:
            try:
                a.stop()
            finally:
                old.stop()

if __name__ == '__main__':
    try:
        main()
    finally:
        (RESULTS / 'review_results.json').write_text(json.dumps(checks, indent=2) + '\n')
    print(f'{len(checks)} review checks passed')
