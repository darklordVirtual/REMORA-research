# Author: Stian Skogbrott
# License: Apache-2.0
"""Oracle diversity analysis and diversity-aware swarm selection.

The standard REMORA hallucination-risk formula assumes mean inter-oracle
correlation ρ̄ ≈ 0.15.  When all three oracles are from the same model
family (e.g., all Groq LLaMA variants) the empirical ρ̄ is likely 0.40–0.60,
which inflates the effective false-consensus rate by 2–4×.

This module provides:

- :class:`OracleDiversityTracker` — accumulates pairwise oracle agreement
  rates from streaming benchmark evaluations and emits correlation warnings.
- :func:`select_diverse_swarm` — greedy algorithm that, given a pool of N
  oracle candidates and their pre-computed correlation matrix, selects the k
  that minimise mean pairwise ρ̄ (maximise independence).
- :func:`diversity_score` — scalar summary of swarm diversity in [0, 1]
  (0 = identical oracles, 1 = perfectly independent).

Relationship to existing CorrelationMatrix
------------------------------------------
:class:`remora.correlation.CorrelationMatrix` tracks *verdict* agreement
within the live Remora engine.  This module works at the *swarm-selection*
level and is designed to run *before* the engine starts, using historical
benchmark responses or a pre-specified correlation matrix.

Typical usage
-------------
    tracker = OracleDiversityTracker()

    # After each benchmark item, record which oracles agreed:
    tracker.observe("llama-3.3-70b", "claude-3.5-haiku", agreed=True)
    tracker.observe("llama-3.3-70b", "gemma-3-27b", agreed=False)

    print(tracker.rho("llama-3.3-70b", "claude-3.5-haiku"))  # 0.67 after 3 obs

    # At swarm-selection time:
    candidates = ["llama-3.3-70b", "llama-3.1-8b", "claude-3.5-haiku",
                  "gemma-3-27b", "mistral-7b"]
    best = select_diverse_swarm(candidates, tracker, k=3)
    # → picks the three with lowest mean pairwise ρ̄
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Diversity tracker
# ---------------------------------------------------------------------------

@dataclass
class OracleDiversityTracker:
    """Rolling pairwise agreement tracker for oracle diversity analysis.

    Each ``observe(a, b, agreed)`` call records whether oracles *a* and *b*
    gave the same verdict on one benchmark item.  After enough observations,
    ``rho(a, b)`` returns the empirical agreement rate ρ ∈ [0, 1].

    This is a simpler, diversity-focused companion to
    :class:`remora.correlation.CorrelationMatrix`, which lives inside the
    Remora engine and tracks verdict objects.
    """

    window_size: int = 500
    high_correlation_threshold: float = 0.60

    # _history[(a, b)] = deque of 0/1 agreement indicators
    _history: dict[tuple[str, str], list[int]] = field(default_factory=dict)

    def _key(self, a: str, b: str) -> tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    def observe(self, oracle_a: str, oracle_b: str, agreed: bool) -> None:
        """Record a pairwise agreement observation."""
        key = self._key(oracle_a, oracle_b)
        if key not in self._history:
            self._history[key] = []
        hist = self._history[key]
        hist.append(1 if agreed else 0)
        # Rolling window — keep only the last window_size entries
        if len(hist) > self.window_size:
            self._history[key] = hist[-self.window_size:]

    def observe_batch(
        self,
        oracle_names: list[str],
        binary_verdicts: list[bool],
    ) -> None:
        """Record all pairwise agreements for one benchmark item.

        Parameters
        ----------
        oracle_names:
            Ordered list of oracle identifiers.
        binary_verdicts:
            Boolean verdict from each oracle (True = affirmed claim).
        """
        if len(oracle_names) != len(binary_verdicts):
            raise ValueError("oracle_names and binary_verdicts must have the same length")
        for i in range(len(oracle_names)):
            for j in range(i + 1, len(oracle_names)):
                agreed = binary_verdicts[i] == binary_verdicts[j]
                self.observe(oracle_names[i], oracle_names[j], agreed)

    def rho(self, oracle_a: str, oracle_b: str) -> float:
        """Return empirical agreement rate ρ ∈ [0, 1] between two oracles.

        Returns 0.5 (maximum entropy prior) when fewer than 2 observations
        are available.
        """
        if oracle_a == oracle_b:
            return 1.0
        key = self._key(oracle_a, oracle_b)
        hist = self._history.get(key, [])
        if not hist:
            return 0.5  # uninformative prior — no observations yet
        return sum(hist) / len(hist)

    def known_oracles(self) -> list[str]:
        """Return the set of oracle names that have been observed."""
        names: set[str] = set()
        for a, b in self._history:
            names.add(a)
            names.add(b)
        return sorted(names)

    def mean_rho(self, oracle_names: list[str]) -> float:
        """Return the mean pairwise ρ̄ for the given swarm."""
        if len(oracle_names) < 2:
            return 0.0
        total = 0.0
        count = 0
        for i in range(len(oracle_names)):
            for j in range(i + 1, len(oracle_names)):
                total += self.rho(oracle_names[i], oracle_names[j])
                count += 1
        return total / count if count else 0.0

    def high_correlation_pairs(self) -> list[tuple[str, str, float]]:
        """Return pairs with ρ > high_correlation_threshold, sorted descending."""
        result = []
        for (a, b), hist in self._history.items():
            if len(hist) < 5:
                continue
            r = sum(hist) / len(hist)
            if r > self.high_correlation_threshold:
                result.append((a, b, r))
        return sorted(result, key=lambda t: -t[2])

    def diversity_score(self, oracle_names: list[str]) -> float:
        """Return swarm diversity score in [0, 1].

        0 = all oracles always agree (zero diversity)
        1 = all oracles are perfectly independent (ρ̄ = 0.5 for binary votes)

        Under random binary voting, maximum expected agreement is 0.5, so
        diversity = 1 − (ρ̄ − 0.5) / 0.5 = (1.0 − ρ̄) / 0.5.
        Clipped to [0, 1].
        """
        rho_mean = self.mean_rho(oracle_names)
        return max(0.0, min(1.0, (1.0 - rho_mean) / 0.5))

    def correlation_report(self, oracle_names: Optional[list[str]] = None) -> dict:
        """Return a human-readable diversity report."""
        names = oracle_names or self.known_oracles()
        matrix = {
            a: {b: round(self.rho(a, b), 4) for b in names}
            for a in names
        }
        return {
            "oracles": names,
            "rho_matrix": matrix,
            "mean_rho": round(self.mean_rho(names), 4),
            "diversity_score": round(self.diversity_score(names), 4),
            "high_correlation_pairs": self.high_correlation_pairs(),
            "n_observations": {
                f"{a}|{b}": len(hist)
                for (a, b), hist in self._history.items()
            },
        }


# ---------------------------------------------------------------------------
# Swarm selection
# ---------------------------------------------------------------------------

def select_diverse_swarm(
    candidates: list[str],
    tracker: OracleDiversityTracker,
    k: int = 3,
    seed_oracle: Optional[str] = None,
) -> list[str]:
    """Greedy selection of k oracles that minimise mean pairwise ρ̄.

    Algorithm (greedy forward selection):
      1. Start with the seed oracle (default: the one with lowest mean ρ̄
         to all others).
      2. At each step, add the candidate that minimises the new mean ρ̄ of
         the selected set.

    This is a 1/2-approximation to the NP-hard maximum-diversity subset
    problem for submodular diversity functions.

    Parameters
    ----------
    candidates:
        List of oracle identifiers to choose from.
    tracker:
        A fitted :class:`OracleDiversityTracker` with historical observations.
    k:
        Desired swarm size (must be ≤ len(candidates)).
    seed_oracle:
        Optional oracle to include first (e.g., the strongest single model).

    Returns
    -------
    list[str]
        k oracle identifiers with minimum mean pairwise correlation.
    """
    if k <= 0 or not candidates:
        return []
    k = min(k, len(candidates))

    if seed_oracle and seed_oracle in candidates:
        selected = [seed_oracle]
        remaining = [c for c in candidates if c != seed_oracle]
    else:
        # Seed: oracle with lowest sum-ρ to all others
        def sum_rho(o: str) -> float:
            return sum(tracker.rho(o, other) for other in candidates if other != o)
        selected = [min(candidates, key=sum_rho)]
        remaining = [c for c in candidates if c != selected[0]]

    while len(selected) < k and remaining:
        # Add the candidate that minimises the new mean ρ̄
        def new_mean_rho(candidate: str) -> float:
            new_set = selected + [candidate]
            return tracker.mean_rho(new_set)

        best = min(remaining, key=new_mean_rho)
        selected.append(best)
        remaining.remove(best)

    return selected


def diversity_score(oracle_names: list[str], rho_matrix: dict[str, dict[str, float]]) -> float:
    """Compute diversity score from a pre-computed ρ-matrix (no tracker needed).

    Parameters
    ----------
    oracle_names:
        Ordered list of oracle identifiers.
    rho_matrix:
        Nested dict[oracle → dict[oracle → ρ]] as returned by
        ``CorrelationMatrix.rho_matrix()``.

    Returns
    -------
    float
        Diversity score in [0, 1].
    """
    if len(oracle_names) < 2:
        return 1.0
    total = 0.0
    count = 0
    for i in range(len(oracle_names)):
        for j in range(i + 1, len(oracle_names)):
            a, b = oracle_names[i], oracle_names[j]
            rho = rho_matrix.get(a, {}).get(b, 0.5)
            total += rho
            count += 1
    rho_mean = total / count if count else 0.5
    return max(0.0, min(1.0, (1.0 - rho_mean) / 0.5))
