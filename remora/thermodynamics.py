# Author: Stian Skogbrott
# License: Apache-2.0
"""Experimental thermodynamic utilities for pre-iteration consensus checks.

These helpers map a pre-sweep consensus snapshot onto a small set of
thermodynamic-style observables. The implementation is intentionally modest:
it exposes the quantities needed for experimentation without claiming a formal
proof beyond the formulas encoded here.
"""
from __future__ import annotations

import json
import math
import re
import zlib
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from remora.stability import EXPERIMENTAL
__stability__ = EXPERIMENTAL


@dataclass(frozen=True)
class ThermodynamicState:
    """Snapshot of the consensus state at a single effective temperature."""

    temperature: float
    free_energy: float
    order_parameter: float
    susceptibility: float
    phase: str
    hallucination_bound: float
    trust_score: float
    raw_temperature: float | None = None
    critical_temperature: float | None = None
    temperature_ratio: float | None = None


@dataclass(frozen=True)
class ThermodynamicCalibration:
    """Empirical calibration for mapping observables into phase/trust signals."""

    temperature_scale: float = 1.0
    temperature_offset: float = 0.0
    critical_tolerance: float = 0.15
    ordered_min_eta: float = 0.5
    ordered_phase_weight: float = 1.0
    critical_phase_weight: float = 0.5
    disordered_phase_weight: float = 0.1
    chi_scale: float = 10.0

    def phase_weight(self, phase: str) -> float:
        return {
            "ordered": self.ordered_phase_weight,
            "critical": self.critical_phase_weight,
            "disordered": self.disordered_phase_weight,
        }.get(phase, self.disordered_phase_weight)


def thermodynamic_calibration_from_dict(payload: dict | None) -> ThermodynamicCalibration:
    """Build a calibration profile from a JSON-like mapping."""
    if not payload:
        return ThermodynamicCalibration()
    baseline = ThermodynamicCalibration()
    return ThermodynamicCalibration(
        temperature_scale=float(payload.get("temperature_scale", baseline.temperature_scale)),
        temperature_offset=float(payload.get("temperature_offset", baseline.temperature_offset)),
        critical_tolerance=float(payload.get("critical_tolerance", baseline.critical_tolerance)),
        ordered_min_eta=float(payload.get("ordered_min_eta", baseline.ordered_min_eta)),
        ordered_phase_weight=float(payload.get("ordered_phase_weight", baseline.ordered_phase_weight)),
        critical_phase_weight=float(payload.get("critical_phase_weight", baseline.critical_phase_weight)),
        disordered_phase_weight=float(payload.get("disordered_phase_weight", baseline.disordered_phase_weight)),
        chi_scale=float(payload.get("chi_scale", baseline.chi_scale)),
    )


def load_thermodynamic_calibration(path: str | Path | None) -> ThermodynamicCalibration | None:
    """Load a calibration profile from disk."""
    if path is None:
        return None
    payload = json.loads(Path(path).read_bytes().rstrip(b"\x00").decode("utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("calibration"), dict):
        payload = payload["calibration"]
    return thermodynamic_calibration_from_dict(payload)


def calibration_to_dict(calibration: ThermodynamicCalibration) -> dict:
    """Return a JSON-serialisable mapping for a calibration profile."""
    return asdict(calibration)


def apply_temperature_calibration(
    temperature: float,
    calibration: ThermodynamicCalibration | None = None,
) -> float:
    """Affine rescaling that aligns estimated temperature with empirical phase boundaries."""
    if calibration is None:
        return max(temperature, 1e-9)
    return max(calibration.temperature_scale * temperature + calibration.temperature_offset, 1e-9)


@dataclass(frozen=True)
class PhaseDiagram:
    """Phase diagram across a temperature sweep for one oracle configuration."""

    n_oracles: int
    n_verdicts: int
    rho_bar: float
    lambda_coupling: float
    T_critical: float
    gamma_exponent: float
    states: list[ThermodynamicState]


# ---------------------------------------------------------------------------
# Structural (pre-inference) temperature — resolves T↔D circularity
# ---------------------------------------------------------------------------

#: Safety-floor thermal priors for known task categories.
#:
#: These values are *intentional safety margins*, not empirical estimates of the
#: oracle-measured temperature.  The purpose is to bias the pre-inference routing
#: toward caution for high-risk categories *before any oracle is called*.
#:
#: Design rationale (calibrated against N=544 benchmark, 2026-05-29):
#:   - ``factoid``    = 0.25  → observed mean oracle-T for BoolQ = 0.290
#:                              (slight conservative bias — safe default)
#:   - ``reasoning``  = 0.85  → no direct calibration dataset; sits between
#:                              factoid and creative as a neutral default
#:   - ``creative``   = 1.50  → intentionally above observed range to force
#:                              VERIFY/ESCALATE for open-ended generation
#:   - ``adversarial``= 1.70  → observed mean oracle-T for TruthfulQA = 0.336;
#:                              prior is intentionally 5× higher to route
#:                              adversarial prompts to ESCALATE before iteration.
#:                              This is a hard safety floor, not a calibrated fit.
#:
#: A production deployment SHOULD override these priors with domain-specific
#: values learned from held-out calibration runs.  The conservative defaults
#: mean the estimator is biased toward caution for unknown domains.
_CATEGORY_PRIORS: dict[str, float] = {
    "factoid": 0.25,      # BoolQ-style yes/no; observed mean T ≈ 0.290
    "reasoning": 0.85,   # multi-step logic / arithmetic; conservative default
    "creative": 1.50,    # open-ended generation; safety floor (forces VERIFY)
    "adversarial": 1.70, # TruthfulQA traps; safety floor (forces ESCALATE)
}


class DomainClassifier:
    """Heuristic prompt category classifier for :func:`estimate_structural_temperature`.

    Classifies a prompt into one of four thermal categories using lightweight
    signal patterns — no model call required.  The classifier runs in O(P·N)
    where P is the number of patterns and N is the prompt length.

    Categories
    ----------
    factoid
        Simple binary or lookup facts.  Signals: "true or false", "yes or no",
        "is it", "what is", "who is", "when did", "where is".
    reasoning
        Multi-step logic, calculation, or analysis.  Signals: "calculate",
        "solve", "prove", "explain why", "step by step", "analyze", "compare".
    creative
        Open-ended generation.  Signals: "write", "create", "generate",
        "compose", "draft", "imagine", "story", "poem".
    adversarial
        TruthfulQA-style traps or self-referential questions.  Signals:
        "always", "never", "everyone knows", "obvious", "actually",
        "you're wrong", "prove that you".

    The classifier checks categories in priority order (adversarial → creative
    → reasoning → factoid) and returns the first match.  If no pattern matches,
    it returns ``"reasoning"`` (default prior 0.85).
    """

    _PATTERNS: dict[str, list[str]] = {
        "adversarial": [
            r"\beveryone knows\b",
            r"\bobviously\b",
            r"\bactually\b.*\bwrong\b",
            r"\bprove that you\b",
            r"\byou('re| are) (wrong|mistaken|lying|incorrect)\b",
            r"\bnever\b.*\balways\b",
            r"\balways\b.*\bnever\b",
            r"\bimpossible.*possible\b",
            r"\bcontradiction\b",
            r"\bparadox\b",
        ],
        "creative": [
            r"\bwrite (a|an|me)\b",
            r"\bcreate (a|an|me)\b",
            r"\bgenerate (a|an|me)\b",
            r"\bcompose (a|an|me)\b",
            r"\bdraft (a|an|me)\b",
            r"\bimagine\b",
            r"\bstory about\b",
            r"\bpoem (about|for|on)\b",
            r"\bessay (about|on)\b",
            r"\bscript for\b",
        ],
        "reasoning": [
            r"\bcalculate\b",
            r"\bsolve\b",
            r"\bprove\b",
            r"\bexplain (why|how)\b",
            r"\bstep[- ]by[- ]step\b",
            r"\banalyze\b",
            r"\banalyse\b",
            r"\bcompare\b",
            r"\bwhat (would|will|should)\b",
            r"\bif .{1,60} then\b",
            r"\bhow (do|does|would|can|could)\b",
            r"\bwhy (does|do|is|are|would|did)\b",
            r"\bderive\b",
            r"\boptimize\b",
            r"\boptimise\b",
        ],
        "factoid": [
            r"\btrue or false\b",
            r"\byes or no\b",
            r"\bis it (true|false|correct|right)\b",
            r"\bwhat is (the|a|an) [a-z]+\b",
            r"\bwho (is|was|are|were)\b",
            r"\bwhen (did|was|is|are)\b",
            r"\bwhere (is|are|was|were)\b",
            r"\bwhich (is|are|was|were)\b",
            r"\bdoes .{1,60}\?$",
            r"\bis .{1,60}\?$",
            # SQuAD / reading-comprehension style factoid lookups.
            # These use interrogative phrases like "In what", "How many", "What type"
            # that the reasoning patterns do not capture.  Structural temperature for
            # these prompts is empirically closer to BoolQ (T≈0.29) than to multi-step
            # reasoning (T≈0.85), so routing them to the factoid prior avoids spurious
            # disordered-phase classification when oracle polarity consensus is high.
            r"\bin what\b",
            r"\bhow many\b",
            r"\bhow much\b",
            r"\bwhat (type|kind|name|year|century|country|city|state|language|color|colour)\b",
            r"\bwho (first|last|did|won|founded|created|invented|built|wrote|led|became)\b",
            r"\bwhat (do|does|did) .{1,40}\?$",
            r"\bwhat (happened|occurs|causes|makes|allows|prevents)\b",
        ],
    }

    # Compiled once at class load
    _COMPILED: dict[str, list[re.Pattern]] = {
        cat: [re.compile(p, re.IGNORECASE) for p in pats]
        for cat, pats in _PATTERNS.items()
    }

    _PRIORITY = ("adversarial", "creative", "reasoning", "factoid")

    @classmethod
    def classify(cls, prompt: str) -> str:
        """Return the thermal category for *prompt*.

        Returns ``"reasoning"`` if no pattern matches (safe default).
        """
        for cat in cls._PRIORITY:
            for pattern in cls._COMPILED[cat]:
                if pattern.search(prompt):
                    return cat
        return "reasoning"


def estimate_structural_temperature(
    prompt: str,
    category: str | None = None,
) -> float:
    """Estimate question temperature from prompt structure alone (pre-inference).

    This is the **circularity-free** alternative to
    :func:`estimate_temperature`.  T is derived from the *input* prompt before
    any oracle has responded, so D (oracle dissensus) plays no role.  The
    result can be used directly in F = λD − TH without the D→T→F feedback
    loop documented in `NEGATIVE_RESULTS.md` (Resolved Findings Archive, R7).

    Algorithm
    ---------
    Three signals, all computable from the raw prompt string:

    1. **Semantic density** — zlib compression ratio as a Kolmogorov
       complexity proxy.  A value close to 1.0 means the prompt is
       information-dense and hard to compress (high structural temperature).
    2. **Log-length factor** — longer prompts with more conditions and
       variables are harder for any model family to answer reliably.
    3. **Category prior** — task-type thermal floor loaded from
       ``_CATEGORY_PRIORS``; defaults to the *reasoning* prior (0.85).

    The weighted combination is::

        T_structural = prior × 0.70 + density × 0.20 + length × 0.10

    Parameters
    ----------
    prompt:
        The raw question string, before any system-prompt wrapping.
    category:
        Optional task category key ("factoid", "reasoning", "creative",
        "adversarial").  Defaults to "reasoning" prior (0.85).

    Returns
    -------
    float
        Structural temperature in [0.05, 2.0].
    """
    if not prompt:
        return _CATEGORY_PRIORS.get(category or "", 0.85)

    # 1. Semantic density — Kolmogorov complexity proxy via zlib
    encoded = prompt.encode("utf-8")
    compressed = zlib.compress(encoded, level=9)
    density = len(compressed) / max(len(encoded), 1)

    # 2. Log-length factor (normalised; log1p(22 000 chars) / 10 ≈ 1.0)
    length_factor = min(math.log1p(len(prompt)) / 10.0, 1.0)

    # 3. Category prior — auto-classify when not provided
    resolved_category = category if category is not None else DomainClassifier.classify(prompt)
    prior = _CATEGORY_PRIORS.get(resolved_category, 0.85)

    # Weighted combination — fully independent of oracle responses
    raw = prior * 0.70 + density * 0.20 + length_factor * 0.10
    return round(max(0.05, min(raw, 2.0)), 6)


def estimate_temperature_prior(prompt: str) -> float:
    """Estimate temperature from prompt structure alone — zero dependency on D.

    Unlike :func:`estimate_structural_temperature`, this function has **no
    category prior**: it uses only the two structural signals that can be
    computed from the raw prompt string without any task-domain knowledge.

    Algorithm::

        density       = len(zlib.compress(prompt)) / len(prompt)   # in (0, 1]
        length_factor = min(log1p(len(prompt)) / 10, 1.0)           # in [0, 1]
        T_prior       = density * 0.60 + length_factor * 0.40

    Both signals are in [0, 1]; the weighted sum therefore lives in [0, 1]
    before clamping to [0.05, 2.0].  The formula is intentionally simple so
    that it is easy to audit and replace with an empirically fitted model.

    Returns
    -------
    float
        Structural temperature prior in [0.05, 2.0].
    """
    if not prompt:
        return 0.50  # uninformative prior

    encoded = prompt.encode("utf-8")
    compressed = zlib.compress(encoded, level=9)
    density = len(compressed) / max(len(encoded), 1)
    length_factor = min(math.log1p(len(prompt)) / 10.0, 1.0)

    raw = density * 0.60 + length_factor * 0.40
    return round(max(0.05, min(raw, 2.0)), 6)


# ---------------------------------------------------------------------------
# Legacy post-hoc temperature (uses oracle distribution — has D↔T circularity)
# ---------------------------------------------------------------------------


def estimate_temperature(
    weighted_distribution: dict[str, float],
    rho_bar: float,
    individual_confidences: list[float],
) -> float:
    """Estimate an effective question temperature from observable signals.

    .. deprecated:: structural
        This function has a mild circular dependency: ``dissensus = 1 − max_support``
        is the same D term used in F = λD − TH, so T inherits 18 % of its
        weight from D.  Prefer :func:`estimate_structural_temperature` when
        the prompt text is available — it is fully independent of oracle outputs.
        See `NEGATIVE_RESULTS.md` (Resolved Findings Archive, R7) for details.
    """
    if not weighted_distribution:
        return float("inf")

    entropy = sum(-p * math.log2(p) for p in weighted_distribution.values() if p > 0)
    if individual_confidences:
        mean_conf = sum(individual_confidences) / len(individual_confidences)
        variance = sum((conf - mean_conf) ** 2 for conf in individual_confidences) / len(individual_confidences)
    else:
        mean_conf = 0.5
        variance = 0.25

    max_support = max(weighted_distribution.values())
    k_eff = math.exp(entropy) if entropy > 0 else 1.0
    bounded_rho = max(0.0, min(rho_bar, 1.0))
    confidence_deficit = max(0.0, 1.0 - mean_conf)
    # NOTE — mild circularity: `dissensus` here equals D = 1 − max_support,
    # the same D term that appears in F = λD − T·H.  T therefore inherits
    # 18 % of its weight from D, so F is not a fully independent composition
    # of D and T.  The coupling is intentional (high disagreement raises
    # effective temperature) but reduces the theoretical cleanness of the
    # free-energy analogy.  A future improvement would estimate T from
    # question-level priors (semantic density, historical category variance)
    # rather than from the current oracle distribution.  See NEGATIVE_RESULTS.md.
    dissensus = max(0.0, 1.0 - max_support)
    # Keep temperature informative even under unanimous pre-sweeps by combining
    # confidence deficit, dissensus, and a small correlation-pressure prior.
    temp = (
        0.30 * entropy
        + 0.20 * (4.0 * variance)
        + 0.10 * math.log2(max(k_eff, 1.0))
        + 0.22 * confidence_deficit
        + 0.18 * dissensus
        + 0.08 * bounded_rho
        + 0.02
    )
    return max(temp, 1e-9)


def critical_temperature(lambda_coupling: float, rho_bar: float, k: int) -> float:
    """Compute the experimental critical temperature proxy for k verdict states."""
    if k <= 1:
        return float("inf")
    bounded_rho = max(0.0, min(rho_bar, 0.999999))
    return lambda_coupling * (1.0 - bounded_rho) / math.log(max(k, 2))


def order_parameter(weighted_distribution: dict[str, float], k: int) -> float:
    """Compute the normalized consensus order parameter eta in [0, 1]."""
    if not weighted_distribution or k <= 1:
        return 0.0
    max_support = max(weighted_distribution.values())
    uniform = 1.0 / k
    if max_support <= uniform:
        return 0.0
    return (max_support - uniform) / (1.0 - uniform)


def susceptibility(eta_values: list[float], t_values: list[float]) -> list[float]:
    """Compute |d eta / dT| with simple finite differences."""
    if len(eta_values) != len(t_values):
        raise ValueError("eta_values and t_values must have the same length")
    if len(eta_values) < 2:
        return [0.0 for _ in eta_values]

    chi: list[float] = []
    for index in range(len(eta_values)):
        if index == 0:
            delta_eta = eta_values[1] - eta_values[0]
            delta_t = t_values[1] - t_values[0]
        elif index == len(eta_values) - 1:
            delta_eta = eta_values[-1] - eta_values[-2]
            delta_t = t_values[-1] - t_values[-2]
        else:
            delta_eta = eta_values[index + 1] - eta_values[index - 1]
            delta_t = t_values[index + 1] - t_values[index - 1]
        chi.append(abs(delta_eta / delta_t) if abs(delta_t) > 1e-12 else 0.0)
    return chi


def critical_exponent_gamma(k: int) -> float:
    """Return 2D-LATTICE Potts susceptibility exponents — reporting decoration only.

    These are the exact 2D Potts values (gamma = 7/4, 13/9, 7/6 for
    k = 2, 3, 4; the transition is first-order for k > 4, hence inf).
    They do NOT apply to REMORA's setting: the consensus model is mean-field
    (fully connected, remora/statphys/potts.py) where gamma = 1, there is no
    lattice, and n <= 5 oracles is nowhere near a scaling regime. The value
    is carried in PhaseDiagram for descriptive labeling only and feeds no
    routing decision (compute_phase_diagram is referenced only by tests).
    """
    if k <= 1:
        return 0.0
    if k == 2:
        return 7.0 / 4.0
    if k == 3:
        return 13.0 / 9.0
    if k == 4:
        return 7.0 / 6.0
    return float("inf")



def estimate_temperature_semantic(
    oracle_responses: list[str],
    rho_bar: float = 0.0,
    individual_confidences: list[float] | None = None,
    backend=None,
    entailment_threshold: float = 0.5,
) -> float:
    """Estimate effective oracle temperature using Semantic Entropy (SE).

    Replaces the token-hash entropy formula in :func:`estimate_temperature`
    with the principled Semantic Entropy of Kuhn, Gal & Farquhar (2023).
    Instead of measuring disagreement over raw token fingerprints, this
    function clusters oracle responses by semantic equivalence and computes::

        SE(x) = -sum_{c in C} p(c | x) log p(c | x)

    where C are NLI-derived equivalence classes.  This eliminates the known
    failure mode of token-hash entropy: two oracles saying "Paris" and
    "France's capital is Paris" now count as a *single* cluster rather than
    two disagreeing responses.

    Algorithm
    ---------
    1. Cluster responses using *backend* (default: TokenFingerprintBackend).
    2. Compute normalised SE: ``SE_norm = SE / log(N)`` in [0, 1].
    3. Map to temperature::

           T = 0.50*SE_norm + 0.30*(1 - eta) + 0.15*rho_bar + 0.05

       where ``eta = dominant_cluster_mass`` (order parameter).

    This function has **no circular dependency** on the dissensus D term
    because it operates on raw oracle strings, not on an already-weighted
    verdict distribution.

    Parameters
    ----------
    oracle_responses:
        Raw text responses from each oracle (before canonicalization).
    rho_bar:
        Mean pairwise inter-oracle correlation from diversity weighting.
    individual_confidences:
        Per-oracle confidence scores (currently informational only).
    backend:
        NLIBackend instance.  Defaults to TokenFingerprintBackend.
    entailment_threshold:
        Bidirectional entailment threshold for clustering (default 0.5).

    Returns
    -------
    float
        Effective temperature in [0.05, 2.0].

    Reference
    ---------
    Kuhn, L., Gal, Y., & Farquhar, S. (2023). Semantic uncertainty:
    Linguistic invariances for uncertainty estimation in natural language
    generation. *ICLR 2023*.
    """
    from remora.semantic_entropy import compute_semantic_entropy, se_to_temperature

    if not oracle_responses:
        return float("inf")

    se_result = compute_semantic_entropy(
        oracle_responses,
        backend=backend,
        entailment_threshold=entailment_threshold,
    )
    return se_to_temperature(se_result, n_oracles=len(oracle_responses), rho_bar=rho_bar)
def hallucination_bound(n_oracles: int, rho_bar: float, individual_error_rate: float) -> float:
    """Heuristic false-consensus RISK PROXY for a correlated oracle pool.

    NOT the proven bound. Two deliberate departures from the theorem in
    remora/proofs/hallucination_bound_theorem.py (B = q^floor(n/2)):

    1. Exponent n/2 instead of floor(n/2) — tighter than what the theorem
       proves (at n=3: q^1.5 vs the proven q^1).
    2. rho_bar clamped at 0.49 — the paper's own §13.5 reports within-family
       rho_bar ≈ 0.4–0.6, so in exactly that regime this proxy UNDERSTATES
       false-consensus risk, which inflates the trust score via the
       (1 − h_bound) factor.

    Both choices keep the signal informative for routing and are preserved
    unchanged because committed benchmark artifacts depend on them; they
    forfeit any guarantee. Do not cite this function as a bound — the paper
    describes it as a heuristic proxy (§5.1).
    """
    eps = max(0.0, min(individual_error_rate, 1.0))
    rho = max(0.0, min(rho_bar, 1.0))
    if eps >= 0.5 or n_oracles < 2:
        return 1.0
    # Heuristic clamp (see docstring point 2): keeps the signal informative,
    # forfeits the bound property for rho_bar >= 0.5.
    rho = min(rho, 0.49)
    base = eps * eps + rho * eps * (1.0 - eps)
    return min(1.0, base ** (n_oracles / 2.0))


def free_energy(entropy: float, dissensus: float, temperature: float, lambda_coupling: float) -> float:
    """Compute the generalized free-energy proxy F(T) = lambda*D - T*H.

    This Helmholtz-style functional underpins the thermodynamic phase analysis.
    Note the sign convention: higher entropy H *lowers* F at T > 0 (the thermal
    term T*H is subtracted), exactly as in Helmholtz F = U - TS.

    Relationship to REMORA's Lyapunov/VETO potential V = H + lambda*D
    -----------------------------------------------------------------------
    V and F are distinct objects.  Their exact algebraic relationship is::

        V(H, D) = H + lambda*D = lambda*D - (-1)*H = F(T=-1; H, D)

    That is, V equals this free energy evaluated at the *inverted* temperature
    T = -1.  In V, entropy enters with a *positive* sign (disorder is penalised
    regardless of temperature), whereas in F it enters with sign -T (disorder
    is thermally forgiven at high T).  The two objects play different roles:

    - F(T) is the analysis tool: its landscape reveals the phase structure and
      the critical temperature as T is varied.
    - V is the static Lyapunov potential: the quantity whose minimisation drives
      the oracle consensus toward ordered states.

    The identification V = F(T=-1) is exact and provides the rigorous bridge
    between the two formulations.  It is *not* claimed that REMORA literally
    operates at negative temperature in the physical sense; rather, T = -1 is
    the formal parameter value at which the two expressions coincide.
    """
    return lambda_coupling * dissensus - temperature * entropy


def classify_phase(
    temperature: float,
    t_critical: float,
    eta: float,
    tolerance: float = 0.15,
    calibration: ThermodynamicCalibration | None = None,
) -> str:
    """Classify the current state as ordered, critical, or disordered."""
    calibrated_temperature = apply_temperature_calibration(temperature, calibration)
    ordered_min_eta = calibration.ordered_min_eta if calibration is not None else 0.5
    tolerance = calibration.critical_tolerance if calibration is not None else tolerance
    if not math.isfinite(t_critical):
        return "ordered" if eta > ordered_min_eta else "disordered"
    if abs(calibrated_temperature - t_critical) / max(t_critical, 1e-9) < tolerance:
        return "critical"
    if calibrated_temperature < t_critical and eta > ordered_min_eta:
        return "ordered"
    return "disordered"


def trust_score(
    eta: float,
    chi: float,
    halluc_bound: float,
    phase: str,
    calibration: ThermodynamicCalibration | None = None,
) -> float:
    """Collapse thermodynamic observables into a trust score in [0, 1]."""
    if calibration is None:
        calibration = ThermodynamicCalibration()
    phase_weight = calibration.phase_weight(phase)
    fragility_penalty = 1.0 / (1.0 + chi / max(calibration.chi_scale, 1e-9))
    return min(1.0, max(0.0, eta * (1.0 - halluc_bound) * phase_weight * fragility_penalty))


def compute_phase_diagram(
    n_oracles: int,
    k_verdicts: int,
    rho_bar: float,
    lambda_coupling: float,
    individual_error_rate: float = 0.10,
    t_range: tuple[float, float] = (0.01, 3.0),
    n_points: int = 200,
    calibration: ThermodynamicCalibration | None = None,
) -> PhaseDiagram:
    """SYNTHETIC ILLUSTRATION of a phase diagram over a temperature range.

    The eta(T) curves below are hard-coded piecewise shapes (including a
    2D-Ising-style 0.125 exponent) chosen for plotting, NOT measured from
    oracle data. Nothing in the runtime decision path consumes this
    function; it exists for tests and illustrative figures only. Do not
    present its output as an empirical result.
    """
    t_critical = critical_temperature(lambda_coupling, rho_bar, k_verdicts)
    gamma = critical_exponent_gamma(k_verdicts)
    t_min, t_max = t_range
    step = (t_max - t_min) / max(n_points, 1)

    eta_values: list[float] = []
    t_values: list[float] = []
    for index in range(n_points + 1):
        temperature = t_min + index * step
        t_values.append(temperature)
        if not math.isfinite(t_critical):
            eta = 1.0
        elif temperature < t_critical * 0.8:
            eta = max(0.0, 1.0 - (temperature / max(t_critical, 1e-9)) ** 2)
        elif temperature > t_critical * 1.2:
            eta = max(0.0, (t_critical / max(temperature, 1e-9)) ** 2 * 0.3)
        elif k_verdicts >= 3:
            eta = 0.8 if temperature < t_critical else 0.15
        else:
            eta = max(0.0, 1.0 - temperature / max(t_critical, 1e-9)) ** 0.125
        eta_values.append(eta)

    chi_values = susceptibility(eta_values, t_values)
    states: list[ThermodynamicState] = []
    for temperature, eta, chi in zip(t_values, eta_values, chi_values):
        calibrated_temperature = apply_temperature_calibration(temperature, calibration)
        entropy = 0.0
        if 0.0 < eta < 1.0:
            entropy = -eta * math.log2(eta) - (1.0 - eta) * math.log2(1.0 - eta)
        dissensus = 1.0 - eta
        phase = classify_phase(temperature, t_critical, eta, calibration=calibration)
        halluc_bound = hallucination_bound(n_oracles, rho_bar, individual_error_rate)
        states.append(
            ThermodynamicState(
                temperature=calibrated_temperature,
                free_energy=free_energy(entropy, dissensus, calibrated_temperature, lambda_coupling),
                order_parameter=eta,
                susceptibility=chi,
                phase=phase,
                hallucination_bound=halluc_bound,
                trust_score=trust_score(eta, chi, halluc_bound, phase, calibration=calibration),
                raw_temperature=temperature,
                critical_temperature=t_critical,
                temperature_ratio=(calibrated_temperature / max(t_critical, 1e-9)) if math.isfinite(t_critical) else None,
            )
        )

    return PhaseDiagram(
        n_oracles=n_oracles,
        n_verdicts=k_verdicts,
        rho_bar=rho_bar,
        lambda_coupling=lambda_coupling,
        T_critical=t_critical,
        gamma_exponent=gamma,
        states=states,
    )


def predict_trust_before_iteration(
    pre_sweep_verdicts: list[tuple[str, str]],
    pre_sweep_confidences: list[float],
    rho_bar: float,
    lambda_coupling: float = 1.0,
    individual_error_rate: float = 0.10,
    calibration: ThermodynamicCalibration | None = None,
    prompt: str | None = None,
    prompt_category: str | None = None,
) -> ThermodynamicState:
    """Estimate trust from the router pre-sweep before any full iteration runs.

    Parameters
    ----------
    prompt:
        When provided, the effective temperature is derived from
        :func:`estimate_structural_temperature` (pre-inference, circularity-free).
        When ``None`` the legacy :func:`estimate_temperature` is used instead
        (post-hoc, inherits 18 % weight from D).
    prompt_category:
        Optional task category passed to :func:`estimate_structural_temperature`.
        Ignored when ``prompt`` is ``None``.
    """
    fingerprints = [fingerprint for _, fingerprint in pre_sweep_verdicts]
    counts = Counter(fingerprints)
    total = len(pre_sweep_verdicts)
    confidence_weighted = len(pre_sweep_confidences) == total and total > 0
    if confidence_weighted:
        raw_distribution: dict[str, float] = {}
        total_weight = 0.0
        for (_, fingerprint), confidence in zip(pre_sweep_verdicts, pre_sweep_confidences):
            weight = max(0.05, float(confidence))
            raw_distribution[fingerprint] = raw_distribution.get(fingerprint, 0.0) + weight
            total_weight += weight
        distribution = {fp: weight / total_weight for fp, weight in raw_distribution.items()} if total_weight else {}
    else:
        distribution = {fp: count / total for fp, count in counts.items()} if total else {}
    k = max(len(counts), 2)

    raw_temperature = (
        estimate_structural_temperature(prompt, prompt_category)
        if prompt is not None
        else estimate_temperature(distribution, rho_bar, pre_sweep_confidences)
    )
    temperature = apply_temperature_calibration(raw_temperature, calibration)
    t_critical = critical_temperature(lambda_coupling, rho_bar, k)
    entropy = sum(-p * math.log2(p) for p in distribution.values() if p > 0)
    dissensus = 1.0 - max(distribution.values()) if distribution else 1.0
    eta = order_parameter(distribution, k)
    phase = classify_phase(raw_temperature, t_critical, eta, calibration=calibration)
    halluc_bound = hallucination_bound(total, rho_bar, individual_error_rate)

    delta_t = 0.01
    eta_plus = max(0.0, eta - delta_t / max(t_critical, 1e-9)) if math.isfinite(t_critical) else eta
    eta_minus = min(1.0, eta + delta_t / max(t_critical, 1e-9)) if math.isfinite(t_critical) else eta
    chi = abs(eta_plus - eta_minus) / (2.0 * delta_t)
    trust = trust_score(eta, chi, halluc_bound, phase, calibration=calibration)

    return ThermodynamicState(
        temperature=temperature,
        free_energy=free_energy(entropy, dissensus, temperature, lambda_coupling),
        order_parameter=eta,
        susceptibility=chi,
        phase=phase,
        hallucination_bound=halluc_bound,
        trust_score=trust,
        raw_temperature=raw_temperature,
        critical_temperature=t_critical,
        temperature_ratio=(temperature / max(t_critical, 1e-9)) if math.isfinite(t_critical) else None,
    )
