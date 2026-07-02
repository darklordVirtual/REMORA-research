# Author: Stian Skogbrott
# License: Apache-2.0
"""Time-uniform (anytime-valid) confidence sequences for a Bernoulli rate.

Motivation
----------
REM-020 monitors the operational false-accept rate continuously and closes
the day its criterion holds. Fixed-sample intervals (Wilson,
Clopper-Pearson — used elsewhere in this repo) are valid only at a single,
pre-committed sample size; inspecting them after every observation and
acting when a threshold is crossed is *optional stopping*, which invalidates
their coverage guarantee (the "peeking" problem). A confidence sequence is
valid *uniformly over time*: P(for all n: p ∈ CS_n) ≥ 1 − α, so a
monitoring gate may look after every observation and act at any
data-dependent stopping time without breaking the guarantee.

Construction
------------
Conjugate-mixture (Beta-binomial) nonnegative supermartingale. For k
successes in n Bernoulli(p) trials and a Beta(a, b) mixing prior, the
mixture likelihood ratio

    M_n(p) = B(a + k, b + n − k) / B(a, b) / (p^k (1 − p)^(n − k))

is a nonnegative martingale with E[M_n(p_true)] = 1, so by Ville's
inequality P(∃n: M_n(p_true) ≥ 1/α) ≤ α. The (1 − α) confidence sequence
is {p : M_n(p) < 1/α}; this module computes its upper endpoint (the
quantity a FAR gate needs). log M_n(p) is strictly increasing in p on
(k/n, 1), so the endpoint is found by bisection; for k = 0 (the FAR = 0
monitoring case) it has the closed form, with a = b = 1:

    p_upper = 1 − (α / (n + 1))^(1/n)

The price of time-uniformity is a wider bound than Wilson at any fixed n
(roughly 2× for k = 0 at moderate n). This is the honest cost of a
guarantee that survives continuous monitoring — report it, do not hide it.

References
----------
- Ville, J. (1939). *Étude critique de la notion de collectif.*
  Gauthier-Villars. (Ville's inequality.)
- Darling, D. A. & Robbins, H. (1967). Confidence sequences for mean,
  variance, and median. *PNAS* 58(1).
- Howard, S. R., Ramdas, A., McAuliffe, J. & Sekhon, J. (2021).
  Time-uniform, nonparametric, nonasymptotic confidence sequences.
  *Annals of Statistics* 49(2).
- Ramdas, A., Grünwald, P., Vovk, V. & Shafer, G. (2023). Game-theoretic
  statistics and safe anytime-valid inference. *Statistical Science* 38(4).
- Waudby-Smith, I. & Ramdas, A. (2024). Estimating means of bounded random
  variables by betting. *JRSS-B* 86(1).

See docs/theoretical_foundations_proposals_v1.md §1 for the adoption
rationale and acceptance criteria.
"""
from __future__ import annotations

from math import exp, lgamma, log

__all__ = [
    "bernoulli_upper_confidence_sequence",
    "log_mixture_martingale",
    "far_monitoring_report",
]


def _log_beta(a: float, b: float) -> float:
    return lgamma(a) + lgamma(b) - lgamma(a + b)


def log_mixture_martingale(
    k: int,
    n: int,
    p: float,
    prior_a: float = 1.0,
    prior_b: float = 1.0,
) -> float:
    """log M_n(p) for the Beta(a, b)-mixture martingale after k of n successes.

    Raises:
        ValueError: on invalid counts, prior, or p outside (0, 1).
    """
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"invalid counts: k={k}, n={n}")
    if prior_a <= 0 or prior_b <= 0:
        raise ValueError("prior_a and prior_b must be positive")
    if not (0.0 < p < 1.0):
        raise ValueError(f"p must be in (0, 1), got {p}")
    log_marginal = _log_beta(prior_a + k, prior_b + n - k) - _log_beta(prior_a, prior_b)
    log_likelihood = k * log(p) + (n - k) * log(1.0 - p)
    return log_marginal - log_likelihood


def bernoulli_upper_confidence_sequence(
    k: int,
    n: int,
    alpha: float = 0.05,
    prior_a: float = 1.0,
    prior_b: float = 1.0,
    tol: float = 1e-10,
) -> float:
    """Upper endpoint of the (1 − alpha) time-uniform confidence sequence.

    Valid simultaneously for all n: the probability that the true rate ever
    exceeds the returned bound, at any point during monitoring, is at most
    alpha. Safe under optional stopping — unlike Wilson/Clopper-Pearson.

    Args:
        k: number of events (e.g. false accepts) observed so far.
        n: number of trials observed so far.
        alpha: miscoverage budget over the whole monitoring horizon.
        prior_a / prior_b: Beta mixing prior (default uniform). The prior
            choice affects tightness, not validity.
        tol: bisection tolerance.

    Returns:
        Upper bound in (0, 1]; returns 1.0 when n == 0 (no data, no bound).
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"invalid counts: k={k}, n={n}")
    if n == 0:
        return 1.0

    target = log(1.0 / alpha)

    def excess(p: float) -> float:
        return log_mixture_martingale(k, n, p, prior_a, prior_b) - target

    # log M_n(p) is strictly increasing in p on (k/n, 1). If even p → 1
    # does not reach 1/alpha, the CS upper endpoint is 1.
    hi = 1.0 - tol
    if excess(hi) < 0:
        return 1.0
    lo = max(k / n, tol)
    if excess(lo) >= 0:
        # Entire (k/n, 1) rejected at this level — cap at the empirical rate.
        return k / n
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if excess(mid) < 0:
            lo = mid
        else:
            hi = mid
    return hi


def closed_form_upper_k0(n: int, alpha: float = 0.05) -> float:
    """Closed-form k = 0 upper endpoint for the uniform (a = b = 1) prior.

    p_upper = 1 − (alpha / (n + 1))^(1/n). Exposed for verification against
    the bisection path; agreement is asserted in tests.
    """
    if n <= 0:
        return 1.0
    return 1.0 - exp(log(alpha / (n + 1)) / n)


def far_monitoring_report(
    k: int,
    n: int,
    alpha: float = 0.05,
    threshold: float | None = None,
) -> dict:
    """Gate-ready summary of the anytime-valid FA-rate bound.

    Args:
        k, n: event and trial counts so far.
        alpha: monitoring-horizon miscoverage budget.
        threshold: optional gate threshold; when given, the report states
            whether the time-uniform upper bound is below it.

    Returns:
        Dict with the bound, its construction parameters, and an explicit
        validity statement suitable for embedding in a result artifact.
    """
    upper = bernoulli_upper_confidence_sequence(k, n, alpha)
    report: dict = {
        "method": "beta_mixture_confidence_sequence",
        "prior": "Beta(1,1)",
        "alpha": alpha,
        "k_events": k,
        "n_trials": n,
        "empirical_rate": (k / n) if n else None,
        "time_uniform_upper_bound": upper,
        "validity": (
            "Time-uniform (anytime-valid): the bound holds simultaneously "
            "for all sample sizes, so it remains valid under continuous "
            "monitoring and data-dependent stopping (Ville's inequality). "
            "It is wider than a fixed-N Wilson interval by construction."
        ),
    }
    if threshold is not None:
        report["threshold"] = threshold
        report["upper_bound_below_threshold"] = upper < threshold
    return report


# Kept out of __all__: verification helper, not public API.
_CLOSED_FORM_K0 = closed_form_upper_k0
