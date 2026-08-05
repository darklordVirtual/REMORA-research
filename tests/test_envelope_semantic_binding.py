# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The envelope must name the declaration set its decision was made under.

SHELF-020 bound the semantic bundle into the ExecutionLease, but the
DecisionEnvelope — the artifact an auditor actually reads — carried no trace
of it. Answering "which tool contracts were active when this was decided?"
required correlating the envelope against the tenant audit chain by hand.

These tests pin the binding, and pin that absence stays absent: with no bundle
configured the fields are None, never a fabricated hash.
"""
from __future__ import annotations

import json

from remora.governance.envelope import AuditBlock, DecisionEnvelope


def test_audit_block_carries_the_semantic_binding_fields() -> None:
    block = AuditBlock(
        tool_contract_bundle_hash="a" * 64,
        intent_authority_hash="b" * 64,
    )
    assert block.tool_contract_bundle_hash == "a" * 64
    assert block.intent_authority_hash == "b" * 64


def test_binding_fields_default_to_absent_not_empty() -> None:
    """None means 'no bundle configured'. An empty string would read as a
    declared-but-blank hash, which is a different and misleading claim."""
    block = AuditBlock()
    assert block.tool_contract_bundle_hash is None
    assert block.intent_authority_hash is None


_REQUEST = {
    "request_id": "r-1", "domain": "ot_plant", "risk_tier": "high",
    "proposed_action": "adjust_setpoint", "action_type": "production_write",
    "target_environment": "prod",
}
_ASSESSMENT = {
    "oracle_votes": [], "thermodynamic": {}, "evidence_quality": {},
    "policy_triggers": [],
}
_GATE: dict = {"outcome": "verify"}


def test_envelope_round_trip_preserves_the_binding() -> None:
    env = DecisionEnvelope.from_dict({
        "request": dict(_REQUEST), "assessment": dict(_ASSESSMENT), "gate": dict(_GATE),
        "audit": {
            "tool_contract_bundle_hash": "c" * 64,
            "intent_authority_hash": "d" * 64,
        },
    })
    assert env.audit.tool_contract_bundle_hash == "c" * 64
    restored = DecisionEnvelope.from_dict(json.loads(json.dumps(env.to_dict())))
    assert restored.audit.tool_contract_bundle_hash == "c" * 64
    assert restored.audit.intent_authority_hash == "d" * 64


def test_absent_binding_does_not_perturb_the_chain_preimage() -> None:
    """A trail recorded before these fields existed must still verify.

    The envelope chain hash covers the whole payload, so a new field would
    otherwise break every stored chain — the verifier gaining a field would be
    indistinguishable from tampering. Unset post-v2 keys are omitted from the
    preimage; set ones are covered.
    """
    from remora.governance.envelope import normalize_audit_for_hash

    legacy = {"audit": {"policy_version": "v1", "hash": None}}
    with_none = {"audit": {"policy_version": "v1", "hash": None,
                           "tool_contract_bundle_hash": None,
                           "intent_authority_hash": None}}
    assert normalize_audit_for_hash(with_none) == normalize_audit_for_hash(legacy)


def test_present_binding_is_covered_by_the_preimage() -> None:
    from remora.governance.envelope import normalize_audit_for_hash

    bound = {"audit": {"policy_version": "v1", "hash": None,
                       "tool_contract_bundle_hash": "e" * 64,
                       "intent_authority_hash": None}}
    normalized = normalize_audit_for_hash(bound)
    assert normalized["audit"]["tool_contract_bundle_hash"] == "e" * 64
    assert "intent_authority_hash" not in normalized["audit"]


def test_envelope_without_binding_round_trips_as_none() -> None:
    env = DecisionEnvelope.from_dict(
        {"request": dict(_REQUEST), "assessment": dict(_ASSESSMENT), "gate": dict(_GATE)}
    )
    restored = DecisionEnvelope.from_dict(json.loads(json.dumps(env.to_dict())))
    assert restored.audit.tool_contract_bundle_hash is None
    assert restored.audit.intent_authority_hash is None
