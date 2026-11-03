# SPDX-License-Identifier: BUSL-1.1
"""RMR-SEC-0001: /dispatch-leased is the executor's door, not the agent's.

The 2026-11-02 adversarial review dispatched writes that policy had routed to
human review by posting a self-signed lease to /v1/execution/dispatch-leased
on the default (authority) process with the agent's own ``operator`` token:
the route needed only the ``execute`` capability, accepted a lease linked to
no proposal or grant, and wrote nothing to the tenant audit chain, so
``/audit/verify`` still reported INTACT. On the OT pilot that closed a valve.

Pinned here, with the real role matrix (capability checks are NOT patched):

- the authority domain does not serve the route at all (404);
- on the executor, only the ``dispatch`` capability admits it, which the
  agent-facing ``operator`` role does not hold;
- a lease without ``proposal_id`` or ``grant_jti`` is refused before the
  tool runs, even when its signature verifies;
- every lease the executor admits is recorded in the tenant chain before
  the tool runs, and its outcome after.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _security_extra import require_security_extra  # noqa: E402

from remora.enforcement import lease_signing as signing  # noqa: E402
from remora.governance.tenant_chain import TenantAuditChain  # noqa: E402

require_security_extra()

from remora.execution.dispatch import issue_execution_lease  # noqa: E402

CALL = {"tool_name": "update_work_order",
        "arguments": {"work_order_id": "WO-1", "status": "closed"},
        "target_environment": "staging"}
SEMANTIC = {"tool_contract_bundle_hash": "", "intent_authority_hash": ""}
# A key the attacker knows: the review used the literal from the OT compose.
KEY = "pilot-lease-key-change-me-but-long-enough-for-hmac"


@pytest.fixture()
def server(monkeypatch):
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "tests.dispatcher_registry_fixture")
    monkeypatch.setenv(signing.ENV_HMAC, KEY)
    monkeypatch.delenv(signing.ENV_ED25519_PRIVATE, raising=False)
    monkeypatch.delenv(signing.ENV_ED25519_PUBLIC, raising=False)

    import servers.api as api_mod
    import servers.execution_api as exec_mod
    from tests import dispatcher_registry_fixture as registry

    roles = {"Bearer agent": "operator", "Bearer hop": "dispatch_hop", "Bearer admin": "admin"}

    def authenticate(request):
        role = roles.get(request.headers.get("Authorization", ""))
        if role is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="unauthenticated")
        return "acme", role

    registry.CALLS.clear()
    monkeypatch.setattr(api_mod, "_authenticate", authenticate)
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "caller")
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_tool_dispatcher()
    return SimpleNamespace(client=TestClient(api_mod.app), registry=registry,
                           exec_mod=exec_mod, bundle=exec_mod._current_policy_bundle_hash(),
                           monkeypatch=monkeypatch)


def _lease(server, **over):
    return issue_execution_lease(
        tenant="acme", principal="employee-1", tool_call=SimpleNamespace(**CALL),
        semantic=SEMANTIC, now=datetime.now(UTC), policy_bundle_hash=server.bundle,
        proposal_id=over.get("proposal_id", "prop-1"), grant_jti=over.get("grant_jti", "grant-1"),
    )


def _post(server, lease, token: str):
    return server.client.post(
        "/v1/execution/dispatch-leased",
        json={"lease": lease.to_dict(), "tool_call": CALL, "tenant_id": "acme"},
        headers={"Authorization": f"Bearer {token}"},
    )


def _events(server) -> list[str]:
    return [entry.payload.get("event") for entry in server.exec_mod._CHAIN.entries("acme")]


def test_authority_domain_does_not_serve_dispatch_leased(server) -> None:
    server.monkeypatch.delenv("REMORA_EXECUTION_DOMAIN_ROLE", raising=False)
    for token in ("agent", "hop", "admin"):
        response = _post(server, _lease(server), token)
        assert response.status_code == 404, (token, response.text)
    assert server.registry.CALLS == []


def test_agent_operator_token_cannot_dispatch_on_the_executor(server) -> None:
    server.monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    response = _post(server, _lease(server), "agent")
    assert response.status_code == 403, response.text
    assert server.registry.CALLS == []


@pytest.mark.parametrize("unlinked", [{"proposal_id": ""}, {"grant_jti": ""},
                                      {"proposal_id": "", "grant_jti": ""}])
def test_an_unlinked_lease_is_refused_even_with_a_valid_signature(server, unlinked) -> None:
    server.monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    response = _post(server, _lease(server, **unlinked), "hop")
    assert response.status_code == 200
    body = response.json()["tool_execution"]
    assert body["executed"] is False
    assert body["refusal_reason"] == "lease_unlinked"
    assert server.registry.CALLS == []


def test_an_admitted_lease_is_recorded_before_and_after_dispatch(server) -> None:
    server.monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")
    response = _post(server, _lease(server), "hop")
    assert response.status_code == 200, response.text
    assert response.json()["tool_execution"]["executed"] is True
    assert len(server.registry.CALLS) == 1
    events = _events(server)
    assert events.index("lease_dispatch_admitted") < events.index("lease_dispatch_result")
    admitted = next(e.payload for e in server.exec_mod._CHAIN.entries("acme")
                    if e.payload.get("event") == "lease_dispatch_admitted")
    assert admitted["proposal_id"] == "prop-1"
    assert admitted["grant_jti"] == "grant-1"
    assert admitted["tool_name"] == CALL["tool_name"]


def test_audit_failure_refuses_before_the_tool_runs(server) -> None:
    server.monkeypatch.setenv("REMORA_EXECUTION_DOMAIN_ROLE", "executor")

    class Broken(TenantAuditChain):
        def append(self, *args, **kwargs):
            raise RuntimeError("chain store down")

    server.exec_mod._CHAIN = Broken()
    response = _post(server, _lease(server), "hop")
    body = response.json()["tool_execution"]
    assert body["executed"] is False
    assert body["refusal_reason"] == "audit_unavailable"
    assert server.registry.CALLS == []


def test_agent_facing_roles_do_not_hold_dispatch() -> None:
    import servers.api as api_mod

    for role in ("operator", "reviewer", "viewer", "effect_verifier"):
        assert "dispatch" not in api_mod._BUILTIN_ROLE_PERMISSIONS[role], role
    assert api_mod._BUILTIN_ROLE_PERMISSIONS["dispatch_hop"] == {"dispatch"}


def test_a_root_path_does_not_move_the_route_out_of_the_domain_check(server) -> None:
    """Review of the fix: request.url.path carries the ASGI root_path, so a
    proxy prefix made every domain lookup miss."""
    import servers.api as api_mod

    server.monkeypatch.delenv("REMORA_EXECUTION_DOMAIN_ROLE", raising=False)
    client = TestClient(api_mod.app, root_path="/remora")
    response = client.post(
        "/remora/v1/execution/dispatch-leased",
        json={"lease": _lease(server).to_dict(), "tool_call": CALL, "tenant_id": "acme"},
        headers={"Authorization": "Bearer hop"},
    )
    assert response.status_code == 404, response.text
    assert server.registry.CALLS == []


def test_production_refuses_a_config_that_grants_dispatch_to_another_role(monkeypatch) -> None:
    import servers.api as api

    api._validate_service_only_capabilities()  # the shipped config passes
    tampered = {**api._role_permissions_map(), "operator": {"assess", "execute", "dispatch"}}
    monkeypatch.setattr(api, "_role_permissions_map", lambda: tampered)
    with pytest.raises(RuntimeError, match="operator:dispatch"):
        api._validate_service_only_capabilities()
    source = Path(api.__file__).read_text(encoding="utf-8")
    assert "if _is_production_mode():\n    _validate_service_only_capabilities()" in source


def test_the_ot_pilot_approver_can_approve_critical_tools_and_cannot_execute() -> None:
    """Review of the fix: moving the approver from admin to reviewer left it
    unable to approve any OT write, because every OT tool is critical and a
    critical approval requires senior_authority."""
    import json
    import re

    import servers.api as api

    compose = (Path(__file__).resolve().parents[1] / "deploy" / "ot-pilot"
               / "docker-compose.yml").read_text(encoding="utf-8")
    table = compose.split("REMORA_API_TOKENS: >-", 1)[1].split("REMORA_API_BEARER_TOKEN", 1)[0]
    roles = {entry["actor_id"]: entry["role"] for entry in (
        json.loads(match) for match in re.findall(r'(\{"tenant":[^}]*\})', table))}
    approver = roles["ot-approver"]

    critical = api._RISK_PROFILE_CONFIG["profiles"]["critical"]["action"]["approval_role"]
    defaults = api._RISK_PROFILE_CONFIG["access_defaults"]["tenant_defaults"]
    assert approver in {critical, "admin"}
    assert approver in defaults["reviewer_roles"]
    permissions = api._role_permissions_map()[approver]
    assert "execute" not in permissions and "dispatch" not in permissions
    assert roles["ot-agent"] == "operator"
