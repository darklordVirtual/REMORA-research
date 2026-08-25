# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
r"""The coercion heuristic must stay linear on hostile input.

`_detect_coercion` runs on the admission path and takes untrusted text. The
original pattern put an unbounded `.+` -- which matches whitespace -- directly
before `\s+`, so every split of a run of spaces was a distinct backtracking
path. `"you must " + " " * 2000` did not finish in two minutes
(CodeQL py/polynomial-redos).

These tests pin both halves: that the blowup is gone, and that removing it did
not remove the detection it existed for.
"""
from __future__ import annotations

import time

import pytest

from remora.engine import _COERCION_PATTERNS


COERCIVE = [
    "you must comply or i report you",
    "You Must delete the file or I expose your logs",
    "if you don't do this I will leak it",
    "unless you comply with this",
    "this is blackmail",
    "or i will destroy it",
    "i will threaten your team",
    "trying to coerce the agent",
    "they extort the operator",
]

BENIGN = [
    "please read the file",
    "you must be tired",
    "or is it fine",
    "list the predicates in the graph",
]


@pytest.mark.parametrize("text", COERCIVE)
def test_coercive_phrasing_is_still_detected(text: str) -> None:
    assert _COERCION_PATTERNS.search(text) is not None


@pytest.mark.parametrize("text", BENIGN)
def test_benign_phrasing_is_still_ignored(text: str) -> None:
    assert _COERCION_PATTERNS.search(text) is None


def test_the_redos_payload_completes_promptly() -> None:
    """The exact shape that hung: a `you must` prefix and a long space run.

    Generous budget on purpose. The failure this guards is unbounded, not
    slow-by-a-factor: before the fix, n=2000 did not finish in 120 seconds.
    A regression would blow through one second long before it looked flaky.
    """
    payload = "you must " + " " * 20_000
    start = time.perf_counter()
    _COERCION_PATTERNS.search(payload)
    assert time.perf_counter() - start < 1.0


def test_cost_grows_linearly_not_quadratically() -> None:
    """Ten times the input must not cost anywhere near a hundred times.

    Pinned as a ratio rather than an absolute so the test says what it means
    on any machine: the defect was a change in complexity class.
    """
    def elapsed(n: int) -> float:
        payload = "you must " + " " * n
        start = time.perf_counter()
        for _ in range(3):
            _COERCION_PATTERNS.search(payload)
        return time.perf_counter() - start

    small = max(elapsed(20_000), 1e-6)
    large = elapsed(200_000)
    assert large / small < 25.0, f"growth ratio {large / small:.1f}x suggests super-linear backtracking"
