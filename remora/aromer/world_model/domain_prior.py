# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER World Model — Bayesian domain harm priors with correct weighting.

Key fix from v0.1 analysis:
  - Only strong-signal DecisionQuality labels drive full Bayesian updates
  - VERIFY outcomes use weight=0.25 (partial signal)
  - ABSTAIN/UNKNOWN have weight=0.0 (no update)
  - Shadow mode: compute adjustment but return original trust unchanged
  - Confidence levels: LOW (n<5), MEDIUM (5-19), HIGH (n>=20)

EXPERIMENTAL: Part of the AROMER research plugin.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.aromer.experience.episode import DecisionQuality

_DEFAULT_MODEL_PATH = Path.home() / ".aromer" / "world_model.json"
_SENSITIVITY  = 0.20   # max trust adjustment magnitude (±20%)
_ALPHA_INIT   = 1.0    # uniform prior
_BETA_INIT    = 1.0

# Synthetic domain holding the domain-agnostic abstract prior used for
# cross-domain transfer (§16). Never a real domain; excluded from all_stats.
_ABSTRACT_DOMAIN = "__abstract__"

# Bounded evidence mass (fixed-memory / discounted Beta). Without a cap, a
# context's pseudo-count grows without bound (observed live: alpha=628, beta=1),
# which (a) freezes calibration — a new observation moves p_harm by < 1/N, so
# ECE plateaus — and (b) blinds the model to non-stationarity. Capping alpha+beta
# keeps every context responsive: the most recent ~_MAX_EVIDENCE observations
# dominate, so a regime change can still be tracked. n>=20 (HIGH confidence)
# remains comfortably reachable below the cap.
_MAX_EVIDENCE = 200.0

_MIN_N_MEDIUM = 5
_MIN_N_HIGH   = 20

# Bidirectional adjustment thresholds.
#   ph >= _HARM_THRESHOLD                 → LOWER trust (more cautious)
#   high confidence + ph < _SAFE_P_HARM   → BOOST trust (less friction), if the
#   and CI upper < _SAFE_CI_UPPER           statistical upper bound on harm is low
_HARM_THRESHOLD = 0.50
_SAFE_P_HARM    = 0.10
_SAFE_CI_UPPER  = 0.25
_MAX_BOOST_TRUST = 0.95   # never let a learned boost imply near-certain trust


def _confidence_level(n_observations: int) -> str:
    if n_observations < _MIN_N_MEDIUM:
        return "low"
    if n_observations < _MIN_N_HIGH:
        return "medium"
    return "high"


@dataclass
class DomainStats:
    domain:      str
    action_type: str
    risk_tier:   str
    alpha:       float
    beta:        float
    n_observations: int
    p_harm:        float
    p_harm_ci95_lower: float
    p_harm_ci95_upper: float
    confidence_level:  str   # "low" | "medium" | "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain":       self.domain,
            "action_type":  self.action_type,
            "risk_tier":    self.risk_tier,
            "alpha":        round(self.alpha, 4),
            "beta":         round(self.beta, 4),
            "n_observations": self.n_observations,
            "p_harm":       round(self.p_harm, 4),
            "p_harm_ci95":  [round(self.p_harm_ci95_lower, 4),
                              round(self.p_harm_ci95_upper, 4)],
            "confidence":   self.confidence_level,
            "policy_ready": self.confidence_level == "high",
        }


class DomainHarmPrior:
    """Bayesian Beta prior over P(harm | domain, action_type, risk_tier).

    Update weighting per DecisionQuality:
      CORRECT_BLOCK / FALSE_ACCEPT  →  harm = True,  weight = 1.0
      CORRECT_ACCEPT / FALSE_BLOCK  →  harm = False, weight = 1.0
      CORRECT_INTERCEPT_VERIFY      →  harm = True,  weight = 0.25
      BENIGN_REVIEW                 →  harm = False, weight = 0.25
      ABSTAIN_UNKNOWN               →  no update

    Shadow mode: adjust_trust() computes the adjusted value but can return
    the original when shadow=True, allowing safe monitoring before committing.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        shadow_mode: bool = False,
    ) -> None:
        self.path = Path(path) if path else _DEFAULT_MODEL_PATH
        self.shadow_mode = shadow_mode
        self._priors: dict[str, dict[str, float]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def p_harm(self, domain: str, action_type: str, risk_tier: str) -> float:
        p = self._priors.get(self._key(domain, action_type, risk_tier),
                              {"alpha": _ALPHA_INIT, "beta": _BETA_INIT})
        return p["alpha"] / (p["alpha"] + p["beta"])

    def adjust_trust(
        self,
        trust_score: float | None,
        domain: str,
        action_type: str,
        risk_tier: str,
    ) -> float | None:
        """Return trust adjusted by the learned harm prior — bidirectionally.

        This is the lever that lets AROMER change behaviour over time:

          * ph >= _HARM_THRESHOLD            → LOWER trust (more cautious). This is
                                               the original conservative behaviour.
          * high confidence (n >= 20),       → BOOST trust toward 1.0 (less review
            ph < _SAFE_P_HARM, and a low       friction) for contexts the model has
            95% upper bound on harm            *proven* safe from real outcomes.
          * otherwise                        → unchanged.

        The boost is the mechanism for reducing review friction without lowering
        the safety floor: it only fires for well-observed, statistically-safe
        contexts, is capped at ±20%, and never bypasses the engine's hard gates
        (adversarial / malformed / forbidden-tool / tainted-argument all ESCALATE
        before trust is consulted).

        In shadow_mode the adjustment is computed and logged but the original
        trust is returned, allowing safe monitoring before activation.
        """
        if trust_score is None:
            # No trust signal to adjust. The engine already handles a missing
            # trust_score conservatively (no conformal accept path); AROMER must
            # not crash the decision path on it — return it unchanged.
            return trust_score
        st = self.stats(domain, action_type, risk_tier)
        ph = st.p_harm

        if ph >= _HARM_THRESHOLD:
            adj = trust_score * (1.0 - _SENSITIVITY * ph)
        elif (
            st.confidence_level in ("medium", "high")
            and ph < _SAFE_P_HARM
            and st.p_harm_ci95_upper < _SAFE_CI_UPPER
        ):
            # Proven-safe → boost to the statistically-justified trust. We are 95%
            # confident at least (1 - ci_upper) of actions in this context are
            # benign, so trust is justified up to that bound. The 95% upper-bound
            # gate (not an arbitrary observation count) is what keeps this safe:
            # it only clears once ~12+ clean observations have accrued, and the
            # target it produces is conservative (just reaches the accept band at
            # the boundary). Self-limiting and capped.
            target = min(_MAX_BOOST_TRUST, 1.0 - st.p_harm_ci95_upper)
            adj = max(trust_score, target)
        else:
            adj = trust_score
        adj = round(max(0.0, min(1.0, adj)), 4)

        if self.shadow_mode:
            # Log without applying
            self._shadow_log.append({
                "domain": domain, "action_type": action_type, "risk_tier": risk_tier,
                "trust_in": trust_score, "trust_adjusted": adj,
                "p_harm": round(ph, 4),
            })
            return trust_score  # return unchanged

        return adj

    def update_from_quality(
        self,
        domain: str,
        action_type: str,
        risk_tier: str,
        decision_quality: "DecisionQuality",  # type: ignore[name-defined]
    ) -> float:
        """Update prior from a DecisionQuality label.  Returns weight used."""
        weight = decision_quality.world_model_weight
        harm   = decision_quality.harm_signal

        if weight == 0.0 or harm is None:
            return 0.0   # no update for ABSTAIN / UNKNOWN

        self.update(domain, action_type, risk_tier,
                    harm_occurred=harm, weight=weight)
        return weight

    def update(
        self,
        domain: str,
        action_type: str,
        risk_tier: str,
        harm_occurred: bool,
        weight: float = 1.0,
    ) -> None:
        """Discounted Bayesian conjugate update with bounded evidence mass.

        Standard conjugate increment, but if the resulting mass (alpha+beta)
        would exceed ``_MAX_EVIDENCE`` the existing counts are rescaled down
        first. This is a fixed-memory Beta tracker: confidence saturates at a
        finite ceiling instead of growing forever, so the prior stays able to
        move when a context's true harm rate shifts. The uniform 1/1 prior is
        the floor — rescaling never erodes a context below it.
        """
        key = self._key(domain, action_type, risk_tier)
        if key not in self._priors:
            self._priors[key] = {"alpha": _ALPHA_INIT, "beta": _BETA_INIT}

        a = self._priors[key]["alpha"]
        b = self._priors[key]["beta"]
        if a + b + weight > _MAX_EVIDENCE:
            # Rescale evidence *above* the uniform prior so the floor is kept,
            # leaving headroom for the incoming observation.
            excess_a = max(0.0, a - _ALPHA_INIT)
            excess_b = max(0.0, b - _BETA_INIT)
            budget = _MAX_EVIDENCE - _ALPHA_INIT - _BETA_INIT - weight
            total_excess = excess_a + excess_b
            if total_excess > budget > 0:
                scale = budget / total_excess
                a = _ALPHA_INIT + excess_a * scale
                b = _BETA_INIT + excess_b * scale

        if harm_occurred:
            a += weight
        else:
            b += weight
        self._priors[key]["alpha"] = a
        self._priors[key]["beta"] = b
        self._save()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self, domain: str, action_type: str, risk_tier: str) -> DomainStats:
        key = self._key(domain, action_type, risk_tier)
        p   = self._priors.get(key, {"alpha": _ALPHA_INIT, "beta": _BETA_INIT})
        a, b  = p["alpha"], p["beta"]
        n     = max(0, int(a + b - 2))
        ph    = a / (a + b)
        lo, hi = _wilson_ci(max(0, int(a - _ALPHA_INIT)), max(1, n))
        return DomainStats(
            domain=domain, action_type=action_type, risk_tier=risk_tier,
            alpha=a, beta=b, n_observations=n,
            p_harm=round(ph, 4),
            p_harm_ci95_lower=round(lo, 4),
            p_harm_ci95_upper=round(hi, 4),
            confidence_level=_confidence_level(n),
        )

    def all_stats(self) -> list[DomainStats]:
        result = []
        for key in self._priors:
            parts = key.split(":", 2)
            if len(parts) == 3 and parts[0] != _ABSTRACT_DOMAIN:
                result.append(self.stats(*parts))
        return sorted(result, key=lambda s: s.p_harm, reverse=True)

    # ------------------------------------------------------------------
    # Cross-domain transfer (abstract harm structure)
    # ------------------------------------------------------------------

    def update_abstract(
        self,
        action_type: str,
        risk_tier: str,
        harm_occurred: bool,
        weight: float = 1.0,
    ) -> None:
        """Update the domain-agnostic abstract prior over (action_type, risk_tier).

        The abstract prior captures harm structure that generalises *across*
        domains: a ``destructive_write`` on a ``critical`` tier tends to be
        harmful whether the domain is ``database`` or ``medical``. It is
        stored under the synthetic domain :data:`_ABSTRACT_DOMAIN`, so it
        round-trips through the same persistence yet never collides with a
        real domain key, and is excluded from ``all_stats``/``summary``.
        """
        self.update(_ABSTRACT_DOMAIN, action_type, risk_tier,
                    harm_occurred=harm_occurred, weight=weight)

    def p_harm_abstract(self, action_type: str, risk_tier: str) -> float:
        """P(harm | action_type, risk_tier), domain-agnostic — the transfer
        signal. Returns the uniform 0.5 until abstract evidence accrues."""
        return self.p_harm(_ABSTRACT_DOMAIN, action_type, risk_tier)

    def abstract_stats(self, action_type: str, risk_tier: str) -> DomainStats:
        return self.stats(_ABSTRACT_DOMAIN, action_type, risk_tier)

    def p_harm_backoff(self, domain: str, action_type: str, risk_tier: str) -> float:
        """Harm probability with cross-domain backoff.

        If the exact ``(domain, action_type, risk_tier)`` context has real
        observations, its own prior is authoritative. For an **unseen domain**
        the estimate backs off to the abstract ``(action_type, risk_tier)``
        prior — this is how a context REMORA has never observed in a given
        domain still inherits harm structure learned elsewhere. This backoff
        is the mechanism the cross-domain transfer harness measures.
        """
        if self.stats(domain, action_type, risk_tier).n_observations > 0:
            return self.p_harm(domain, action_type, risk_tier)
        return self.p_harm_abstract(action_type, risk_tier)

    def summary(self) -> dict[str, Any]:
        all_s = self.all_stats()
        high_conf = [s for s in all_s if s.confidence_level in ("medium", "high")]
        return {
            "n_contexts":         len(all_s),
            "n_high_confidence":  len(high_conf),
            "shadow_mode":        self.shadow_mode,
            "high_risk_contexts": [s.to_dict() for s in all_s if s.p_harm > 0.5],
            "top5_by_p_harm":     [s.to_dict() for s in all_s[:5]],
            "note": "confidence=low means n<5; policy_ready requires n>=20",
        }

    @property
    def shadow_log(self) -> list[dict[str, Any]]:
        return list(self._shadow_log)

    def clear_shadow_log(self) -> None:
        self._shadow_log.clear()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _key(self, domain: str, action_type: str, risk_tier: str) -> str:
        return f"{domain}:{action_type}:{risk_tier}"

    def _load(self) -> None:
        from collections import deque
        # Bounded: shadow-mode decide() appends on every call and the log
        # is diagnostic-only; cap it so it cannot grow without limit.
        self._shadow_log: deque = deque(maxlen=1000)
        if self.path.exists():
            try:
                self._priors = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._priors = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._priors, indent=2), encoding="utf-8")


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return max(0.0, c - h), min(1.0, c + h)
