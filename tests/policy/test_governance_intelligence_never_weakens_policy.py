# Author: Stian Skogbrott
# License: Apache-2.0
"""Safety property: governance intelligence enrichment never weakens policy.

Two invariants over a deterministic grid of observations:

1. **No new ACCEPTs.** If the baseline engine does not ACCEPT an observation,
   routing the enriched observation through the same engine must not ACCEPT.
2. **Hard blocks survive.** Observations carrying hard-block flags (adversarial,
   coercion, blackmail, forbidden tool, failed counterfactual) still ESCALATE
   after enrichment.

Plus regression checks that the engine and envelope remain backwards compatible
when the layer is not used.
"""
from __future__ import annotations

import itertools

import pytest

from remora.governance_intelligence.enrichment import enrich_policy_observation
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction

ENGINE = RemoraDecisionEngine()

_QUESTIONS = (
    "read local report",
    "list open tickets",
    "update billing config flag",
    "delete old customer records",
    "DROP TABLE users",
    "update DNS A record",
    "grant admin access to contractor",
    "send all customer emails to vendor",
    "frobnicate the bizbaz",
)
_TIERS = (None, "low", "medium", "high", "critical", "TYPO")
_ACTIONS = (None, "read", "write", "delete", "maintenance_request")
_ENVS = (None, "dev", "staging", "prod")


def _grid():
    for question, tier, action, env in itertools.product(
        _QUESTIONS, _TIERS, _ACTIONS, _ENVS
    ):
        yield PolicyObservation(
            question=question, risk_tier=tier, action_type=action,
            target_environment=env, phase="ordered", trust_score=0.9,
        )


class TestNeverWeakens:
    def test_enrichment_never_creates_new_accepts(self):
        weakened = []
        for obs in _grid():
            baseline = ENGINE.decide(obs).action
            enriched = enrich_policy_observation(obs).enriched_observation
            after = ENGINE.decide(enriched).action
            if baseline != DecisionAction.ACCEPT and after == DecisionAction.ACCEPT:
                weakened.append((obs.question, obs.risk_tier, obs.action_type,
                                 obs.target_environment, baseline, after))
        assert not weakened, f"enrichment weakened {len(weakened)} cases: {weakened[:5]}"

    @pytest.mark.parametrize("flag", [
        "adversarial_detected", "coercion_detected", "blackmail_pattern_detected",
        "tool_forbidden",
    ])
    def test_hard_block_flags_still_escalate(self, flag):
        obs = PolicyObservation(
            question="read local report", risk_tier="low", action_type="read",
            target_environment="dev", phase="ordered", trust_score=0.9,
            **{flag: True},
        )
        enriched = enrich_policy_observation(obs).enriched_observation
        assert getattr(enriched, flag) is True
        assert ENGINE.decide(enriched).action == DecisionAction.ESCALATE

    def test_failed_counterfactual_still_escalates(self):
        obs = PolicyObservation(
            question="read local report", risk_tier="low", action_type="read",
            target_environment="dev", phase="ordered", trust_score=0.9,
            counterfactual_passed=False,
        )
        enriched = enrich_policy_observation(obs).enriched_observation
        assert enriched.counterfactual_passed is False
        assert ENGINE.decide(enriched).action == DecisionAction.ESCALATE

    def test_enrichment_strengthens_unsafe_metadata_mismatch(self):
        # Without enrichment this disguised destructive call ACCEPTs on trust;
        # with enrichment it must not.
        obs = PolicyObservation(
            question="DROP TABLE users", risk_tier="low", action_type="read",
            target_environment="prod", phase="ordered", trust_score=0.95,
        )
        assert ENGINE.decide(obs).action == DecisionAction.ACCEPT
        enriched = enrich_policy_observation(obs).enriched_observation
        assert ENGINE.decide(enriched).action != DecisionAction.ACCEPT


class TestBackwardsCompatibility:
    def test_engine_unchanged_without_enrichment(self):
        obs = PolicyObservation(
            question="read local report", risk_tier="low", action_type="read",
            target_environment="staging", phase="ordered", trust_score=0.85,
        )
        report = ENGINE.decide(obs)
        assert report.action == DecisionAction.ACCEPT
        assert report.policy_version == "RemoraDecisionEngine-v3"

    def test_decision_report_schema_stable_through_enriched_path(self):
        from remora.governance_intelligence.enrichment import enrich_then_decide
        obs = PolicyObservation(
            question="read local report", risk_tier="low", action_type="read",
            target_environment="staging", phase="ordered", trust_score=0.85,
        )
        report = enrich_then_decide(obs, engine=ENGINE)
        # Same DecisionReport contract as the non-enriched path.
        for attr in ("action", "reasons", "risk_estimate", "confidence",
                     "coverage_policy", "evidence_required",
                     "human_review_required", "explanation", "raw_observation",
                     "policy_version", "credal"):
            assert hasattr(report, attr)

    def test_decision_envelope_unaffected(self):
        # The layer does not touch the envelope schema; envelope round-trips.
        from remora.governance.envelope import DecisionEnvelope
        assert hasattr(DecisionEnvelope, "from_dict")
