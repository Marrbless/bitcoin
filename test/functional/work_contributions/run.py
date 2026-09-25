#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.
"""Run the standalone private-regtest contribution research suites."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bitcoind', type=Path, required=True)
parser.add_argument('--parent-bitcoind', type=Path, required=True)
parser.add_argument('--results', type=Path, required=True)
parser.add_argument('--extended', action='store_true', help='Also mine and validate both real reward maturity boundaries')
parser.add_argument('--stress', action='store_true', help='Also run bounded hostile socket traffic during block production')
parser.add_argument('--review', action='store_true', help='Also check marginal fees, the inherited hook and temporary maturity overlap')
args = parser.parse_args()
for binary in (args.bitcoind, args.parent_bitcoind):
    if not binary.is_file():
        parser.error(f'Missing binary: {binary}')
output = args.results.resolve()
if output.exists() and any(output.iterdir()):
    parser.error('Use a new or empty results directory to preserve earlier evidence')
output.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, CONTRIBUTION_BITCOIND=str(args.bitcoind.resolve()),
           CONTRIBUTION_PARENT_BITCOIND=str(args.parent_bitcoind.resolve()),
           CONTRIBUTION_RESULTS=str(output), PYTHONDONTWRITEBYTECODE='1')
root = Path(__file__).resolve().parent
summary = {'binaries': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in
                       [('candidate', args.bitcoind), ('parent', args.parent_bitcoind)]}, 'suites': []}
suites = [('test_blake.py', 'results.json'),
          ('test_sha_boundary.py', 'sha_results.json'),
          ('test_endpoint_blake.py', 'endpoint_results.json'),
          ('test_adversarial.py', 'adversarial_results.json')]
if args.extended:
    suites.append(('test_maturity.py', 'maturity_results.json'))
if args.stress:
    suites.append(('test_stress.py', 'stress_results.json'))
if args.review:
    suites.extend([('test_review.py', 'review_results.json'),
                   ('test_maturity_overlap.py', 'maturity_overlap_results.json')])
try:
    for suite, result in suites:
        with (output / (suite + '.log')).open('w') as log:
            process = subprocess.run([sys.executable, str(root / suite)], env=env,
                                     stdout=log, stderr=subprocess.STDOUT,
                                     timeout={'test_maturity.py': 1800, 'test_maturity_overlap.py': 1800,
                                              'test_stress.py': 3900}.get(suite, 600))
        records = json.loads((output / result).read_text()) if (output / result).exists() else []
        entry = {'suite': suite, 'returncode': process.returncode, 'checks': len(records),
                 'passed': process.returncode == 0 and bool(records) and all(x['passed'] for x in records)}
        summary['suites'].append(entry)
        print(json.dumps(entry), flush=True)
        if not entry['passed']:
            raise SystemExit(f'Failed: see {output / (suite + ".log")}')
finally:
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
