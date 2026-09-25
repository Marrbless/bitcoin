#!/usr/bin/env python3
# Distributed under the MIT software license, see the accompanying COPYING.
"""Bounded hostile socket traffic with interleaved actual block production."""
import json
import os
import random
import socket
import tempfile
import time
from pathlib import Path

import native_checks as n
from settings import CANDIDATE, RESULTS
from test_endpoint_blake import SiaMiner, wait

checks = []
metrics = {}
def check(name, actual, expected=True):
    item = dict(name=name, actual=actual, expected=expected, passed=actual == expected)
    checks.append(item)
    if not item['passed']:
        raise AssertionError(item)

def rss(pid):
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        if line.startswith('VmRSS:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('Missing process RSS')

def main():
    seconds = int(os.environ.get('CONTRIBUTION_STRESS_SECONDS', '120'))
    if not 10 <= seconds <= 3600:
        raise ValueError('Stress duration must be between 10 and 3600 seconds')
    with tempfile.TemporaryDirectory(prefix='contribution-stress-') as tmp:
        a = n.Node('candidate', CANDIDATE, Path(tmp), ['-testactivationheight=blake2b@2', '-blake2b_headline=Contribution stress', '-rdtsexpiry=2000000000', '-testgatewayallocationheight=101', f'-testgatewaykeys={n.G_PUB.hex()}:{n.H_PUB.hex()}'])
        miner = None
        try:
            a.rpc.generatetodescriptor(100, 'raw(51)')
            port = a.rpc.startminingendpoint([], '')
            miner = SiaMiner(port)
            miner.login()
            initial_rss = rss(a.process.pid)
            peak_rss = initial_rss
            rng = random.Random(8675309)
            frames = [b'{not json}\n', b'[]\n', b'null\n', b'{}\n', b'[' * 600 + b'0' + b']' * 600 + b'\n', b'x' * 131073]
            attempts = 0
            blocks = 0
            max_block_ms = 0.0
            start = time.monotonic()
            deadline = start + seconds
            while time.monotonic() < deadline:
                frame = frames[attempts % len(frames)]
                if attempts % 7 == 0:
                    proof = bytes(rng.randrange(256) for _ in range(rng.randrange(220, 689)))
                    frame = (json.dumps({'id': attempts, 'method': 'mining.contribute', 'params': [proof.hex(), []]}) + '\n').encode()
                attacker = socket.create_connection(('127.0.0.1', port), timeout=2)
                attacker.settimeout(2)
                try:
                    # Separate writes exercise partial framing as well as oversized input.
                    attacker.sendall(frame[:11])
                    attacker.sendall(frame[11:])
                    attacker.shutdown(socket.SHUT_WR)
                    while attacker.recv(4096):
                        pass
                except (ConnectionError, TimeoutError):
                    pass
                finally:
                    attacker.close()
                attempts += 1
                if attempts % 16 == 0:
                    params, digest = miner.find(True, seed=attempts)
                    oldjob = miner.job[0]
                    before = time.monotonic()
                    assert miner.request('mining.submit', params)['result'] is True
                    wait(lambda: a.rpc.getbestblockhash() == digest)
                    miner.nextjob(oldjob)
                    max_block_ms = max(max_block_ms, (time.monotonic() - before) * 1000)
                    blocks += 1
                    miner.trace.clear()
                    peak_rss = max(peak_rss, rss(a.process.pid))
            check('stress exercised all malformed frame families', attempts >= 16)
            check('actual block production continued during attack', blocks >= 1)
            check('node survived hostile connections', a.process.poll(), None)
            check('endpoint has no worker error', a.rpc.getminingendpointinfo()['error'], '')
            check('malformed traffic earned no contributions', a.rpc.getminingendpointinfo()['proofs'], [])
            check('RSS growth stayed under fixture budget', peak_rss - initial_rss < 128 * 1024 * 1024)
            metrics.update(duration_seconds=round(time.monotonic() - start, 3), connections=attempts, accepted_blocks=blocks,
                           initial_rss_bytes=initial_rss, peak_rss_bytes=peak_rss, max_block_response_ms=round(max_block_ms, 3),
                           seed=8675309, scope='Loopback fixture; not an Internet capacity or denial of service guarantee')
        finally:
            if miner:
                miner.close()
            a.stop()

if __name__ == '__main__':
    try:
        main()
    finally:
        (RESULTS / 'stress_results.json').write_text(json.dumps(checks, indent=2) + '\n')
        (RESULTS / 'stress_metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
    print(json.dumps(metrics), flush=True)
    print(f'{len(checks)} stress checks passed')
