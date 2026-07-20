from __future__ import annotations

import hashlib
import importlib

import pytest
from remora.governance.envelope import validate_decision_envelope_dict

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # type: ignore[import-not-found]


def _load_api_module(monkeypatch: pytest.MonkeyPatch, token: str | None = None):
    # Tests always run in development mode so the no-auth dev fallback is available.
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_API_ALLOW_MOCK_ORACLES", raising=False)
    monkeypatch.delenv("REMORA_API_TOKENS", raising=False)

    if token is None:
        monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    else:
        monkeypatch.setenv("REMORA_API_BEARER_TOKEN", token)
    import servers.api as api

    # Ensure the module picks up any env updates between tests.
    return importlib.reload(api)


def _load_multitenant_api(monkeypatch: pytest.MonkeyPatch, tokens: dict):
    import json as _json

    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("REMORA_API_ALLOW_MOCK_ORACLES", raising=False)
    monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("REMORA_API_TOKENS", _json.dumps(tokens))
    import servers.api as api

    return importlib.reload(api)


def test_header_role_cannot_override_authenticated_token_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P0-A regression: a viewer-bound token must not gain admin capability by
    asserting X-Remora-Role: admin. In multi-tenant mode the token role is
    authoritative; the header must be ignored for authorization."""
    api = _load_multitenant_api(
        monkeypatch,
        {"viewer-tok": {"tenant": "acme", "role": "viewer"}},
    )
    client = TestClient(api.app)

    # viewer has only {"read"} — /v1/assess needs "assess". The admin header
    # must NOT grant it.
    resp = client.post(
        "/v1/assess",
        json={"question": "deploy?", "risk_tier": "high"},
        headers={
            "Authorization": "Bearer viewer-tok",
            "X-Remora-Role": "admin",
        },
    )
    assert resp.status_code == 403, (
        "header role escalation: viewer token + X-Remora-Role:admin was accepted"
    )


def test_authenticated_admin_token_has_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control: an admin-bound token legitimately gets the capability,
    with no X-Remora-Role header present."""
    api = _load_multitenant_api(
        monkeypatch,
        {"admin-tok": {"tenant": "acme", "role": "admin"}},
    )
    client = TestClient(api.app)
    resp = client.post(
        "/v1/assess",
        json={"question": "deploy?", "risk_tier": "high"},
        headers={"Authorization": "Bearer admin-tok"},
    )
    assert resp.status_code == 200


def test_assess_returns_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token=None)
    client = TestClient(api.app)

    resp = client.post(
        "/v1/assess",
        json={"question": "Should we patch this service?", "risk_tier": "medium"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "envelope" in payload
    assert payload["envelope"]["request"]["proposed_action"]
    assert payload["envelope"]["request"]["request_id"] == payload["request_id"]
    assert payload["envelope"]["assessment"]
    assert payload["envelope"]["gate"]
    assert payload["policy_profile"]
    assert "require_human_approval" in payload["review_requirements"]


def test_assess_envelope_conforms_to_schema_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token=None)
    client = TestClient(api.app)

    resp = client.post(
        "/v1/assess",
        json={"question": "Should we patch this service?", "risk_tier": "medium"},
    )
    assert resp.status_code == 200
    payload = resp.json()

    errors = validate_decision_envelope_dict(payload["envelope"])
    assert errors == []


def test_readme_destructive_prod_payload_escalates_before_oracles(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token=None)
    client = TestClient(api.app)

    resp = client.post(
        "/v1/assess",
        json={
            "question": "DROP TABLE users",
            "risk_tier": "critical",
            "action_type": "destructive_write",
            "target_environment": "prod",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["policy_decision"]["action"] == "escalate"
    assert payload["policy_decision"]["source_of_decision"] == "hard_block"
    assert payload["oracle_calls"] == 0
    assert payload["envelope"]["gate"]["outcome"] == "escalate"
    assert payload["envelope"]["gate"]["blocked_action"] == "DROP TABLE users"


def test_assess_requires_bearer_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    resp = client.post(
        "/v1/assess",
        json={"question": "Can I run this migration?", "risk_tier": "high"},
    )
    assert resp.status_code == 401


def test_assess_forbidden_for_viewer_role(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    resp = client.post(
        "/v1/assess",
        json={"question": "Can I run this migration?", "risk_tier": "high"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Role": "viewer",
        },
    )
    assert resp.status_code == 403


def test_assess_accepts_valid_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    resp = client.post(
        "/v1/assess",
        json={"question": "Can I run this migration?", "risk_tier": "high"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["policy_decision"]["action"] in {"accept", "verify", "abstain", "escalate"}


def test_get_envelope_by_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={"question": "Should we rotate certificates?", "risk_tier": "high"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert create.status_code == 200
    req_id = create.json()["request_id"]

    env_resp = client.get(
        f"/v1/envelope/{req_id}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert env_resp.status_code == 200
    payload = env_resp.json()
    assert payload["request_id"] == req_id
    assert payload["tenant_id"] == "default"
    assert payload["envelope"]["request"]
    assert payload["envelope"]["gate"]


def test_tenant_scope_isolation_for_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={"question": "Should we rotate key material?", "risk_tier": "high"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-a",
        },
    )
    assert create.status_code == 200
    req_id = create.json()["request_id"]

    missing = client.get(
        f"/v1/envelope/{req_id}",
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-b",
        },
    )
    assert missing.status_code == 404

    found = client.get(
        f"/v1/envelope/{req_id}",
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-a",
        },
    )
    assert found.status_code == 200


def test_get_audit_record_by_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={"question": "Can we change firewall rules?", "risk_tier": "critical"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert create.status_code == 200
    req_id = create.json()["request_id"]

    audit_resp = client.get(
        f"/v1/audit/{req_id}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert audit_resp.status_code == 200
    payload = audit_resp.json()
    assert payload["request_id"] == req_id
    assert payload["decision"] in {"accept", "verify", "abstain", "escalate"}
    assert isinstance(payload["reasons"], list)


def test_metrics_increments_after_assess(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    m0 = client.get("/v1/metrics", headers={"Authorization": "Bearer test-token"})
    assert m0.status_code == 200
    n0 = m0.json()["assess_total"]

    create = client.post(
        "/v1/assess",
        json={"question": "Should we patch today?", "risk_tier": "medium"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert create.status_code == 200

    m1 = client.get("/v1/metrics", headers={"Authorization": "Bearer test-token"})
    assert m1.status_code == 200
    payload = m1.json()
    assert payload["assess_total"] >= n0 + 1
    assert "decision_counts" in payload
    assert "decision_counts_by_risk" in payload
    assert "slo" in payload
    assert "targets" in payload["slo"]
    assert "breaches" in payload["slo"]


def test_review_and_follow_up_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={"question": "Should we deploy this hotfix?", "risk_tier": "high"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-review",
        },
    )
    assert create.status_code == 200
    req_id = create.json()["request_id"]

    review = client.post(
        "/v1/review",
        json={
            "request_id": req_id,
            "reviewer_id": "alice",
            "decision": "approved",
            "reason": "Change reviewed and rollback plan exists.",
            "evidence_refs": ["ticket-123", "runbook-45"],
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-review",
            "X-Remora-Role": "admin",  # explicit — operator lacks review; admin has wildcard capability
        },
    )
    assert review.status_code == 200
    assert review.json()["status"] == "recorded"

    follow_up = client.post(
        "/v1/follow-up",
        json={
            "request_id": req_id,
            "follow_up_type": "evidence_request",
            "payload": {"required": ["incident-postmortem"]},
            "requested_by": "alice",
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-review",
            # follow_up capability belongs to reviewer/admin, not operator.
            # In single-token mode the role is set at auth time via this header.
            "X-Remora-Role": "reviewer",
        },
    )
    assert follow_up.status_code == 200
    assert follow_up.json()["status"] == "recorded"


def test_review_requires_tenant_profile_approval_role(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={
            "question": "Should we deploy this hotfix?",
            "risk_tier": "high",
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "production",
            "X-Remora-Role": "operator",
        },
    )
    assert create.status_code == 200
    req_id = create.json()["request_id"]

    denied = client.post(
        "/v1/review",
        json={
            "request_id": req_id,
            "reviewer_id": "alice",
            "decision": "approved",
            "reason": "Attempt approval with wrong role.",
            "evidence_refs": ["ticket-456"],
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "production",
            "X-Remora-Role": "operator",
        },
    )
    assert denied.status_code == 403

    allowed = client.post(
        "/v1/review",
        json={
            "request_id": req_id,
            "reviewer_id": "bob",
            "decision": "approved",
            "reason": "Approved by required role.",
            "evidence_refs": ["ticket-456"],
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "production",
            "X-Remora-Role": "domain_expert",
        },
    )
    assert allowed.status_code == 200


def test_evidence_endpoint_records_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={"question": "Should we approve this config change?", "risk_tier": "high"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-evidence",
        },
    )
    assert create.status_code == 200
    req_id = create.json()["request_id"]

    submit = client.post(
        "/v1/evidence",
        json={
            "request_id": req_id,
            "evidence_type": "runbook",
            "payload": {"ref": "rb-2026-05", "summary": "Rollback validated"},
            "submitted_by": "ops-bot",
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-evidence",
        },
    )
    assert submit.status_code == 200
    evidence_payload = submit.json()
    assert evidence_payload["status"] == "recorded"
    assert evidence_payload["evidence_type"] == "runbook"

    m = client.get("/v1/metrics", headers={"Authorization": "Bearer test-token"})
    assert m.status_code == 200
    assert m.json()["evidence_total"] >= 1


def test_evidence_endpoint_is_tenant_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={"question": "Should we open this maintenance window?", "risk_tier": "medium"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-a",
        },
    )
    assert create.status_code == 200
    req_id = create.json()["request_id"]

    wrong_tenant = client.post(
        "/v1/evidence",
        json={
            "request_id": req_id,
            "evidence_type": "ticket",
            "payload": {"id": "INC-42"},
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-b",
        },
    )
    assert wrong_tenant.status_code == 404


def test_rerun_endpoint_replays_same_request_context(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={
            "question": "Should we deploy this change set now?",
            "risk_tier": "medium",
            "domain": "infra",
            "action_type": "write",
            "target_environment": "staging",
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-rerun",
        },
    )
    assert create.status_code == 200
    original_request_id = create.json()["request_id"]

    rerun = client.post(
        "/v1/rerun",
        json={"request_id": original_request_id},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-rerun",
        },
    )
    assert rerun.status_code == 200
    payload = rerun.json()
    assert payload["status"] == "recorded"
    assert payload["original_request_id"] == original_request_id
    assert payload["rerun_request_id"] != original_request_id
    assert payload["replay_mode"] == "same_input"
    assert payload["evidence_records_used"] == 0

    metrics = client.get("/v1/metrics", headers={"Authorization": "Bearer test-token"})
    assert metrics.status_code == 200
    assert metrics.json()["rerun_total"] >= 1


def test_rerun_endpoint_is_tenant_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={"question": "Should we rotate these certs?", "risk_tier": "medium"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-a",
        },
    )
    assert create.status_code == 200
    req_id = create.json()["request_id"]

    wrong_tenant = client.post(
        "/v1/rerun",
        json={"request_id": req_id},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-b",
        },
    )
    assert wrong_tenant.status_code == 404


def test_rerun_uses_persisted_evidence_context(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={
            "question": "Should we proceed with this maintenance action?",
            "risk_tier": "high",
            "domain": "ops",
            "action_type": "write",
            "target_environment": "prod",
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-evidence-rerun",
        },
    )
    assert create.status_code == 200
    req_id = create.json()["request_id"]

    ev = client.post(
        "/v1/evidence",
        json={
            "request_id": req_id,
            "evidence_type": "change_ticket",
            "payload": {"id": "CHG-777", "approved": True},
            "submitted_by": "change-manager",
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-evidence-rerun",
        },
    )
    assert ev.status_code == 200

    rerun = client.post(
        "/v1/rerun",
        json={"request_id": req_id},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-evidence-rerun",
        },
    )
    assert rerun.status_code == 200
    payload = rerun.json()
    assert payload["replay_mode"] == "same_input_plus_evidence"
    assert payload["evidence_records_used"] >= 1
    signal_source = payload["envelope"]["assessment"]["evidence_quality"]["signal_source"]
    assert "external" in signal_source
    assert payload["determinism_checks"]["stable_policy_hash"] is True
    assert payload["policy_hash"].startswith("sha256:")


def test_rerun_reports_determinism_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    create = client.post(
        "/v1/assess",
        json={
            "question": "Should we perform this staged rollout?",
            "risk_tier": "medium",
            "domain": "ops",
            "action_type": "write",
            "target_environment": "staging",
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-rerun-determinism",
        },
    )
    assert create.status_code == 200
    req_id = create.json()["request_id"]

    rerun = client.post(
        "/v1/rerun",
        json={"request_id": req_id},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-rerun-determinism",
        },
    )
    assert rerun.status_code == 200
    payload = rerun.json()
    checks = payload["determinism_checks"]
    assert checks["same_action_as_original"] is True
    assert checks["same_evidence_signal_source"] is True
    assert checks["stable_policy_hash"] is True


def test_openapi_contract_includes_governance_extensions(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    spec_resp = client.get("/openapi.json")
    assert spec_resp.status_code == 200
    spec = spec_resp.json()
    paths = spec.get("paths", {})

    assert "/v1/policy/version" in paths
    assert "get" in paths["/v1/policy/version"]

    assert "/v1/evidence" in paths
    assert "post" in paths["/v1/evidence"]

    assert "/v1/rerun" in paths
    assert "post" in paths["/v1/rerun"]

    components = spec.get("components", {}).get("schemas", {})
    assert "EvidenceRequest" in components
    assert "RerunRequest" in components


def test_prometheus_metrics_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    resp = client.get("/metrics", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    body = resp.text
    assert "# HELP remora_assess_total" in body
    assert "remora_assess_total" in body


def test_policy_version_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    unauthorized = client.get("/v1/policy/version")
    assert unauthorized.status_code == 401

    ok = client.get("/v1/policy/version", headers={"Authorization": "Bearer test-token"})
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["policy_version"].startswith("RemoraDecisionEngine-v")
    assert payload["policy_hash"].startswith("sha256:")
    assert payload["risk_profile_hash"].startswith("sha256:")
    assert payload["schema_hash"].startswith("sha256:")
    assert payload["source"] == "python_decision_engine"
    assert payload["runtime_mode"] in {"development", "production"}


def test_assess_populates_envelope_audit_chain_and_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_ENVELOPE_SIGNING_KEY", "signing-key")
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    first = client.post(
        "/v1/assess",
        json={"question": "Should we approve maintenance action A?", "risk_tier": "high"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-audit-chain",
        },
    )
    assert first.status_code == 200
    first_audit = first.json()["envelope"]["audit"]
    assert first_audit["hash"]
    assert first_audit["signature"]
    assert first_audit["previous_hash"] is None

    second = client.post(
        "/v1/assess",
        json={"question": "Should we approve maintenance action B?", "risk_tier": "high"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-audit-chain",
        },
    )
    assert second.status_code == 200
    second_audit = second.json()["envelope"]["audit"]
    assert second_audit["signature"]
    assert second_audit["previous_hash"] == first_audit["hash"]


def test_make_engine_allows_configured_non_mock_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api_module(monkeypatch, token="test-token")
    from remora.core import Oracle

    class _FakeOracle(Oracle):
        def __init__(self, name: str):
            self._name = name

        @property
        def name(self) -> str:
            return self._name

        def _call(self, prompt: str):
            return '{"answer": true, "claim": "ok", "confidence": 0.9}', 0.0, 1.0

    monkeypatch.setenv("REMORA_ORACLE_BACKEND", "groq")
    monkeypatch.setattr(api, "_is_production_mode", lambda: True)
    monkeypatch.setattr("remora.oracles.factory.build_swarm", lambda backend: [_FakeOracle("o1"), _FakeOracle("o2"), _FakeOracle("o3")])

    engine = api._make_engine()
    assert len(engine.oracles) == 3


def test_production_mode_requires_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.delenv("REMORA_API_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DSN", "postgresql://localhost/remora")

    with pytest.raises(RuntimeError, match="missing required env vars"):
        import servers.api as api

        importlib.reload(api)


def test_production_mode_requires_control_plane_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "token")
    monkeypatch.delenv("REMORA_CONTROL_PLANE_DSN", raising=False)

    with pytest.raises(RuntimeError, match="missing required env vars"):
        import servers.api as api

        importlib.reload(api)


def test_production_mode_requires_oracle_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "token")
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DSN", "postgresql://localhost/remora")
    monkeypatch.delenv("REMORA_ORACLE_BACKEND", raising=False)

    with pytest.raises(RuntimeError, match="missing required env vars"):
        import servers.api as api

        importlib.reload(api)


def test_production_mode_requires_api_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "token")
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DSN", "postgresql://localhost/remora")
    monkeypatch.setenv("REMORA_ORACLE_BACKEND", "groq")
    monkeypatch.delenv("REMORA_API_TOKENS", raising=False)

    with pytest.raises(RuntimeError, match="missing required env vars"):
        import servers.api as api

        importlib.reload(api)


def test_production_mode_rejects_mock_oracle_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMORA_ENV", "production")
    monkeypatch.setenv("REMORA_API_BEARER_TOKEN", "token")
    monkeypatch.setenv("REMORA_CONTROL_PLANE_DSN", "postgresql://localhost/remora")
    monkeypatch.setenv("REMORA_ORACLE_BACKEND", "groq")
    monkeypatch.setenv("REMORA_API_TOKENS", '{"tok":{"tenant":"t","role":"operator"}}')
    monkeypatch.setenv("REMORA_API_ALLOW_MOCK_ORACLES", "true")

    with pytest.raises(RuntimeError, match="mock oracles are disabled"):
        import servers.api as api

        importlib.reload(api)


def test_assess_populates_enterprise_audit_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """assess endpoint must populate schema_version, timestamp_utc, tenant_id, policy_bundle_hash."""
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    resp = client.post(
        "/v1/assess",
        json={"question": "Should we run this DB migration?", "risk_tier": "high"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Tenant": "tenant-ent",
            "X-Remora-Actor": "svc-ci@example.com",
        },
    )
    assert resp.status_code == 200
    audit = resp.json()["envelope"]["audit"]

    assert audit["schema_version"] == "2"
    assert audit["timestamp_utc"] is not None and "T" in audit["timestamp_utc"]
    assert audit["tenant_id"] == "tenant-ent"
    # Identity is credential-derived; the self-reported header is recorded
    # only as an unverified on_behalf_of annotation (non-repudiation).
    expected_principal = "cred-" + hashlib.sha256(b"test-token").hexdigest()[:12]
    assert audit["actor_identity"] == (
        f"{expected_principal} (on_behalf_of=svc-ci@example.com, unverified)"
    )
    assert audit["policy_bundle_hash"] is not None and audit["policy_bundle_hash"].startswith("sha256:")


def test_assess_actor_identity_cannot_be_spoofed_via_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """X-Remora-Actor must never become the audit identity on its own."""
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    resp = client.post(
        "/v1/assess",
        json={"question": "Read replica lag status?", "risk_tier": "low"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Remora-Actor": "ceo@example.com",
        },
    )
    assert resp.status_code == 200
    actor = resp.json()["envelope"]["audit"]["actor_identity"]
    expected_principal = "cred-" + hashlib.sha256(b"test-token").hexdigest()[:12]
    assert actor.startswith(expected_principal)
    assert "unverified" in actor

    # Without the header, the audit identity is exactly the principal.
    resp2 = client.post(
        "/v1/assess",
        json={"question": "Read replica lag status?", "risk_tier": "low"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["envelope"]["audit"]["actor_identity"] == expected_principal


def test_assess_envelope_conforms_to_schema_with_enterprise_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Envelope including new enterprise audit fields must still pass schema validation."""
    api = _load_api_module(monkeypatch, token="test-token")
    client = TestClient(api.app)

    resp = client.post(
        "/v1/assess",
        json={"question": "Should we proceed with this action?", "risk_tier": "medium"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    from remora.governance.envelope import validate_decision_envelope_dict

    errors = validate_decision_envelope_dict(resp.json()["envelope"])
    assert errors == [], f"Schema validation errors after enterprise fields added: {errors}"
