# Copyright (c) 2026 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.
"""Explicit binaries and output directory; never write fixture outputs into source."""
import os
from pathlib import Path
CANDIDATE = Path(os.environ['CONTRIBUTION_BITCOIND']).resolve()
PARENT = Path(os.environ['CONTRIBUTION_PARENT_BITCOIND']).resolve()
RESULTS = Path(os.environ['CONTRIBUTION_RESULTS']).resolve()
RESULTS.mkdir(parents=True, exist_ok=True)
