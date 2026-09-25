#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying COPYING.
"""Fixed v4 certificates, independent Python commitments and actual BLAKE work."""
import copy
import hashlib
import io
import json
import tempfile
from pathlib import Path

import native_checks as n
from settings import CANDIDATE, PARENT, RESULTS
from test_framework.messages import CBlock, CBlockHeader, uint256_from_compact

checks = []
def check(name, actual, expected=True):
    checks.append(dict(name=name, actual=actual, expected=expected, passed=actual == expected))
    if actual != expected:
        raise AssertionError(checks[-1])

def decode(raw):
    b = CBlock()
    b.deserialize(io.BytesIO(bytes.fromhex(raw)))
    b.rehash()
    for tx in b.vtx:
        tx.rehash()
    return b

def refresh(b, weak=False):
    for tx in b.vtx:
        tx.rehash()
    b.hashMerkleRoot = b.calc_merkle_root()
    b.m_txcount = len(b.vtx) if b.m_header_v2 else 0
    target = uint256_from_compact(b.nBits)
    while True:
        h = b.rehash()
        if (target < h <= min(target * 20, 2**256 - 1)) if weak else h <= target:
            return b
        b.nNonce += 1

def commitment(x, early=n.G_PUB, late=n.H_PUB):
    tag = hashlib.sha256(b'Bitcoin mining contribution v4').digest()
    return hashlib.sha256(tag + tag + bytes.fromhex(x)[::-1] + early + late).digest()

def cert(b, x, early=n.G_PUB, late=n.H_PUB):
    assert b.m_header_v2
    return bytes([4]) + CBlockHeader(b).serialize() + bytes.fromhex(x)[::-1] + early + late

def fragment(o):
    return b'N4PF' in bytes(o.scriptPubKey)[:10]

def fragment_data(o):
    return next(x for x in n.CScript(o.scriptPubKey) if isinstance(x, bytes))

def setdata(o, data):
    o.scriptPubKey = n.CScript([n.OP_RETURN, data])

def main():
    with tempfile.TemporaryDirectory(prefix='contribution-v4-') as tmp:
        common = ['-testactivationheight=blake2b@2', '-blake2b_headline=Contribution v4', '-rdtsexpiry=2000000000']
        a = n.Node('candidate', CANDIDATE, Path(tmp), common + ['-testgatewayallocationheight=101', f'-testgatewaykeys={n.G_PUB.hex()}:{n.H_PUB.hex()}'])
        old = n.Node('parent', PARENT, Path(tmp), common)
        try:
            funding = n.next_block(a, legacy=True)
            n.add_witness_commitment(funding)
            refresh(funding)
            check('funding accepted', a.rpc.submitblock(funding.serialize().hex()), None)
            a.rpc.generatetodescriptor(99, 'raw(51)')
            for height in range(1, 101):
                assert old.rpc.submitblock(a.rpc.getblock(a.rpc.getblockhash(height), 0)) is None
            check('parent and candidate tips agree', old.rpc.getbestblockhash(), a.rpc.getbestblockhash())
            tx = n.CTransaction()
            tx.vin = [n.CTxIn(n.COutPoint(funding.vtx[0].sha256, 0))]
            tx.vout = [n.CTxOut(funding.vtx[0].vout[0].nValue - 1000, n.script_to_p2wsh_script(n.CScript([n.OP_TRUE])))]
            tx.rehash()
            def assemble(proofs=(), x=tx.hash, txs=None):
                result = a.rpc.getcontributionblock([t.serialize().hex() for t in ([tx] if txs is None else txs)], [p.hex() for p in proofs], x)
                b = decode(result['hex'])
                if x:
                    assert bytes.fromhex(result['candidateproof']) == cert(b, x)
                    assert b.m_mm_rhs.to_bytes(32, 'little') == commitment(x)
                return b
            def proposal(b, node=a):
                refresh(b)
                return node.rpc.getblocktemplate({'mode': 'proposal', 'data': b.serialize().hex(), 'rules': ['segwit', 'blake2b', 'gatewayallocation', 'nodecontributions']})
            def rejected(f):
                try:
                    f()
                    return False
                except n.JSONRPCException:
                    return True
            source = assemble()
            check('candidate uses inherited BLAKE header', source.m_header_v2)
            check('header commits exact tagged terms', source.m_mm_rhs.to_bytes(32, 'little').hex(), commitment(tx.hash).hex())
            check('source no longer has padded coinbase commitment', all(b'N8C0' not in bytes(o.scriptPubKey) for o in source.vtx[0].vout))
            check('all source data outputs within83', all(len(o.scriptPubKey) <= 83 for o in source.vtx[0].vout))
            proofs = []
            for profile in range(4):
                b = copy.deepcopy(source)
                b.m_flags = profile | 4
                b.m_time_offset, b.m_nonce2, b.m_nonce3 = 13, 17, 23
                b.m_extranonce, b.m_xor_key = 12345 + profile, 98765
                b.m_xor_key_mask_clear_bits = [0, 7, 128, 255][profile]
                refresh(b, True)
                p = cert(b, tx.hash)
                proofs.append(p)
                check(f'profile {profile} fixed certificate size', len(p), 263)
                check(f'profile {profile} contribution accepted', proposal(assemble([p])), None)
                check(f'profile {profile} parent accepts settlement', proposal(assemble([p]), old), None)
            # Coinbase size no longer changes evidence size or needs imported state.
            for length in [0, 1, 31, 63]:
                b = copy.deepcopy(source)
                b.vtx[0].vin[0].scriptSig = n.CScript([101, bytes(length)])
                refresh(b, True)
                p = cert(b, tx.hash)
                check(f'coinbase variation {length} keeps size', len(p), 263)
                check(f'coinbase variation {length} accepted', proposal(assemble([p])), None)
            while len(proofs) < 19:
                b = copy.deepcopy(source)
                b.m_extranonce = len(proofs) + 100
                refresh(b, True)
                proofs.append(cert(b, tx.hash))
            cap = assemble(proofs)
            check('nineteen proofs accepted', proposal(copy.deepcopy(cap)), None)
            check('nineteen proof settlement parent compatible', proposal(copy.deepcopy(cap), old), None)
            check('maximum evidence uses70 fragments', sum(fragment(o) for o in cap.vtx[0].vout), 70)
            check('maximum evidence body4998 bytes', sum(len(fragment_data(o)) - 8 for o in cap.vtx[0].vout if fragment(o)), 4998)
            check('maximum output script83 bytes', max(len(o.scriptPubKey) for o in cap.vtx[0].vout), 83)
            check('twentieth proof rejected', rejected(lambda: assemble(proofs + [proofs[0]])))
            check('duplicate proof rejected', rejected(lambda: assemble([proofs[0], proofs[0]])))
            check('full inventory reward including fees', sum(o.nValue for o in cap.vtx[0].vout), 20 * ((5000000000 + 1000) // 20))
            one = assemble([proofs[0]])
            positions = [i for i, o in enumerate(one.vtx[0].vout) if fragment(o)]
            check('one proof uses4 fragments', len(positions), 4)
            mutations = [
                ('missing fragment', lambda b: b.vtx[0].vout.pop(positions[0])),
                ('duplicate fragment', lambda b: b.vtx[0].vout.insert(positions[0], copy.deepcopy(b.vtx[0].vout[positions[0]]))),
                ('noncontiguous fragments', lambda b: b.vtx[0].vout.insert(positions[0]+1, n.CTxOut(0, n.CScript([n.OP_RETURN])))),
                ('wrong payout', lambda b: setattr(b.vtx[0].vout[0], 'nValue', b.vtx[0].vout[0].nValue-1)),
                ('oversize return', lambda b: b.vtx[0].vout.append(n.CTxOut(0, n.CScript([n.OP_RETURN, bytes(81)])))),
            ]
            for name, mutate in mutations:
                b = copy.deepcopy(one)
                mutate(b)
                check(name + ' rejected', proposal(b) is not None)
            for name, mutate in [
                ('reordered', lambda d: d[:4]+b'\1\0'+d[6:]),
                ('zero count', lambda d: d[:6]+b'\0\0'+d[8:]),
                ('oversized count', lambda d: d[:6]+b'\xff\xff'+d[8:]),
                ('short nonfinal', lambda d: d[:-1]),
                ('extra final byte', lambda d: d+b'\0'),
                ('legacy carrier', lambda d: b'N8PF'+d[4:]),
            ]:
                b = copy.deepcopy(one)
                pos = positions[-1] if name == 'extra final byte' else positions[0]
                setdata(b.vtx[0].vout[pos], mutate(fragment_data(b.vtx[0].vout[pos])))
                check(name + ' rejected', proposal(b) is not None)
            for name, offset in [('version', 0), ('parent', 5), ('bits', 73), ('height', 129), ('hook', 133), ('X', 165), ('early key', 197), ('late key', 230)]:
                q = bytearray(proofs[0])
                q[offset] ^= 1
                check('changed ' + name + ' rejected', rejected(lambda: assemble([bytes(q)])))
            for name, mutate in [('height', lambda b: setattr(b, 'm_height', 102)), ('reserved flags', lambda b: setattr(b, 'm_flags', 0xc0)), ('past time', lambda b: setattr(b, 'nTime', 1))]:
                b = copy.deepcopy(source)
                mutate(b)
                refresh(b, True)
                check('fresh work with invalid ' + name + ' rejected', rejected(lambda: assemble([cert(b, tx.hash)])))
            legacy = bytearray(proofs[0])
            legacy[4] &= 0x7f  # Clear the inherited v2 serialization flag at fixed total size.
            for name, raw in [('truncated', proofs[0][:-1]), ('trailing', proofs[0]+b'\0'), ('old version', bytes([3])+proofs[0][1:]), ('legacy header', bytes(legacy))]:
                check(name + ' certificate rejected', rejected(lambda: assemble([raw])))
            b = copy.deepcopy(source)
            refresh(b)
            check('full block result cannot be paid as weak', rejected(lambda: assemble([cert(b, tx.hash)])))
            omitted = copy.deepcopy(one)
            omitted.vtx.pop()
            n.add_witness_commitment(omitted)
            check('missing X control valid for parent', proposal(omitted, old), None)
            check('missing X specifically rejected', proposal(omitted), 'n5-missing-x')
            refresh(cap)
            raw = cap.serialize().hex()
            check('actual settlement accepted', a.rpc.submitblock(raw), None)
            check('actual settlement parent accepted', old.rpc.submitblock(raw), None)
            check('settled tips agree', a.rpc.getbestblockhash(), old.rpc.getbestblockhash())
            check('old parent proof expires', rejected(lambda: assemble([proofs[0]], x='', txs=[])))
            a.rpc.invalidateblock(cap.hash)
            check('proof eligible on restored parent', proposal(assemble([proofs[0]])), None)
            a.rpc.reconsiderblock(cap.hash)
            check('settlement restored', a.rpc.getbestblockhash(), cap.hash)
            (RESULTS/'settled_block.hex').write_text(raw+'\n')
            (RESULTS/'example_proof.hex').write_text(proofs[0].hex()+'\n')
            (RESULTS/'sizes.json').write_text(json.dumps({'certificate_bytes': 263, 'nineteen_proof_block_bytes': len(cap.serialize()), 'coinbase_bytes': len(cap.vtx[0].serialize()), 'proof_fragments': 70, 'evidence_body_bytes': 4998, 'max_output_script_bytes': 83}, indent=2)+'\n')
        finally:
            try:
                a.stop()
            finally:
                old.stop()

if __name__ == '__main__':
    try:
        main()
    finally:
        (RESULTS/'results.json').write_text(json.dumps(checks, indent=2)+'\n')
    print(f'{len(checks)} native BLAKE checks passed')
