from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional, Sequence

# Friction target (real product goal) and decay constant for the AII friction
# component. Kept here as the single tested source of truth for the formula that
# the worker mirrors.
FRICTION_TARGET = 0.15
FRICTION_TAU = 0.20

# EMA smoothing factor for published AII series. The 4-hourly cycle samples a
# sliding 200-episode window whose composition varies between cycles; the raw
# AII therefore carries measurement noise that is not a real learning signal.
# alpha=0.35 keeps ~3 cycles of memory: responsive to true change, deaf to
# single-cycle composition swings.
EMA_ALPHA = 0.35

# Reference volatility for the stability dispersion term. A std-dev of 0.15
# across recent component scores means the measurement is pure noise (score 0);
# a std-dev of 0 means perfectly repeatable measurement (score 1).
STABILITY_SIGMA_REF = 0.15


def ema_smooth(values: Sequence[float], alpha: float = EMA_ALPHA) -> list[float]:
    """Exponential moving average over *values* (oldest first).

    Single tested source of truth for the smoothing the worker mirrors in
    ``GET /intelligence`` (``aii_smoothed``). Returns a list the same length
    as the input; empty input returns an empty list.
    """
    if not values:
        return []
    if not 0.0 < alpha <= 1.0:
        raise ValueError(f"alpha must be in (0, 1], got {alpha}")
    out = [float(values[0])]
    for v in values[1:]:
        out.append(alpha * float(v) + (1.0 - alpha) * out[-1])
    return out


def dispersion_stability(
    recent_scores: Sequence[float], sigma_ref: float = STABILITY_SIGMA_REF
) -> float:
    """Stability of a measurement series: 1 at zero variance, 0 at sigma_ref.

    Used by the worker's stability component (T5) v2: the old formula spent
    half its weight on oracle-bandit entropy, which can never converge because
    the bandit arms receive correlated proxy updates — the term was
    structurally pinned near zero. This measures what "stability" should mean:
    do repeated measurements of the same system agree with each other?

    Fewer than 2 samples → 0.0 (unknown is not stable).
    """
    if len(recent_scores) < 2:
        return 0.0
    mean = sum(recent_scores) / len(recent_scores)
    var = sum((s - mean) ** 2 for s in recent_scores) / len(recent_scores)
    std = math.sqrt(var)
    return max(0.0, min(1.0, 1.0 - std / sigma_ref))


def stability_score_v2(
    recent_friction: Sequence[float],
    recent_metajudge: Sequence[float],
    high_conf_coverage: float,
) -> float:
    """AII stability component (T5) v2 — mirror of the worker formula.

    0.5 * mean(dispersion stability of the two noisiest components)
    + 0.5 * high-confidence world-model prior coverage.

    The friction and metajudge series are the operative volatility sources
    (sliding-window composition and small critique batches respectively), and
    neither depends on the stability score itself, so there is no
    self-reference loop.
    """
    dispersion = (
        dispersion_stability(recent_friction)
        + dispersion_stability(recent_metajudge)
    ) / 2.0
    coverage = max(0.0, min(1.0, high_conf_coverage))
    return max(0.0, min(1.0, 0.5 * dispersion + 0.5 * coverage))


def friction_score(benign_review_rate: float) -> float:
    """Gradient-retaining friction score (mirror of the worker's AII component).

    ``exp(-r / 0.20)``: strictly decreasing in the review rate, never an
    uninformative hard zero, and ~0.47 at the 15% product target. Replaces the
    old ``max(0, 1 - r/0.27)`` which flat-lined at 0 for any review rate >= 27%,
    killing the signal exactly where improvement most needs to be visible.
    """
    return max(0.0, min(1.0, math.exp(-benign_review_rate / FRICTION_TAU)))


def friction_score_smoothed(
    recent_benign_review_rates: Sequence[float], alpha: float = EMA_ALPHA
) -> float:
    """Friction component computed on an EMA of recent benign-review rates.

    The AII friction component was computed on a single 4-hourly cycle's
    benign-review rate, but each cycle is a sliding 200-episode window whose
    *composition* varies between cycles (live: 0.07 ↔ 0.635). That swing is a
    sampling artefact, not a change in the system's true friction, yet it
    dominated AII variance and depressed the stability component (T5).

    Smoothing the rate before applying ``friction_score`` makes the estimator
    track sustained friction rather than per-batch composition. It is a better
    estimator of the same quantity — not masking — and mirrors the EMA the
    worker already applies to the *published* AII series.

    Oldest rate first. Empty input → friction at the baseline rate (0.27).
    """
    if not recent_benign_review_rates:
        return friction_score(0.27)
    smoothed_rate = ema_smooth(recent_benign_review_rates, alpha)[-1]
    return friction_score(smoothed_rate)


@dataclass
class AiiComponents:
    calibration_score: float = 0.0
    friction_score: float = 0.0
    metajudge_quality: float = 0.0
    transfer_score: float = 0.50
    stability_score: float = 0.0
    ece: float = 0.5
    benign_review_rate: float = 0.27
    false_accept_rate: float = 0.0
    world_model_active: bool = False
    lora_active: bool = False
    n_episodes: int = 0
    n_high_confidence: int = 0


@dataclass
class IntelligenceScore:
    aii: float
    components: AiiComponents
    trend: str = "insufficient_data"
    interpretation: str = "WARMUP"
    timestamp: Optional[str] = None

    WEIGHTS = {
        "calibration": 0.30,
        "friction": 0.25,
        "metajudge": 0.20,
        "transfer": 0.15,
        "stability": 0.10,
    }

    THRESHOLDS = {
        "TRAINED": 0.80,
        "CAPABLE": 0.60,
        "LEARNING": 0.40,
        "WARMUP": 0.0,
    }

    def summary(self) -> str:
        c = self.components
        lines = [
            f"AII: {self.aii:.4f}  [{self.interpretation}]  trend={self.trend}",
            f"  T1 calibration:   {c.calibration_score:.4f}  (ECE={c.ece:.4f})",
            f"  T2 friction:      {c.friction_score:.4f}  (benign_review={c.benign_review_rate:.2%})",
            f"  T3 metajudge:     {c.metajudge_quality:.4f}  (LoRA={'on' if c.lora_active else 'off'})",
            f"  T4 transfer:      {c.transfer_score:.4f}",
            f"  T5 stability:     {c.stability_score:.4f}  (high_conf={c.n_high_confidence})",
            f"  episodes={c.n_episodes}  world_model={'active' if c.world_model_active else 'shadow'}",
        ]
        return "\n".join(lines)

    @classmethod
    def from_api(cls, data: dict) -> "IntelligenceScore":
        current = data.get("current") or {}
        components = AiiComponents(
            calibration_score=float(current.get("calibration_score", 0.0)),
            friction_score=float(current.get("friction_score", 0.0)),
            metajudge_quality=float(current.get("metajudge_quality", 0.0)),
            transfer_score=float(current.get("transfer_score", 0.50)),
            stability_score=float(current.get("stability_score", 0.0)),
            ece=float(current.get("ece", 0.5)),
            benign_review_rate=float(current.get("benign_review_rate", 0.27)),
            false_accept_rate=float(current.get("false_accept_rate", 0.0)),
            world_model_active=bool(current.get("world_model_active", 0)),
            lora_active=bool(current.get("lora_active", 0)),
            n_episodes=int(current.get("n_episodes", 0)),
            n_high_confidence=int(current.get("n_high_confidence", 0)),
        )
        return cls(
            aii=float(current.get("aii", 0.0)),
            components=components,
            trend=data.get("trend", "insufficient_data"),
            interpretation=data.get("interpretation", "WARMUP"),
            timestamp=current.get("timestamp"),
        )
