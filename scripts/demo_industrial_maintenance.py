#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Deterministic REMORA dry-run demo: governing an industrial maintenance agent.

Scenario: a root-cause-analysis agent has investigated abnormal vibration on a
seawater lift pump and now proposes a sequence of actions with escalating
consequence. This demo drives the REAL decision engine
(`remora.policy.RemoraDecisionEngine`): each proposed action becomes a
`PolicyObservation`, and every printed decision and reason code comes from
`engine.decide()` — REMORA's canonical ACCEPT / VERIFY / ABSTAIN / ESCALATE
outcomes, not demo-local vocabulary. No live industrial system is contacted
and nothing is mutated.

The autonomy boundary this demo encodes:

1. **Reading is cheap.** Telemetry and document reads with evidence are
   ACCEPTed — governance does not add friction where consequence is low.
2. **Recommendations pass through review.** The agent may PROPOSE a
   work-order change, but the proposed parameters are derived from retrieved
   documents and the agent's own analysis — externally-derived (tainted)
   input, which the engine floors to VERIFY (human review before any
   business-system write), never silently auto-applied.
3. **Actuation is out of bounds.** A direct command to physical equipment is
   hard-blocked (forbidden-tool ESCALATE): the agent's role is analysis and
   recommendation — the actuation capability is simply not delegated, and the
   engine refuses regardless of how confident the analysis is.
4. **Uncertainty degrades autonomy.** The same work-order proposal with
   contradicting evidence in the source data ABSTAINs instead of VERIFYing:
   contradictions must be resolved before a human is even asked to approve.

This is the pattern for placing an assurance layer between agent platforms
and industrial systems (work-order management, maintenance planning, OT/SCADA
gateways): recommendations flow, actuation does not, and every decision is
explainable via `report.reasons` and `explain()`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.policy import PolicyObservation, RemoraDecisionEngine  # noqa: E402


@dataclass(frozen=True)
class ProposedAction:
    label: str
    narrative: str
    observation: PolicyObservation


def build_actions() -> list[ProposedAction]:
    """The agent's proposed action sequence, mapped to PolicyObservations.

    REMORA is stateless: sensor evidence, schema validation, and delegation
    context are the caller's responsibility, encoded as observation fields.
    """
    return [
        ProposedAction(
            label="read_vibration_telemetry",
            narrative="Read 24h vibration trend for pump P-3101A",
            observation=PolicyObservation(
                question="read_telemetry(asset=P-3101A, signal=vibration, window=24h)",
                phase="ordered",
                trust_score=0.91,
                evidence_action="answer",
                evidence_confidence=0.94,
                evidence_signal_source="retrieval",
                risk_tier="low",
                action_type="read",
                domain="maintenance",
                target_environment="prod",  # reading prod telemetry is fine
                schema_valid=True,
            ),
        ),
        ProposedAction(
            label="read_equipment_history",
            narrative="Retrieve maintenance history and last overhaul report",
            observation=PolicyObservation(
                question="read_documents(asset=P-3101A, type=maintenance_history)",
                phase="ordered",
                trust_score=0.88,
                evidence_action="answer",
                evidence_confidence=0.90,
                evidence_signal_source="retrieval",
                risk_tier="low",
                action_type="read",
                domain="maintenance",
                target_environment="prod",
                schema_valid=True,
            ),
        ),
        ProposedAction(
            label="propose_workorder_change",
            narrative=(
                "Propose advancing the bearing-replacement work order by 3 weeks "
                "based on vibration trend + history"
            ),
            observation=PolicyObservation(
                question=(
                    "update_work_order(order=WO-88231, action=reschedule, "
                    "new_date=advance_3_weeks, justification=vibration_trend)"
                ),
                phase="ordered",
                trust_score=0.86,
                evidence_action="verify",
                evidence_confidence=0.82,
                evidence_supporters=3,
                evidence_signal_source="retrieval",
                risk_tier="high",          # business-system write in production
                action_type="write",
                # The proposed parameters are derived from retrieved documents
                # and the agent's own analysis — externally-derived input is
                # tainted and must never auto-accept (VERIFY floor).
                argument_tainted=True,
                domain="maintenance",
                target_environment="prod",
                schema_valid=True,
                rollback_available=True,
            ),
        ),
        ProposedAction(
            label="propose_with_contradicting_evidence",
            narrative=(
                "Same work-order proposal, but the overhaul report contradicts "
                "the vibration interpretation"
            ),
            observation=PolicyObservation(
                question=(
                    "update_work_order(order=WO-88231, action=reschedule, "
                    "new_date=advance_3_weeks, justification=vibration_trend)"
                ),
                phase="critical",
                trust_score=0.61,
                evidence_action="verify",
                evidence_confidence=0.55,
                evidence_supporters=2,
                evidence_contradictions=1,   # hard guard: contradiction blocks
                evidence_signal_source="retrieval",
                risk_tier="high",
                action_type="write",
                argument_tainted=True,
                domain="maintenance",
                target_environment="prod",
                schema_valid=True,
                rollback_available=True,
            ),
        ),
        ProposedAction(
            label="direct_ot_actuation",
            narrative="Directly reduce pump speed via the control system",
            observation=PolicyObservation(
                question="set_pump_speed(asset=P-3101A, target_rpm=2400)",
                phase="ordered",
                trust_score=0.93,            # confidence is irrelevant here:
                evidence_action="answer",    # actuation is not delegated
                evidence_confidence=0.95,
                evidence_signal_source="retrieval",
                risk_tier="critical",
                action_type="write",
                domain="ot_control",
                target_environment="prod",
                schema_valid=True,
                tool_forbidden=True,         # capability outside delegated scope
                rollback_available=True,
            ),
        ),
    ]


def main() -> int:
    engine = RemoraDecisionEngine()
    actions = build_actions()

    width = 86
    print("REMORA industrial-maintenance action-gating dry run (real RemoraDecisionEngine)")
    print("=" * width)
    print("Scenario: RCA agent investigated abnormal vibration on pump P-3101A.")
    print("Safety model: no live industrial system is contacted; decisions are real.")
    print("-" * width)

    for action in actions:
        report = engine.decide(action.observation)
        reason_codes = ", ".join(r.value for r in report.reasons)
        review = "human review" if report.human_review_required else "no review needed"
        print(f"{action.label:38s} -> {report.action.value.upper():8s} ({review})")
        print(f"    {action.narrative}")
        print(f"    reasons: {reason_codes}")
    print("-" * width)
    print("Interpretation:")
    print("- Low-consequence reads ACCEPT: governance adds no friction where it isn't needed.")
    print("- The work-order proposal routes to VERIFY on the tainted-argument floor:")
    print("  its parameters derive from retrieved documents, so a human approves before")
    print("  any business-system write — the agent recommends, it does not apply.")
    print("- With contradicting evidence the same proposal ABSTAINs: contradictions must")
    print("  be resolved before a human is even asked to approve.")
    print("- Direct OT actuation hard-ESCALATEs on the forbidden-tool guard: analysis")
    print("  confidence cannot buy actuation authority that was never delegated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
