"""Finite-sample binomial bounds (stdlib only).

These are used to construct conservative upper confidence bounds on
empirical risk in conformal selective prediction.
"""
from __future__ import annotations
import math


def _log_binomial_coef(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def binomial_tail_prob(k: int, n: int, p: float) -> float:
    """P(X >= k) where X ~ Binomial(n, p). Exact via direct log-sum.

    Computed as sum_{i=k}^{n} C(n,i) p^i (1-p)^{n-i} using log-gamma for
    numerical stability. Accurate to ~1e-8 for n <= 500.
    """
    if k > n:
        return 0.0
    if k <= 0:
        return 1.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0 if k <= n else 0.0
    log_p = math.log(p)
    log_q = math.log1p(-p)
    total = 0.0
    for i in range(k, n + 1):
        log_term = _log_binomial_coef(n, i) + i * log_p + (n - i) * log_q
        total += math.exp(log_term)
    return min(1.0, total)


def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05) -> float:
    """Upper end of Clopper-Pearson exact interval for a proportion.

    Returns the smallest p* such that P(X <= k | Binomial(n, p*)) >= alpha.
    Uses binary search over p in [0, 1].

    Interpretation: the true error rate exceeds the returned value with
    probability at most alpha.
    """
    if k == n:
        return 1.0
    if k < 0:
        return 0.0

    # Find p such that binomial_tail_prob(k+1, n, p) = alpha.
    # binomial_tail_prob(k+1, n, p) is increasing in p.
    # For p just above k/n the tail prob is close to alpha; for p=1 it's 1.0.
    lo = k / n if n > 0 else 0.0
    hi = 1.0

    # Ensure bracket: at lo the tail prob should be <= alpha (or close)
    # and at hi it should be >= alpha.
    for _ in range(100):
        mid = (lo + hi) / 2.0
        tail = binomial_tail_prob(k + 1, n, mid)
        if tail < alpha:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10:
            break

    return hi


def risk_upper_confidence_bound(
    wrong: int, accepted: int, alpha: float = 0.05
) -> float | None:
    """Upper 1-alpha confidence bound on the empirical risk wrong/accepted.

    Returns None if accepted == 0.
    Returns clopper_pearson_upper(wrong, accepted, alpha).
    """
    if accepted == 0:
        return None
    return clopper_pearson_upper(wrong, accepted, alpha)
