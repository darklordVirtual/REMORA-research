# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""AI-control resolution protocols for VERIFY decisions (RF-04, slice 1).

Library-only and flag-gated: nothing in the decision path imports this module
yet, and it is disabled unless ``REMORA_CONTROL_PROTOCOLS`` is set truthy.
Design and the frozen pre-registered decision rule for the future offline
re-scoring live in ``docs/research/verify_control_protocols.md``.

The status quo (REM-032/REM-033, ``remora/governance/review_queue.py``): every
VERIFY awaits a human, TTL expiry resolves to ABSTAIN — never auto-accept,
never indefinite silent pending. The AI-control literature (Greenblatt et al.
2024, arXiv:2312.06942; Bhatt et al. 2025, arXiv:2504.10374) resolves the
resulting benign-utility corner with interventions instead of terminal review:
defer-to-trusted, trusted editing, defer-to-resample. This module encodes
those strategies as a deterministic resolution function over *trusted
verdicts*. The "trusted model" role is played by the deterministic policy
layer — the module only consumes :class:`TrustedVerdict` values, it never
calls models.

Safety invariants, enforced in code (not just tests):

(a) **VERIFY-only scope** — a non-VERIFY decision passes through unchanged;
    the protocol can never weaken a hard block or an ESCALATE.
(b) **Flag-gated status quo** — with ``enabled=False`` (or the SEEK_EVIDENCE
    strategy) the resolution is the status-quo route to human review,
    represented as ESCALATE.
(c) **Monitored accept is earned** — MONITORED_ACCEPT requires a non-status-quo
    strategy, unanimous trusted approval (unanimity over an empty verdict set
    is not approval), at least ``resample_k`` verdicts for DEFER_TO_RESAMPLE,
    and remaining audit budget; anything less resolves ESCALATE.
(d) **Budget exhaustion is loud** — an exhausted audit budget resolves
    ESCALATE with the budget state recorded, never a silent accept.
(e) **Adaptive-attack guard** — for DEFER_TO_RESAMPLE, a monotonically
    non-increasing suspicion sequence spanning more than ``resample_k``
    verdicts (the suspiciousness-suppression pattern, arXiv:2510.09462)
    resolves ESCALATE even when every verdict approves.

Channel separation (arXiv:2510.09462, arXiv:2605.26047): the agent-visible
field is ``agent_message`` alone — a fixed neutral sentence carrying no
monitor scores, no rule identifiers, no strategy names. Everything else goes
to ``audit_detail``, the internal audit channel.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from remora.policy.report import DecisionAction


class VerifyStrategy(str, Enum):
    """How a VERIFY decision may be resolved.

    SEEK_EVIDENCE is the status quo: pass through to the review queue.
    The remaining strategies are the AI-control interventions.
    """

    SEEK_EVIDENCE = "seek_evidence"
    DEFER_TO_TRUSTED = "defer_to_trusted"
    TRUSTED_EDIT = "trusted_edit"
    DEFER_TO_RESAMPLE = "defer_to_resample"


class VerifyResolution(str, Enum):
    """Terminal resolution of a VERIFY under a control protocol.

    There is deliberately NO plain ACCEPT: the least severe outcome a control
    protocol can grant is MONITORED_ACCEPT — execution under audit, spending
    audit budget. ABSTAIN exists for vocabulary parity with the review queue's
    TTL-expiry resolution; :func:`resolve_verify` itself never emits it.
    """

    MONITORED_ACCEPT = "monitored_accept"
    ESCALATE = "escalate"
    ABSTAIN = "abstain"


# Agent-visible sentences — the ONLY strings resolve_verify ever places on the
# agent channel. Fixed and neutral by design: no digits, no monitor scores, no
# rule identifiers, no strategy names, no diff of what would have passed. All
# ESCALATE paths share ONE sentence so the agent cannot distinguish a
# disapproval from an exhausted budget from the adaptive-attack guard.
AGENT_MESSAGE_PROCEED = "The requested action may proceed."
AGENT_MESSAGE_REVIEW = (
    "The requested action requires further review before it can proceed."
)
AGENT_MESSAGE_UNCHANGED = "The requested action keeps its original decision."

AGENT_MESSAGES = frozenset(
    {AGENT_MESSAGE_PROCEED, AGENT_MESSAGE_REVIEW, AGENT_MESSAGE_UNCHANGED}
)


def _env_enabled() -> bool:
    """Parse ``REMORA_CONTROL_PROTOCOLS`` with the repo's boolean-string
    convention (mirrors ``PolicyObservation.from_json_record``)."""
    raw = os.environ.get("REMORA_CONTROL_PROTOCOLS", "")
    return raw.strip().lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class TrustedVerdict:
    """One verdict from the trusted (deterministic policy-layer) monitor.

    ``suspicion`` is the monitor's suspicion score in [0, 1]; ``source``
    identifies which deterministic gate produced the verdict (audit
    correlation only — it is never shown to the agent).
    """

    approved: bool
    suspicion: float
    source: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.suspicion <= 1.0:
            raise ValueError(
                f"suspicion must be within [0, 1]; got {self.suspicion}"
            )


@dataclass
class ControlProtocolConfig:
    """Configuration for one control-protocol session/window.

    ``audit_budget`` caps MONITORED_ACCEPTs per session/window; ``audit_spent``
    is the mutable counter :func:`resolve_verify` increments on each grant
    (its only side effect). ``enabled`` defaults to the
    ``REMORA_CONTROL_PROTOCOLS`` environment flag so the module stays inert
    unless explicitly switched on.
    """

    strategy: VerifyStrategy = VerifyStrategy.SEEK_EVIDENCE
    audit_budget: int = 10
    resample_k: int = 3
    enabled: bool = field(default_factory=_env_enabled)
    audit_spent: int = 0

    def __post_init__(self) -> None:
        if self.audit_budget < 0:
            raise ValueError(f"audit_budget must be >= 0; got {self.audit_budget}")
        if self.resample_k < 1:
            raise ValueError(f"resample_k must be >= 1; got {self.resample_k}")
        if self.audit_spent < 0:
            raise ValueError(f"audit_spent must be >= 0; got {self.audit_spent}")

    @property
    def budget_remaining(self) -> int:
        return max(self.audit_budget - self.audit_spent, 0)


@dataclass(frozen=True)
class ControlProtocolResult:
    """Resolution of one decision through the control protocol.

    ``agent_message`` is the ONLY agent-visible field (always drawn from
    ``AGENT_MESSAGES``); ``audit_detail`` is the internal audit channel.
    """

    resolution: DecisionAction | VerifyResolution
    audit_detail: dict
    agent_message: str


def _budget_state(config: ControlProtocolConfig) -> dict:
    return {
        "audit_budget": config.audit_budget,
        "audit_spent": config.audit_spent,
        "remaining": config.budget_remaining,
    }


def _audit_detail(
    reason: str,
    config: ControlProtocolConfig,
    observation_summary: dict,
    verdicts: Sequence[TrustedVerdict] | None = None,
    *,
    adaptive_guard_triggered: bool = False,
) -> dict:
    """Internal-channel record. ``verdicts=None`` means the path did not
    consult verdicts (passthrough / status quo), keeping those results
    verdict-independent by construction."""
    detail: dict = {
        "reason": reason,
        "strategy": config.strategy.value,
        "enabled": config.enabled,
        "budget": _budget_state(config),
        "adaptive_guard_triggered": adaptive_guard_triggered,
        "observation_summary": dict(observation_summary),
    }
    if verdicts is not None:
        approved = sum(1 for v in verdicts if v.approved)
        detail["verdicts"] = {
            "total": len(verdicts),
            "approved": approved,
            "disapproved": len(verdicts) - approved,
            "sources": [v.source for v in verdicts],
        }
    return detail


def resolve_verify(
    decision_action: DecisionAction,
    observation_summary: dict,
    trusted_verdicts: Sequence[TrustedVerdict],
    config: ControlProtocolConfig,
) -> ControlProtocolResult:
    """Resolve one decision through the configured control protocol.

    Enforces invariants (a)–(e) from the module docstring: (a)–(c) first,
    then the adaptive-attack guard (e) before the budget check (d), so a
    suppression pattern is recorded as such even when the budget is also
    exhausted. The only mutation is ``config.audit_spent += 1`` on a
    MONITORED_ACCEPT grant.

    Parameters
    ----------
    decision_action:
        The engine's decision. Anything but VERIFY passes through unchanged.
    observation_summary:
        Caller-provided summary of the observation (e.g. ``tool_call_hash``),
        recorded verbatim on the audit channel for correlation.
    trusted_verdicts:
        Verdicts from the deterministic trusted monitor, in emission order
        (order is load-bearing for the adaptive-attack guard).
    config:
        Session/window configuration, including the mutable audit budget.
    """
    # (a) VERIFY-only scope: never touch a hard block, an ESCALATE, an
    # ABSTAIN, or an ACCEPT the engine already granted.
    if decision_action != DecisionAction.VERIFY:
        return ControlProtocolResult(
            resolution=decision_action,
            audit_detail=_audit_detail(
                "non_verify_passthrough", config, observation_summary
            ),
            agent_message=AGENT_MESSAGE_UNCHANGED,
        )

    # (b) Flag-gated status quo: disabled, or SEEK_EVIDENCE, routes to human
    # review exactly as today — represented as ESCALATE. Verdicts are not
    # consulted, so the result is verdict-independent by construction.
    if not config.enabled:
        return ControlProtocolResult(
            resolution=VerifyResolution.ESCALATE,
            audit_detail=_audit_detail(
                "protocols_disabled", config, observation_summary
            ),
            agent_message=AGENT_MESSAGE_REVIEW,
        )
    if config.strategy is VerifyStrategy.SEEK_EVIDENCE:
        return ControlProtocolResult(
            resolution=VerifyResolution.ESCALATE,
            audit_detail=_audit_detail(
                "seek_evidence_status_quo", config, observation_summary
            ),
            agent_message=AGENT_MESSAGE_REVIEW,
        )

    def _escalate(reason: str, *, guard: bool = False) -> ControlProtocolResult:
        return ControlProtocolResult(
            resolution=VerifyResolution.ESCALATE,
            audit_detail=_audit_detail(
                reason, config, observation_summary, trusted_verdicts,
                adaptive_guard_triggered=guard,
            ),
            agent_message=AGENT_MESSAGE_REVIEW,
        )

    # (c) Monitored accept is earned: unanimity over an empty verdict set is
    # not approval (fail closed), and any single disapproval escalates.
    if not trusted_verdicts:
        return _escalate("no_trusted_verdicts")
    if not all(v.approved for v in trusted_verdicts):
        return _escalate("verdict_disapproval")

    if config.strategy is VerifyStrategy.DEFER_TO_RESAMPLE:
        # (c) resample quorum: fewer than resample_k verdicts is insufficient.
        if len(trusted_verdicts) < config.resample_k:
            return _escalate("insufficient_resamples")
        # (e) adaptive-attack guard (arXiv:2510.09462): a monotonically
        # non-increasing suspicion sequence spanning more than resample_k
        # verdicts is the suppression signature — escalate despite unanimity.
        suspicions = [v.suspicion for v in trusted_verdicts]
        if len(suspicions) > config.resample_k and all(
            later <= earlier for earlier, later in zip(suspicions, suspicions[1:])
        ):
            return _escalate("suspicion_suppression_guard", guard=True)

    # (d) Budget exhaustion is loud: escalate with the budget state recorded.
    if config.budget_remaining <= 0:
        return _escalate("audit_budget_exhausted")

    config.audit_spent += 1
    return ControlProtocolResult(
        resolution=VerifyResolution.MONITORED_ACCEPT,
        audit_detail=_audit_detail(
            "monitored_accept_granted", config, observation_summary,
            trusted_verdicts,
        ),
        agent_message=AGENT_MESSAGE_PROCEED,
    )
