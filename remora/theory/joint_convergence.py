"""
Theorem 1 — Joint Convergence of REMORA's Coupled Online Learners
=================================================================

REMORA runs two online learning algorithms simultaneously:

  · ThermodynamicAdapter  — online SGD on Θ = (λ, w₁, w₂, w₃)
  · OracleBandit          — Thompson Sampling on pool O = {o₁,…,oₖ}

These are NOT independent.  Oracle selection quality directly controls the
gradient variance of the adapter, creating a feedback loop that makes the
joint regret bound TIGHTER than the sum of the individual bounds.

Protocol (round t)
------------------
1. OracleBandit selects S_t ⊆ O via Thompson Sampling.
2. Oracles in S_t answer query q_t; ground truth y_t ∈ {0,1}.
3. Dissensus D_t computed from votes of S_t.
4. ThermodynamicAdapter receives (D_t, y_t, phase_t) and updates Θ_t.
5. OracleBandit updates Beta posteriors with y_t.

Gradient analysis
-----------------
The stochastic gradient in the adapter is:

    g_t = (trust_t − y_t) · (−D_t)

y_t is Bernoulli(μ_t) where μ_t = E[accuracy of selected oracles at step t].
Conditional gradient variance:

    Var[g_t | μ_t] ≤ G² · σ²(μ_t)    where σ²(μ) = μ(1−μ)

σ²(μ) is minimised when μ → 1 and maximised at μ = 0.5 (random).  Because
Thompson Sampling drives μ_t → μ* (best oracle accuracy), gradient variance
decreases over time — a benefit absent in decoupled operation.

Theorem 1 (Joint Convergence)
------------------------------
Under:
  (A1) L(Θ) convex and β-smooth in Θ
  (A2) ‖g_t‖ ≤ G almost surely
  (A3) μ* = max_{i∈O} μᵢ > 0.5  (at least one oracle beats random)
  (A4) Thompson Sampling satisfies E[μ* − μ_t] ≤ C_ts·√(k·log t / t)

With learning rate η = D₀ / (G·√T):

    E[R_T] ≤ D₀·G·√T · √(σ²_avg(T)) + C_ts·√(k·T·log T)          (1)

where σ²_avg(T) = (1/T)Σ_t E[σ²(μ_t)] converges to σ²(μ*) from above.

Corollary (Coupling Improvement)
----------------------------------
For decoupled operation (fixed random oracle selection, σ²=0.25):

    E[R_T^decoupled] ≤ D₀·G·√T · 0.5 + C_ts·√(k·T·log T)          (2)

Subtracting (1) from (2):

    E[R_T^decoupled] − E[R_T^coupled] ≥ D₀·G·√T · (0.5 − √(σ²_avg(T))) > 0

The saving is O(√T) — unbounded improvement as T → ∞.

Asymptotic coupling factor
--------------------------
As T → ∞, σ²_avg → σ²(μ*).  Define the asymptotic coupling factor:

    κ = σ²(μ*)/0.25 = 4μ*(1−μ*)  ∈ (0, 1)  for μ* > 0.5

For μ* = 0.85: κ = 0.51  (49 % gradient-variance reduction)
For μ* = 0.90: κ = 0.36  (64 % gradient-variance reduction)
For μ* = 0.70: κ = 0.84  (16 % gradient-variance reduction)

References
----------
· Zinkevich (2003) — Online convex programming and SGD regret bound
· Agrawal & Goyal (2012) — Analysis of Thompson Sampling for MAB
· Hazan (2016) — Introduction to Online Convex Optimization (Theorem 3.1)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CoupledConvergenceResult:
    """Numerical evaluation of Theorem 1 at a given (T, k, μ*) operating point."""

    t: int
    k: int
    mu_star: float
    eta_optimal: float           # optimal learning rate η* = D₀/(G·√T)
    sigma_sq_random: float       # gradient variance under random selection (0.25)
    sigma_sq_optimal: float      # σ²(μ*) — asymptotic coupled variance
    sigma_sq_avg: float          # σ²_avg(T) — finite-time average variance
    adapter_regret_bound: float  # D₀·G·√T·√(σ²_avg)
    bandit_regret_bound: float   # C_ts·√(k·T·log T)
    joint_regret_bound: float    # sum
    decoupled_regret_bound: float
    coupling_improvement: float          # absolute reduction in regret bound
    coupling_improvement_pct: float      # percentage reduction
    asymptotic_coupling_factor: float    # κ = 4μ*(1−μ*)


class JointConvergenceTheorem:
    """Computes the joint convergence bounds from Theorem 1.

    Parameters
    ----------
    k:              oracle pool size |O|
    mu_star:        best oracle accuracy μ* — must be > 0.5
    G:              gradient norm bound (‖g_t‖ ≤ G a.s.)
    D0:             initial parameter distance ‖Θ₀ − Θ*‖
    C_ts:           Thompson Sampling constant (default 1.0, from Agrawal & Goyal 2012)
    """

    C_TS: float = 1.0  # Thompson Sampling regret constant

    def __init__(
        self,
        k: int,
        mu_star: float,
        G: float = 1.0,
        D0: float = 1.0,
        C_ts: float = 1.0,
    ) -> None:
        if not 0.5 < mu_star <= 1.0:
            raise ValueError("mu_star must be in (0.5, 1.0] for coupling improvement")
        if k < 1:
            raise ValueError("k >= 1 required")
        self.k = k
        self.mu_star = mu_star
        self.G = G
        self.D0 = D0
        self.C_ts = C_ts

    # ------------------------------------------------------------------
    # Building blocks
    # ------------------------------------------------------------------

    @staticmethod
    def sigma_sq(mu: float) -> float:
        """Bernoulli variance σ²(μ) = μ(1−μ).  Range [0, 0.25]."""
        return mu * (1.0 - mu)

    def oracle_quality_at(self, t: int) -> float:
        """Expected oracle quality at round t under Thompson Sampling.

        Converges to μ* from below at rate O(√(k·log t / t)).
        Lower-bounded at 0.5 (Thompson Sampling never does worse than random
        in expectation, by the symmetry of the Beta prior).
        """
        if t <= 0:
            return 0.5
        gap = self.C_ts * math.sqrt(self.k * max(1.0, math.log(t)) / t)
        return max(0.5, self.mu_star - gap)

    def sigma_sq_avg(self, t: int, *, n_sum: int = 500) -> float:
        """Average gradient variance over t rounds.

        σ²_avg(T) = (1/T) Σ_{s=1}^{T} σ²(μ_s)

        Exact sum up to n_sum; tail approximated via geometric decay toward σ²(μ*).
        """
        if t <= 0:
            return 0.25
        sigma_star = self.sigma_sq(self.mu_star)
        cap = min(t, n_sum)
        total = sum(self.sigma_sq(self.oracle_quality_at(s)) for s in range(1, cap + 1))
        if t > cap:
            # Tail contribution: excess over σ²* decays as O(1/√s); integrate analytically.
            # Σ_{s=cap+1}^{T} excess_s ≈ excess_{cap} · 2(√T − √cap)
            excess_cap = self.sigma_sq(self.oracle_quality_at(cap)) - sigma_star
            tail_excess = max(0.0, excess_cap * 2.0 * (math.sqrt(t) - math.sqrt(cap)))
            total += sigma_star * (t - cap) + tail_excess
        return total / t

    # ------------------------------------------------------------------
    # Regret bounds
    # ------------------------------------------------------------------

    def adapter_regret_bound(self, t: int) -> float:
        """ThermodynamicAdapter regret bound with coupling (equation 1).

        E[adapter regret] ≤ D₀·G·√T · √(σ²_avg(T))

        Uses optimal η* = D₀ / (G·√(T·σ²_avg(T))); reduces to D₀·G·√(T·σ²_avg).
        """
        if t <= 0:
            return 0.0
        return self.D0 * self.G * math.sqrt(t * self.sigma_sq_avg(t))

    def bandit_regret_bound(self, t: int) -> float:
        """OracleBandit Thompson Sampling regret bound.

        E[bandit regret] ≤ C_ts · √(k · T · log T)
        """
        if t <= 0:
            return 0.0
        return self.C_ts * math.sqrt(self.k * t * max(1.0, math.log(t)))

    def decoupled_regret_bound(self, t: int) -> float:
        """Hypothetical bound with fixed random oracle selection (σ² = 0.25).

        This is strictly worse than coupled operation for μ* > 0.5.
        """
        if t <= 0:
            return 0.0
        adapter_decoupled = self.D0 * self.G * math.sqrt(t * 0.25)
        return adapter_decoupled + self.bandit_regret_bound(t)

    def evaluate(self, t: int) -> CoupledConvergenceResult:
        """Evaluate Theorem 1 at round t, returning all bound components."""
        eta_opt = self.D0 / (self.G * math.sqrt(max(1, t)))
        sa = self.sigma_sq_avg(t)
        adapter = self.adapter_regret_bound(t)
        bandit = self.bandit_regret_bound(t)
        joint = adapter + bandit
        decoupled = self.decoupled_regret_bound(t)
        improvement = decoupled - joint
        pct = 100.0 * improvement / decoupled if decoupled > 0 else 0.0
        return CoupledConvergenceResult(
            t=t,
            k=self.k,
            mu_star=self.mu_star,
            eta_optimal=eta_opt,
            sigma_sq_random=0.25,
            sigma_sq_optimal=self.sigma_sq(self.mu_star),
            sigma_sq_avg=sa,
            adapter_regret_bound=adapter,
            bandit_regret_bound=bandit,
            joint_regret_bound=joint,
            decoupled_regret_bound=decoupled,
            coupling_improvement=improvement,
            coupling_improvement_pct=pct,
            asymptotic_coupling_factor=self.asymptotic_coupling_factor(self.mu_star),
        )

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def asymptotic_coupling_factor(mu_star: float) -> float:
        """κ = σ²(μ*)/σ²(0.5) = 4μ*(1−μ*).

        Fraction of gradient variance retained in the coupled system
        as T → ∞.  Lower is better.
        """
        return 4.0 * mu_star * (1.0 - mu_star)

    @staticmethod
    def rounds_to_epsilon(
        epsilon: float,
        k: int,
        mu_star: float = 0.85,
        G: float = 1.0,
        D0: float = 1.0,
        C_ts: float = 1.0,
    ) -> int:
        """Minimum T for average regret E[R_T]/T ≤ ε.

        Solves D₀·G·√(σ²(μ*))/√T + C_ts·√(k·log T / T) ≤ ε via bisection.
        """
        sigma_star = math.sqrt(mu_star * (1.0 - mu_star))
        lo, hi = 1, 10 ** 9
        for _ in range(64):
            mid = (lo + hi) // 2
            bound = D0 * G * sigma_star / math.sqrt(mid) + C_ts * math.sqrt(
                k * max(1.0, math.log(mid)) / mid
            )
            if bound <= epsilon:
                hi = mid
            else:
                lo = mid
        return hi
