# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Pure mappings fixed by REMORA APS Interop Profile v0.1."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from remora.interop.jcs import canonicalise


class MappingRefused(ValueError):
    """The requested projection would weaken or misstate REMORA authority."""


def actionref_canonical(
    *,
    actor_identity: str,
    action_type: str,
    credential_scope: Sequence[str],
    issued_at: str,
    toolspec_bundle_verified: bool = True,
) -> tuple[list[str], str]:
    """Project deployment-owned REMORA fields into an APS ActionRef.

    The returned identity is APS-facing correlation evidence only. It is never
    a substitute for REMORA's exact-call identity.
    """

    if not toolspec_bundle_verified:
        raise MappingRefused("ToolSpec bundle is not verified")
    if not action_type:
        raise MappingRefused("ToolSpec action_type is absent")
    if not credential_scope:
        raise MappingRefused("ToolSpec credential_scope is empty")

    normalised = [unicodedata.normalize("NFC", item) for item in credential_scope]
    if len(set(normalised)) != len(normalised):
        raise MappingRefused("credential_scope contains a duplicate after NFC")
    ordered = sorted(normalised)
    value = {
        "agentId": actor_identity,
        "actionType": action_type,
        "scopeRequired": ordered,
        "timestamp": issued_at,
    }
    return ordered, hashlib.sha256(canonicalise(value)).hexdigest()


def accountability_decision(
    *, remora_verdict: str, executed: bool, review_resolved_as_refused: bool = False
) -> tuple[str, bool]:
    """Apply the frozen lossy REMORA-to-APS accountability mapping."""

    verdict = remora_verdict.upper()
    if verdict == "ACCEPT":
        return "allow", executed
    if verdict in {"VERIFY", "ESCALATE"}:
        return ("deny" if review_resolved_as_refused else "halt"), executed
    if verdict == "ABSTAIN":
        return "deny", executed
    raise MappingRefused(f"unknown REMORA verdict: {remora_verdict!r}")


__all__ = ["MappingRefused", "actionref_canonical"]


_COMPONENT_TAGS = {
    "authority_state": "APS-DECISION-AUTHORITY-V1",
    "policy_input": "APS-DECISION-POLICY-V1",
    "decision_context": "APS-DECISION-CONTEXT-V1",
    "decision_output": "APS-DECISION-OUTPUT-V1",
}


def _tagged_hash(tag: str, value: Any) -> str:
    return hashlib.sha256(tag.encode() + b"\0" + canonicalise(value)).hexdigest()


def _normalise_decision_output(value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "profile", "verdict", "effective_authority_ref", "constraints", "valid_until"
    }
    if set(value) != required:
        raise MappingRefused("decision_output members do not match the profile")
    constraints = [unicodedata.normalize("NFC", item) for item in value["constraints"]]
    return {**value, "constraints": sorted(set(constraints))}


def receipt_decision_ref(action_ref: str, evidence: dict[str, Any]) -> str:
    """Project committed REMORA decision evidence into the APS relation digest."""

    if len(action_ref) != 64 or any(c not in "0123456789abcdef" for c in action_ref):
        raise MappingRefused("receipt action_ref is not lowercase SHA-256 hex")
    missing = set(_COMPONENT_TAGS) - set(evidence)
    if missing:
        raise MappingRefused(f"decision evidence is incomplete: {sorted(missing)}")
    components = dict(evidence)
    components["decision_output"] = _normalise_decision_output(
        dict(evidence["decision_output"])
    )
    digest_input = {
        "profile": "aps-decision-ref-v1",
        "action_ref": action_ref,
        "authority_state_ref": _tagged_hash(
            _COMPONENT_TAGS["authority_state"], components["authority_state"]
        ),
        "policy_ref": _tagged_hash(
            _COMPONENT_TAGS["policy_input"], components["policy_input"]
        ),
        "context_ref": _tagged_hash(
            _COMPONENT_TAGS["decision_context"], components["decision_context"]
        ),
        "decision_output_ref": _tagged_hash(
            _COMPONENT_TAGS["decision_output"], components["decision_output"]
        ),
    }
    return _tagged_hash("APS-DECISION-REF-V1", digest_input)


def classify_receipt_decision_relation(
    *, receipt: dict[str, Any], evidence: dict[str, Any]
) -> str:
    """Classify binding before time, matching the frozen profile ordering."""

    observed = receipt_decision_ref(receipt["action_ref"], evidence)
    if observed != receipt.get("decision_ref"):
        return "DECISION_REF_MISMATCH"
    try:
        issued = datetime.fromisoformat(receipt["issued_at"].replace("Z", "+00:00"))
        valid = datetime.fromisoformat(
            evidence["decision_output"]["valid_until"].replace("Z", "+00:00")
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise MappingRefused("relation timestamps are not valid UTC instants") from exc
    return "PASS" if valid > issued else "VALID_UNTIL_NOT_LATER"


__all__ = [
    "MappingRefused",
    "accountability_decision",
    "actionref_canonical",
    "classify_receipt_decision_relation",
    "receipt_decision_ref",
]
