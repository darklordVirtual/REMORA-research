# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""MockOracle is documented as deterministic; it must be so across processes.

It seeded its RNG with ``hash(name)``, which Python salts per process
(PYTHONHASHSEED), so two runs of the same experiment gave different
per-item traces (found by the quality program's reproduction probe on
experiments/end_to_end_n500_v2.py).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNIPPET = (
    "from remora.oracles.mock import MockOracle\n"
    "o = MockOracle(name='mock-1')\n"
    "print([o._call('q')[0] for _ in range(5)])\n"
)


def _run(seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT)}
    return subprocess.run([sys.executable, "-c", SNIPPET], env=env, capture_output=True,
                          text=True, check=True).stdout


def test_same_answers_under_different_hash_seeds():
    assert _run("1") == _run("2") == _run("12345")
