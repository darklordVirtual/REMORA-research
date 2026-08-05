# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The SDK effect loop, driven the way a product actually drives it.

Everything about effect verification was tested from one side or the
other: the endpoint against raw JSON, the models against hand-built
dicts, the SDK surface against ``hasattr``. Nothing put the two together.
``record_effect`` — the one call a product makes to close the loop — had
never issued a request in any test, and a method nobody has called is a
method nobody knows works.

So this drives the whole thing through ``remora.sdk`` alone: assess,
approve, execute, verify against the declared delta, record the result,
and read the verdict back. If the client and the server disagree about
the wire shape, it fails here rather than in a consumer's integration.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from remora.sdk import (  # noqa: E402
    EffectStatus,
    EffectVerificationView,
    RemoraClient,
    ToolCall,
    build_postcondition,
    content_digest,
    verify_effect,
)

ARGS = {"artifact_id": "roundtrip-1", "content": {"reading": 12.5}}


@pytest.fixture()
def http(monkeypatch, tmp_path):
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "roundtrip-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "roundtrip-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE",
                       "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    for var in ("REMORA_TOOLSPEC_BUNDLE", "REMORA_TOOLSPEC_SIGNING_KEY",
                "REMORA_TOOLSPEC_TRUSTED_IDENTITIES"):
        monkeypatch.delenv(var, raising=False)

    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal",
                        lambda request: "employee-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability",
                        lambda role, tenant, cap: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role",
                        lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    exec_mod._reset_toolspec_bundle()
    return TestClient(api_mod.app)


@pytest.fixture()
def sdk(http):
    return RemoraClient("http://demo", token="t", http_client=http)


def _call() -> ToolCall:
    return ToolCall(tool_name="store_artifact", arguments=dict(ARGS),
                    target_environment="prod", schema_valid=True)


def _through_execution(sdk) -> str:
    assessed = sdk.assess(_call())
    assert assessed.review_item_id, "expected the review branch for a prod write"
    sdk.approve(assessed.review_item_id)
    executed = sdk.execute(assessed.review_item_id, _call())
    assert executed.outcome == "execute", executed.detail
    return executed.proposal_id


def _postcondition():
    return build_postcondition(
        tool_id="store_artifact",
        target_selector={"artifact_id": ARGS["artifact_id"]},
        expected_fields={"artifact_id": ARGS["artifact_id"],
                         "content": content_digest(ARGS["content"])},
        comparison_rules={"content": "hash"},
    )


# ── The loop closes through the SDK only ───────────────────────────────────

def test_a_product_can_close_the_loop_with_the_client(sdk) -> None:
    proposal_id = _through_execution(sdk)

    verified = verify_effect(
        _postcondition(),
        {"artifact_id": ARGS["artifact_id"], "content": ARGS["content"]},
        proposal_id=proposal_id, execution_id=proposal_id,
        toolspec_hash="", verifier_identity="acme.reader/v1",
    )
    assert verified.status is EffectStatus.VERIFIED

    recorded = sdk.record_effect(proposal_id, verified)
    assert isinstance(recorded, EffectVerificationView)
    assert recorded.status is EffectStatus.VERIFIED
    assert recorded.verifier_identity == "acme.reader/v1"

    view = sdk.get_proposal(proposal_id)
    assert view.effect is not None
    assert view.effect.status is EffectStatus.VERIFIED
    assert view.current_state == "EFFECT_VERIFIED"


def test_a_mismatch_survives_the_round_trip_unsoftened(sdk) -> None:
    """A product reporting bad news about itself must arrive as bad news."""
    proposal_id = _through_execution(sdk)
    mismatch = verify_effect(
        _postcondition(),
        {"artifact_id": ARGS["artifact_id"], "content": {"reading": 999.0}},
        proposal_id=proposal_id, execution_id=proposal_id,
        toolspec_hash="", verifier_identity="acme.reader/v1",
    )
    assert mismatch.status is EffectStatus.MISMATCH

    sdk.record_effect(proposal_id, mismatch)
    assert sdk.get_proposal(proposal_id).effect.status is EffectStatus.MISMATCH


def test_an_unobservable_effect_arrives_as_unknown_not_failure(sdk) -> None:
    proposal_id = _through_execution(sdk)
    unknown = verify_effect(
        _postcondition(), None, proposal_id=proposal_id,
        execution_id=proposal_id, toolspec_hash="",
        verifier_identity="acme.reader/v1",
    )
    sdk.record_effect(proposal_id, unknown)
    view = sdk.get_proposal(proposal_id)
    assert view.effect.status is EffectStatus.UNOBSERVABLE
    assert view.current_state == "EFFECT_UNKNOWN"


def test_the_recorded_verification_reaches_the_evidence_bundle(sdk) -> None:
    proposal_id = _through_execution(sdk)
    verified = verify_effect(
        _postcondition(),
        {"artifact_id": ARGS["artifact_id"], "content": ARGS["content"]},
        proposal_id=proposal_id, execution_id=proposal_id,
        toolspec_hash="", verifier_identity="acme.reader/v1",
    )
    sdk.record_effect(proposal_id, verified)

    bundle = sdk.export_evidence(proposal_id)
    assert bundle["effect_verification"]["status"] == "EFFECT_VERIFIED"
    assert "effect_verification" in bundle["manifest"]["section_sha256"]


# ── Lineage arrives from a real server response ────────────────────────────

def test_lineage_parses_from_a_real_assessment(sdk) -> None:
    """Previously only asserted against a hand-built dict, which cannot
    catch the client and server disagreeing about the field name."""
    first = sdk.assess(ToolCall(tool_name="read_telemetry",
                                arguments={"sensor": "P-1"},
                                target_environment="prod", schema_valid=True))
    second = sdk.assess(ToolCall(tool_name="read_telemetry",
                                 arguments={"sensor": "P-1", "detail": "full"},
                                 target_environment="prod", schema_valid=True))
    assert second.lineage is not None
    assert second.lineage.superseded_proposal_id == first.proposal_id
    assert second.lineage.probe_sequence_no == 2
    assert second.lineage.shadow_only is True
