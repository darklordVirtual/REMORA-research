# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA's own evaluation of its execution-boundary interop fixtures.

The packages under ``artifacts/interop/exact-call-binding-v1``,
``fresh-authority-v1`` and ``effect-evidence-v1`` describe three bounded
properties of the execution boundary in implementation-agnostic terms. The
reference verifiers next to them model the property without REMORA code.
This module is the other half: it runs every fixture case through the real
primitives (``PolicyDecisionToken`` and ``EnforcementGate`` for a grant,
``ExecutionLease`` and ``GovernedToolDispatcher`` for a dispatch,
``verify_declared_delta`` for an effect) and reports the outcome in the
fixture's vocabulary, so a committed fixture is evidence about REMORA and not
only about the reference verifier.

Nothing here is on the authority path. The evaluators construct leases and
tokens the way a deployment would and read what the enforcement code
returns; they never decide. A run of this module is an L0 self-test under
``interop-result-v1``: it advances no contract lifecycle.
"""
from __future__ import annotations

import dataclasses
import os
from typing import Any, Callable, Mapping
from unittest import mock

from remora.enforcement.gate import EnforcementGate
from remora.enforcement.lease import DispatchResult, ExecutionLease, GovernedToolDispatcher
from remora.enforcement.token import PolicyDecisionToken
from remora.governance.effect_verification import (
    EffectStatus,
    PostconditionContract,
    verify_declared_delta,
)

__all__ = [
    "FixtureEnvironmentError",
    "REFUSAL_CLASS_BY_REASON",
    "evaluate_effect_evidence",
    "evaluate_exact_call_binding",
    "evaluate_fresh_authority",
    "evaluate_package",
]

#: Fixture-vocabulary class for each REMORA refusal reason the three fixtures
#: can provoke. A reason outside this table is reported verbatim, prefixed,
#: so a new refusal path shows up as a mismatch rather than being absorbed.
REFUSAL_CLASS_BY_REASON: Mapping[str, str] = {
    "tool_args_hash_mismatch": "call_mismatch",
    "tool_name_mismatch": "call_mismatch",
    "tenant_mismatch": "call_mismatch",
    "target_environment_mismatch": "call_mismatch",
    "unknown_tool": "call_mismatch",
    "actor_identity_mismatch": "principal_mismatch",
    "actor_identity_required": "principal_mismatch",
    "nonce_already_consumed": "authority_consumed",
    "nonce_consumed_by_failed_execution": "authority_consumed",
    "token_already_consumed": "authority_consumed",
    "lease_not_signed": "authority_unverifiable",
    "token_not_signed": "authority_unverifiable",
    "signature_invalid": "authority_unverifiable",
    "no_signing_key": "authority_unverifiable",
    "signature_algorithm_refused": "authority_unverifiable",
    "lease_expired": "authority_expired",
    "token_expired": "authority_expired",
    "lease_not_yet_valid": "authority_not_yet_valid",
    "token_not_yet_valid": "authority_not_yet_valid",
    "kid_revoked": "authority_revoked",
    "observation_hash_mismatch": "authority_stale",
    "context_mismatch": "authority_stale",
    "policy_bundle_mismatch": "authority_stale",
    "policy_bundle_missing": "authority_stale",
    "toolspec_hash_mismatch": "authority_stale",
    "toolspec_version_mismatch": "authority_stale",
    "decision_not_accept": "decision_not_accept",
}

_BUNDLE = "sha256:" + "f" * 64


class FixtureEnvironmentError(RuntimeError):
    """The process is not configured to mint the authority a case needs."""


def _refusal_class(reason: str | None) -> str:
    if reason is None:
        return "unspecified"
    # The PEP gate prefixes a failed token verification with its stage.
    reason = reason.rsplit(":", 1)[-1]
    if reason.startswith("decision_") and reason.endswith("_not_accept"):
        return "decision_not_accept"
    return REFUSAL_CLASS_BY_REASON.get(reason, f"unmapped:{reason}")


def _outcome(result: DispatchResult, dispatched: str = "DISPATCHED") -> dict[str, Any]:
    if result.executed:
        return {"outcome": dispatched, "refusal_class": None}
    return {"outcome": "REFUSED", "refusal_class": _refusal_class(result.refusal_reason)}


def _apply_integrity(lease: ExecutionLease, integrity: str) -> ExecutionLease:
    if integrity == "intact":
        if not lease.is_signed:
            raise FixtureEnvironmentError(
                "the lease was issued unsigned; set REMORA_LEASE_SIGNING_KEY before evaluating"
            )
        return lease
    if integrity == "unsigned":
        return dataclasses.replace(lease, signature="", is_signed=False)
    if integrity == "tampered":
        return dataclasses.replace(lease, signature="00" * 32)
    raise ValueError(f"unknown integrity {integrity!r}")


def _dispatcher(tools: tuple[str, ...], *, expected_bundle: str,
                spec_identity: Callable[[str], tuple[str, int] | None] | None = None) -> GovernedToolDispatcher:
    dispatcher = GovernedToolDispatcher(expected_policy_bundle_hash=expected_bundle)
    for name in tools:
        dispatcher.register(name, lambda arguments: {"ok": True})
    if spec_identity is not None:
        dispatcher.bind_toolspec_identity(spec_identity)
    return dispatcher


# ── exact-call-binding-v1 ──────────────────────────────────────────────────


def evaluate_exact_call_binding(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Issue one lease for ``authorization`` and present every ``dispatches``
    entry to a governed dispatcher, in order."""
    authorization = case["authorization"]
    lease = ExecutionLease.issue(
        decision="accept",
        tenant_id=authorization["tenant"],
        actor_identity=authorization["actor"],
        tool_name=authorization["tool"],
        arguments=authorization["arguments"],
        target_environment=authorization["target"],
        policy_bundle_hash=_BUNDLE,
        issued_at="2026-10-04T12:00:00+00:00",
    )
    lease = _apply_integrity(lease, authorization.get("integrity", "intact"))
    tools = tuple(sorted({authorization["tool"], *(d["tool"] for d in case["dispatches"])}))
    dispatcher = _dispatcher(tools, expected_bundle=_BUNDLE)
    outcomes = []
    for presented in case["dispatches"]:
        result = dispatcher.dispatch(
            lease, presented["tool"], presented["arguments"],
            tenant_id=presented["tenant"], target_environment=presented["target"],
            actor_identity=presented["actor"], now="2026-10-04T12:00:30+00:00",
        )
        outcomes.append(_outcome(result))
    return outcomes


# ── fresh-authority-v1 ─────────────────────────────────────────────────────


def _evaluate_grant(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    authorization = case["authorization"]
    integrity = authorization.get("integrity", "intact")
    issue_env = {"REMORA_PDP_SIGNING_KEY": "fixture-grant-key", "REMORA_PDP_SIGNING_KID": authorization["kid"]}
    with mock.patch.dict(os.environ, issue_env):
        token = PolicyDecisionToken.issue(
            action=authorization["decision"],
            observation_hash=authorization["observation"],
            request_id="fixture-request",
            issued_at=authorization["issued_at"],
            expires_at=authorization["expires_at"],
        )
    if integrity == "unsigned":
        token = dataclasses.replace(token, signature="", is_signed=False)
    elif integrity == "tampered":
        token = dataclasses.replace(token, signature="00" * 32)
    gate = EnforcementGate(strict=True)
    outcomes = []
    for presentation in case["presentations"]:
        present_env = dict(issue_env, REMORA_PDP_REVOKED_KIDS=",".join(presentation.get("revoked_kids", [])))
        with mock.patch.dict(os.environ, present_env):
            result = gate.check(
                token, expected_observation_hash=presentation["observation"],
                consume=True, now=presentation["at"],
            )
        if result.allowed:
            outcomes.append({"outcome": "ADMITTED", "refusal_class": None})
        else:
            outcomes.append({"outcome": "REFUSED", "refusal_class": _refusal_class(result.reason)})
    return outcomes


def _evaluate_dispatch(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    authorization = case["authorization"]
    dispatch = case["dispatch"]
    lease = ExecutionLease.issue(
        decision="accept",
        tenant_id=authorization["tenant"],
        actor_identity=authorization["actor"],
        tool_name=authorization["tool"],
        arguments=authorization["arguments"],
        target_environment=authorization["target"],
        policy_bundle_hash=authorization["policy_bundle"],
        issued_at=authorization["issued_at"],
        expires_at=authorization["expires_at"],
        toolspec_hash=authorization["toolspec_hash"],
        toolspec_version=authorization["toolspec_version"],
    )
    lease = _apply_integrity(lease, authorization.get("integrity", "intact"))
    dispatcher = _dispatcher(
        (authorization["tool"],), expected_bundle=dispatch["policy_bundle"],
        spec_identity=lambda _tool: (dispatch["toolspec_hash"], dispatch["toolspec_version"]),
    )
    result = dispatcher.dispatch(
        lease, authorization["tool"], authorization["arguments"],
        tenant_id=authorization["tenant"], target_environment=authorization["target"],
        actor_identity=authorization["actor"], now=dispatch["at"],
    )
    return [_outcome(result)]


def evaluate_fresh_authority(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A grant case goes through the PEP gate; a dispatch case through the
    governed dispatcher. Both re-evaluate authority at presentation time."""
    if case["stage"] == "grant":
        return _evaluate_grant(case)
    if case["stage"] == "dispatch":
        return _evaluate_dispatch(case)
    raise ValueError(f"unknown stage {case['stage']!r}")


# ── effect-evidence-v1 ─────────────────────────────────────────────────────


def evaluate_effect_evidence(case: Mapping[str, Any]) -> dict[str, Any]:
    """Effect status from ``verify_declared_delta`` and the highest state the
    evidence supports, per the fixture's ladder rule."""
    if case["dispatch"]["outcome"] == "REFUSED":
        return {"effect_status": "NOT_EVALUATED", "highest_established_state": "NOT_DISPATCHED"}
    state = "DISPATCHED"
    report = case.get("execution_report")
    if report is not None and report.get("status") == "success":
        state = "EXECUTION_REPORTED_SUCCESS"
    postcondition = case.get("postcondition")
    if postcondition is None:
        return {"effect_status": "NOT_EVALUATED", "highest_established_state": state}
    contract = PostconditionContract(
        tool_id=postcondition["tool_id"], reader="fixture-reader", target_selector={},
        expected_fields=postcondition["expected_fields"],
        comparison_rules=postcondition.get("comparison_rules", {}),
    )
    verification = verify_declared_delta(
        contract, case.get("observed"), proposal_id="fixture-proposal",
        execution_id="fixture-execution", toolspec_hash="fixture-spec",
        verifier_identity="fixture-verifier",
    )
    status = verification.status
    if status is EffectStatus.VERIFIED:
        state = "EFFECT_VERIFIED"
    elif status is EffectStatus.MISMATCH:
        state = "DISPATCHED"
    return {"effect_status": status.value, "highest_established_state": state}


# ── package runner ─────────────────────────────────────────────────────────

_EVALUATORS: dict[str, Callable[[Mapping[str, Any]], Any]] = {
    "remora-exact-call-binding-fixtures-v1": evaluate_exact_call_binding,
    "remora-fresh-authority-fixtures-v1": evaluate_fresh_authority,
    "remora-effect-evidence-fixtures-v1": evaluate_effect_evidence,
}


def _expected(case: Mapping[str, Any]) -> Any:
    expected = case["expected"]
    if "outcomes" in expected:
        return expected["outcomes"]
    return {k: expected[k] for k in ("effect_status", "highest_established_state")}


def evaluate_package(fixtures: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One record per case: expected, observed through REMORA, and the result
    in the contract vocabulary. A case whose observed outcome differs from the
    expected one is CONTRADICTED whatever the fixture's own ceiling says."""
    evaluator = _EVALUATORS[fixtures["schema_version"]]
    records = []
    for case in fixtures["cases"]:
        expected = _expected(case)
        observed = evaluator(case)
        matches = observed == expected
        records.append({
            "case_id": case["id"],
            "claim_id": case["claim_id"],
            "expected": {"value": expected},
            "observed": {"value": observed},
            "result": case["expected"]["claim_result"] if matches else "CONTRADICTED",
        })
    return records
