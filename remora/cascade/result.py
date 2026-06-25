# Author: Stian Skogbrott
# License: Apache-2.0
"""Cascade result types — one StageResult per stage, wrapped in a CascadeResult."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CascadeStage(int, Enum):
    FAST_GATE = 1
    CONSENSUS = 2
    VERIFIER = 3
    SELF_CONSISTENCY = 4
    CRITIQUE_REVISION = 5
    MOA_SYNTH = 6


class CascadeVerdict(str, Enum):
    ACCEPT = "accept"
    VERIFY = "verify"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


@dataclass
class StageResult:
    stage: CascadeStage
    verdict: CascadeVerdict
    confidence: float
    oracle_calls: int = 0
    answer: Optional[str] = None
    critique: Optional[str] = None
    stopped: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class CascadeResult:
    """Final output of the multi-stage cascade pipeline.

    Attributes:
        final_verdict:      Overall pipeline decision (ACCEPT / VERIFY / ABSTAIN / ESCALATE).
        final_confidence:   Confidence of the last stage that ran.
        answer:             Best answer accumulated across stages (may be None if no stage produced one).
        critique:           Most recent critique from the LLM judge or revision gate.
        stages_run:         Ordered list of StageResult objects, one per stage executed.
        total_oracle_calls: Cumulative oracle calls across all stages.
        stopped_at_stage:   CascadeStage.value of the stage that produced the terminal verdict.
                            Can be 5 (CRITIQUE_REVISION) when Stage 3b was the last stage run.
    """

    final_verdict: CascadeVerdict
    final_confidence: float
    answer: Optional[str] = None
    critique: Optional[str] = None
    stages_run: list[StageResult] = field(default_factory=list)
    total_oracle_calls: int = 0
    stopped_at_stage: int = 0
    uncertainty_epistemic: Optional[float] = None
    uncertainty_aleatoric: Optional[float] = None

    @property
    def is_accepted(self) -> bool:
        return self.final_verdict == CascadeVerdict.ACCEPT

    @property
    def is_abstained(self) -> bool:
        return self.final_verdict in (CascadeVerdict.ABSTAIN, CascadeVerdict.ESCALATE)

    def summary(self) -> dict:
        return {
            "verdict": self.final_verdict.value,
            "confidence": round(self.final_confidence, 4),
            "oracle_calls": self.total_oracle_calls,
            "stages_run": self.stopped_at_stage,
            "answer": self.answer,
            "critique": self.critique,
        }
