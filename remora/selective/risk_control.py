# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Finite-sample selective risk control: SGR, CRC and LTT-style selection.

Implements the certification procedures surveyed in
docs/research/method_alternatives_2026_07.md as LIBRARY code with tests.
Nothing here is wired into the decision engine: per the exploratory
2026-07 analysis, engine integration is gated on the pre-registered SAP v3
round showing effect on fresh data.

Procedures
----------
``sgr_threshold``
    Selection with Guaranteed Risk per Geifman & El-Yaniv (2017),
    Algorithm 1: binary search over candidate score-thresholds, testing at
    most ``m = ceil(log2(K)) + 1`` candidates, each with a Clopper-Pearson
    upper bound at Bonferroni level ``delta / m`` (union bound => FWER <=
    ``delta``). The returned threshold's conditional selective risk
    (errors among ACCEPTED) is <= ``target_risk`` with probability >=
    1 - ``delta`` under i.i.d./exchangeable calibration data. Small
    calibration sets can yield certified coverage 0 — valid but
    uninformative, and reported as such.

``crc_threshold``
    Conformal Risk Control (Angelopoulos, Bates, Fisch, Lei, Schuster,
    2024): choose the largest acceptance set whose criterion
    ``(n/(n+1)) * Rhat_n + B/(n+1) <= alpha`` holds, where the loss is the
    monotone, bounded ``accepted-and-wrong`` indicator. NOTE the
    semantics: CRC controls the EXPECTED UNCONDITIONAL selective loss
    (errors-among-accepted counted over ALL items) of a fresh
    exchangeable test point — not the conditional accuracy among accepted,
    and not any statement about out-of-distribution data.

Limitations (stated so callers cannot over-claim):
- Both guarantees assume exchangeability between calibration and test
  items; template/cluster dependence weakens them.
- "Certified" means the STATISTICAL criterion held on this calibration
  data at the stated level — a guarantee about the defined loss, never a
  general safety guarantee about an action.
- Small calibration sets yield valid but possibly useless results (zero
  certifiable coverage); that outcome is reported explicitly, never
  papered over.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class RiskControlResult:
    """Outcome of a threshold-certification procedure.

    ``certified`` False means NO threshold met the criterion — coverage 0,
    threshold ``inf`` (accept nothing). ``risk_bound`` is the bound at the
    returned threshold (or the best rejected bound when not certified).
    """

    procedure: str
    certified: bool
    threshold: float
    coverage: float
    n_calibration: int
    n_accepted: int
    empirical_risk: float
    risk_bound: float
    target: float
    delta_spent: float | None = None


def clopper_pearson_upper(k_errors: int, n: int, delta: float) -> float:
    """Exact upper (1 - delta) confidence limit for a binomial proportion.

    Smallest p_u such that P(X <= k_errors | n, p_u) <= delta — the
    classical Clopper-Pearson upper limit, computed by bisection on the
    exact binomial CDF (no SciPy dependency). Fails closed: n == 0 -> 1.0.
    """
    if n <= 0:
        return 1.0
    if k_errors >= n:
        return 1.0
    if not 0.0 < delta < 1.0:
        raise ValueError(f"delta must be in (0, 1), got {delta}")

    def cdf(p: float) -> float:
        return sum(
            math.comb(n, i) * (p ** i) * ((1.0 - p) ** (n - i))
            for i in range(0, k_errors + 1)
        )

    lo, hi = k_errors / n, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if cdf(mid) > delta:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return hi


def _validate(scores: Sequence[float], losses: Sequence[int]) -> None:
    if len(scores) != len(losses):
        raise ValueError(
            f"scores and losses must align: {len(scores)} vs {len(losses)}"
        )
    if not scores:
        raise ValueError("calibration data must be non-empty")
    for ls in losses:
        if ls not in (0, 1):
            raise ValueError(f"losses must be 0/1 indicators, got {ls!r}")


def sgr_threshold(
    scores: Sequence[float],
    losses: Sequence[int],
    *,
    target_risk: float,
    delta: float,
) -> RiskControlResult:
    """Certify the largest score-threshold whose selective risk is bounded.

    ``scores``: higher = more confident (accept when score >= threshold).
    ``losses``: 1 = the item's prediction is wrong, 0 = correct.
    Returns the largest acceptance set (fixed-sequence walk from smallest)
    whose Clopper-Pearson upper bound on errors-among-accepted stays
    <= ``target_risk`` at confidence 1 - ``delta``.
    """
    _validate(scores, losses)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    n = len(order)

    # Candidate cut points: prefixes ending at DISTINCT score values, so the
    # rule {score >= tau} reproduces the prefix exactly (tie-safety).
    cuts: list[tuple[float, int, int]] = []  # (threshold, n_accepted, k_errors)
    k_err = 0
    for prefix in range(1, n + 1):
        idx = order[prefix - 1]
        k_err += losses[idx]
        if prefix < n and scores[order[prefix]] == scores[idx]:
            continue
        cuts.append((scores[idx], prefix, k_err))

    # Geifman & El-Yaniv Algorithm 1: binary search over the cut points,
    # each test at Bonferroni level delta/m so FWER <= delta.
    m = max(1, math.ceil(math.log2(len(cuts))) + 1)
    delta_step = delta / m
    best: tuple[float, int, int, float] | None = None
    last_bound = 1.0
    lo, hi = 0, len(cuts) - 1
    for _ in range(m):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        threshold, n_acc, k_acc_err = cuts[mid]
        bound = clopper_pearson_upper(k_acc_err, n_acc, delta_step)
        last_bound = bound
        if bound <= target_risk:
            best = (threshold, n_acc, k_acc_err, bound)
            lo = mid + 1  # try larger coverage
        else:
            hi = mid - 1  # retreat to smaller coverage

    if best is None:
        return RiskControlResult(
            procedure="sgr_binary_search",
            certified=False,
            threshold=math.inf,
            coverage=0.0,
            n_calibration=n,
            n_accepted=0,
            empirical_risk=0.0,
            risk_bound=last_bound,
            target=target_risk,
            delta_spent=delta_step,
        )
    threshold, n_acc, k_acc_err, bound = best
    return RiskControlResult(
        procedure="sgr_binary_search",
        certified=True,
        threshold=threshold,
        coverage=n_acc / n,
        n_calibration=n,
        n_accepted=n_acc,
        empirical_risk=k_acc_err / n_acc,
        risk_bound=bound,
        target=target_risk,
        delta_spent=delta_step,
    )


def crc_threshold(
    scores: Sequence[float],
    losses: Sequence[int],
    *,
    alpha: float,
    loss_bound: float = 1.0,
) -> RiskControlResult:
    """Conformal Risk Control over the accepted-and-wrong indicator loss.

    Chooses the largest acceptance set with
    ``(n/(n+1)) * Rhat_n + B/(n+1) <= alpha`` where ``Rhat_n`` is the mean
    over ALL calibration items of the monotone loss
    ``1[score_i >= tau and wrong_i]`` and ``B`` = ``loss_bound``. The
    controlled quantity is the EXPECTED loss of a fresh exchangeable test
    point (unconditional), not accuracy among accepted.
    """
    _validate(scores, losses)
    n = len(scores)
    order = sorted(range(n), key=lambda i: -scores[i])

    best: tuple[float, int, int, float] | None = None
    k_err = 0
    for prefix in range(1, n + 1):
        idx = order[prefix - 1]
        k_err += losses[idx]
        if prefix < n and scores[order[prefix]] == scores[idx]:
            continue
        rhat = k_err / n  # unconditional: errors among accepted over ALL items
        criterion = (n / (n + 1)) * rhat + loss_bound / (n + 1)
        if criterion <= alpha:
            best = (scores[idx], prefix, k_err, criterion)
        # No early break: the unconditional loss is monotone increasing in
        # coverage, but ties make prefix-skips uneven — scan fully.

    if best is None:
        floor = loss_bound / (n + 1)
        return RiskControlResult(
            procedure="crc",
            certified=False,
            threshold=math.inf,
            coverage=0.0,
            n_calibration=n,
            n_accepted=0,
            empirical_risk=0.0,
            risk_bound=floor,
            target=alpha,
        )
    threshold, n_acc, k_acc_err, criterion = best
    return RiskControlResult(
        procedure="crc",
        certified=True,
        threshold=threshold,
        coverage=n_acc / n,
        n_calibration=n,
        n_accepted=n_acc,
        empirical_risk=k_acc_err / n,
        risk_bound=criterion,
        target=alpha,
    )
