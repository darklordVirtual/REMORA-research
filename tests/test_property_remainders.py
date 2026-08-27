# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Invariant tests for the code added against the A-G remainders.

One test per behaviour, each pinned to the refusal or label it introduces.
Property identifiers refer to the Agent Authority Conformance model.
"""
from __future__ import annotations

import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

# --------------------------------------------------------------------------
# D — intent provenance floor in the decision engine
# --------------------------------------------------------------------------


def test_d_strict_profile_refuses_an_unresolved_intent_before_review() -> None:
    from remora.policy.decision_engine import hard_guard_floor
    from remora.policy.observation import PolicyObservation
    from remora.policy.report import DecisionAction, DecisionReason

    obs = PolicyObservation(
        question="q", intent_provenance_required=True, intent_provenance_resolved=False
    )
    action, reason = hard_guard_floor(obs)
    assert action is DecisionAction.ABSTAIN
    assert reason is DecisionReason.INTENT_PROVENANCE_REQUIRED


def test_d_research_posture_is_unchanged_when_not_required() -> None:
    from remora.policy.decision_engine import hard_guard_floor
    from remora.policy.observation import PolicyObservation
    from remora.policy.report import DecisionReason

    obs = PolicyObservation(question="q", intent_provenance_resolved=False)
    floor = hard_guard_floor(obs)
    assert floor is None or floor[1] is not DecisionReason.INTENT_PROVENANCE_REQUIRED


def test_d_a_resolved_intent_passes_the_floor() -> None:
    from remora.policy.decision_engine import hard_guard_floor
    from remora.policy.observation import PolicyObservation
    from remora.policy.report import DecisionReason

    obs = PolicyObservation(
        question="q", intent_provenance_required=True, intent_provenance_resolved=True
    )
    floor = hard_guard_floor(obs)
    assert floor is None or floor[1] is not DecisionReason.INTENT_PROVENANCE_REQUIRED


# --------------------------------------------------------------------------
# B — approver revoked after approval
# --------------------------------------------------------------------------


def _queue_and_item():
    from remora.governance.review_queue import ReviewQueue
    from remora.policy.observation import PolicyObservation
    from remora.policy.report import DecisionAction

    q = ReviewQueue()
    obs = PolicyObservation(
        question="update_work_order(order=WO-1)",
        risk_tier="high",
        action_type="production_write",
        tool_call_hash="h" * 64,
    )
    item = q.enqueue(obs, DecisionAction.VERIFY, queue_ttl=timedelta(hours=1))
    return q, item.item_id, obs


def test_b_revoked_approver_invalidates_a_granted_approval() -> None:
    from remora.governance.review_queue import ExecutionDecision

    q, item_id, obs = _queue_and_item()
    q.approve(item_id, approver="alice", approval_ttl=timedelta(minutes=5))
    q.revoke_principal("alice", reason="left the organisation")

    outcome = q.execute(item_id, obs)
    assert outcome.decision is ExecutionDecision.APPROVAL_INVALIDATED
    assert "revoked" in outcome.detail
    assert any(e.kind == "principal_revoked" for e in q.events)


def test_b_revocation_of_another_principal_does_not_touch_the_approval() -> None:
    from remora.governance.review_queue import ExecutionDecision

    q, item_id, obs = _queue_and_item()
    q.approve(item_id, approver="alice", approval_ttl=timedelta(minutes=5))
    q.revoke_principal("bob")
    assert q.execute(item_id, obs).decision is ExecutionDecision.EXECUTE


def test_b_empty_principal_is_refused() -> None:
    q, _item_id, _obs = _queue_and_item()
    with pytest.raises(ValueError):
        q.revoke_principal("  ")


# --------------------------------------------------------------------------
# G — generic HTTP read-back verifier
# --------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, bytes]] = {}

    def log_message(self, *_a: object) -> None:
        return

    def do_GET(self) -> None:
        status, body = self.routes.get(self.path, (404, b"{}"))
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def readback_server():
    _Handler.routes = {
        "/ok": (200, json.dumps({"state": "sent", "to": "a@example.com"}).encode()),
        "/wrong": (200, json.dumps({"state": "queued"}).encode()),
        "/boom": (500, b"{}"),
        "/text": (200, b"not json"),
    }
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _contract():
    from remora.governance.effect_verification import PostconditionContract

    return PostconditionContract(
        tool_id="send_mail",
        reader="http",
        target_selector={"url": "/ok"},
        expected_fields={"state": "sent"},
    )


def _verify(url: str):
    from remora.integrations.http_readback import verify_http_effect

    return verify_http_effect(
        _contract(), url, proposal_id="p1", execution_id="e1", toolspec_hash="t" * 64
    )


def test_g_declared_delta_verified_against_a_live_read_back(readback_server) -> None:
    from remora.governance.effect_verification import EffectStatus

    result = _verify(readback_server + "/ok")
    assert result.status is EffectStatus.VERIFIED
    assert result.verifier_identity == "remora.integrations.http_readback"


def test_g_mismatch_is_mismatch(readback_server) -> None:
    from remora.governance.effect_verification import EffectStatus

    assert _verify(readback_server + "/wrong").status is EffectStatus.MISMATCH


def test_g_absent_object_is_unobservable_not_mismatch(readback_server) -> None:
    from remora.governance.effect_verification import EffectStatus

    assert _verify(readback_server + "/missing").status is EffectStatus.UNOBSERVABLE


@pytest.mark.parametrize("path", ["/boom", "/text"])
def test_g_a_failed_read_back_is_verifier_failed_not_a_verdict(
    readback_server, path: str
) -> None:
    from remora.governance.effect_verification import EffectStatus

    result = _verify(readback_server + path)
    assert result.status is EffectStatus.VERIFIER_FAILED
    assert result.reason_code == "read_back_failed"


def test_g_unreachable_host_is_verifier_failed() -> None:
    from remora.governance.effect_verification import EffectStatus
    from remora.integrations.http_readback import verify_http_effect

    result = verify_http_effect(
        _contract(), "http://127.0.0.1:9/never", proposal_id="p", execution_id="e",
        toolspec_hash="t" * 64, timeout_seconds=1,
    )
    assert result.status is EffectStatus.VERIFIER_FAILED


# --------------------------------------------------------------------------
# C — legacy /v1/assess binding is labelled and full when a call is present
# --------------------------------------------------------------------------


def test_c_legacy_audit_block_names_its_binding(monkeypatch) -> None:
    from servers import api

    monkeypatch.setattr(api, "_latest_tenant_audit_hash", lambda _t: None)
    monkeypatch.setattr(api, "_sign_envelope_audit_hash", lambda _h: None)

    summary_env = {"request": {"proposed_action": "send", "action_type": "email"}, "audit": {}}
    api._finalize_envelope_audit(
        envelope_payload=summary_env, tenant_id="t1", fallback_hash=None, actor_identity=None
    )
    assert summary_env["audit"]["tool_args_binding"] == "summary"

    full_env = {
        "request": {
            "proposed_action": "send", "action_type": "email",
            "tool_call": {"tool_name": "send_mail", "arguments": {"to": "a@example.com"}},
        },
        "audit": {},
    }
    api._finalize_envelope_audit(
        envelope_payload=full_env, tenant_id="t1", fallback_hash=None, actor_identity=None
    )
    assert full_env["audit"]["tool_args_binding"] == "full_arguments"

    edited = json.loads(json.dumps(full_env))
    edited["request"]["tool_call"]["arguments"]["to"] = "attacker@example.com"
    edited["audit"] = {}
    api._finalize_envelope_audit(
        envelope_payload=edited, tenant_id="t1", fallback_hash=None, actor_identity=None
    )
    assert edited["audit"]["tool_args_hash"] != full_env["audit"]["tool_args_hash"]
