# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""One-call tool-call assessment — the library form of ``remora assess``.

The shortest path from an agent's proposed tool call to an auditable
governance verdict, with no configuration, no API keys, and no network:

    from remora import assess_tool_call

    a = assess_tool_call("drop_database", {"db": "prod-main"},
                         risk_tier="critical",              # from YOUR tool
                         action_type="destructive_write")   # registry
    if a.should_execute:          # True only on ACCEPT
        run_tool(...)
    audit_log.write(a.envelope.to_dict())

**Advisory, not enforcement** (external review 2026-07-29 F-04). This
function judges the metadata *you* hand it — it is not bound to the callable
that will actually run. It is only as strong as its inputs:

- ``risk_tier`` / ``action_type`` must come from a **trusted tool registry**
  keyed by callable identity, never from the caller of the tool or from the
  tool's *name*: a mutating callable behind a benign name, or caller-asserted
  ``risk_tier="low"``, defeats the assessment.
- ``infer=True`` guesses from the name for exploration and demos. **Never
  let inference drive real execution** — check ``a.advisory`` (True when
  inference filled fields) and treat those verdicts as advisory only.
- ``trust_score``/``phase`` are caller-supplied stand-ins for live
  multi-oracle consensus (REST API / ``--live``).

The enforcement-grade path is the ``/v1/execution`` API with the
``GovernedToolDispatcher`` PEP: tools registered by deployment configuration,
risk/action resolved server-side, execution lease-bound to the exact call.

Runs the same production code paths as the CLI and the REST API's
deterministic layer: the admission firewall (``detect_adversarial``),
``RemoraDecisionEngine.decide`` for the verdict, ``.explain`` for the
rule-by-rule trace, and ``build_decision_envelope`` for the canonical audit
contract. Anything left unset is handled fail-closed by the engine (unknown
risk routes to VERIFY, never ACCEPT).

Framework loop (OpenAI-style; LangGraph/CrewAI adapters in
``remora.integrations``) — metadata looked up per tool, not inferred::

    for call in response.choices[0].message.tool_calls:
        meta = TOOL_REGISTRY[call.function.name]    # KeyError = unknown tool
        a = assess_tool_call(call.function.name,
                             json.loads(call.function.arguments), **meta)
        if not a.should_execute:
            report_blocked(call, why=a.decision.explanation)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from remora.governance.envelope import DecisionEnvelope
from remora.policy.decision_engine import PolicyTrace, RemoraDecisionEngine
from remora.policy.report import DecisionAction, DecisionReport

if TYPE_CHECKING:
    from remora.policy.whatif import WhatIfReport

# ---------------------------------------------------------------------------
# Name inference — transparent stand-in defaults from well-known name patterns
# ---------------------------------------------------------------------------

# Opt-in (``infer=True`` / CLI default): fills only fields the caller left
# unset, and the result records exactly what was inferred. This is caller
# convenience, not engine policy — the engine still fail-closes on unset.
_NAME_INFERENCE: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("drop", "delete", "remove", "truncate", "destroy", "wipe", "purge"),
     "destructive_write", "critical"),
    (("disable", "revoke", "unlock", "mfa", "firewall", "permission", "suspend"),
     "security_change", "critical"),
    (("wire", "transfer", "payment", "payout", "refund", "charge"),
     "financial_transaction", "high"),
    (("deploy", "release", "rollout", "restart", "scale", "migrate"),
     "deploy", "medium"),
    # assign/close/approve: the §14/M4 write bug — verbs that read as
    # bookkeeping but mutate state. Encoded here so the heuristic floor
    # covers them; see NEGATIVE_RESULTS.md backlog theme 8.
    (("send", "publish", "notify", "write", "update", "create", "insert",
      "upload", "assign", "close", "approve", "set", "change", "modify",
      "cancel", "book", "exchange"),
     "write", "medium"),
    (("read", "get", "list", "fetch", "query", "search", "view", "describe"),
     "read", "low"),
)


#: Strictness order for the raise-only clamp. Anything outside this map
#: (typos, custom tiers) is never clamped — the engine's own validation
#: owns unknown tiers.
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


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
    floored: dict[str, str] = field(default_factory=dict)
    """Declared metadata clamped UP to the heuristic floor (§14/M4,
    raise-only): key → the floor value that replaced a weaker declaration.
    Recorded, never silent. Empty when nothing was clamped."""

    @property
    def action(self) -> str:
        """The outcome as a string: accept / verify / abstain / escalate."""
        return self.decision.action.value

    @property
    def should_execute(self) -> bool:
        """True only when the outcome is ACCEPT.

        Gate real side effects on this **only** when risk_tier/action_type
        came from a trusted registry — see :attr:`advisory`.
        """
        return self.action == "accept"

    @property
    def advisory(self) -> bool:
        """True when name inference filled governance fields.

        An advisory verdict rests on guessed metadata and must not drive
        real execution (external review 2026-07-29 F-04); resolve the tool's
        registered risk/action and assess again, or route to the
        ``/v1/execution`` path where metadata is resolved server-side.
        """
        return bool(self.inferred)

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

    # Raise-only clamp (§14/M4, NEGATIVE_RESULTS theme 8): a caller may
    # RAISE risk above the deterministic name-heuristic floor, never lower
    # it below. The floor clamps explicit declarations only — unset fields
    # stay unset (the engine fail-closes on them), so infer=False semantics
    # are untouched. Every clamp is recorded in ``floored``; a silent
    # correction is how the assign/close/approve write bug hid.
    floored: dict[str, str] = {}
    floor_type, floor_risk = infer_risk_and_type(name)
    if (
        risk_tier is not None and floor_risk is not None
        and risk_tier in _RISK_ORDER
        and _RISK_ORDER[risk_tier] < _RISK_ORDER[floor_risk]
    ):
        risk_tier = floor_risk
        floored["risk_tier"] = floor_risk
    if (
        action_type == "read" and floor_type is not None and floor_type != "read"
    ):
        action_type = floor_type
        floored["action_type"] = floor_type

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
        floored=floored,
    )


def what_if_tool_call(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    risk_tier: str | None = None,
    action_type: str | None = None,
    target_environment: str = "prod",
    trust_score: float | None = None,
    phase: str | None = None,
    infer: bool = False,
    target: str = "accept",
    max_depth: int = 4,
    max_evaluations: int = 20_000,
    engine: RemoraDecisionEngine | None = None,
) -> tuple[ToolCallAssessment, WhatIfReport]:
    """Assess one tool call, then ask what would have to change to reach *target*.

    The library form of ``remora whatif``. Builds the observation exactly as
    :func:`assess_tool_call` does (same inference, same raise-only clamp, same
    admission firewall) and hands it to :func:`remora.policy.whatif.what_if`.
    Returns the assessment and the what-if report together so the caller can
    show the verdict and the path in one place.

    *target* is ``"accept"`` (what autonomy would take) or ``"verify"`` (what
    would put an ABSTAINed call in front of a person). The report is an
    analysis, not a grant: it names facts, and only establishing them and
    assessing again yields the verdict.
    """
    from remora.policy.whatif import what_if

    assessment = assess_tool_call(
        name, arguments,
        risk_tier=risk_tier, action_type=action_type,
        target_environment=target_environment, trust_score=trust_score,
        phase=phase, infer=infer,
    )
    report = what_if(
        assessment.decision.raw_observation, engine,
        target=DecisionAction(target), max_depth=max_depth,
        max_evaluations=max_evaluations,
    )
    return assessment, report
