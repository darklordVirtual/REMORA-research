# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Put the question set to a provider and admit the answers as signals.

This is the one place provider output meets a policy observation, and every
route it takes is either a model-signal write through :func:`project` or a
narrowing write through :func:`project_narrowing`. There is no third route.

How each answer is admitted
---------------------------

``intent_match`` and ``target_matches_request``
    Both above their thresholds, and ``scope_drift`` below its own: the
    observation gains ``evidence_action="answer"`` with
    ``evidence_confidence`` set to the smaller of the two probabilities. That
    is the engine's evidence-supported path, and under the execution profile
    it reaches VERIFY, never ACCEPT. Either below threshold, or drift above:
    nothing is written. A withheld favourable signal is how a provider says
    no; it never writes an unfavourable label the engine could misread.

``possible_injection``
    Above its threshold: ``adversarial_detected`` is raised, and the
    deterministic hard block escalates. This is the one narrowing write, and
    it can only raise the flag.

``action_reversibility`` and ``semantic_risk``
    Recorded in the evidence and **not** projected. The observation has no
    model-signal field for them, and the fields that look right,
    ``risk_tier`` and ``rollback_available``, are deployment facts. They exist
    in the evidence so a calibration study can compare them against the
    deployment's own classification, which is the study that has to happen
    before either could be trusted for anything.

Failure is structural, not configured. A provider that cannot answer leaves
the observation exactly as it was, and the engine then makes the deterministic
decision. Because a provider can only add a favourable model signal or raise a
safety flag, the decision without the provider is never more permissive than
the decision with it. No per-tier failure table is needed, and none is
offered, because a table would be a place to configure a fail-open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from remora.decision_providers import (
    DecisionEvidence,
    DecisionProvider,
    DecisionProviderError,
    DecisionQuestion,
    project,
    project_narrowing,
)
from remora.decision_providers.questions import (
    QUESTION_SET_VERSION,
    REMORA_QUESTIONS_V1,
)

__all__ = [
    "Enrichment",
    "SemanticThresholds",
    "enrich",
    "semantic_state",
]

#: Keys that must never reach a provider, matched case-insensitively as
#: substrings. A provider needs meaning, not credentials.
_SECRET_KEY = re.compile(
    r"(secret|token|password|passwd|credential|api[_-]?key|private[_-]?key"
    r"|authorization|cookie|session)",
    re.IGNORECASE,
)


def semantic_state(
    *,
    intent: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The minimised state a provider is shown.

    Only the fields a semantic question needs: the stated intent, the tool
    name, the arguments, and any declared context. A key whose name suggests
    a credential is refused rather than redacted, so a caller cannot ship a
    secret by mistake and discover it in a provider's logs.
    """
    offending = sorted(
        str(key)
        for source in (arguments, context or {})
        for key in source
        if _SECRET_KEY.search(str(key))
    )
    if offending:
        raise ValueError(
            f"refusing to send credential-shaped keys to a decision provider: {offending}"
        )
    state: dict[str, Any] = {
        "intent": intent,
        "tool_name": tool_name,
        "arguments": dict(arguments),
    }
    if context:
        state["context"] = dict(context)
    return state


@dataclass(frozen=True, slots=True)
class SemanticThresholds:
    """Where each probability is cut. No defaults, by design.

    A threshold is a calibrated policy decision. Giving it a default here would
    make the most consequential number in the integration the one nobody
    reviewed. Calibrate against a corpus in the deployment's language, record
    the corpus hash, and construct this from configuration.
    """

    intent_match: float
    target_matches_request: float
    possible_injection: float
    scope_drift: float

    def __post_init__(self) -> None:
        for name in (
            "intent_match",
            "target_matches_request",
            "possible_injection",
            "scope_drift",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} threshold must be in [0, 1], got {value}")


Outcome = Literal["signals_applied", "signals_withheld", "provider_unavailable"]


@dataclass(frozen=True, slots=True)
class Enrichment:
    """What :func:`enrich` did, for the record."""

    observation: Any
    evidence: DecisionEvidence | None
    outcome: Outcome
    #: Human-readable account of each admission decision, for the audit line.
    notes: tuple[str, ...]


def _probability(evidence: DecisionEvidence, question_id: str) -> float | None:
    answer = evidence.answer(question_id)
    if answer is None or isinstance(answer.value, bool):
        return None
    if not isinstance(answer.value, (int, float)):
        return None
    return float(answer.value)


def enrich(
    observation: Any,
    provider: DecisionProvider,
    *,
    state: Mapping[str, Any],
    thresholds: SemanticThresholds,
    questions: Sequence[DecisionQuestion] = REMORA_QUESTIONS_V1,
    timeout_s: float = 2.0,
) -> Enrichment:
    """Ask, then admit. Returns a new observation; the input is untouched."""
    try:
        evidence = provider.evaluate(state=state, questions=questions, timeout_s=timeout_s)
    except DecisionProviderError as exc:
        return Enrichment(
            observation=observation,
            evidence=None,
            outcome="provider_unavailable",
            notes=(f"provider unavailable: {exc}; deterministic decision stands",),
        )

    notes: list[str] = [
        f"question_set={evidence.question_set_version} model={evidence.resolved_model}"
    ]
    if questions is REMORA_QUESTIONS_V1 and evidence.question_set_version != QUESTION_SET_VERSION:
        notes.append(
            f"provider reports question set {evidence.question_set_version!r}; "
            f"thresholds were calibrated for {QUESTION_SET_VERSION!r}"
        )

    injection = _probability(evidence, "possible_injection")
    if injection is not None and injection >= thresholds.possible_injection:
        updated = project_narrowing(observation, {"adversarial_detected": True})
        notes.append(f"possible_injection={injection:.2f} raised adversarial_detected")
        return Enrichment(updated, evidence, "signals_applied", tuple(notes))

    intent = _probability(evidence, "intent_match")
    target = _probability(evidence, "target_matches_request")
    drift = _probability(evidence, "scope_drift")

    favourable = (
        intent is not None
        and target is not None
        and intent >= thresholds.intent_match
        and target >= thresholds.target_matches_request
        and (drift is None or drift < thresholds.scope_drift)
    )
    if favourable:
        confidence = min(intent, target)  # type: ignore[type-var]
        updated = project(
            observation, {"evidence_action": "answer", "evidence_confidence": confidence}
        )
        notes.append(
            f"intent_match={intent:.2f} target_matches_request={target:.2f} "
            f"admitted as evidence_confidence={confidence:.2f}"
        )
        return Enrichment(updated, evidence, "signals_applied", tuple(notes))

    notes.append(
        "favourable signal withheld: "
        f"intent_match={intent} target_matches_request={target} scope_drift={drift}"
    )
    return Enrichment(observation, evidence, "signals_withheld", tuple(notes))
