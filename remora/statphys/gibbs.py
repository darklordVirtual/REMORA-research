# Author: Stian Skogbrott
# License: Apache-2.0
"""Gibbs/Boltzmann distributions over consensus states.

Physical analogy
----------------
In statistical physics, the Gibbs (Boltzmann) distribution assigns a
probability to each microstate proportional to exp(-E/kT), where E is
the energy, k is Boltzmann's constant, and T is temperature.

Applied to multi-oracle consensus, this provides a principled way to
convert energy values into probabilities — e.g. the probability that
a particular routing action is correct given the system temperature.

Assumptions and gaps
--------------------
- We set k = 1 (natural units) so T is the only scale parameter.
- T here is the effective question temperature from remora/thermodynamics.py,
  which is a composite observable — NOT a physical temperature.  The
  identification with a Boltzmann temperature is an analogy, not a proof.
- The partition function is approximated over a finite discrete state space.
  For continuous state spaces, this approximation may be poor.
- There is no proof that the oracle system obeys detailed balance or that
  the stationary distribution is Gibbs-form.
"""
from __future__ import annotations

import math


def _safe_exp(x: float, clip: float = 500.0) -> float:
    """Numerically stable exp with overflow protection."""
    return math.exp(max(-clip, min(clip, x)))


def partition_function_approx(energies: list[float], temperature: float) -> float:
    """Approximate the partition function Z = Σ exp(-E_i / T).

    Parameters
    ----------
    energies:
        List of energy values for each state.
    temperature:
        Effective temperature T > 0.

    Returns
    -------
    float
        Partition function Z.  Always positive.

    Raises
    ------
    ValueError
        If temperature ≤ 0 or energies is empty.
    """
    if not energies:
        raise ValueError("energies must be non-empty")
    if temperature <= 0.0:
        raise ValueError(f"temperature must be positive, got {temperature}")
    return sum(_safe_exp(-e / temperature) for e in energies)


def gibbs_probability(energy: float, temperature: float, energies: list[float]) -> float:
    """Gibbs probability of a single state with given energy.

    P(state) = exp(-E / T) / Z

    Parameters
    ----------
    energy:
        Energy of the state of interest.
    temperature:
        Effective temperature T > 0.
    energies:
        Energies of all states in the system (used to compute Z).
        Must include `energy`.

    Returns
    -------
    float
        Gibbs probability in [0, 1].

    Notes
    -----
    For T → 0 the distribution concentrates on the lowest-energy state.
    For T → ∞ the distribution becomes uniform.

    Assumptions
    -----------
    - The effective question temperature T from remora/thermodynamics.py is
      used as a proxy for physical temperature.  This is a modelling choice
      that has not been derived from first principles.
    """
    if temperature <= 0.0:
        raise ValueError(f"temperature must be positive, got {temperature}")
    if not energies:
        raise ValueError("energies must be non-empty")
    Z = partition_function_approx(energies, temperature)
    return _safe_exp(-energy / temperature) / Z


def free_energy_approx(energies: list[float], temperature: float) -> float:
    """Approximate Helmholtz free energy F = -T · log(Z).

    This is the statistical-physics analogue of the Lyapunov objective
    used in remora/lyapunov.py.  The formal identification is:
        V = H + λD  ≡  F(T = -1)
    for a two-observable energy E = H + λD.

    Parameters
    ----------
    energies:
        List of energy values for all states.
    temperature:
        Effective temperature T (must be > 0 for valid physics). The T = -1
        substitution used in the Lyapunov identification is a SIGN CONVENTION
        (it flips -T·H to +H so that V = H + λD matches F's algebraic form);
        it is not an analytic continuation and carries no physical content.

    Returns
    -------
    float
        Approximate free energy.
    """
    if not energies:
        raise ValueError("energies must be non-empty")
    if temperature == 0.0:
        raise ValueError("temperature must be non-zero")
    Z = sum(_safe_exp(-e / temperature) for e in energies)
    if Z <= 0.0:
        return float("inf")
    return -temperature * math.log(Z)
