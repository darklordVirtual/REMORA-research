#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Deterministic REMORA dry-run demo: governing an industrial maintenance agent.

Scenario: a root-cause-analysis agent has investigated abnormal vibration on a
seawater lift pump and now proposes a sequence of actions with escalating
consequence. This demo drives the REAL components end to end:

    A2AGovernanceEnvelope.verify()          (delegation actually verified)
            │
    capability outside effective scope → PolicyObservation.tool_forbidden
            │
    RemoraDecisionEngine.decide()           (real engine, real reason codes)

No live industrial system is contacted and nothing is mutated.

The autonomy boundary this demo encodes:

1. **Reading is cheap.** Telemetry and document reads with evidence are
   ACCEPTed — governance does not add friction where consequence is low.
2. **Recommendations pass through review by explicit policy.** The proposal
   is a high-risk production write against the work-order system, so the
   engine's production-write policy matrix routes it to VERIFY: a human
   approves before any business-system write. (The data comes from the
   operator's own controlled maintenance sources, so it is *not* modeled as
   tainted — review is a policy decision, not a data-provenance workaround.)
3. **Actuation is out of bounds — and provably so.** The agent's delegation
   chain simply does not include the OT-actuation capability. The A2A
   envelope for that request fails scope verification, the failure sets the
   forbidden-tool signal, and the engine hard-ESCALATEs — regardless of how
   confident the analysis is.
4. **Uncertainty degrades autonomy.** The same work-order proposal with
   contradicting evidence in the source data ABSTAINs instead of VERIFYing:
   contradictions must be resolved before a human is even asked to approve.

This is the pattern for placing an assurance layer between agent platforms
and industrial systems (work-order management, maintenance planning, OT/SCADA
gateways): recommendations flow, actuation does not, and every decision is
explainable via `report.reasons` and the envelope's verification failures.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remora.governance.a2a_envelope import (  # noqa: E402
    A2AGovernanceEnvelope,
    AgentIdentity,
    DelegationLink,
    RegisteredKey,
    sign_delegation_link,
)
from remora.policy import PolicyObservation, RemoraDecisionEngine  # noqa: E402
from remora.policy.observation import canonical_tool_call_hash  # noqa: E402

# Demo-fixed keys (this is a dry run — in production these come from key
# management, and the HMAC layer is replaced by asymmetric signatures).
ENVELOPE_KEY = b"demo-envelope-key"
COE_KEY, ORCH_KEY = b"demo-coe-key", b"demo-orchestrator-key"
# kid -> RegisteredKey binds key material to a principal: a valid registered
# key cannot sign a link claiming a different delegator.
LINK_KEYS = {
    "coe-2026": RegisteredKey(key=COE_KEY, principal="operator-coe"),
    "orch-2026": RegisteredKey(key=ORCH_KEY, principal="agent://orchestrator/01"),
}

# Replay guard: the verifier remembers seen nonces (caller-owned state).
_SEEN_NONCES: set[str] = set()


def _replay_guard(nonce: str) -> bool:
    seen = nonce in _SEEN_NONCES
    _SEEN_NONCES.add(nonce)
    return seen

AGENT_ID = "agent://maintenance-planner/07"
AUDIENCE = "control-plane://operator-remora"

# What the operator actually delegated to this agent — note what is absent:
# no "ot:*" capability. Actuation authority was never granted.
DELEGATED_SCOPE = ("telemetry:read", "docs:read", "workorder:propose_change")


def issue_envelope(capability: str, tool_call_hash: str | None = None) -> A2AGovernanceEnvelope:
    """Issue the agent's delegation envelope for one requested capability,
    bound to the exact tool-call payload it authorises."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    chain = (
        sign_delegation_link(
            DelegationLink(
                delegator="operator-coe",
                delegatee="agent://orchestrator/01",
                scope=("telemetry:read", "docs:read",
                       "workorder:propose_change", "workorder:read"),
                issued_at=now,
            ),
            key=COE_KEY, kid="coe-2026",
        ),
        sign_delegation_link(
            DelegationLink(
                delegator="agent://orchestrator/01",
                delegatee=AGENT_ID,
                scope=DELEGATED_SCOPE,  # attenuated: workorder:read dropped
                issued_at=now,
            ),
            key=ORCH_KEY, kid="orch-2026",
        ),
    )
    return A2AGovernanceEnvelope.issue(
        identity=AgentIdentity(
            agent_id=AGENT_ID,
            agent_version="2.4.1",
            issuer_org="operator-coe",
            responsible_org="operator-asset-team",
        ),
        delegation_chain=chain,
        requested_scope=(capability,),
        policy_version="RemoraDecisionEngine-v3",
        audience=AUDIENCE,
        tool_call_hash=tool_call_hash,
        signing_key=ENVELOPE_KEY,
    )


def delegation_check(
    capability: str, tool_call_hash: str,
) -> tuple[bool, tuple[str, ...], A2AGovernanceEnvelope]:
    """Verify the A2A envelope for a capability, bound to the exact payload.

    Returns (tool_forbidden, failures, envelope): a request outside the
    verified effective scope — or any verification failure, including a
    payload-binding mismatch or nonce replay — sets the forbidden-tool
    signal, which the engine hard-escalates. Fail closed.
    """
    envelope = issue_envelope(capability, tool_call_hash=tool_call_hash)
    result = envelope.verify(
        signing_key=ENVELOPE_KEY,
        expected_audience=AUDIENCE,
        link_keys=LINK_KEYS,
        expected_tool_call_hash=tool_call_hash,
        replay_guard=_replay_guard,
    )
    return (not result.valid), result.failures, envelope


@dataclass(frozen=True)
class ProposedAction:
    label: str
    narrative: str
    capability: str
    observation: PolicyObservation
    delegation_failures: tuple[str, ...]


def build_actions() -> list[ProposedAction]:
    """The agent's proposed action sequence.

    For each action the A2A envelope is verified first; the delegation
    outcome feeds `tool_forbidden` on the PolicyObservation. REMORA is
    stateless: sensor evidence and schema validation are the caller's
    responsibility, encoded as observation fields.
    """

    def action(label: str, narrative: str, capability: str,
               tool: str, tool_args: dict, **obs_fields) -> ProposedAction:
        # Bind the delegation envelope to the exact payload — the same hash the
        # enforcement gate recomputes immediately before execution.
        payload_hash = canonical_tool_call_hash(
            name=tool, arguments=tool_args,
            target=obs_fields.get("target_environment"),
        )
        tool_forbidden, failures, _envelope = delegation_check(capability, payload_hash)
        return ProposedAction(
            label=label,
            narrative=narrative,
            capability=capability,
            observation=PolicyObservation(
                tool_forbidden=tool_forbidden,
                tool_call_hash=payload_hash,
                **obs_fields,
            ),
            delegation_failures=failures,
        )

    return [
        action(
            "read_vibration_telemetry",
            "Read 24h vibration trend for pump P-3101A",
            "telemetry:read",
            tool="read_telemetry",
            tool_args={"asset": "P-3101A", "signal": "vibration", "window": "24h"},
            question="read_telemetry(asset=P-3101A, signal=vibration, window=24h)",
            phase="ordered", trust_score=0.91,
            evidence_action="answer", evidence_confidence=0.94,
            evidence_signal_source="retrieval",
            risk_tier="low", action_type="read", domain="maintenance",
            target_environment="prod", schema_valid=True,
        ),
        action(
            "read_equipment_history",
            "Retrieve maintenance history and last overhaul report",
            "docs:read",
            tool="read_documents",
            tool_args={"asset": "P-3101A", "type": "maintenance_history"},
            question="read_documents(asset=P-3101A, type=maintenance_history)",
            phase="ordered", trust_score=0.88,
            evidence_action="answer", evidence_confidence=0.90,
            evidence_signal_source="retrieval",
            risk_tier="low", action_type="read", domain="maintenance",
            target_environment="prod", schema_valid=True,
        ),
        action(
            "propose_workorder_change",
            "Propose advancing the bearing-replacement work order by 3 weeks "
            "based on vibration trend + history",
            "workorder:propose_change",
            tool="update_work_order",
            tool_args={"order": "WO-88231", "action": "reschedule",
                       "new_date": "advance_3_weeks",
                       "justification": "vibration_trend"},
            question=(
                "update_work_order(order=WO-88231, action=reschedule, "
                "new_date=advance_3_weeks, justification=vibration_trend)"
            ),
            phase="ordered", trust_score=0.86,
            evidence_action="verify", evidence_confidence=0.82,
            evidence_supporters=3, evidence_signal_source="retrieval",
            # High-risk production write → the engine's explicit
            # production-write policy matrix requires human review.
            risk_tier="high", action_type="production_write",
            domain="maintenance", target_environment="prod",
            schema_valid=True, rollback_available=True,
        ),
        action(
            "propose_with_contradicting_evidence",
            "Same work-order proposal, but the overhaul report contradicts "
            "the vibration interpretation",
            "workorder:propose_change",
            tool="update_work_order",
            tool_args={"order": "WO-88231", "action": "reschedule",
                       "new_date": "advance_3_weeks",
                       "justification": "vibration_trend",
                       "evidence_state": "contradicted"},
            question=(
                "update_work_order(order=WO-88231, action=reschedule, "
                "new_date=advance_3_weeks, justification=vibration_trend)"
            ),
            phase="critical", trust_score=0.61,
            evidence_action="verify", evidence_confidence=0.55,
            evidence_supporters=2,
            evidence_contradictions=1,   # hard guard: contradiction blocks
            evidence_signal_source="retrieval",
            risk_tier="high", action_type="production_write",
            domain="maintenance", target_environment="prod",
            schema_valid=True, rollback_available=True,
        ),
        action(
            "direct_ot_actuation",
            "Directly reduce pump speed via the control system",
            "ot:set_pump_speed",   # never delegated → envelope verify fails
            tool="set_pump_speed",
            tool_args={"asset": "P-3101A", "target_rpm": 2400},
            question="set_pump_speed(asset=P-3101A, target_rpm=2400)",
            phase="ordered", trust_score=0.93,   # confidence is irrelevant:
            evidence_action="answer",            # authority was never granted
            evidence_confidence=0.95,
            evidence_signal_source="retrieval",
            risk_tier="critical", action_type="write", domain="ot_control",
            target_environment="prod", schema_valid=True,
            rollback_available=True,
        ),
    ]


def main() -> int:
    engine = RemoraDecisionEngine()
    actions = build_actions()

    width = 86
    print("REMORA industrial-maintenance action-gating dry run (real RemoraDecisionEngine)")
    print("=" * width)
    print("Scenario: RCA agent investigated abnormal vibration on pump P-3101A.")
    print(f"Delegated scope (A2A envelope, per-link signed): {', '.join(DELEGATED_SCOPE)}")
    print("Safety model: no live industrial system is contacted; decisions are real.")
    print("-" * width)

    for action in actions:
        report = engine.decide(action.observation)
        reason_codes = ", ".join(r.value for r in report.reasons)
        review = "human review" if report.human_review_required else "no review needed"
        print(f"{action.label:38s} -> {report.action.value.upper():8s} ({review})")
        print(f"    {action.narrative}")
        print(f"    capability: {action.capability}  |  reasons: {reason_codes}")
        if action.delegation_failures:
            print(f"    delegation verify FAILED: {', '.join(action.delegation_failures)}")
    print("-" * width)
    print("Interpretation:")
    print("- Low-consequence reads ACCEPT: governance adds no friction where it isn't needed.")
    print("- The work-order proposal routes to VERIFY via the explicit production-write")
    print("  policy matrix (high-risk production write): a human approves before any")
    print("  business-system write — the agent recommends, it does not apply.")
    print("- With contradicting evidence the same proposal ABSTAINs: contradictions must")
    print("  be resolved before a human is even asked to approve.")
    print("- Direct OT actuation fails A2A scope verification (the capability was never")
    print("  delegated); that failure feeds tool_forbidden and the engine hard-ESCALATEs.")
    print("  Analysis confidence cannot buy actuation authority.")

    # -- Replay and payload-binding demonstration ------------------------------
    print("-" * width)
    print("Replay/binding checks (same telemetry envelope, attacked two ways):")
    telemetry_hash = canonical_tool_call_hash(
        name="read_telemetry",
        arguments={"asset": "P-3101A", "signal": "vibration", "window": "24h"},
        target="prod",
    )
    envelope = issue_envelope("telemetry:read", tool_call_hash=telemetry_hash)
    first = envelope.verify(
        signing_key=ENVELOPE_KEY, expected_audience=AUDIENCE,
        link_keys=LINK_KEYS, expected_tool_call_hash=telemetry_hash,
        replay_guard=_replay_guard,
    )
    replayed = envelope.verify(
        signing_key=ENVELOPE_KEY, expected_audience=AUDIENCE,
        link_keys=LINK_KEYS, expected_tool_call_hash=telemetry_hash,
        replay_guard=_replay_guard,
    )
    other_payload = canonical_tool_call_hash(
        name="read_telemetry",
        arguments={"asset": "P-9999Z", "signal": "vibration", "window": "24h"},
        target="prod",
    )
    rebound = envelope.verify(
        signing_key=ENVELOPE_KEY, expected_audience=AUDIENCE,
        link_keys=LINK_KEYS, expected_tool_call_hash=other_payload,
    )
    print(f"  first use              : {'VALID' if first.valid else first.failures}")
    print(f"  replayed (same nonce)  : {'VALID' if replayed.valid else ', '.join(replayed.failures)}")
    print(f"  different payload hash : {'VALID' if rebound.valid else ', '.join(rebound.failures)}")
    print("  One envelope authorises one payload, once.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
