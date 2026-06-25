"""
Scaling Analysis for REMORA's Coupled Online Learning System
============================================================

Answers three questions:
  1. How does performance scale with T (rounds / claims processed)?
  2. How does performance scale with k (oracle pool size)?
  3. What is the optimal oracle pool size k*(T) for a given budget?

All bounds derive from Theorem 1 in joint_convergence.py.

Summary of scaling laws
-----------------------
  · Adapter regret / T  → 0  at rate O(√(σ²(μ*)/T))
  · Bandit regret  / T  → 0  at rate O(√(k·log T / T))
  · Optimal η*(T)       = D₀ / (G · √(T · σ²(μ*)))   (decreasing)
  · Marginal k*(T)      ≈ (D₀·G·σ(μ*) / C_ts)² / log T  (decreases as 1/log T)
  · Rounds to ε-optimal = O(max(1/ε², k·log(k)/ε²))

Practical guidance
------------------
  · For T ≤ 100:   use k = 2–3 oracles (bandit has not converged for large k)
  · For T > 1000:  use k = 3–5 oracles only when diversity benefit, latency,
    and budget justify the extra calls. The marginal regret-equalising k*(T)
    above decreases with T under this cost model; it is not a claim that the
    optimal pool should grow automatically.
  · Best oracle (μ*) dominates: recruiting even one 90%-accurate oracle
    reduces gradient variance by 64 % asymptotically.
"""

from __future__ import annotations

import math


class ScalingAnalysis:
    """Computes optimal operating points from Theorem 1's scaling laws.

    Parameters
    ----------
    mu_star:   best oracle accuracy (> 0.5)
    G:         gradient norm bound
    D0:        initial parameter distance ‖Θ₀ − Θ*‖
    C_ts:      Thompson Sampling constant (default 1.0)
    """

    def __init__(
        self,
        mu_star: float = 0.85,
        G: float = 1.0,
        D0: float = 1.0,
        C_ts: float = 1.0,
    ) -> None:
        if not 0.5 < mu_star <= 1.0:
            raise ValueError("mu_star must be in (0.5, 1.0]")
        self.mu_star = mu_star
        self.G = G
        self.D0 = D0
        self.C_ts = C_ts
        self._sigma = math.sqrt(mu_star * (1.0 - mu_star))

    # ------------------------------------------------------------------
    # Optimal parameters
    # ------------------------------------------------------------------

    def optimal_learning_rate(self, t: int) -> float:
        """η*(T) = D₀ / (G · √(T · σ²(μ*)))."""
        if t <= 0:
            return float("inf")
        return self.D0 / (self.G * math.sqrt(t) * self._sigma)

    def optimal_oracle_count(self, t: int) -> float:
        """k*(T): marginal oracle count that equalises regret terms.

        Solve D₀·G·σ(μ*)·√T = C_ts·√(k·T·log T) → k* = (D₀·G·σ(μ*))² / (C_ts²·log T)

        Returns a real-valued marginal optimum under the simplified cost model.
        Since k* is divided by log(T), this quantity decreases as T grows.
        Production pool size should additionally account for correlation,
        domain diversity, latency budgets, and minimum redundancy requirements.
        """
        if t <= 1:
            return 1.0
        log_t = max(1.0, math.log(t))
        return (self.D0 * self.G * self._sigma / self.C_ts) ** 2 / log_t

    # ------------------------------------------------------------------
    # Regret bounds at given (T, k)
    # ------------------------------------------------------------------

    def adapter_regret(self, t: int) -> float:
        """Asymptotic adapter regret bound (coupling applied): D₀·G·σ(μ*)·√T."""
        return self.D0 * self.G * self._sigma * math.sqrt(max(0, t))

    def bandit_regret(self, t: int, k: int) -> float:
        """OracleBandit Thompson Sampling regret: C_ts·√(k·T·log T)."""
        if t <= 0:
            return 0.0
        return self.C_ts * math.sqrt(k * t * max(1.0, math.log(t)))

    def joint_regret(self, t: int, k: int) -> float:
        return self.adapter_regret(t) + self.bandit_regret(t, k)

    def average_regret(self, t: int, k: int) -> float:
        """E[R_T]/T — converges to 0."""
        return self.joint_regret(t, k) / max(1, t)

    # ------------------------------------------------------------------
    # Table generation
    # ------------------------------------------------------------------

    def regret_table(
        self, t_values: list[int], k_values: list[int]
    ) -> list[dict[str, object]]:
        """Grid of joint regret bounds over (T, k) pairs."""
        rows = []
        for t in t_values:
            for k in k_values:
                rows.append(
                    {
                        "T": t,
                        "k": k,
                        "adapter_regret": round(self.adapter_regret(t), 4),
                        "bandit_regret": round(self.bandit_regret(t, k), 4),
                        "joint_regret": round(self.joint_regret(t, k), 4),
                        "average_regret": round(self.average_regret(t, k), 6),
                        "optimal_k_star": round(self.optimal_oracle_count(t), 2),
                        "optimal_eta": round(self.optimal_learning_rate(t), 6),
                    }
                )
        return rows

    def rounds_to_epsilon_table(
        self, epsilon_values: list[float], k_values: list[int]
    ) -> list[dict[str, object]]:
        """Rounds T needed for E[R_T]/T ≤ ε, for each (ε, k) pair.

        Solves via bisection since T appears in the log term.
        """
        rows = []
        for eps in epsilon_values:
            for k in k_values:
                t = self._rounds_to_epsilon(eps, k)
                rows.append({"epsilon": eps, "k": k, "T_required": t})
        return rows

    def _rounds_to_epsilon(self, epsilon: float, k: int) -> int:
        """Bisection search for minimum T such that average_regret(T, k) ≤ ε."""
        lo, hi = 1, 10**10
        for _ in range(64):
            mid = (lo + hi) // 2
            if self.average_regret(mid, k) <= epsilon:
                hi = mid
            else:
                lo = mid
        return hi

    # ------------------------------------------------------------------
    # Coupling benefit across mu_star values
    # ------------------------------------------------------------------

    @staticmethod
    def coupling_benefit_table(
        mu_star_values: list[float], t: int = 1000, k: int = 3
    ) -> list[dict[str, object]]:
        """Show how the coupling improvement scales with oracle quality μ*.

        For each μ*, computes:
          - σ²(μ*): asymptotic gradient variance (coupled)
          - Variance reduction vs random selection
          - Adapter regret saving at T=t
        """
        rows = []
        G, D0 = 1.0, 1.0
        for mu in mu_star_values:
            if not 0.5 < mu <= 1.0:
                continue
            sigma_sq_opt = mu * (1.0 - mu)
            variance_reduction_pct = 100.0 * (0.25 - sigma_sq_opt) / 0.25
            sigma_opt = math.sqrt(sigma_sq_opt)
            adapter_coupled = D0 * G * sigma_opt * math.sqrt(t)
            adapter_decoupled = D0 * G * 0.5 * math.sqrt(t)  # σ(0.5) = 0.5
            saving = adapter_decoupled - adapter_coupled
            rows.append(
                {
                    "mu_star": mu,
                    "sigma_sq_optimal": round(sigma_sq_opt, 4),
                    "variance_reduction_pct": round(variance_reduction_pct, 1),
                    "adapter_regret_coupled": round(adapter_coupled, 4),
                    "adapter_regret_decoupled": round(adapter_decoupled, 4),
                    "adapter_regret_saving": round(saving, 4),
                    "asymptotic_coupling_factor_kappa": round(4 * mu * (1 - mu), 4),
                }
            )
        return rows
