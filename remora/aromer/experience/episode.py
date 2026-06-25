# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER Episode — the atomic unit of experience.

Every governance decision produces one Episode.  When the ground truth is
later observed, the episode is updated with a precise DecisionQuality label
derived from the combination of (verdict × ground_truth).

Taxonomy (from AROMER analysis):

  Verdict   Ground truth  → DecisionQuality
  ─────────────────────────────────────────────────────────────────
  ACCEPT    benign        → correct_accept
  ACCEPT    harmful       → false_accept              ← damages users
  VERIFY    benign        → benign_review             ← unnecessary friction
  VERIFY    harmful       → correct_intercept_verify  ← human sees it
  ESCALATE  benign        → false_block               ← unnecessary hard block
  ESCALATE  harmful       → correct_block             ← threat stopped
  ABSTAIN   any           → abstain_unknown

Key metrics derived from this taxonomy:
  hard_fpr          = false_block / total_benign
  review_friction   = benign_review / total_benign
  false_accept_rate = false_accept / total_harmful
  correct_intercept = (correct_block + correct_intercept_verify) / total_harmful

EXPERIMENTAL: Part of the AROMER research plugin.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Ground truth — what actually happened
# ---------------------------------------------------------------------------

class GroundTruth(str, Enum):
    """Was the governed action actually harmful or benign?"""
    HARMFUL = "harmful"
    BENIGN  = "benign"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Decision quality — verdict × ground truth
# ---------------------------------------------------------------------------

class DecisionQuality(str, Enum):
    """Precise outcome label from (verdict, ground_truth)."""

    CORRECT_ACCEPT           = "correct_accept"
    FALSE_ACCEPT             = "false_accept"             # ACCEPT + harmful
    BENIGN_REVIEW            = "benign_review"            # VERIFY + benign
    CORRECT_INTERCEPT_VERIFY = "correct_intercept_verify" # VERIFY + harmful
    FALSE_BLOCK              = "false_block"              # ESCALATE + benign
    CORRECT_BLOCK            = "correct_block"            # ESCALATE + harmful
    ABSTAIN_UNKNOWN          = "abstain_unknown"

    @classmethod
    def from_verdict_truth(
        cls,
        verdict: str,
        ground_truth: GroundTruth,
    ) -> "DecisionQuality":
        """Derive decision quality from (verdict, ground_truth)."""
        v = verdict.upper()
        if v == "ABSTAIN" or ground_truth == GroundTruth.UNKNOWN:
            return cls.ABSTAIN_UNKNOWN
        harmful = ground_truth == GroundTruth.HARMFUL
        if v == "ACCEPT":
            return cls.FALSE_ACCEPT if harmful else cls.CORRECT_ACCEPT
        if v == "VERIFY":
            return cls.CORRECT_INTERCEPT_VERIFY if harmful else cls.BENIGN_REVIEW
        if v == "ESCALATE":
            return cls.CORRECT_BLOCK if harmful else cls.FALSE_BLOCK
        return cls.ABSTAIN_UNKNOWN

    @property
    def is_governance_error(self) -> bool:
        """True for labels that indicate a governance mistake."""
        return self in {
            DecisionQuality.FALSE_ACCEPT,
            DecisionQuality.FALSE_BLOCK,
        }

    @property
    def is_strong_signal(self) -> bool:
        """True for labels suitable for strong Bayesian world-model updates."""
        return self in {
            DecisionQuality.CORRECT_ACCEPT,
            DecisionQuality.FALSE_ACCEPT,
            DecisionQuality.CORRECT_BLOCK,
            DecisionQuality.FALSE_BLOCK,
        }

    @property
    def world_model_weight(self) -> float:
        """Weight for Bayesian P(harm) update.

        Strong signal = 1.0  (clear correct or incorrect governance)
        Weak signal   = 0.25 (review outcome — partial information)
        No signal     = 0.0  (abstain or unknown)
        """
        if self in {DecisionQuality.FALSE_ACCEPT, DecisionQuality.CORRECT_BLOCK}:
            return 1.0    # confirms harm
        if self in {DecisionQuality.CORRECT_ACCEPT, DecisionQuality.FALSE_BLOCK}:
            return 1.0    # confirms benign
        if self in {DecisionQuality.CORRECT_INTERCEPT_VERIFY,
                    DecisionQuality.BENIGN_REVIEW}:
            return 0.25   # review signal only
        return 0.0

    @property
    def harm_signal(self) -> bool | None:
        """
        True  → action was harmful (update α)
        False → action was benign  (update β)
        None  → no signal
        """
        if self in {DecisionQuality.FALSE_ACCEPT,
                    DecisionQuality.CORRECT_BLOCK,
                    DecisionQuality.CORRECT_INTERCEPT_VERIFY}:
            return True
        if self in {DecisionQuality.CORRECT_ACCEPT,
                    DecisionQuality.FALSE_BLOCK,
                    DecisionQuality.BENIGN_REVIEW}:
            return False
        return None


# ---------------------------------------------------------------------------
# Legacy OutcomeType (kept for backward compat, derived from DecisionQuality)
# ---------------------------------------------------------------------------

class OutcomeType(str, Enum):
    """Legacy outcome enum — now DERIVED from DecisionQuality.

    New code should use DecisionQuality.  This enum is kept for backward
    compatibility with existing tests and the EpisodeStore JSONL format.
    """
    CORRECT_ACCEPT   = "correct_accept"
    CORRECT_BLOCK    = "correct_block"
    FALSE_ACCEPT     = "false_accept"
    FALSE_BLOCK      = "false_block"
    SAFETY_VIOLATION = "safety_violation"
    PENDING          = "pending"
    UNKNOWN          = "unknown"

    @property
    def is_negative(self) -> bool:
        return self in {OutcomeType.FALSE_ACCEPT, OutcomeType.SAFETY_VIOLATION}

    @property
    def is_positive(self) -> bool:
        return self in {OutcomeType.CORRECT_ACCEPT, OutcomeType.CORRECT_BLOCK}

    def to_correct(self) -> bool | None:
        if self.is_positive:
            return True
        if self.is_negative:
            return False
        return None


def _quality_to_legacy(quality: DecisionQuality) -> OutcomeType:
    mapping = {
        DecisionQuality.CORRECT_ACCEPT:           OutcomeType.CORRECT_ACCEPT,
        DecisionQuality.FALSE_ACCEPT:             OutcomeType.FALSE_ACCEPT,
        DecisionQuality.BENIGN_REVIEW:            OutcomeType.CORRECT_ACCEPT,
        DecisionQuality.CORRECT_INTERCEPT_VERIFY: OutcomeType.CORRECT_BLOCK,
        DecisionQuality.FALSE_BLOCK:              OutcomeType.FALSE_BLOCK,
        DecisionQuality.CORRECT_BLOCK:            OutcomeType.CORRECT_BLOCK,
        DecisionQuality.ABSTAIN_UNKNOWN:          OutcomeType.UNKNOWN,
    }
    return mapping.get(quality, OutcomeType.UNKNOWN)


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------

@dataclass
class Episode:
    """One governance decision with its observed ground truth.

    Primary update API:
        episode.record_ground_truth(GroundTruth.HARMFUL)

    The `decision_quality` field is computed automatically from (verdict, ground_truth).
    """

    domain: str
    risk_tier: str
    action_type: str
    phase: str
    trust_score: float
    entropy_H: float
    dissensus_D: float
    verdict: str
    confidence: float
    rules_triggered: list[str] = field(default_factory=list)

    # Ground truth — set after observing what actually happened
    ground_truth:     GroundTruth      = GroundTruth.UNKNOWN
    decision_quality: DecisionQuality | None = None
    outcome_severity: float            = 0.0
    outcome_ts:       str              = ""

    # Derived governance flags
    executed:        bool = False   # was the action autonomously executed?
    hard_block:      bool = False   # was this a hard block (ESCALATE)?
    review_required: bool = False   # did it trigger human review?

    # MetaJudge
    critique_score: float | None = None
    critique_text:  str          = ""

    # Legacy field — derived from decision_quality for backward compat
    outcome: OutcomeType = OutcomeType.PENDING

    meta: dict[str, Any] = field(default_factory=dict)
    episode_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Provenance — tracks where each episode comes from and how trustworthy it is
    source: str = "unknown"
    # source values: "claude_code_hook" | "replay" | "seed" | "mcp_gateway" | "manual_label" | "unknown"

    label_source: str = "unknown"
    # label_source values: "human" | "synthetic" | "oracle" | "auto_label" | "replay_truth" | "unknown"

    label_confidence: float = 1.0
    # 0.0–1.0: how confident we are in the ground_truth label

    synthetic: bool = False
    # True if episode was synthetically generated, not from a real agent session

    can_train: bool = True
    # False for holdout episodes — AROMER must never adapt from these

    can_publish_metric: bool = True
    # False for episodes with sensitive content that shouldn't appear in public reports

    oracles_used: list[str] = field(default_factory=list)
    # Oracle IDs actually consulted for this decision. The bandit may only credit
    # oracles that genuinely produced a signal — crediting non-consulted arms with
    # a copied/proxy outcome fabricates differentiation and pins every arm to the
    # same posterior. Empty list means provenance is unknown (credit the primary
    # oracle only, never the whole pool).

    # ------------------------------------------------------------------
    # Outcome recording (new API)
    # ------------------------------------------------------------------

    def record_ground_truth(
        self,
        ground_truth: GroundTruth,
        severity: float = 0.0,
    ) -> None:
        """Record actual ground truth and derive decision quality."""
        self.ground_truth    = ground_truth
        self.outcome_severity = max(-1.0, min(1.0, severity))
        self.outcome_ts      = datetime.now(timezone.utc).isoformat()
        self.decision_quality = DecisionQuality.from_verdict_truth(
            self.verdict, ground_truth
        )
        # Derived governance flags
        v = self.verdict.upper()
        self.executed        = (v == "ACCEPT")
        self.hard_block      = (v == "ESCALATE")
        self.review_required = (v in ("VERIFY", "ESCALATE", "ABSTAIN"))
        # Legacy
        self.outcome = _quality_to_legacy(self.decision_quality)

    # Legacy alias
    def record_outcome(
        self,
        outcome: OutcomeType,
        severity: float = 0.0,
    ) -> None:
        """Legacy API — maps OutcomeType to GroundTruth then calls record_ground_truth."""
        truth = GroundTruth.UNKNOWN
        if outcome in {OutcomeType.FALSE_ACCEPT, OutcomeType.SAFETY_VIOLATION,
                       OutcomeType.CORRECT_BLOCK}:
            truth = GroundTruth.HARMFUL
        elif outcome in {OutcomeType.CORRECT_ACCEPT, OutcomeType.FALSE_BLOCK}:
            truth = GroundTruth.BENIGN
        self.record_ground_truth(truth, severity)
        # A safety violation is only an execution failure if the action ran.
        if outcome == OutcomeType.SAFETY_VIOLATION and self.verdict.upper() == "ACCEPT":
            self.outcome = OutcomeType.SAFETY_VIOLATION

    def record_critique(self, score: float, text: str) -> None:
        self.critique_score = round(max(-1.0, min(1.0, score)), 4)
        self.critique_text  = text

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def content_hash(self) -> str:
        payload = json.dumps({
            "domain":      self.domain,
            "risk_tier":   self.risk_tier,
            "action_type": self.action_type,
            "phase":       self.phase,
            "verdict":     self.verdict,
            "trust_score": round(self.trust_score, 4),
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["outcome"]          = self.outcome.value
        d["ground_truth"]     = self.ground_truth.value
        d["decision_quality"] = (
            self.decision_quality.value if self.decision_quality else None
        )
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Episode":
        outcome_raw    = data.pop("outcome",          "pending")
        gt_raw         = data.pop("ground_truth",     "unknown")
        dq_raw         = data.pop("decision_quality", None)
        ep = cls(**{k: v for k, v in data.items()
                    if k in cls.__dataclass_fields__})
        try:
            ep.outcome = OutcomeType(outcome_raw)
        except ValueError:
            ep.outcome = OutcomeType.UNKNOWN
        try:
            ep.ground_truth = GroundTruth(gt_raw)
        except ValueError:
            ep.ground_truth = GroundTruth.UNKNOWN
        try:
            ep.decision_quality = DecisionQuality(dq_raw) if dq_raw else None
        except ValueError:
            ep.decision_quality = None
        return ep

    def feature_vector(self) -> dict[str, float]:
        phase_map = {"ordered": 0.0, "critical": 0.5, "disordered": 1.0}
        tier_map  = {"low": 0.0, "medium": 0.33, "high": 0.67, "critical": 1.0}
        return {
            "trust_score": self.trust_score,
            "entropy_H":   self.entropy_H,
            "dissensus_D": self.dissensus_D,
            "phase_num":   phase_map.get(self.phase, 0.5),
            "risk_num":    tier_map.get(self.risk_tier, 0.5),
        }


# ---------------------------------------------------------------------------
# EpisodeSummary — with corrected metrics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EpisodeSummary:
    """Aggregated statistics with correct three-way governance metrics."""

    total:           int
    n_harmful:       int
    n_benign:        int
    n_unknown:       int

    # Error rates (what matters for safety)
    false_accept_rate:  float | None   # ACCEPT + harmful  / total_harmful
    hard_fpr:           float | None   # ESCALATE + benign / total_benign
    review_friction:    float | None   # VERIFY + benign   / total_benign

    # Correct rates
    correct_block_rate:     float | None   # ESCALATE + harmful / total_harmful
    correct_intercept_rate: float | None   # (VERIFY+ESCALATE) + harmful / harmful

    # Legacy
    false_accepts:      int
    false_blocks:       int
    safety_violations:  int
    pending:            int

    mean_confidence:    float
    mean_critique_score: float | None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["correct"] = self.correct
        data["false_block_rate"] = self.false_block_rate
        return data

    @property
    def false_block_rate(self) -> float | None:
        """Backward-compatible alias for hard false-positive rate."""
        return self.hard_fpr

    @property
    def correct(self) -> int:
        """Backward-compatible count of labelled non-error decisions."""
        labelled = self.total - self.pending
        return max(0, labelled - self.false_accepts - self.false_blocks)

    @classmethod
    def from_episodes(cls, episodes: list[Episode]) -> "EpisodeSummary":
        if not episodes:
            return cls(0, 0, 0, 0, None, None, None, None, None, 0, 0, 0, 0, 0.0, None)

        total   = len(episodes)
        harmful = [e for e in episodes if e.ground_truth == GroundTruth.HARMFUL]
        benign  = [e for e in episodes if e.ground_truth == GroundTruth.BENIGN]
        unknown = [e for e in episodes if e.ground_truth == GroundTruth.UNKNOWN]

        n_h, n_b = len(harmful), len(benign)

        fa = sum(1 for e in harmful if e.decision_quality == DecisionQuality.FALSE_ACCEPT)
        fb = sum(1 for e in benign  if e.decision_quality == DecisionQuality.FALSE_BLOCK)
        sv = sum(1 for e in episodes if e.outcome == OutcomeType.SAFETY_VIOLATION)
        pending = sum(1 for e in episodes if e.ground_truth == GroundTruth.UNKNOWN)

        # Hard FPR: ESCALATE on benign
        hard_fps = sum(1 for e in benign if e.verdict.upper() == "ESCALATE")
        # Review friction: VERIFY on benign. ABSTAIN remains unknown.
        review_f = sum(1 for e in benign if e.verdict.upper() == "VERIFY")
        # Correct intercept: (VERIFY + ESCALATE) on harmful
        intercepts = sum(1 for e in harmful
                        if e.verdict.upper() in ("VERIFY", "ESCALATE"))

        mean_conf   = sum(e.confidence for e in episodes) / total
        scored      = [e.critique_score for e in episodes if e.critique_score is not None]
        mean_crit   = sum(scored) / len(scored) if scored else None

        return cls(
            total=total,
            n_harmful=n_h, n_benign=n_b, n_unknown=len(unknown),
            false_accept_rate  = round(fa / n_h, 4) if n_h else None,
            hard_fpr           = round(hard_fps / n_b, 4) if n_b else None,
            review_friction    = round(review_f / n_b, 4) if n_b else None,
            correct_block_rate = round(sum(1 for e in harmful
                                          if e.verdict.upper() == "ESCALATE") / n_h, 4)
                                 if n_h else None,
            correct_intercept_rate = round(intercepts / n_h, 4) if n_h else None,
            false_accepts=fa, false_blocks=fb, safety_violations=sv, pending=pending,
            mean_confidence    = round(mean_conf, 4),
            mean_critique_score= round(mean_crit, 4) if mean_crit is not None else None,
        )
