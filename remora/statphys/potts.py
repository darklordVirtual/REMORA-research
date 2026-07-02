# Author: Stian Skogbrott
# License: Apache-2.0
"""Potts-model approximation for multi-verdict consensus systems.

Physical analogy
----------------
The q-state Potts model is a generalisation of the Ising model to q states.
Applied to a pool of n oracles each choosing among k verdict labels, we
model the joint state as a q^n configuration space with an interaction
energy that rewards agreement.

The order parameter η in remora/thermodynamics.py is already a discrete
Potts-style observable: η = (k·n_max/n − 1)/(k − 1), where n_max is the
plurality count.

This module provides a more explicit Potts energy function and order
parameter computation that can be compared against the thermodynamics.py
implementation.

Assumptions and gaps
--------------------
- We use a mean-field (fully-connected) Potts model, which overestimates
  the coupling between correlated oracles.
- The Potts coupling J is treated as a free parameter; REMORA does not
  have a first-principles derivation of J from oracle architecture.
- Real oracles are not Potts spins: they produce text, not discrete
  elements of Z_k.  The approximation is valid only after canonicalisation
  maps outputs to verdict space.
- There is no proof that the empirical phase transition in REMORA
  corresponds to the Potts model's known critical temperature T_c(k,J).
  The connection is analogical.
"""
from __future__ import annotations



def potts_energy(
    verdict_counts: dict[str, int],
    J: float = 1.0,
) -> float:
    """Potts interaction energy for a multi-oracle verdict distribution.

    Uses the mean-field approximation:
        E = -J · Σ_{a} n_a(n_a - 1) / (2 · N(N-1))

    where n_a is the number of oracles voting for verdict a and N is the
    total number of oracles.  The energy is minimised when all oracles agree.

    Parameters
    ----------
    verdict_counts:
        Map from verdict label to the number of oracles producing it.
    J:
        Potts coupling constant (positive = ferromagnetic, rewards agreement).

    Returns
    -------
    float
        Potts energy.  Negative = ordered (agreement favoured).
        Zero = single-oracle or all-different.

    Notes
    -----
    For N=3 and all three oracles agreeing: E = -J · 3·2/(2·3·2) = -J/2.
    For N=3 with all oracles disagreeing: E = -J · 0 = 0.

    Assumptions
    -----------
    See module docstring.  This is a mean-field approximation.
    """
    N = sum(verdict_counts.values())
    if N <= 1:
        return 0.0
    pair_agreement = sum(n * (n - 1) for n in verdict_counts.values())
    total_pairs = N * (N - 1)
    return -J * pair_agreement / total_pairs


def potts_order_parameter(verdict_counts: dict[str, int], k: int | None = None) -> float:
    """Potts order parameter η for a multi-oracle verdict distribution.

    Definition (consistent with remora/thermodynamics.py):
        η = (k · n_max / N − 1) / (k − 1)

    where n_max is the plurality count, N the total oracle count, and k
    the number of possible verdict states.

    For k=2 (binary): η = 2·n_max/N − 1  (goes from 0 at 50/50 to 1 at 100/0).
    For general k:    η ∈ [0, 1]  (0 = uniform, 1 = full consensus).

    Parameters
    ----------
    verdict_counts:
        Map from verdict label to count.  Must be non-empty.
    k:
        Number of possible verdict states.  If None, defaults to the
        number of distinct verdicts observed.

    Returns
    -------
    float
        Order parameter η ∈ [0, 1].

    Raises
    ------
    ValueError
        If verdict_counts is empty or k < 2.
    """
    if not verdict_counts:
        raise ValueError("verdict_counts must be non-empty")
    N = sum(verdict_counts.values())
    if N == 0:
        raise ValueError("verdict_counts must contain at least one oracle vote")
    n_max = max(verdict_counts.values())
    if k is None:
        k = max(2, len(verdict_counts))
    if k < 2:
        raise ValueError(f"k must be >= 2, got {k}")
    return (k * n_max / N - 1.0) / (k - 1.0)


def potts_critical_temperature_approx(k: int, J: float = 1.0) -> float:
    """Mean-field critical temperature for the q-state Potts model.

    T_c(mean-field) = J · (k − 1) / k · N_eff

    T_c = J (k-1)/k is used here as a simple REFERENCE VALUE for the
    per-site coupling convention. It is not presented as the exact
    mean-field Potts result: the mean-field q-state Potts transition is
    FIRST-order for q >= 3 (Wu, Rev. Mod. Phys. 54, 235 (1982)), and no
    transition-order claim is made for REMORA's small-n consensus setting.

    This is provided for reference only.  REMORA's empirical T_c is
    determined by calibration, not by this formula.

    Parameters
    ----------
    k:
        Number of Potts states (verdict labels).
    J:
        Potts coupling constant.

    Returns
    -------
    float
        Mean-field critical temperature.
    """
    if k < 2:
        raise ValueError(f"k must be >= 2, got {k}")
    return J * (k - 1) / k
