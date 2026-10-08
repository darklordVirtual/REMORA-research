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

``possible_injection`` (V1), or any V2 or V2.1 injection question
    At or above the ``possible_injection`` threshold: ``adversarial_detected``
    is raised, and the deterministic hard block escalates. This is the one
    narrowing write, and it can only raise the flag. V2 asks three narrower
    injection questions; the largest answer is the one compared, so splitting
    the question can only add ways to raise the flag.

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

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from remora.decision_providers import (
    DecisionEvidence,
    DecisionProvider,
    DecisionQuestion,
    project,
    project_narrowing,
)
from remora.decision_providers.questions import (
    INJECTION_QUESTIONS_V2,
    INJECTION_QUESTIONS_V2_1,
    QUESTION_SET_VERSION,
    QUESTION_SET_VERSION_V2,
    QUESTION_SET_VERSION_V2_1,
    REMORA_QUESTIONS_V1,
    REMORA_QUESTIONS_V2,
    REMORA_QUESTIONS_V2_1,
)

__all__ = [
    "Enrichment",
    "SemanticThresholds",
    "enrich",
    "semantic_state",
    "semantic_state_v2",
]

#: Every question id whose answer is admitted as injection evidence.
_INJECTION_IDS: tuple[str, ...] = tuple(
    dict.fromkeys(("possible_injection", *INJECTION_QUESTIONS_V2, *INJECTION_QUESTIONS_V2_1))
)

#: The version each shipped question set was published under.
_SHIPPED_SETS = (
    (REMORA_QUESTIONS_V1, QUESTION_SET_VERSION),
    (REMORA_QUESTIONS_V2, QUESTION_SET_VERSION_V2),
    (REMORA_QUESTIONS_V2_1, QUESTION_SET_VERSION_V2_1),
)

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
    secret by mistake and discover it in a provider's logs. The check reaches
    every depth, and the state must stay inside the JSON domain and the egress
    bounds (``EGRESS_MAX_*``), or it is refused.
    """
    _refuse_credentials(arguments, context or {})
    state: dict[str, Any] = {
        "intent": intent,
        "tool_name": tool_name,
        "arguments": dict(arguments),
    }
    if context:
        state["context"] = dict(context)
    _check_egress(state)
    return state


#: Bounds on what may leave the process (issue #753). Generous for a tool call
#: and its context, tight enough that a provider never receives an unbounded
#: payload. A state outside them is refused, never trimmed: trimming would change
#: the meaning of the question the provider is asked.
EGRESS_MAX_DEPTH = 16
EGRESS_MAX_ITEMS = 1_000
EGRESS_MAX_TEXT = 16_384
EGRESS_MAX_BYTES = 65_536


def _refuse_credentials(*sources: Mapping[str, Any]) -> None:
    """Refuse a credential-shaped key at any depth, inside objects and lists."""
    offending: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                where = f"{path}.{key}" if path else str(key)
                if _SECRET_KEY.search(str(key)):
                    offending.append(where)
                walk(child, where)
        elif isinstance(value, (list, tuple)):
            for i, child in enumerate(value):
                walk(child, f"{path}[{i}]")

    for source in sources:
        walk(source, "")
    if offending:
        raise ValueError(
            f"refusing to send credential-shaped keys to a decision provider: {sorted(offending)}"
        )


def _check_egress(state: Mapping[str, Any]) -> None:
    """Refuse a state outside the JSON domain or the egress bounds."""

    def walk(value: Any, depth: int, path: str) -> None:
        if depth > EGRESS_MAX_DEPTH:
            raise ValueError(f"refusing to send state nested deeper than {EGRESS_MAX_DEPTH} at {path}")
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, int):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"refusing to send a non-finite number at {path}")
            return
        if isinstance(value, str):
            if len(value) > EGRESS_MAX_TEXT:
                raise ValueError(
                    f"refusing to send text longer than {EGRESS_MAX_TEXT} characters at {path}")
            return
        if isinstance(value, Mapping):
            if len(value) > EGRESS_MAX_ITEMS:
                raise ValueError(f"refusing to send more than {EGRESS_MAX_ITEMS} entries at {path}")
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"refusing to send a non-string key at {path}")
                walk(child, depth + 1, f"{path}.{key}" if path else key)
            return
        if isinstance(value, (list, tuple)):
            if len(value) > EGRESS_MAX_ITEMS:
                raise ValueError(f"refusing to send more than {EGRESS_MAX_ITEMS} items at {path}")
            for i, child in enumerate(value):
                walk(child, depth + 1, f"{path}[{i}]")
            return
        raise ValueError(
            f"refusing to send a {type(value).__name__} at {path}: only JSON values leave the process")

    walk(state, 0, "")
    size = len(json.dumps(state, ensure_ascii=False).encode("utf-8"))
    if size > EGRESS_MAX_BYTES:
        raise ValueError(f"refusing to send {size} bytes of state; the bound is {EGRESS_MAX_BYTES}")


def semantic_state_v2(
    *,
    operator_request: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    tool_description: str | None = None,
    untrusted_content: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The state :data:`REMORA_QUESTIONS_V2` is written against.

    Each part has a name the questions refer to. ``operator_request`` is the
    trusted task. ``proposed_call`` is what the agent wants to run, with the
    tool's own description when there is one (take it from the signed
    ToolSpec, not from the agent). ``untrusted_content`` holds text that came
    from outside the operator, such as ticket bodies, customer messages or
    tool output; the injection questions judge only that and the free-text
    arguments. Keeping the two apart is what lets the operator's imperative
    request stay out of the injection question.

    Credential-shaped keys are refused, as in :func:`semantic_state`.
    """
    _refuse_credentials(arguments, untrusted_content or {})
    call: dict[str, Any] = {"tool": tool_name, "arguments": dict(arguments)}
    if tool_description:
        call["tool_description"] = tool_description
    state: dict[str, Any] = {"operator_request": operator_request, "proposed_call": call}
    if untrusted_content:
        state["untrusted_content"] = dict(untrusted_content)
    _check_egress(state)
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
    probability = float(answer.value)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        return None
    return probability


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
    except Exception as exc:  # noqa: BLE001 - any provider failure leaves the observation unchanged
        return Enrichment(
            observation=observation,
            evidence=None,
            outcome="provider_unavailable",
            notes=(
                f"provider unavailable: {type(exc).__name__}: {exc}; "
                "deterministic decision stands",
            ),
        )

    notes: list[str] = [
        f"question_set={evidence.question_set_version} model={evidence.resolved_model}"
    ]
    for shipped, version in _SHIPPED_SETS:
        if questions is shipped and evidence.question_set_version != version:
            notes.append(
                f"provider reports question set {evidence.question_set_version!r}; "
                f"thresholds were calibrated for {version!r}"
            )

    injections = [
        (question_id, value)
        for question_id in _INJECTION_IDS
        if (value := _probability(evidence, question_id)) is not None
    ]
    if injections:
        question_id, injection = max(injections, key=lambda pair: pair[1])
        if injection >= thresholds.possible_injection:
            updated = project_narrowing(observation, {"adversarial_detected": True})
            notes.append(f"{question_id}={injection:.2f} raised adversarial_detected")
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
