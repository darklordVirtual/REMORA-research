# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Evidence-sufficiency inference for bounded synthetic conformance fixtures.

This module does not decide whether REMORA or any external system is secure.
It answers a narrower question: given accepted fixture premises, what property
claim is justified by the observation set?

The three statuses are deliberately separate from runtime outcome and from
whether a test case matched its authored expectation:

    ESTABLISHED      accepted evidence is sufficient for the bounded claim
    VIOLATED         accepted evidence is sufficient to refute the bounded claim
    NOT_ESTABLISHED  the observation set does not distinguish the relevant worlds

The `_accepted` and completeness inputs are trusted synthetic-harness premises.
Production code MUST NOT accept these booleans from an untrusted caller as proof.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class EvidenceStatus(StrEnum):
    ESTABLISHED = "established"
    VIOLATED = "violated"
    NOT_ESTABLISHED = "not_established"


@dataclass(frozen=True)
class EvidenceVerdict:
    claim: str
    status: EvidenceStatus
    reason: str
    scope: Mapping[str, Any]
    missing_evidence: tuple[str, ...] = ()
    decisive_if: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "claim": self.claim,
            "status": self.status.value,
            "reason": self.reason,
            "scope": dict(self.scope),
            "missing_evidence": list(self.missing_evidence),
        }
        if self.decisive_if is not None:
            out["decisive_if"] = self.decisive_if
        return out


_REASON_GUIDANCE: dict[str, tuple[tuple[str, ...], str]] = {
    "execution_observation_unaccepted_or_missing": (
        ("accepted execution/effect observation",),
        "supply an independently accepted observation of the execution or effect",
    ),
    "scope_unaccepted_or_missing": (
        ("accepted bounded scope",),
        "bind the evidence to the authority, tenant, target, operation, attempt and interval",
    ),
    "admission_observation_unaccepted": (
        ("accepted admission observation",),
        "establish provenance and acceptance for the candidate admission record",
    ),
    "candidate_admission_does_not_establish_a_covering_admission": (
        ("covering admission bound to this execution",),
        "supply a candidate admission that joins to the same bounded action context",
    ),
    "admission_presence_unknown": (
        ("admission presence/absence observation",),
        "determine whether a candidate covering admission is present in the observation set",
    ),
    "admission_requirement_not_defined": (
        ("mandatory-admission rule",),
        "state the rule requiring a covering admission for this action class",
    ),
    "observation_window_open": (
        ("finalized observation interval",),
        "close the interval under a stated finalization/watermark rule",
    ),
    "admission_coverage_incomplete": (
        ("complete admission coverage for the bounded scope",),
        "justify capture/export completeness for every admission stream in scope",
    ),
    "route_observation_unaccepted_or_missing": (
        ("accepted alternative-route observation",),
        "supply accepted evidence that the named route was actually exercised",
    ),
    "target_or_operation_not_bound": (
        ("same protected target and operation",),
        "bind the route/control evidence to the same protected operation",
    ),
    "alternative_route_not_established": (
        ("route outside the required PEP",),
        "establish that the tested route is genuinely outside the required enforcement point",
    ),
    "protected_effect_observation_unaccepted": (
        ("accepted protected-effect observation",),
        "supply accepted downstream evidence for the protected effect",
    ),
    "protected_effect_unknown": (
        ("decisive protected-effect observation",),
        "observe whether the protected effect occurred for the named attempt",
    ),
    "no_effect_observation_not_complete": (
        ("complete downstream effect window",),
        "close the downstream observation window before inferring non-occurrence",
    ),
    "valid_control_missing_or_incomparable": (
        ("comparable valid control",),
        "show the same route and operation succeeds when the tested boundary condition is absent",
    ),
    "refusal_not_attributed_to_required_boundary": (
        ("accepted boundary-attribution evidence",),
        "identify the required boundary as the cause of refusal rather than inferring it from 403/no-effect",
    ),
    "readback_unavailable": (
        ("authoritative read-back",),
        "obtain a read-back from the declared observation source",
    ),
    "readback_source_not_accepted": (
        ("accepted read-back source",),
        "establish provenance/trust for the read-back source",
    ),
    "target_or_predicate_not_bound": (
        ("same target and declared postcondition predicate",),
        "bind expected and observed state to the same target and predicate",
    ),
    "readback_stale_or_time_unbound": (
        ("fresh read-back in the declared window",),
        "obtain a fresh observation bound to the declared settlement interval",
    ),
    "declared_settlement_point_not_reached": (
        ("settlement point reached",),
        "wait for the declared deadline/settlement point before appraising the postcondition",
    ),
    "state_value_missing": (
        ("expected state", "observed state"),
        "supply both sides of the declared postcondition comparison",
    ),
}


def _scope(scope: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not scope:
        return {"kind": "synthetic_fixture", "bounded": True}
    return dict(scope)


def _result(
    claim: str,
    status: EvidenceStatus,
    reason: str,
    scope: Mapping[str, Any] | None,
) -> EvidenceVerdict:
    missing: tuple[str, ...] = ()
    decisive_if: str | None = None
    if status is EvidenceStatus.NOT_ESTABLISHED and reason in _REASON_GUIDANCE:
        missing, decisive_if = _REASON_GUIDANCE[reason]
    return EvidenceVerdict(
        claim=claim,
        status=status,
        reason=reason,
        scope=_scope(scope),
        missing_evidence=missing,
        decisive_if=decisive_if,
    )


def _unknown(claim: str, reason: str, scope: Mapping[str, Any] | None) -> EvidenceVerdict:
    return _result(claim, EvidenceStatus.NOT_ESTABLISHED, reason, scope)


def admission_accounting(o: Mapping[str, Any], scope: Mapping[str, Any] | None) -> EvidenceVerdict:
    """Does accepted evidence establish a covering admission for this execution?

    Missing admission evidence is decisive only under an independently justified
    closed-world premise: mandatory admission, finalized window and complete
    admission coverage for the bounded scope.
    """
    claim = "admission_accounting"
    if o.get("effect_source_accepted") is not True or o.get("effect_seen") is not True:
        return _unknown(claim, "execution_observation_unaccepted_or_missing", scope)
    if o.get("scope_accepted") is not True:
        return _unknown(claim, "scope_unaccepted_or_missing", scope)
    if o.get("admission_present") is True:
        if o.get("admission_source_accepted") is not True:
            return _unknown(claim, "admission_observation_unaccepted", scope)
        if o.get("admission_matches") is True:
            return _result(
                claim,
                EvidenceStatus.ESTABLISHED,
                "covering_admission_observed_for_this_execution",
                scope,
            )
        return _unknown(claim, "candidate_admission_does_not_establish_a_covering_admission", scope)
    if o.get("admission_present") is not False:
        return _unknown(claim, "admission_presence_unknown", scope)
    if o.get("mandatory_admission") is not True:
        return _unknown(claim, "admission_requirement_not_defined", scope)
    if o.get("window_finalized") is not True:
        return _unknown(claim, "observation_window_open", scope)
    if o.get("admission_coverage_complete") is not True:
        return _unknown(claim, "admission_coverage_incomplete", scope)
    return _result(
        claim,
        EvidenceStatus.VIOLATED,
        "mandatory_admission_absent_in_complete_bounded_history",
        scope,
    )


def tested_route_enforcement(o: Mapping[str, Any], scope: Mapping[str, Any] | None) -> EvidenceVerdict:
    """Did the named alternative route enforce the required boundary?

    A direct accepted effect outside the required PEP is a counterexample.
    A refusal earns positive credit only with an isolating control, complete
    downstream observation and accepted attribution to the required boundary.
    """
    claim = "tested_route_enforcement"
    if o.get("route_observation_accepted") is not True:
        return _unknown(claim, "route_observation_unaccepted_or_missing", scope)
    if o.get("same_protected_operation") is not True:
        return _unknown(claim, "target_or_operation_not_bound", scope)
    if o.get("outside_required_pep") is not True:
        return _unknown(claim, "alternative_route_not_established", scope)
    if o.get("effect_observation_accepted") is not True:
        return _unknown(claim, "protected_effect_observation_unaccepted", scope)
    if o.get("protected_effect_observed") is True:
        return _result(
            claim,
            EvidenceStatus.VIOLATED,
            "accepted_effect_observed_outside_required_pep",
            scope,
        )
    if o.get("protected_effect_observed") is not False:
        return _unknown(claim, "protected_effect_unknown", scope)
    if o.get("effect_window_complete") is not True:
        return _unknown(claim, "no_effect_observation_not_complete", scope)
    if o.get("valid_control_same_context") is not True:
        return _unknown(claim, "valid_control_missing_or_incomparable", scope)
    if o.get("required_boundary_refusal_accepted") is not True:
        return _unknown(claim, "refusal_not_attributed_to_required_boundary", scope)
    return _result(
        claim,
        EvidenceStatus.ESTABLISHED,
        "named_route_refused_at_required_boundary_in_test_scope",
        scope,
    )


def postcondition_observed(o: Mapping[str, Any], scope: Mapping[str, Any] | None) -> EvidenceVerdict:
    """Does accepted read-back establish the declared postcondition at its observation point?

    This deliberately does not establish causation, lasting state or policy
    correctness. Tool self-report is irrelevant to the predicate.
    """
    claim = "postcondition_observed"
    if o.get("readback_available") is not True:
        return _unknown(claim, "readback_unavailable", scope)
    if o.get("source_accepted") is not True:
        return _unknown(claim, "readback_source_not_accepted", scope)
    if o.get("same_target_and_predicate") is not True:
        return _unknown(claim, "target_or_predicate_not_bound", scope)
    if o.get("fresh_in_declared_window") is not True:
        return _unknown(claim, "readback_stale_or_time_unbound", scope)
    if o.get("settlement_reached") is not True:
        return _unknown(claim, "declared_settlement_point_not_reached", scope)
    if "expected_state" not in o or "observed_state" not in o:
        return _unknown(claim, "state_value_missing", scope)
    if canonical(o["expected_state"]) == canonical(o["observed_state"]):
        return _result(
            claim,
            EvidenceStatus.ESTABLISHED,
            "declared_postcondition_observed_at_named_point",
            scope,
        )
    return _result(
        claim,
        EvidenceStatus.VIOLATED,
        "declared_postcondition_disagreed_at_named_point",
        scope,
    )


def validate_json(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is list:
        for item in value:
            validate_json(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            validate_json(item)
        return
    raise ValueError(
        "fixture values must be JSON objects, lists, strings, booleans, integers or null"
    )


def canonical(value: Any) -> str:
    """Deterministic comparison encoding, not a cryptographic canonicalization."""
    validate_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


ASSESSORS = {
    "admission_accounting": admission_accounting,
    "tested_route_enforcement": tested_route_enforcement,
    "postcondition_observed": postcondition_observed,
}


def assess(
    claim: str,
    observations: Mapping[str, Any],
    *,
    scope: Mapping[str, Any] | None = None,
    premise_source: str = "synthetic_fixture",
) -> EvidenceVerdict:
    """Assess one bounded claim from trusted synthetic fixture premises.

    The explicit `premise_source` guard prevents accidental reuse as a production
    verifier. A production adapter must first implement independent provenance,
    completeness and scope-establishment logic and should call a separate API.
    """
    if premise_source != "synthetic_fixture":
        raise ValueError(
            "evidence-sufficiency-v1 accepts only trusted synthetic_fixture premises; "
            "production evidence acceptance is intentionally not implemented"
        )
    if claim not in ASSESSORS or not isinstance(observations, Mapping):
        raise ValueError("unknown claim or malformed observations")
    validate_json(dict(observations))
    if scope is not None:
        validate_json(dict(scope))
    return ASSESSORS[claim](observations, scope)
