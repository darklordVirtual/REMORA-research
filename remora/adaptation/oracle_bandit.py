"""Dynamic oracle recruitment via Thompson Sampling (multi-armed bandit).

Problem
-------
REMORA's oracle pool is static by default.  Different oracles may be
better-suited to different question domains (legal, scientific, factual),
and oracle quality can drift over time as model providers update weights.

Solution
--------
Model each oracle as an arm of a multi-armed bandit with unknown reward
probability θᵢ.  Use Thompson Sampling to select the top-k oracles for
each query, updating Beta posteriors from observed correctness signals.

Thompson Sampling
-----------------
Prior:        θᵢ ~ Beta(α₀, β₀)   (default: α₀ = β₀ = 1.0, uniform)
Likelihood:   yᵢ ~ Bernoulli(θᵢ)
Posterior:    θᵢ | y₁…yₙ ~ Beta(α₀ + #correct, β₀ + #incorrect)

At each selection step:
  1. Sample s̃ᵢ ~ Beta(αᵢ, βᵢ) for each oracle i
  2. Rank oracles by s̃ᵢ descending
  3. Select the top-k

Regret bound
------------
Thompson Sampling achieves logarithmic expected cumulative regret:

    E[Regret(T)] = O(√(k · T · log T))

where k is the pool size and T is the number of rounds.  This is
near-optimal; no algorithm can do better than Ω(√(kT)) in general.

UCB1 alternative
----------------
The UCB1 score is also provided:

    UCB(i, t) = μᵢ + √(2 ln t / nᵢ)

where μᵢ is the posterior mean and nᵢ is the number of observations for
oracle i.  UCB1 is deterministic and easier to audit; Thompson Sampling
tends to be more empirically efficient.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class OracleStats:
    oracle_id: str
    alpha: float
    beta: float
    expected_accuracy: float
    n_observations: int
    ucb_score: float | None


class OracleBandit:
    """Thompson Sampling bandit for dynamic oracle pool management.

    Parameters
    ----------
    oracle_ids:    identifiers for the oracle pool
    prior_alpha:   Beta prior α (successes) — default 1.0 = uniform
    prior_beta:    Beta prior β (failures) — default 1.0 = uniform
    seed:          optional RNG seed for reproducibility
    """

    def __init__(
        self,
        oracle_ids: list[str],
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
        seed: int | None = None,
    ) -> None:
        if not oracle_ids:
            raise ValueError("oracle_ids must be non-empty")
        self._alpha: dict[str, float] = {oid: prior_alpha for oid in oracle_ids}
        self._beta: dict[str, float] = {oid: prior_beta for oid in oracle_ids}
        self._rng = random.Random(seed)
        self._t: int = 0  # global round counter for UCB

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select(self, n: int) -> list[str]:
        """Select the top-n oracle IDs via Thompson Sampling.

        Parameters
        ----------
        n:  number of oracles to select (clamped to pool size)

        Returns
        -------
        Ordered list of oracle IDs (highest sampled accuracy first).
        """
        n = min(n, len(self._alpha))
        scores = {
            oid: self._beta_sample(self._alpha[oid], self._beta[oid])
            for oid in self._alpha
        }
        self._t += 1
        return sorted(scores, key=lambda oid: scores[oid], reverse=True)[:n]

    def select_ucb(self, n: int) -> list[str]:
        """Select the top-n oracle IDs via UCB1 (deterministic alternative)."""
        n = min(n, len(self._alpha))
        self._t += 1
        scores = {oid: self._ucb(oid, self._t) for oid in self._alpha}
        return sorted(scores, key=lambda oid: scores[oid], reverse=True)[:n]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, oracle_id: str, correct: bool) -> None:
        """Update the Beta posterior for oracle_id after observing a result.

        correct=True  → α += 1  (Bayesian success count)
        correct=False → β += 1  (Bayesian failure count)
        """
        if oracle_id not in self._alpha:
            raise KeyError(f"Unknown oracle: {oracle_id!r}")
        if correct:
            self._alpha[oracle_id] += 1.0
        else:
            self._beta[oracle_id] += 1.0

    def update_many(self, outcomes: dict[str, bool]) -> None:
        """Update multiple oracle posteriors at once."""
        for oid, correct in outcomes.items():
            self.update(oid, correct)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def expected_accuracy(self, oracle_id: str) -> float:
        """Posterior mean accuracy: α / (α + β)."""
        a = self._alpha[oracle_id]
        b = self._beta[oracle_id]
        return a / (a + b)

    def ranking(self) -> list[str]:
        """Oracle IDs sorted by posterior mean accuracy (best first)."""
        return sorted(self._alpha, key=self.expected_accuracy, reverse=True)

    def stats(self, oracle_id: str, t: int | None = None) -> OracleStats:
        a = self._alpha[oracle_id]
        b = self._beta[oracle_id]
        t_eff = t if t is not None else self._t
        return OracleStats(
            oracle_id=oracle_id,
            alpha=a,
            beta=b,
            expected_accuracy=a / (a + b),
            n_observations=int(a + b) - 2,  # subtract priors
            ucb_score=self._ucb(oracle_id, t_eff) if t_eff > 0 else None,
        )

    def summary(self) -> dict[str, object]:
        return {
            "rounds": self._t,
            "oracles": {
                oid: {
                    "expected_accuracy": round(self.expected_accuracy(oid), 4),
                    "alpha": self._alpha[oid],
                    "beta": self._beta[oid],
                    "n_observations": int(self._alpha[oid] + self._beta[oid]) - 2,
                }
                for oid in self._alpha
            },
            "ranking": self.ranking(),
        }

    # ------------------------------------------------------------------
    # Theoretical bounds
    # ------------------------------------------------------------------

    def regret_bound(self, t: int | None = None) -> float:
        """Upper bound on expected cumulative regret after t rounds.

        Thompson Sampling achieves  E[Regret(T)] = O(√(k · T · log T))
        where k = number of oracles in the pool.

        This bound is near-optimal (matching lower bound up to log factor).
        """
        t = t if t is not None else self._t
        k = len(self._alpha)
        if t <= 0:
            return 0.0
        return math.sqrt(k * t * max(1.0, math.log(t)))

    def posterior_variance(self, oracle_id: str) -> float:
        """Posterior variance of accuracy: αβ / [(α+β)²(α+β+1)]."""
        a = self._alpha[oracle_id]
        b = self._beta[oracle_id]
        s = a + b
        if s < 1e-9:
            return 0.25
        return (a * b) / (s * s * (s + 1.0))

    def add_oracle(self, oracle_id: str, prior_alpha: float = 1.0, prior_beta: float = 1.0) -> None:
        """Add a new oracle to the pool with given priors."""
        if oracle_id in self._alpha:
            raise ValueError(f"Oracle {oracle_id!r} already in pool")
        self._alpha[oracle_id] = prior_alpha
        self._beta[oracle_id] = prior_beta

    def remove_oracle(self, oracle_id: str) -> None:
        """Remove an oracle from the pool (e.g., if it becomes unavailable)."""
        if oracle_id not in self._alpha:
            raise KeyError(f"Unknown oracle: {oracle_id!r}")
        del self._alpha[oracle_id]
        del self._beta[oracle_id]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _beta_sample(self, alpha: float, beta: float) -> float:
        """Sample from Beta(alpha, beta) using stdlib Gamma variates."""
        x = self._rng.gammavariate(alpha, 1.0)
        y = self._rng.gammavariate(beta, 1.0)
        total = x + y
        return x / total if total > 0 else 0.5

    def _ucb(self, oracle_id: str, t: int) -> float:
        a = self._alpha[oracle_id]
        b = self._beta[oracle_id]
        n_i = a + b - 2.0  # observations (subtract priors)
        mu_i = a / (a + b)
        if n_i <= 0 or t <= 0:
            return float("inf")
        return mu_i + math.sqrt(2.0 * math.log(t) / n_i)
