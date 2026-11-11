# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""In-process policy decision (PDP) for embedding REMORA without a server.

A host that drives REMORA in one process — a simulator, a benchmark, a shadow
comparison — needs a stable, deterministic way to get the gate's verdict on a
proposed action. :func:`evaluate_policy` is the policy decision point as a
**pure function** of the observation (and any external caps): the engine reads
no wall clock and no random source, so the same observation always yields the
same :class:`GateDecision`. That is what makes an embedding host reproducible.

This is the policy decision **only**. It is NOT an authorization grant. A real
write still goes through the governed execution path (assess, a signed
single-use token, execute, effect verification), where one-time consumption,
cumulative limits, the custody split and the audit chain apply. Embedding this
function does not move authority out of that path; it exposes the decision the
path also computes, for a host that must decide in-process and deterministically.

Build the observation from premises the host has verified itself. A field the
agent merely asserts is not evidence, and the engine treats an ungrounded
critical action conservatively (it is held for a human or abstained, never
auto-approved).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from remora.policy.observation import PolicyObservation
from remora.policy.report import DecisionAction

if TYPE_CHECKING:
    from remora.policy.decision_engine import RemoraDecisionEngine


class GateVerdict(str, Enum):
    """The four-way verdict a host acts on.

    ALLOW, VERIFY and ABSTAIN come from the policy decision. DENY is a
    host-side mapping of a governed refusal with no approvable path (see
    :meth:`GateDecision.deny`); the pure policy decision never fabricates it.
    """

    ALLOW = "allow"
    DENY = "deny"
    VERIFY = "verify"
    ABSTAIN = "abstain"


#: The decision action to verdict mapping. ESCALATE folds into VERIFY: both
#: route to a human, and the higher bar is carried by ``escalated``.
_ACTION_VERDICT = {
    DecisionAction.ACCEPT: GateVerdict.ALLOW,
    DecisionAction.VERIFY: GateVerdict.VERIFY,
    DecisionAction.ESCALATE: GateVerdict.VERIFY,
    DecisionAction.ABSTAIN: GateVerdict.ABSTAIN,
}


def verdict_for_action(action: DecisionAction) -> GateVerdict:
    """Map a :class:`DecisionAction` to a :class:`GateVerdict`.

    The policy decision never yields DENY: an outright refusal with no
    approvable path is a hard-guard outcome of the governed execution path (a
    typed refusal / 4xx), which a host maps with :meth:`GateDecision.deny`.
    """
    try:
        return _ACTION_VERDICT[action]
    except KeyError:  # pragma: no cover - the enum has exactly these members
        raise ValueError(f"unmapped decision action: {action!r}") from None


@dataclass(frozen=True)
class GateDecision:
    """One policy decision, as a host reads it.

    ``action`` is REMORA's own decision action, kept for fidelity;
    ``verdict`` is the four-way mapping. ``escalated`` is True when the action
    was ESCALATE (a higher approval bar than a plain VERIFY).
    """

    verdict: GateVerdict
    action: DecisionAction
    reasons: tuple[str, ...]
    escalated: bool
    human_review_required: bool
    evidence_required: bool
    explanation: str = ""
    resolution_plan: Any = None

    @classmethod
    def deny(cls, reasons: Sequence[str], *, explanation: str = "") -> "GateDecision":
        """A host-side DENY for a governed refusal with no approvable path.

        Use this to fold a refusal the governed execution path raised (for
        example ``limit_exceeded`` or an intent-scope refusal) into the same
        four-way verdict vocabulary as the policy decision.
        """
        return cls(
            verdict=GateVerdict.DENY,
            action=DecisionAction.ABSTAIN,
            reasons=tuple(reasons),
            escalated=False,
            human_review_required=False,
            evidence_required=False,
            explanation=explanation,
        )


_DEFAULT_ENGINE: "RemoraDecisionEngine | None" = None


def _default_engine() -> "RemoraDecisionEngine":
    # Lazily built with default feature flags, shared, and pure: it reads no
    # clock and no random source, so sharing it changes no result. A host that
    # needs specific flags passes its own engine for reproducibility.
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        from remora.policy.decision_engine import RemoraDecisionEngine

        _DEFAULT_ENGINE = RemoraDecisionEngine()
    return _DEFAULT_ENGINE


def evaluate_policy(
    observation: PolicyObservation,
    *,
    caps: Sequence[Any] = (),
    engine: "RemoraDecisionEngine | None" = None,
) -> GateDecision:
    """The policy decision for *observation*, as a pure, deterministic call.

    Pass ``engine`` to pin specific feature flags; otherwise a shared engine
    with default flags is used. ``caps`` are external monitor or control-
    protocol results; a cap can route a decision down (to VERIFY or ABSTAIN)
    but never up, exactly as on the governed path.
    """
    report = (engine or _default_engine()).decide(observation, caps=tuple(caps))
    return GateDecision(
        verdict=verdict_for_action(report.action),
        action=report.action,
        reasons=tuple(r.value for r in report.reasons),
        escalated=report.action is DecisionAction.ESCALATE,
        human_review_required=bool(report.human_review_required),
        evidence_required=bool(report.evidence_required),
        explanation=report.explanation,
        resolution_plan=report.resolution_plan,
    )
