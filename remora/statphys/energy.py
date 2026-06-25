# Author: Stian Skogbrott
# License: Apache-2.0
"""Consensus energy functions for multi-oracle state distributions.

Physical analogy
----------------
A multi-oracle consensus state can be described as a distribution over
possible verdicts.  The "energy" of a state is higher when the system
is disordered (high entropy, low agreement) and lower when it is ordered
(low entropy, strong agreement).

This mirrors the idea in statistical physics that low-energy states
correspond to organised, coherent configurations.

Assumptions and gaps
--------------------
- We treat oracle votes as independent spins.  Real oracles share training
  data and exhibit correlated errors (see remora/correlation_error.py).
- The energy scale (lambda_e, lambda_d) is empirically tuned, not derived
  from first principles.  A proper free-energy derivation would require
  a known partition function.
- 'energy' here is an analogy.  The values are not in joules and do not
  obey thermodynamic laws unless those laws are separately proved.
"""
from __future__ import annotations

import math


def state_entropy(state_distribution: dict[str, float]) -> float:
    """Shannon entropy of a state distribution over verdicts.

    Parameters
    ----------
    state_distribution:
        Map from verdict label to probability/weight.  Need not be
        normalised; weights are re-normalised internally.

    Returns
    -------
    float
        Shannon entropy in nats.

    Notes
    -----
    Entropy H = -Σ p_i log(p_i).  Zero for a deterministic state
    (single verdict with full weight).  Maximum for a uniform distribution
    over k states: log(k).
    """
    weights = list(state_distribution.values())
    total = sum(weights)
    if total <= 0.0:
        return 0.0
    normalised = [w / total for w in weights]
    return -sum(p * math.log(p) for p in normalised if p > 0.0)


def consensus_energy(
    state_distribution: dict[str, float],
    lambda_e: float = 1.0,
    lambda_d: float = 1.0,
) -> float:
    """Compute the consensus energy of a multi-oracle state distribution.

    Energy is defined as:
        E(σ) = λ_e · H(σ) + λ_d · D(σ)

    where H(σ) is the Shannon entropy of the verdict distribution and
    D(σ) is the dissensus (1 − max_weight).

    This is a phenomenological model: it assigns higher energy to states
    with more disorder (high H) or weaker plurality (high D).

    Parameters
    ----------
    state_distribution:
        Map from verdict label to weight/probability.
    lambda_e:
        Weight on entropy term (default 1.0).
    lambda_d:
        Weight on dissensus term (default 1.0).

    Returns
    -------
    float
        Energy value ≥ 0.  Zero only when a single verdict has all weight.

    Assumptions
    -----------
    - Oracle votes are treated as drawn from this distribution independently.
    - lambda_e and lambda_d are hyperparameters, not derived from first
      principles.  Empirical calibration is required before any claim about
      absolute energy values.

    See Also
    --------
    remora.thermodynamics.temperature : Temperature observable derived from
        a superset of these observables.
    remora.lyapunov : Lyapunov objective V = H + λD, which is equivalent
        to consensus_energy(lambda_e=1, lambda_d=lambda) at T_internal=-1.
    """
    weights = list(state_distribution.values())
    total = sum(weights)
    if total <= 0.0:
        return 0.0

    normalised = [w / total for w in weights]
    H = -sum(p * math.log(p) for p in normalised if p > 0.0)
    D = 1.0 - max(normalised)
    return lambda_e * H + lambda_d * D


def minimum_energy_verdict(state_distribution: dict[str, float]) -> str | None:
    """Return the verdict with the highest weight (most ordered state).

    Returns None if state_distribution is empty.
    """
    if not state_distribution:
        return None
    return max(state_distribution, key=lambda k: state_distribution[k])
