# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""One-call tool-call assessment — the library form of ``remora assess``.

The shortest path from an agent's proposed tool call to an auditable
governance verdict, with no configuration, no API keys, and no network:

    from remora import assess_tool_call

    a = assess_tool_call("drop_database", {"db": "prod-main"}, infer=True)
    if a.should_execute:          # True only on ACCEPT
        run_tool(...)
    audit_log.write(a.envelope.to_dict())

Runs the same production code paths as the CLI and the REST API's
deterministic layer: the admission firewall (``detect_adversarial``),
``RemoraDecisionEngine.decide`` for the verdict, ``.explain`` for the
rule-by-rule trace, and ``build_decision_envelope`` for the canonical audit
contract. Anything left unset is handled fail-closed by the engine (unknown
risk routes to VERIFY, never ACCEPT). ``trust_score``/``phase`` stand in for
live multi-oracle consensus, which runs via the REST API or ``--live``.

Framework loop (OpenAI-style; LangGraph/CrewAI adapters in
``remora.integrations``)::

    for call in response.choices[0].message.tool_calls:
        a = assess_tool_call(call.function.name,
                             json.loads(call.function.arguments), infer=True)
        if not a.should_execute:
            report_blocked(call, why=a.decision.explanation)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from remora.governance.envelope import DecisionEnvelope
from remora.policy.decision_engine import PolicyTrace, RemoraDecisionEngine
from remora.policy.report import DecisionReport

# ---------------------------------------------------------------------------
# Name inference — transparent stand-in defaults from well-known name patterns
# ---------------------------------------------------------------------------

# Opt-in (``infer=True`` / CLI default): fills only fields the caller left
# unset, and the result records exactly what was inferred. This is caller
# convenience, not engine policy — the engine still fail-closes on unset.
_NAME_INFERENCE: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("drop", "delete", "remove", "truncate", "destroy", "wipe", "purge"),
     "destructive_write", "critical"),
    (("disable", "revoke", "unlock", "mfa", "firewall", "permission"),
     "security_change", "critical"),
    (("wire", "transfer", "payment", "payout", "refund", "charge"),
     "financial_transaction", "high"),
    (("deploy", "release", "rollout", "restart", "scale", "migrate"),
     "deploy", "medium"),
    (("send", "publish", "notify", "write", "update", "create", "insert", "upload"),
     "write", "medium"),
    (("read", "get", "list", "fetch", "query", "search", "view", "describe"),
     "read", "low"),
)


def infer_risk_and_type(name: str) -> tuple[str | None, str | None]:
    """Return ``(action_type, risk_tier)`` inferred from a tool name.

    Matches whole words of the name (split on ``_``/``-``/camelCase) by
    prefix, so ``read_file`` matches ``read`` but ``widget`` does not match
    ``get``. Returns ``(None, None)`` when nothing matches.
    """
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    tokens = [t for t in re.split(r"[^a-z0-9]+", snake.lower()) if t]
    for keywords, action_type, risk in _NAME_INFERENCE:
        if any(t.startswith(k) for t in tokens for k in keywords):
            return action_type, risk
    return None, None


# ---------------------------------------------------------------------------
# The one-call assessment
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolCallAssessment:
    """Everything one governance decision produced, in one object."""

    decision: DecisionReport
    """The verdict: ``.action``, ``.reasons``, ``.human_review_required``, ..."""
    trace: PolicyTrace
    """Rule-by-rule reasoning: ``.decision_path``, ``.rule_evaluations``."""
    envelope: DecisionEnvelope
    """The canonical auditable DecisionEnvelope — persist this."""
    inferred: dict[str, str] = field(default_factory=dict)
    """Fields filled by name inference (empty unless ``infer=True`` matched)."""

    @property
    def action(self) -> str:
        """The outcome as a string: accept / verify / abstain / escalate."""
        return self.decision.action.value

    @property
    def should_execute(self) -> bool:
        """True only when the outcome is ACCEPT."""
        return self.action == "accept"

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready summary (decision + trace + inferred + envelope)."""
        return {
            "decision": {
                "action": self.action,
                "reasons": [r.value for r in self.decision.reasons],
                "risk_estimate": self.decision.risk_estimate,
                "confidence": self.decision.confidence,
                "human_review_required": self.decision.human_review_required,
                "evidence_required": self.decision.evidence_required,
                "explanation": self.decision.explanation,
                "policy_version": self.decision.policy_version,
            },
            "trace": {
                "decision_path": self.trace.decision_path,
                "triggered_rules": [
                    e.rule for e in self.trace.rule_evaluations if e.triggered
                ],
            },
            "inferred": dict(self.inferred),
            "envelope": self.envelope.to_dict(),
        }


def assess_tool_call(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    risk_tier: str | None = None,
    action_type: str | None = None,
    target_environment: str = "prod",
    trust_score: float | None = None,
    phase: str | None = None,
    infer: bool = False,
) -> ToolCallAssessment:
    """Assess one proposed tool call; deterministic, offline, auditable.

    Parameters mirror ``PolicyObservation.from_tool_call``. With ``infer=True``
    unset ``risk_tier``/``action_type`` are filled from well-known name
    patterns (see :func:`infer_risk_and_type`); explicit values always win and
    ``ToolCallAssessment.inferred`` records exactly what was filled.
    """
    from remora.policy.observation import PolicyObservation
    from remora.reporting import build_decision_envelope
    from remora.safety.adversarial import detect_adversarial

    arguments = arguments or {}
    inferred: dict[str, str] = {}
    if infer and (risk_tier is None or action_type is None):
        inf_type, inf_risk = infer_risk_and_type(name)
        if action_type is None and inf_type:
            action_type = inf_type
            inferred["action_type"] = inf_type
        if risk_tier is None and inf_risk:
            risk_tier = inf_risk
            inferred["risk_tier"] = inf_risk

    probe = f"{name} {json.dumps(arguments, sort_keys=True, default=str)}"
    obs = PolicyObservation.from_tool_call(
        name=name,
        arguments=arguments,
        risk_tier=risk_tier,
        action_type=action_type,
        target_environment=target_environment,
        trust_score=trust_score,
        phase=phase,
        adversarial_detected=detect_adversarial(probe),
    )
    engine = RemoraDecisionEngine()
    decision = engine.decide(obs)
    trace = engine.explain(obs)
    envelope = build_decision_envelope(obs, decision, question=obs.question)
    return ToolCallAssessment(
        decision=decision, trace=trace, envelope=envelope, inferred=inferred,
    )
