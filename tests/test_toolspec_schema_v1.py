# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The frozen ToolSpec v1 contract, pinned so it cannot drift silently.

``schemas/tool_spec_v1.yaml`` is the machine-readable half of the FT-03
decision: eight ADR questions resolved, the required field set, the
binding chain, and the reason codes AAE will branch on. Prose alone would
let runtime and contract diverge without anything failing.

Reason codes get the strictest treatment here because they are a *public*
contract: the SDK maps them to typed errors and the product repository
branches on them. Adding one is additive; renaming or removing one breaks
a downstream consumer that has no way to know until it misroutes an
error.
"""
from __future__ import annotations

from pathlib import Path

import yaml

SPEC = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "schemas" / "tool_spec_v1.yaml")
    .read_text(encoding="utf-8")
)


def test_contract_is_frozen_and_dated() -> None:
    assert SPEC["schema_version"] == 1
    assert SPEC["status"] == "frozen"
    assert SPEC["frozen_at"] == "2026-08-05"


def test_every_adr_open_question_has_a_recorded_decision() -> None:
    """The ADR left eight questions open; a frozen contract answers all."""
    required = {
        "signing_model", "trust_bundle_distribution", "key_rotation",
        "stale_version_rejection", "unverifiable_signature",
        "canonical_signing_bytes", "callable_digest_basis",
        "effect_cardinality", "tool_id_namespace",
        "argument_schema_failure", "pin_mode_default",
        "postcondition_reader_requirement", "module_home",
    }
    assert required <= set(SPEC["decisions"]), required - set(SPEC["decisions"])


def test_every_decision_states_a_choice_and_a_reason() -> None:
    """A decision without a rationale is a preference someone will undo."""
    for name, decision in SPEC["decisions"].items():
        assert decision.get("choice"), f"{name}: no choice recorded"
        has_reason = any(
            decision.get(k) for k in ("rationale", "mechanism", "definition",
                                      "import_direction_note")
        )
        assert has_reason, f"{name}: choice recorded with no reasoning"


def test_signing_key_is_owned_by_the_deployment() -> None:
    """An agent that can sign its own spec can grant itself anything."""
    signing = SPEC["decisions"]["signing_model"]
    assert signing["key_owner"] == "deployment"
    assert "agent" in signing["key_owner_note"]


def test_unverifiable_signature_has_no_fallback() -> None:
    """A fallback that executes anyway reads as protection and is not."""
    decision = SPEC["decisions"]["unverifiable_signature"]
    assert decision["choice"] == "fail_closed"
    assert decision["fallback"] == "none"


def test_callable_digest_records_what_it_cannot_see() -> None:
    """The blindness is real; recording it now beats discovering it later."""
    basis = SPEC["decisions"]["callable_digest_basis"]
    assert basis["choice"] == "source_span"
    assert basis["known_blindness"]


def test_argument_schema_failure_is_a_hard_refusal() -> None:
    """Handoff gate §1.4: arguments that fail the schema must be refused,
    not merely distrusted — the old downgrade-only rule existed because
    nothing validated the schema."""
    assert SPEC["decisions"]["argument_schema_failure"]["choice"] == (
        "hard_refuse_in_strict_mode"
    )


def test_no_trust_on_first_use() -> None:
    assert SPEC["decisions"]["pin_mode_default"]["choice"] == (
        "strict_when_bundle_configured"
    )


def test_required_fields_cover_the_handoff_gate_list() -> None:
    """Handoff gate §1.2 enumerates what a ToolSpec must carry."""
    required = set(SPEC["required_fields"])
    for field in (
        "tool_id", "version", "callable_digest", "implementation_identity",
        "description", "description_sha256", "argument_schema", "risk_tier",
        "action_type", "domain", "capabilities", "semantic_contract",
        "credential_scope", "allowed_targets", "idempotency_contract",
        "postcondition_reader", "compensation_tool", "timeout_policy",
        "network_policy", "signing_identity",
    ):
        assert field in required, f"handoff gate requires {field}"


def test_nullable_fields_are_a_subset_of_required_fields() -> None:
    """Nullable means 'present and explicitly null', never 'may be absent':
    a missing key and a declared absence are different facts."""
    assert set(SPEC["nullable_fields"]) <= set(SPEC["required_fields"])


def test_binding_chain_covers_assessment_through_dispatch() -> None:
    assert SPEC["binding_chain"] == [
        "assessment", "authorization_token", "execution_lease", "dispatch",
    ]


def test_lease_binds_toolspec_identity_and_payload() -> None:
    """Handoff gate §1.5: an approval must not be reusable with a different
    ToolSpec or a changed argument set."""
    bound = set(SPEC["lease_bound_fields"])
    for field in ("tool_id", "toolspec_version", "toolspec_hash",
                  "canonical_tool_call_hash", "policy_bundle_hash",
                  "tenant", "target_environment"):
        assert field in bound, f"lease must bind {field}"


# ── Reason codes: the public half of the contract ──────────────────────────

EXPECTED_REASON_CODES = {
    "toolspec_trust_bundle_missing",
    "toolspec_signature_invalid",
    "toolspec_signing_identity_unknown",
    "toolspec_signing_identity_revoked",
    "toolspec_bundle_stale",
    "toolspec_version_stale",
    "toolspec_unknown_tool",
    "toolspec_description_changed",
    "toolspec_argument_schema_changed",
    "toolspec_callable_digest_mismatch",
    "toolspec_credential_scope_mismatch",
    "toolspec_target_not_allowed",
    "toolspec_arguments_schema_invalid",
    "toolspec_changed_between_assess_and_dispatch",
}


def test_reason_codes_are_exactly_the_published_set() -> None:
    """Equality, not containment: a silently added code is an unversioned
    contract change to a consumer that branches on these."""
    actual = {entry["code"] for entry in SPEC["reason_codes"]}
    assert actual == EXPECTED_REASON_CODES, {
        "added": actual - EXPECTED_REASON_CODES,
        "removed": EXPECTED_REASON_CODES - actual,
    }


def test_every_reason_code_explains_itself() -> None:
    for entry in SPEC["reason_codes"]:
        assert entry.get("meaning"), f"{entry['code']}: no meaning recorded"


def test_reason_codes_cover_every_fail_closed_condition() -> None:
    """Handoff gate §1.4 lists what runtime must refuse; each needs a code
    a consumer can branch on, or the refusal is untypeable."""
    codes = {entry["code"] for entry in SPEC["reason_codes"]}
    for condition in (
        "signature_invalid", "signing_identity_unknown",
        "signing_identity_revoked", "version_stale", "description_changed",
        "argument_schema_changed", "callable_digest_mismatch",
        "credential_scope_mismatch", "target_not_allowed",
        "arguments_schema_invalid",
        "changed_between_assess_and_dispatch",
    ):
        assert f"toolspec_{condition}" in codes, condition


def test_realization_status_does_not_overclaim() -> None:
    """The contract is frozen; nothing here is implemented yet, and the
    file must not imply otherwise."""
    realization = SPEC["realization"]
    assert realization["contract"] == "frozen"
    assert realization["runtime_enforcement"] == "not_implemented"
    assert realization["sdk_surface"] == "not_implemented"
