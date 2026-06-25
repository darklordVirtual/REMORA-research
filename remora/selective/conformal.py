# Author: Stian Skogbrott
# License: Apache-2.0
"""Split-conformal calibration for selective prediction.

Implements the calibration leg of split-conformal risk control:
- partition holdout into calibration/test
- find smallest threshold tau s.t. empirical risk on calibration <= target
- coverage at a threshold over an arbitrary score vector

Validity argument: under exchangeability of calibration and test draws, the
empirical risk on calibration is a Beta(k, n-k+1)-distributed estimator of the
true risk on the population from which both were drawn (Vovk et al.). The
threshold returned here is the empirical lower bound; for finite-sample
correction the caller should pass target_risk - delta (Clopper-Pearson margin)
computed externally if a one-sided guarantee is required.
"""
from __future__ import annotations

import random
from typing import Sequence


UNATTAINABLE_THRESHOLD: float = 1.01
"""Sentinel returned by conformal_threshold when no threshold satisfies the
target risk. Consumers MUST treat any value > 1.0 as 'no acceptance possible'
and route to abstain. The value 1.01 is chosen so that any real score in [0, 1]
satisfies `score < UNATTAINABLE_THRESHOLD` and so a single numeric comparison
(`> 1.0`) detects the sentinel without requiring exact equality."""


def split_calibration(
    scores: Sequence[float],
    labels: Sequence[bool],
    cal_fraction: float = 0.6,
    seed: int | None = 0,
) -> tuple[tuple[list[float], list[bool]], tuple[list[float], list[bool]]]:
    """Random split into (calibration, test) halves.

    Returns ((cal_scores, cal_labels), (test_scores, test_labels)).
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels must have same length")
    if not 0.0 < cal_fraction < 1.0:
        raise ValueError("cal_fraction must be in (0, 1)")
    n = len(scores)
    idx = list(range(n))
    rng = random.Random(seed)
    rng.shuffle(idx)
    cut = int(round(n * cal_fraction))
    cal_idx = idx[:cut]
    test_idx = idx[cut:]
    cal = ([scores[i] for i in cal_idx], [labels[i] for i in cal_idx])
    test = ([scores[i] for i in test_idx], [labels[i] for i in test_idx])
    return cal, test


def conformal_threshold(
    scores: Sequence[float],
    labels: Sequence[bool],
    target_risk: float,
) -> float:
    """Smallest threshold whose empirical risk on (scores, labels) is <= target_risk.

    Returns UNATTAINABLE_THRESHOLD if no threshold satisfies the target (caller
    should abstain). Tied scores are processed as a single block: a candidate
    threshold is only committed after consuming every item at that score,
    because callers select acceptance with `s >= threshold` and would otherwise
    accept all tied items even when only a prefix of them respected the target.
    """
    if not 0.0 <= target_risk <= 1.0:
        raise ValueError("target_risk must be in [0, 1]")
    if len(scores) != len(labels):
        raise ValueError("scores and labels must have same length")
    if not scores:
        return UNATTAINABLE_THRESHOLD
    ranked = sorted(zip(scores, labels), key=lambda x: x[0], reverse=True)
    accepted = 0
    wrong = 0
    best_threshold = UNATTAINABLE_THRESHOLD
    n = len(ranked)
    i = 0
    while i < n:
        # Consume the entire block of items sharing the current score before
        # evaluating risk, since `s >= threshold` would accept all of them.
        s = ranked[i][0]
        j = i
        while j < n and ranked[j][0] == s:
            accepted += 1
            if not ranked[j][1]:
                wrong += 1
            j += 1
        risk = wrong / accepted
        if risk <= target_risk:
            best_threshold = float(s)
        i = j
    return best_threshold


def coverage_at_threshold(scores: Sequence[float], threshold: float) -> float:
    """Fraction of items with score >= threshold."""
    if not scores:
        return 0.0
    return sum(1 for s in scores if s >= threshold) / len(scores)
