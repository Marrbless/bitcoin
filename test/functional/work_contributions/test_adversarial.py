#!/usr/bin/env python3
# Distributed under the MIT software license, see the accompanying COPYING.
"""Adversarial settlement and endpoint tests using actual private regtest work."""
import copy
import json
import os
import random
import socket
import struct
import tempfile
import time
from pathlib import Path

import native_checks as n
from settings import CANDIDATE, PARENT, RESULTS
from test_blake import cert, decode, fragment, fragment_data, refresh
from test_endpoint_blake import SiaMiner, wait

checks = []
def check(name, actual, expected=True):
    item = dict(name=name, actual=actual, expected=expected, passed=actual == expected)
    checks.append(item)
    if not item['passed']:
        raise AssertionError(item)

def main():
    with tempfile.TemporaryDirectory(prefix='contribution-audit-') as tmp:
        run = Path(tmp)
        common = ['-testactivationheight=blake2b@2', '-blake2b_headline=Contribution audit', '-rdtsexpiry=2000000000']
        keys = f'-testgatewaykeys={n.G_PUB.hex()}:{n.H_PUB.hex()}'
        a = n.Node('candidate', CANDIDATE, run, common + ['-testgatewayallocationheight=101', keys])
        old = n.Node('parent', PARENT, run, common)
        miners = []
        try:
            funding = n.next_block(a, legacy=True)
            check('funding block accepted', a.rpc.submitblock(funding.serialize().hex()), None)
            a.rpc.generatetodescriptor(99, 'raw(51)')
            for height in range(1, 101):
                assert old.rpc.submitblock(a.rpc.getblock(a.rpc.getblockhash(height), 0)) is None
            x = n.CTransaction()
            x.vin = [n.CTxIn(n.COutPoint(funding.vtx[0].sha256, 0))]
            x.vout = [n.CTxOut(funding.vtx[0].vout[0].nValue - 1237, n.script_to_p2wsh_script(n.CScript([n.OP_TRUE])))]
            x.rehash()
            def assemble(proofs=(), own=x.hash):
                return decode(a.rpc.getcontributionblock([x.serialize().hex()], [p.hex() for p in proofs], own)['hex'])
            source = assemble()
            refresh(source, True)
            proof = cert(source, x.hash)
            good = assemble([proof], '')
            def proposal(b, node=None):
                if node is None:
                    node = a
                refresh(b)
                return node.rpc.getblocktemplate({'mode': 'proposal', 'data': b.serialize().hex(), 'rules': ['segwit', 'blake2b', 'gatewayallocation', 'nodecontributions']})
            check('valid control', proposal(copy.deepcopy(good)), None)
            check('valid control parent compatibility', proposal(copy.deepcopy(good), old), None)
            # Multiple allocations can legally share a script. Rounding is per allocation.
            grouped = copy.deepcopy(good)
            sums = {}
            zero = []
            for out in grouped.vtx[0].vout:
                if out.nValue:
                    script = bytes(out.scriptPubKey)
                    sums[script] = sums.get(script, 0) + out.nValue
                else:
                    zero.append(out)
            grouped.vtx[0].vout = [n.CTxOut(v, n.CScript(k)) for k, v in sums.items()] + zero
            check('aggregated recipient outputs accepted', proposal(grouped), None)
            split = copy.deepcopy(grouped)
            out = split.vtx[0].vout[0]
            out.nValue -= 1
            split.vtx[0].vout.insert(1, n.CTxOut(1, out.scriptPubKey))
            check('split identical recipient output accepted', proposal(split), None)
            for name, mutate in [
                ('early lock shortened', lambda b: setattr(b.vtx[0].vout[0], 'scriptPubKey', n.script_to_p2wsh_script(n.redeem(n.G_PUB, n.G_DEPTH - 1)))),
                ('finder key substituted', lambda b: setattr(b.vtx[0].vout[2], 'scriptPubKey', n.CScript([n.OP_RETURN, b'GWA1' + n.H_PUB + n.H_PUB]))),
                ('one sat redirected', lambda b: (setattr(b.vtx[0].vout[0], 'nValue', b.vtx[0].vout[0].nValue - 1), b.vtx[0].vout.append(n.CTxOut(1, n.script_to_p2wsh_script(n.CScript([n.OP_TRUE])))))),
                ('assigned reward underclaimed', lambda b: setattr(b.vtx[0].vout[0], 'nValue', b.vtx[0].vout[0].nValue - 1)),
                ('finder metadata duplicated', lambda b: b.vtx[0].vout.append(copy.deepcopy(b.vtx[0].vout[2]))),
            ]:
                b = copy.deepcopy(good)
                mutate(b)
                check(name + ' rejected by proposal', proposal(b) is not None)
                check(name + ' allowed by parent', proposal(b, old), None)
            # Every strict prefix of a valid certificate must fail; exercise the real block parser.
            def replace_evidence(raw):
                b = copy.deepcopy(good)
                b.vtx[0].vout = [o for o in b.vtx[0].vout if not fragment(o)]
                count = (len(raw) + 71) // 72
                for i in range(count):
                    payload = b'N4PF' + struct.pack('<HH', i, count) + raw[i * 72:(i + 1) * 72]
                    b.vtx[0].vout.append(n.CTxOut(0, n.CScript([n.OP_RETURN, payload])))
                return b
            truncations = 0
            for size in range(len(proof)):
                body = bytes([1]) + proof[:size]
                assert proposal(replace_evidence(body)) is not None, size
                truncations += 1
            check('all certificate truncations rejected', truncations, len(proof))
            # Deterministic random bytes are bounded and must not credit the expected contribution.
            rng = random.Random(20260925)
            corpus_size = int(os.environ.get('CONTRIBUTION_FUZZ_CASES', '256'))
            if not 256 <= corpus_size <= 100000:
                raise ValueError('Random corpus size must be between 256 and 100000')
            for i in range(corpus_size):
                size = rng.randrange(1, 700)
                raw = bytes(rng.randrange(256) for _ in range(size))
                if i % 2:
                    structured = bytearray(proof)
                    offset = rng.randrange(165, 263)
                    structured[offset] ^= rng.randrange(1, 256)
                    raw = bytes(structured)
                assert proposal(replace_evidence(bytes([1]) + raw)) is not None, i
            check('bounded random certificate corpus rejected', corpus_size, corpus_size)
            for name, offset, replacement in [
                ('early recipient', -66, n.H_PUB), ('late recipient', -33, n.G_PUB),
                ('transaction', -98, bytes(32)), ('header hook', -130, bytes(32)),
            ]:
                raw = bytearray(proof)
                start = len(raw) + offset
                raw[start:start + len(replacement)] = replacement
                body = bytes([1]) + raw
                check('reused work with changed ' + name + ' rejected', proposal(replace_evidence(body)) is not None)
            # Peer validation must be bounded across connections, while actual block solutions remain usable.
            port = a.rpc.startminingendpoint([x.serialize().hex()], x.hash)
            miner = SiaMiner(port)
            miners.append(miner)
            miner.login()
            poisoned = bytearray(proof)
            poisoned[-1] ^= 1
            attacker = socket.create_connection(('127.0.0.1', port), timeout=5)
            attacker.settimeout(15)
            requests = b''.join((json.dumps({'id': i, 'method': 'mining.contribute', 'params': [poisoned.hex(), [x.serialize().hex()]]}) + '\n').encode() for i in range(96))
            attacker.sendall(requests)
            with attacker.makefile('rb') as stream:
                replies = [json.loads(stream.readline()) for _ in range(96)]
            attacker.close()
            check('poisoned batch has no accepted proofs', all(r['result'] is False for r in replies))
            check('hostile validation batch is rate limited', any('validation rate limit' in str(r['error']) for r in replies))
            check('rejected batch leaves proof inbox empty', a.rpc.getminingendpointinfo()['proofs'], [])
            time.sleep(1.1)
            check('valid contribution accepted after budget replenishes', miner.request('mining.contribute', [proof.hex(), [x.serialize().hex()]])['result'])
            oldjob = miner.job[0]
            miner.nextjob(oldjob)
            # A second authorization must not rebuild arbitrary candidates repeatedly.
            check('repeat authorization rejected', miner.request('mining.authorize', ['fixture.worker', ''])['result'], False)
            params, digest = miner.find(True, seed=501)
            check('full block survives hostile contribution traffic', miner.request('mining.submit', params)['result'])
            wait(lambda: a.rpc.getblockcount() == 101)
            check('accepted block is submitted work', a.rpc.getbestblockhash(), digest)
            check('attack recovery block accepted by parent', old.rpc.submitblock(a.rpc.getblock(digest, 0)), None)
            miner.close()
            miners.clear()
            a.stop()
            a = n.Node('candidate', CANDIDATE, run, common + ['-testgatewayallocationheight=101', keys, '-reindex-chainstate=1'], reuse=True)
            wait(lambda: a.rpc.getblockcount() == 101, seconds=60)
            check('chainstate reindex reproduces settlement tip', a.rpc.getbestblockhash(), digest)
            a.rpc.invalidateblock(digest)
            check('reindex then reorg restores exact parent', a.rpc.getblockcount(), 100)
            check('earned proof valid after restored parent', a.rpc.getcontributionblock([x.serialize().hex()], [proof.hex()], '')['proofs'], 1)
            a.rpc.reconsiderblock(digest)
            check('reconsider restores settled chain after reindex', a.rpc.getbestblockhash(), digest)
            boundary_parent = a.rpc.getblockhash(100)
            for node in (a, old):
                node.rpc.invalidateblock(boundary_parent)
            check('reorg crosses activation boundary', a.rpc.getblockcount(), 99)
            alternate = n.create_block(int(a.rpc.getbestblockhash(), 16), n.create_coinbase(100),
                                       a.rpc.getblockheader(a.rpc.getbestblockhash())['time'] + 2,
                                       height=100, header_v2=True)
            n.add_witness_commitment(alternate)
            refresh(alternate)
            check('ordinary reward valid below activation after reorg', a.rpc.submitblock(alternate.serialize().hex()), None)
            check('alternate parent accepted by inherited node', old.rpc.submitblock(alternate.serialize().hex()), None)
            unrestricted = n.create_block(int(a.rpc.getbestblockhash(), 16), n.create_coinbase(101),
                                          alternate.nTime + 1, height=101, header_v2=True)
            n.add_witness_commitment(unrestricted)
            check('unrestricted reward still allowed by parent', proposal(unrestricted, old), None)
            check('activation reapplied on alternate branch', proposal(unrestricted) is not None)
            active = decode(a.rpc.getcontributionblock([], [], '')['hex'])
            refresh(active)
            check('restricted reward accepted on alternate branch', a.rpc.submitblock(active.serialize().hex()), None)
            check('alternate activation block accepted by parent', old.rpc.submitblock(active.serialize().hex()), None)
            check('nodes agree after activation boundary reorg', a.rpc.getbestblockhash(), old.rpc.getbestblockhash())
        finally:
            for miner in miners:
                miner.close()
            a.stop()
            old.stop()

if __name__ == '__main__':
    try:
        main()
    finally:
        (RESULTS / 'adversarial_results.json').write_text(json.dumps(checks, indent=2) + '\n')
    print(f'{len(checks)} adversarial checks passed')
