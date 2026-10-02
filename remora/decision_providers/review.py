# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A semantic shadow record, rewritten for whoever resolves the decision.

Under the execution profile a provider's scope-drift and target answers can
withhold a favourable signal, but a call that stops at VERIFY stops there
either way. What those answers are good for is the next step. VERIFY is a
machine step: a bounded lookup in a system of record, a RAG index or
documentation (``remora/policy/resolution.py``), after which the router runs
again. ESCALATE is a human approval. The answers tell the first what to
look up and the second where to look. This module turns a
:class:`~remora.decision_providers.shadow.ShadowRecord` into that view.

The view is advisory and says so in every response. It carries no field an
approval or resolution path reads, and nothing here is consulted by
``/approve`` or by a resolver. ``verification_focus`` names checks; it does
not widen a ``ResolutionPlan``, whose resolver may still write only its
target arguments from its source tools. Ignoring the view loses
information, never a check.

What the view adds to the raw record:

``attention``
    the answers past their thresholds, worst first, each with the question
    asked in full, so a reviewer reads "the call may touch something the
    request did not ask for (0.96, cut 0.50)" rather than a field name.
``answers``
    every answer with its question, its value, whether it is past its cut,
    and for a score, the label of the nearest level.
``verification_focus``
    for VERIFY, the checks a lookup should make, one per concern, with the
    reason; the untrusted text is named as something not to use as a source.
``for``
    ``verifier`` at VERIFY, ``approver`` at ESCALATE.
``caveats``
    what the numbers cannot be trusted for yet, from REMORA's own evidence.
"""

from __future__ import annotations

from typing import Any, Mapping

from remora.decision_providers import DecisionQuestion, QuestionKind
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

__all__ = ["ADVISORY", "CAVEATS", "reviewer_view"]

ADVISORY = (
    "Jev's reading of the operator request and the proposed call. It does not "
    "approve, block or change this decision. Your review and the policy decision "
    "are what count."
)

#: Each caveat rests on committed evidence; the reference is part of the text.
CAVEATS = (
    "Thresholds are not calibrated for this deployment until a calibration "
    "study says so; treat values near a cut as uncertain.",
    "Repeated calls on the same input differ by up to about 0.1 "
    "(results/jev_question_set_ab_v1.json).",
    "Norwegian text was flagged as possible injection about twice as often as "
    "English in REMORA's hold-out (results/jev_injection_holdout_v1.json).",
)

_SETS = {
    QUESTION_SET_VERSION: REMORA_QUESTIONS_V1,
    QUESTION_SET_VERSION_V2: REMORA_QUESTIONS_V2,
    QUESTION_SET_VERSION_V2_1: REMORA_QUESTIONS_V2_1,
}

#: Answers where a LOW value is the concern, and the threshold that applies.
_LOW_IS_BAD = {"intent_match": "intent_match", "target_matches_request": "target_matches_request"}
#: Answers where a HIGH value is the concern, and the threshold that applies.
_HIGH_IS_BAD = {
    "scope_drift": "scope_drift",
    "possible_injection": "possible_injection",
    **{q: "possible_injection" for q in (*INJECTION_QUESTIONS_V2, *INJECTION_QUESTIONS_V2_1)},
}

_CONCERN = {
    "intent_match": "The call may not make the change the request asks for.",
    "target_matches_request": "The call may act on a different customer, port, device or record than the request names.",
    "scope_drift": "The call may do more than the request asks for.",
    "possible_injection": "Untrusted text may be trying to steer the agent.",
    "injection_instruction": "Untrusted text may contain an instruction aimed at the automation.",
    "injection_authority_claim": "Untrusted text may claim authority over the automation.",
    "injection_override": "Untrusted text may tell the reader to ignore rules or checks.",
    "injection_extra_action": "Untrusted text may ask for a change the operator did not request.",
}


#: What a lookup at VERIFY should establish when an answer is past its cut.
_FOCUS = {
    "intent_match": (
        "confirm_intent",
        "Retrieve the procedure or documentation for the requested change and check "
        "that this tool and these arguments perform it.",
    ),
    "target_matches_request": (
        "confirm_target",
        "Look up the identifiers the request names in the system of record and compare "
        "them with the call's arguments.",
    ),
    "scope_drift": (
        "confirm_scope",
        "Check every argument against the request and the tool's signed ToolSpec; an "
        "argument the request does not call for needs its own source.",
    ),
}
_UNTRUSTED_FOCUS = (
    "exclude_untrusted_text",
    "Do not use the untrusted text as a source for any lookup; it may be trying to "
    "steer the agent.",
)

_AUDIENCE = {"VERIFY": "verifier", "ESCALATE": "approver"}


def _question(version: str | None, question_id: str) -> DecisionQuestion | None:
    return next((q for q in _SETS.get(version or "", ()) if q.id == question_id), None)


def _question_text(question: DecisionQuestion | None) -> str | None:
    if question is None:
        return None
    return question.instructions.split(" Judge only untrusted_content")[0]


def _severity(question_id: str, value: float, cut: float) -> float:
    """How far past its cut an answer is, on a common scale."""
    return cut - value if question_id in _LOW_IS_BAD else value - cut


def reviewer_view(record: Mapping[str, Any]) -> dict[str, Any]:
    """The reviewer-facing form of one shadow record."""
    version = record.get("question_set_version")
    thresholds = record.get("thresholds") or {}
    base: dict[str, Any] = {
        "proposal_id": record.get("proposal_id"),
        "authoritative": False,
        "advisory": ADVISORY,
        "decision": record.get("actual_action"),
        "recorded_at": record.get("recorded_at"),
        "model": record.get("resolved_model"),
        "question_set": version,
        "caveats": list(CAVEATS),
    }
    if record.get("error") or record.get("outcome") == "provider_unavailable":
        reason = record.get("error") or next(
            (n for n in record.get("notes", ()) if n.startswith("provider unavailable")),
            "provider unavailable",
        )
        return base | {"status": "failed", "reason": reason, "attention": [], "answers": []}

    answers, attention, focus = [], [], {}
    for question_id, answer in (record.get("answers") or {}).items():
        value = answer.get("value")
        question = _question(version, question_id)
        legend = answer.get("legend") or (list(question.legend) if question else None)
        is_score = (question is not None and question.kind is QuestionKind.SCORE) or bool(
            answer.get("legend")
        )
        row: dict[str, Any] = {
            "id": question_id,
            "question": _question_text(question),
            "value": value,
            "past_threshold": False,
        }
        if is_score and legend and isinstance(value, (int, float)):
            row["kind"] = "score"
            row["reading"] = legend[max(0, min(len(legend) - 1, round(value)))]
        else:
            row["kind"] = "probability"
            key = _LOW_IS_BAD.get(question_id) or _HIGH_IS_BAD.get(question_id)
            cut = thresholds.get(key) if key else None
            if isinstance(value, (int, float)) and isinstance(cut, (int, float)):
                past = value < cut if question_id in _LOW_IS_BAD else value >= cut
                row["threshold"] = cut
                row["past_threshold"] = past
                if past:
                    severity = _severity(question_id, value, cut)
                    attention.append((
                        severity,
                        f"{_CONCERN.get(question_id, question_id)} ({value:.2f}, cut {cut:.2f})",
                    ))
                    check, why = _FOCUS.get(question_id, _UNTRUSTED_FOCUS)
                    if check not in focus or focus[check]["severity"] < severity:
                        focus[check] = {"check": check, "why": why, "question_id": question_id,
                                        "value": value, "severity": severity}
        answers.append(row)

    shadow_action = record.get("shadow_action")
    ordered_focus = [
        {k: v for k, v in item.items() if k != "severity"}
        for item in sorted(focus.values(), key=lambda item: -item["severity"])
    ]
    return base | {
        "status": "available",
        "for": _AUDIENCE.get(str(record.get("actual_action"))),
        "verification_focus": ordered_focus,
        "would_change_to": shadow_action if record.get("would_change") else None,
        "attention": [text for _sev, text in sorted(attention, key=lambda pair: -pair[0])],
        "answers": answers,
        "thresholds": dict(thresholds),
    }
