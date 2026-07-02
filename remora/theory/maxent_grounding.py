"""
Maximum Entropy Grounding: what the F = λD − H identity is, and is not
=======================================================================

SCOPE (read before citing): this module verifies a narrow, exact algebraic
identity for a hand-constructed exponential family over oracle votes. It does
NOT ground REMORA's runtime free-energy expression F(T) = λD − TH for T ≠ 1,
and it does not license physical-thermodynamics language for the system.
(A prior version of this docstring claimed "F(T) = λD − TH is NOT a metaphor"
via a MaxEnt derivation; that derivation was invalid — see "What is NOT
established" below — and the claim is withdrawn, 2026-07-03.)

What IS established (and numerically verified by this class)
-------------------------------------------------------------
For the MaxEnt problem over consensus distributions p = (p_1, ..., p_m):

    maximise  H(p) = -sum_j p_j log p_j
    subject to  sum_j p_j * phi_j = D_bar   (dissensus constraint, phi_j = 1 - e_j)
                sum_j p_j = 1               (normalisation)

the stationarity conditions give the Gibbs form p*_j = exp(-λ·phi_j)/Z with
Z = Σ_j exp(-λ·phi_j), and at the optimum the standard identity

    F := λ · D_bar − H(p*) = −log Z

holds exactly (Jaynes 1957). `verify_free_energy_formula()` confirms this to
< 1e-9, and `verify_gibbs_minimises_free_energy()` confirms that the Gibbs
distribution minimises F(p) = λ·Σp_j·phi_j − H(p) over random alternatives
(convexity of −H plus linearity of the constraint term). Note the entropy
coefficient in this identity is fixed at 1.

What is NOT established
-----------------------
1. The runtime expression F(T) = λD − T·H for T ≠ 1 does NOT follow from the
   derivation above. H is the MaxEnt *objective*; it has no Lagrange
   multiplier, so there is no principled place for a free "temperature"
   coefficient on H in this framework. T in REMORA's runtime is a heuristic
   difficulty/uncertainty dial (see `remora/thermodynamics.py` and the
   paper's disclosure that no physical thermodynamic law is claimed).
2. No phase-transition result is established here. The Potts-model analogy
   used elsewhere in the research layer is qualitative; note that the
   mean-field q-state Potts transition is first-order for q ≥ 3, so
   second-order 2D-lattice results do not transfer to this setting.
3. The V = F(T=−1) relation checked by `lyapunov_free_energy_identity()` is
   a sign convention (substituting T = −1 flips −TH to +H), not an analytic
   continuation and not a physical statement. It is one line of algebra.
4. Any variational-inference interpretation is an informal analogy; no ELBO
   equivalence is derived or verified here.

References
----------
* Jaynes, E.T. (1957), Information theory and statistical mechanics,
  Phys. Rev. 106, 620.
* Cover, T.M. & Thomas, J.A. (2006), Elements of Information Theory,
  ch. 12 (maximum entropy).
"""

from __future__ import annotations

import math


class MaxEntropyGrounding:
    """Verifies the MaxEnt ↔ Free Energy equivalence numerically.

    Given a discrete vote distribution and a Lagrange multiplier λ,
    this class confirms that the Gibbs distribution maximises entropy
    subject to the dissensus constraint, and that F = λD − H holds exactly.
    """

    def __init__(self, lambda_: float = 1.0) -> None:
        self.lambda_ = lambda_

    # ------------------------------------------------------------------
    # Core distributions
    # ------------------------------------------------------------------

    def gibbs_distribution(self, vote_counts: list[int]) -> list[float]:
        """Gibbs distribution p*ⱼ = exp(−λφⱼ) / Z.

        Feature φⱼ = 1 − eⱼ where eⱼ = vote_count_j / total (empirical vote share).
        Higher vote share → lower dissensus penalty → higher Gibbs weight.

        Parameters
        ----------
        vote_counts : raw vote counts per answer option (length = n answers)
        """
        total = sum(vote_counts)
        n = len(vote_counts)
        if total == 0:
            return [1.0 / n] * n
        e = [c / total for c in vote_counts]                      # empirical proportions
        phi = [1.0 - ej for ej in e]                             # feature φⱼ = 1 − eⱼ
        log_unnorm = [-self.lambda_ * phj for phj in phi]
        max_log = max(log_unnorm)
        unnorm = [math.exp(x - max_log) for x in log_unnorm]
        z = sum(unnorm)
        return [u / z for u in unnorm]

    def empirical_distribution(self, vote_counts: list[int]) -> list[float]:
        """Normalised vote share eⱼ = vote_count_j / total."""
        total = sum(vote_counts)
        if total == 0:
            n = len(vote_counts)
            return [1.0 / n] * n
        return [c / total for c in vote_counts]

    def _feature(self, vote_counts: list[int]) -> list[float]:
        """φⱼ = 1 − eⱼ (same feature used in Gibbs and free energy)."""
        e = self.empirical_distribution(vote_counts)
        return [1.0 - ej for ej in e]

    # ------------------------------------------------------------------
    # Information-theoretic quantities
    # ------------------------------------------------------------------

    @staticmethod
    def entropy(p: list[float]) -> float:
        """Shannon entropy H(p) = −Σⱼ pⱼ log pⱼ (nats)."""
        return -sum(pj * math.log(pj) for pj in p if pj > 1e-15)

    @staticmethod
    def dissensus(p: list[float]) -> float:
        """Herfindahl dissensus D(p) = 1 − Σⱼ pⱼ²  (0 = full consensus)."""
        return 1.0 - sum(pj * pj for pj in p)

    def constraint_dissensus(self, p: list[float], vote_counts: list[int]) -> float:
        """Constraint dissensus: D = Σⱼ pⱼ φⱼ = 1 − Σⱼ pⱼ eⱼ.

        This is the dissensus term that appears in the MaxEnt Lagrangian,
        consistent with the Gibbs feature φⱼ = 1 − eⱼ.
        """
        phi = self._feature(vote_counts)
        return sum(pj * phj for pj, phj in zip(p, phi))

    def free_energy(self, p: list[float], vote_counts: list[int]) -> float:
        """F(p) = λ · D_constraint(p) − H(p).

        Uses the constraint dissensus D = Σpⱼφⱼ (not Herfindahl) so that
        F = −log Z holds exactly at the Gibbs optimum.
        """
        return self.lambda_ * self.constraint_dissensus(p, vote_counts) - self.entropy(p)

    def log_partition(self, vote_counts: list[int]) -> float:
        """log Z = Σⱼ exp(−λφⱼ), computed directly from features."""
        phi = self._feature(vote_counts)
        max_neg = max(-self.lambda_ * phj for phj in phi)
        return max_neg + math.log(sum(math.exp(-self.lambda_ * phj - max_neg) for phj in phi))

    # ------------------------------------------------------------------
    # Verification methods
    # ------------------------------------------------------------------

    def verify_gibbs_minimises_free_energy(
        self, vote_counts: list[int], n_random: int = 1_000, seed: int = 0
    ) -> dict[str, object]:
        """Confirm that the Gibbs distribution minimises F(p) over random alternatives.

        F(p) = λ·Σpⱼφⱼ − H(p) with fixed features φⱼ = 1 − eⱼ.
        By the convexity of −H and linearity of the dissensus term, the Gibbs
        distribution is the unique minimiser.
        """
        import random

        rng = random.Random(seed)
        p_gibbs = self.gibbs_distribution(vote_counts)
        f_gibbs = self.free_energy(p_gibbs, vote_counts)
        n = len(vote_counts)
        violations = 0
        min_f_random = float("inf")
        for _ in range(n_random):
            gammas = [rng.expovariate(1.0) for _ in range(n)]
            s = sum(gammas)
            p_rand = [g / s for g in gammas]
            f_rand = self.free_energy(p_rand, vote_counts)
            min_f_random = min(min_f_random, f_rand)
            if f_rand < f_gibbs - 1e-9:
                violations += 1
        return {
            "f_gibbs": f_gibbs,
            "f_random_min": min_f_random,
            "violations": violations,
            "gibbs_is_minimum": violations == 0,
        }

    def verify_free_energy_formula(self, vote_counts: list[int]) -> dict[str, float]:
        """Verify F(p*) = −log Z (the fundamental thermodynamic identity).

        F(p*) = λ·D_constraint(p*) − H(p*)  [computed via distributions]
        −log Z                               [computed directly from features]
        These must agree to floating-point precision.
        """
        p_gibbs = self.gibbs_distribution(vote_counts)
        f_via_formula = self.free_energy(p_gibbs, vote_counts)   # λD − H
        f_via_log_z = -self.log_partition(vote_counts)            # −log Z
        return {
            "f_via_lambda_D_minus_H": f_via_formula,
            "f_via_neg_log_Z": f_via_log_z,
            "absolute_error": abs(f_via_formula - f_via_log_z),
            "formula_verified": abs(f_via_formula - f_via_log_z) < 1e-9,
        }

    def lyapunov_free_energy_identity(self, vote_counts: list[int]) -> dict[str, float]:
        """Verify V = H + lambda * D and F(T=-1) under REMORA's sign convention.

        This diagnostic bridges control-theoretic stability and the free-energy
        interpretation used by the research layer.
        """
        p = self.gibbs_distribution(vote_counts)
        H = self.entropy(p)
        D = self.dissensus(p)
        V = H + self.lambda_ * D  # Lyapunov function
        F_neg1 = self.lambda_ * D - (-1.0) * H  # F at T = -1
        # At T=-1: F(T=-1) = lambda * D + H = V.
        return {
            "H": H,
            "D": D,
            "V_lyapunov": V,
            "F_at_T_neg1": F_neg1,
            "identity_holds": abs(V - F_neg1) < 1e-12,
        }

    # ------------------------------------------------------------------
    # Phase transition analysis
    # ------------------------------------------------------------------

    @staticmethod
    def critical_temperature(lambda_: float, mean_consensus: float, k: int) -> float:
        """T_c = λ(1 − ρ̄) / ln(k).

        Below T_c: ordered phase (peaked Gibbs distribution, ACCEPT).
        Above T_c: disordered phase (flat Gibbs distribution, ABSTAIN).

        Parameters
        ----------
        lambda_:         coupling constant
        mean_consensus:  ρ̄ = mean oracle agreement
        k:               number of oracle options (answers)
        """
        if k <= 1:
            return float("inf")
        return lambda_ * (1.0 - mean_consensus) / math.log(k)

    @staticmethod
    def potts_order_parameter(p: list[float]) -> float:
        """η = (max_p − 1/k) / (1 − 1/k).

        0 = fully disordered, 1 = fully ordered.
        Matches the Potts model order parameter for k states.
        """
        k = len(p)
        if k <= 1:
            return 1.0
        max_p = max(p)
        return (max_p - 1.0 / k) / (1.0 - 1.0 / k)
