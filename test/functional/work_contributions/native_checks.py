#!/usr/bin/env python3
"""Real unmodified-parent vs candidate regtest nodes; no hardware or public peers."""
# Copyright (c) 2026 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.
from pathlib import Path
import copy
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from test_framework.authproxy import AuthServiceProxy, JSONRPCException
from test_framework.blocktools import create_block, create_coinbase, add_witness_commitment
from test_framework.key import ECKey
from test_framework.messages import COutPoint, CTransaction, CTxIn, CTxInWitness, CTxOut
from test_framework.script import CScript, OP_0, OP_TRUE, OP_RETURN, OP_CHECKSEQUENCEVERIFY, OP_DROP, OP_CHECKSIG, SIGHASH_ALL, SegwitV0SignatureHash
from test_framework.script_util import script_to_p2wsh_script

G_DEPTH, H_DEPTH = 6480, 52560
G_KEY, H_KEY = ECKey(), ECKey()
G_KEY.set((1).to_bytes(32, 'big'), True)
H_KEY.set((2).to_bytes(32, 'big'), True)
G_PUB = G_KEY.get_pubkey().get_bytes()
H_PUB = H_KEY.get_pubkey().get_bytes()
GENESIS_TIME = 1296688602
checks = []
nodes = []


def record(name, observed, expected=True):
    if observed != expected:
        raise AssertionError((name, observed, expected))
    checks.append({'name': name, 'observed': observed, 'expected': expected})


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Node:
    def __init__(self, name, binary, run_dir, extra=(), *, reuse=False, startup_mocktime=None):
        self.name = name
        self.directory = run_dir / name
        self.directory.mkdir(exist_ok=reuse)
        self.rpcport, self.p2pport = free_port(), free_port()
        args = [str(binary), '-regtest', '-server', '-listen=1', '-listenonion=0',
                '-discover=0', '-dnsseed=0', '-connect=0', '-persistmempool=0',
                '-fallbackfee=0.00001', '-debug=0', '-maxmempool=50', '-dbcache=100',
                '-rpcbind=127.0.0.1', '-rpcallowip=127.0.0.1', '-rpcservertimeout=600',
                f'-bind=127.0.0.1:{self.p2pport}', f'-port={self.p2pport}',
                f'-rpcport={self.rpcport}', f'-datadir={self.directory}',
                f'-mocktime={GENESIS_TIME + 60000 if startup_mocktime is None else startup_mocktime}', *extra]
        self.log = (self.directory / 'console.log').open('w')
        self.process = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT)
        nodes.append(self)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError((name, (self.directory / 'console.log').read_text()[-2500:]))
            try:
                cookie = (self.directory / 'regtest/.cookie').read_text().strip()
                self.rpc = AuthServiceProxy(f'http://{cookie}@127.0.0.1:{self.rpcport}', timeout=120)
                self.rpc.getblockcount()
                return
            except (OSError, JSONRPCException):
                time.sleep(0.05)
        raise RuntimeError('Node startup timed out')

    def stop(self):
        if self.process.poll() is None:
            try:
                self.rpc.stop()
                self.process.wait(timeout=15)
            except Exception:
                self.process.terminate()
                self.process.wait(timeout=10)
        self.log.close()
        if self.process.returncode != 0:
            output = (self.directory / 'console.log').read_text()
            raise RuntimeError(f'{self.name} exited with {self.process.returncode}: {output[-8000:]}')


def redeem(pub, depth):
    return CScript([depth, OP_CHECKSEQUENCEVERIFY, OP_DROP, pub, OP_CHECKSIG])


def outputs(value, g=G_PUB, h=H_PUB):
    out = []
    if value // 2:
        out.append(CTxOut(value // 2, script_to_p2wsh_script(redeem(g, G_DEPTH))))
    if value - value // 2:
        out.append(CTxOut(value - value // 2, script_to_p2wsh_script(redeem(h, H_DEPTH))))
    out.append(CTxOut(0, CScript([OP_RETURN, b'GWA1' + g + h])))
    return out


def next_block(node, txs=(), fee=0, value=None, g=G_PUB, h=H_PUB, legacy=False):
    tip = node.rpc.getbestblockhash()
    height = node.rpc.getblockcount() + 1
    coinbase = create_coinbase(height)
    claimed = coinbase.vout[0].nValue + fee if value is None else value
    if not legacy:
        coinbase.vout = outputs(claimed, g, h)
    coinbase.rehash()
    block = create_block(int(tip, 16), coinbase, node.rpc.getblockheader(tip)['time'] + 1,
                         height=height, txlist=list(txs))
    add_witness_commitment(block)
    block.solve()
    return block


def remine(block):
    block.vtx[0].rehash()
    block.hashMerkleRoot = block.calc_merkle_root()
    block.nNonce = 0
    block.solve()
