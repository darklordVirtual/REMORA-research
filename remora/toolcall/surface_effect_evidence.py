# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Recomputable effect evidence checked against trusted contracts and audit events.

A content digest detects changes; it does not authenticate the observation.
The caller supplies the authenticated principal and server-owned audit events.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from remora.governance.effect_receipt import ReceiptRefused, verify_receipt
from remora.governance.effect_verification import (
    EffectStatus, PostconditionContract, verify_declared_delta,
)
from remora.toolcall.runtime_surface import canonical_json


def _contract(contract: PostconditionContract) -> dict[str, Any]:
    return dict(tool_id=contract.tool_id, reader=contract.reader,
                target_selector=dict(contract.target_selector),
                expected_fields=dict(contract.expected_fields),
                comparison_rules=dict(contract.comparison_rules),
                observation_deadline_seconds=contract.observation_deadline_seconds,
                repeatable=contract.repeatable, evidence_fields=list(contract.evidence_fields))


def build_effect_evidence(*, contract: PostconditionContract,
                          observed: Mapping[str, Any] | None,
                          events: Sequence[Mapping[str, Any]], proposal_id: str,
                          tool_call_hash: str, grant_jti: str, verified_at: str,
                          verifier_identity: str, principal: str,
                          trusted_verifiers: Mapping[str, str]) -> dict[str, Any]:
    if not principal or trusted_verifiers.get(verifier_identity) != principal:
        raise ValueError("verifier_principal_mismatch")
    if verifier_identity != contract.reader:
        raise ValueError("contract_reader_mismatch")
    rules = dict(contract.comparison_rules)
    if set(rules) - set(contract.expected_fields) or any(
        r not in {"exact", "hash", "present", "absent", "version_increment"}
        for r in rules.values()
    ):
        raise ValueError("unsupported_comparison_rule")
    if not contract.expected_fields:
        raise ValueError("empty_postcondition")
    observed = None if observed is None else json.loads(canonical_json(dict(observed)))
    contract_data = json.loads(canonical_json(_contract(contract)))
    now = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    if now.tzinfo is None:
        raise ValueError("observation_timezone_required")
    verification = verify_declared_delta(
        contract, observed, proposal_id=proposal_id, execution_id=grant_jti,
        toolspec_hash="", verifier_identity=verifier_identity, now=now)
    status = verification.status
    # Missing fields cannot satisfy an exact null or a hash-of-null condition.
    if observed is not None and any(
        name not in observed and rules.get(name, "exact") in {"exact", "hash"}
        for name in contract.expected_fields
    ):
        status = EffectStatus.MISMATCH
    try:
        lineage, _ = verify_receipt(
            events=events, proposal_id=proposal_id, claimed_status=status,
            tool_call_hash=tool_call_hash, grant_jti=grant_jti,
            expected_sha256=verification.expected_sha256,
            observed_sha256=verification.observed_sha256, verified_at=verified_at,
            verifier_identity=verifier_identity, trusted_verifiers=tuple(trusted_verifiers))
    except ReceiptRefused as exc:
        raise ValueError(exc.reason) from exc
    attempted = datetime.fromisoformat(lineage.attempted_at.replace("Z", "+00:00"))
    if attempted.tzinfo is None or (now - attempted).total_seconds() > contract.observation_deadline_seconds:
        raise ValueError("observation_deadline_exceeded")
    evidence = dict(version="surface-effect-evidence-v1", contract=contract_data,
                    observed=observed, proposal_id=proposal_id, tool_call_hash=tool_call_hash,
                    grant_jti=grant_jti, verified_at=verified_at,
                    verifier_identity=verifier_identity, principal=principal,
                    expected_sha256=verification.expected_sha256,
                    observed_sha256=verification.observed_sha256,
                    binding_verdict="FRESH_AND_BOUND",
                    property_verdict=status.value if status in (EffectStatus.VERIFIED, EffectStatus.MISMATCH)
                    else "NOT_ESTABLISHED")
    evidence["content_sha256"] = hashlib.sha256(canonical_json(evidence).encode()).hexdigest()
    return evidence


def recheck_effect_evidence(evidence: Mapping[str, Any], *, contract: PostconditionContract,
                            events: Sequence[Mapping[str, Any]], principal: str,
                            trusted_verifiers: Mapping[str, str]) -> dict[str, Any]:
    try:
        rebuilt = build_effect_evidence(
            contract=contract, observed=evidence["observed"], events=events,
            proposal_id=evidence["proposal_id"], tool_call_hash=evidence["tool_call_hash"],
            grant_jti=evidence["grant_jti"], verified_at=evidence["verified_at"],
            verifier_identity=evidence["verifier_identity"], principal=principal,
            trusted_verifiers=trusted_verifiers)
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid_effect_evidence") from exc
    if canonical_json(dict(evidence)) != canonical_json(rebuilt):
        raise ValueError("effect_evidence_mismatch")
    return rebuilt
