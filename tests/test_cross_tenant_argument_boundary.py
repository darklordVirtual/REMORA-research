# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Issue #368/#369: tenant scope is not a reviewable ambiguity.

Value grounding and tenant scope answer different questions. A foreign value
may be sent to a reviewer when provenance is merely absent; a value that the
deployment can prove addresses another tenant must hard-abstain before a
proposal exists, and the fresh re-gate must invalidate any older proposal.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from deploy.gateway.bundle import validate_argument_scope  # noqa: E402
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402
from remora.policy.decision_engine import RemoraDecisionEngine  # noqa: E402
from remora.policy.observation import PolicyObservation  # noqa: E402
from remora.toolcall.semantic_bundle import (  # noqa: E402
    ArgumentScopeResult,
    IntentResolution,
)
from remora.toolcall.routing.compatibility import (  # noqa: E402
    StateIndex,
    argument_grounding,
)


CALL = {
    "tool_name": "store_artifact",
    "arguments": {"artifact_id": "tenant-boundary-1", "content": {"n": 1}},
    "target_environment": "prod",
    "schema_valid": True,
    "intent_ref": "wo-artifact-1",
}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    intent_file = tmp_path / "workflow_intents.json"
    intent_file.write_text(json.dumps({
        "wo-artifact-1": {
            "task_text": "Create an artifact named tenant-boundary-1.",
            "operation": "create",
            "resource_type": "artifact",
            "requested_effect": "create",
            "target_entities": ["target_resource"],
            "source_spans": ["artifact"],
            "action_spans": ["create an artifact"],
        },
    }), encoding="utf-8")
    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "tenant-boundary-test-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv(
        "REMORA_SEMANTIC_BUNDLE_MODULE", "servers.semantic_bundle_research"
    )
    monkeypatch.setenv("REMORA_INTENT_SOURCE_FILE", str(intent_file))
    monkeypatch.setenv(
        "REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research"
    )
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))

    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "reviewer-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda *args: None)
    monkeypatch.setattr(api_mod, "_enforce_review_approval_role", lambda **kwargs: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    yield TestClient(api_mod.app), exec_mod, monkeypatch
    exec_mod._reset_semantic_bundle()


def test_gateway_validator_hard_bounds_tenant_qualified_graphs(monkeypatch) -> None:
    monkeypatch.setenv("REMORA_KG_TENANT", "luftfiber")
    own = validate_argument_scope(
        "kg_list_predicates",
        {"graph": "urn:exeqta:tenant:luftfiber:business"},
        "ignored-auth-tenant",
    )
    foreign = validate_argument_scope(
        "kg_list_predicates",
        {"graph": "urn:exeqta:tenant:remora:internal"},
        "ignored-auth-tenant",
    )
    assert own == ArgumentScopeResult(True)
    assert foreign == ArgumentScopeResult(False, ("graph",))


def test_grounding_names_the_argument_that_failed_provenance() -> None:
    result = argument_grounding(
        {"graph": "urn:exeqta:tenant:remora:internal", "limit": 50},
        task_text="Survey the luftfiber business graph with a limit of 50.",
        state=StateIndex(frozenset()),
        domain="knowledge_graph",
    )
    assert result.grounded is False
    assert result.ungrounded_arguments == ("graph",)


def test_graph_intent_audit_distinguishes_absence_from_transport_failure(
    monkeypatch,
) -> None:
    from deploy.gateway import kg_intent, kg_registry

    monkeypatch.setattr(kg_registry, "read_intent", lambda _subject: {})
    assert (
        kg_intent.resolve_intent_detailed("task:missing").status
        == "intent_not_authorized"
    )

    def unavailable(_subject):
        raise kg_registry.GraphUnavailable("D1 transport unavailable")

    monkeypatch.setattr(kg_registry, "read_intent", unavailable)
    assert (
        kg_intent.resolve_intent_detailed("task:missing").status
        == "intent_resolution_failed"
    )


def test_scope_violation_is_hard_abstain_not_review() -> None:
    report = RemoraDecisionEngine().decide(PolicyObservation(
        question="list another tenant's predicates",
        risk_tier="low",
        action_type="read",
        schema_valid=True,
        argument_scope_valid=False,
        scope_violating_arguments=("graph",),
    ))
    assert report.action.value == "abstain"
    assert [reason.value for reason in report.reasons] == [
        "cross_tenant_argument_blocked"
    ]


def test_external_escalate_cannot_turn_tenant_abstain_into_approval() -> None:
    from remora.policy.opa_adapter import OPAAdapter
    from remora.policy.report import DecisionAction, DecisionReport

    obs = PolicyObservation(
        question="cross tenant",
        risk_tier="low",
        action_type="read",
        argument_scope_valid=False,
        scope_violating_arguments=("graph",),
    )
    external = DecisionReport(
        action=DecisionAction.ESCALATE,
        reasons=(),
        risk_estimate=None,
        confidence=None,
        coverage_policy="test",
        evidence_required=True,
        human_review_required=True,
        audit_root=None,
        explanation="send to a reviewer",
        raw_observation=obs,
    )
    adjudicated = OPAAdapter()._apply_decision_floor(external, obs)
    assert adjudicated.action is DecisionAction.ABSTAIN
    assert adjudicated.human_review_required is False


def test_assess_refuses_before_creating_a_review_item(client) -> None:
    api, exec_mod, monkeypatch = client
    monkeypatch.setattr(
        exec_mod,
        "load_argument_scope_validator",
        lambda: lambda *_args: ArgumentScopeResult(False, ("artifact_id",)),
    )
    body = api.post("/v1/execution/assess", json=CALL).json()
    assert body["decision"] == "abstain"
    assert "cross_tenant_argument_blocked" in body["reasons"]
    assert "review_item_id" not in body
    assert body["semantic"]["argument_scope_valid"] is False
    assert body["semantic"]["scope_violating_arguments"] == ["artifact_id"]
    assert not any(
        entry.payload.get("event") == "review_enqueued"
        for entry in exec_mod._CHAIN.entries("acme")
    )


def test_preexisting_approval_is_invalidated_by_fresh_scope_check(client) -> None:
    api, exec_mod, monkeypatch = client
    state = {"valid": True}

    def validator(*_args):
        return (
            ArgumentScopeResult(True)
            if state["valid"]
            else ArgumentScopeResult(False, ("artifact_id",))
        )

    monkeypatch.setattr(exec_mod, "load_argument_scope_validator", lambda: validator)
    assessed = api.post("/v1/execution/assess", json=CALL).json()
    item_id = assessed["review_item_id"]
    assert api.post("/v1/execution/approve", json={"item_id": item_id}).status_code == 200

    state["valid"] = False
    body = api.post(
        "/v1/execution/execute", json={"item_id": item_id, "tool_call": CALL}
    ).json()
    assert body["outcome"] == "approval_invalidated"
    assert body.get("tool_execution") is None
    assert not any(
        entry.payload.get("event") == "execution_authorized"
        for entry in exec_mod._CHAIN.entries("acme")
    )


def test_intent_failure_class_is_audit_only(client) -> None:
    api, exec_mod, monkeypatch = client

    public: list[tuple[str, list[str], dict[str, object]]] = []
    for status in ("intent_not_authorized", "intent_resolution_failed"):
        monkeypatch.setattr(
            exec_mod,
            "load_intent_resolution_provider",
            lambda status=status: (
                lambda _ref: IntentResolution(None, status)
            ),
        )
        body = api.post("/v1/execution/assess", json=CALL).json()
        public.append((body["decision"], body["reasons"], body["semantic"]))

    assert public[0] == public[1]
    statuses = [
        entry.payload.get("intent_resolution_status")
        for entry in exec_mod._CHAIN.entries("acme")
        if entry.payload.get("event") == "assessed"
    ]
    assert statuses[-2:] == ["intent_not_authorized", "intent_resolution_failed"]
