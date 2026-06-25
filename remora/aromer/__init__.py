# Author: Stian Skogbrott
# License: Apache-2.0
"""AROMER — Autonomous REMORA Orchestrator, Meta-Emergent Reasoner.

EXPERIMENTAL: Research plugin exploring meta-cognitive AI governance.

    from remora.aromer import AromerOrchestrator, OutcomeType

    aromer = AromerOrchestrator()
    report, ep_id = aromer.decide(obs)
    aromer.record_outcome(ep_id, OutcomeType.CORRECT_ACCEPT)
    print(aromer.adapt())
"""
from remora.aromer.orchestrator import AromerOrchestrator, AromerDecision
from remora.aromer.experience.episode import (
    DecisionQuality,
    Episode,
    GroundTruth,
    OutcomeType,
)
from remora.aromer.experience.store import EpisodicStore
from remora.aromer.world_model.domain_prior import DomainHarmPrior
from remora.aromer.integration.bridge import AromerAdapterBridge
from remora.aromer.meta_judge.judge import AromerMetaJudge, Critique
from remora.aromer.intelligence import IntelligenceScore, AiiComponents, IntelligenceClient

# Kept in lockstep with the deployed AROMER worker (workers/aromer/wrangler.toml).
AROMER_VERSION = "0.2.0-experimental"

__all__ = [
    "AromerOrchestrator",
    "AromerDecision",
    "DecisionQuality",
    "Episode",
    "GroundTruth",
    "OutcomeType",
    "EpisodicStore",
    "DomainHarmPrior",
    "AromerAdapterBridge",
    "AromerMetaJudge",
    "Critique",
    "IntelligenceScore",
    "AiiComponents",
    "IntelligenceClient",
    "AROMER_VERSION",
]
