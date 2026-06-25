"""Candidate false-consensus bound (v2).

This module intentionally avoids theorem-strength language.

Purpose
-------
Provide a conservative, falsifiable candidate upper-bound program for
P(all n oracles wrong) while explicitly separating:

- response correlation: agreement in oracle outputs,
- error correlation: correlation in oracle error indicators.

The v1 bound in ``hallucination_bound_theorem.py`` remains useful as a research
heuristic, but this v2 module is the preferred place for future proof work.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class BoundInputs:
    """Inputs for candidate bound computations.

    epsilon:
        Estimated per-oracle error rate (pool-level proxy).
    rho_error:
        Pairwise correlation for error indicators, not response agreement.
    n_oracles:
        Number of independent oracle channels in the pool.
    """

    epsilon: float
    rho_error: float
    n_oracles: int


def _clamp_unit(x: float) -> float:
    return max(0.0, min(float(x), 1.0))


def pair_failure_upper_q(epsilon: float, rho_error: float) -> float:
    """Upper bound for a pair joint-failure event.

    q = eps^2 + rho_err * eps * (1 - eps)

    This is a pair-level bound only. It does not imply an n-oracle theorem
    unless additional between-pair assumptions are validated.
    """

    eps = _clamp_unit(epsilon)
    rho = _clamp_unit(rho_error)
    return _clamp_unit(eps * eps + rho * eps * (1.0 - eps))


def candidate_bound(inputs: BoundInputs, assume_pair_independence: bool = False) -> float:
    """Compute a candidate upper bound for false consensus.

    Conservative policy:
    - default (no pair-independence assumption): return q.
      This is weaker but safer than raising q to n/2.
    - optional pair-independence assumption: return q^(floor(n/2)).

    Returning q as the default keeps the claim falsifiable without over-claiming
    theorem-level guarantees.
    """

    if inputs.n_oracles < 2:
        return 1.0
    q = pair_failure_upper_q(inputs.epsilon, inputs.rho_error)
    if not assume_pair_independence:
        return q
    return _clamp_unit(q ** math.floor(inputs.n_oracles / 2))


def candidate_report(epsilon: float, rho_error: float, n_oracles: int = 3) -> dict:
    """Return a small machine-readable report for dashboards/tests."""

    inputs = BoundInputs(epsilon=epsilon, rho_error=rho_error, n_oracles=n_oracles)
    q = pair_failure_upper_q(inputs.epsilon, inputs.rho_error)
    return {
        "status": "candidate",
        "n_oracles": n_oracles,
        "epsilon": round(float(epsilon), 6),
        "rho_error": round(float(rho_error), 6),
        "pair_failure_q": round(q, 6),
        "bound_without_pair_independence": round(candidate_bound(inputs, assume_pair_independence=False), 6),
        "bound_with_pair_independence": round(candidate_bound(inputs, assume_pair_independence=True), 6),
        "note": (
            "Use rho_error from labeled error indicators. "
            "Do not substitute response-agreement rho without calibration."
        ),
    }


if __name__ == "__main__":
    sample = candidate_report(epsilon=0.264, rho_error=0.236, n_oracles=3)
    print(sample)
