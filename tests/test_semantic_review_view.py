# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Jev's reading for the verifier at VERIFY and the approver at ESCALATE.

VERIFY is a bounded machine lookup (a system of record, RAG or documentation)
followed by a re-run of the router; ESCALATE is a human approval. The view
tells the first what to check and the second where to look, and is read by
neither the approval nor the resolution path.

Scope (declared, not exhaustive): the view's construction and the read
endpoint, with records written directly or by a deterministic provider.
Nothing here is evidence about a live model.
"""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest

from remora.decision_providers import DeterministicDecisionProvider
from remora.decision_providers.enrich import SemanticThresholds
from remora.decision_providers.questions import QUESTION_SET_VERSION_V2_1, REMORA_QUESTIONS_V2_1
from remora.decision_providers.review import ADVISORY, CAVEATS, reviewer_view
from remora.decision_providers.shadow import JsonlShadowSink, shadow_evaluate
from remora.policy.decision_engine import RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from remora.decision_providers.enrich import semantic_state_v2

THRESHOLDS = SemanticThresholds(0.85, 0.85, 0.5, 0.5)
ANSWERS = {q.id: 0.03 for q in REMORA_QUESTIONS_V2_1} | {
    "intent_match": 0.62, "target_matches_request": 0.34, "scope_drift": 0.96,
    "action_reversibility": 1.2, "semantic_risk": 2.4,
}


def _record(answers=ANSWERS, provider=None, tenant="acme", proposal_id="p-1"):
    engine = RemoraDecisionEngine(execution_profile=True)
    obs = PolicyObservation(question="Change VLAN for C123 to 420", risk_tier="high",
                            action_type="configuration_change", target_environment="prod")
    return shadow_evaluate(
        obs, engine.decide(obs).action,
        provider or DeterministicDecisionProvider(answers, question_set_version=QUESTION_SET_VERSION_V2_1),
        engine=engine,
        state=semantic_state_v2(operator_request="Change VLAN for C123 to 420", tool_name="t",
                                arguments={"customer_id": "C129", "also_ports": ["p1"]}),
        thresholds=THRESHOLDS, questions=REMORA_QUESTIONS_V2_1,
        proposal_id=proposal_id, tenant=tenant, tool_name="t",
    ).as_dict()


def test_the_view_says_it_is_advisory_and_carries_its_caveats() -> None:
    view = reviewer_view(_record())
    assert view["authoritative"] is False
    assert view["advisory"] == ADVISORY
    assert view["caveats"] == list(CAVEATS)
    assert view["status"] == "available"


def test_attention_lists_answers_past_their_cut_worst_first() -> None:
    view = reviewer_view(_record())
    assert len(view["attention"]) == 3
    assert view["attention"][0].startswith("The call may act on a different customer")  # 0.34 vs 0.85
    assert "(0.96, cut 0.50)" in view["attention"][1]
    assert view["attention"][2].startswith("The call may not make the change")


def test_answers_carry_the_question_and_a_score_reads_as_its_nearest_level() -> None:
    by_id = {a["id"]: a for a in reviewer_view(_record())["answers"]}
    assert by_id["target_matches_request"]["question"].startswith("Do the identifiers")
    assert by_id["target_matches_request"]["past_threshold"] is True
    assert by_id["injection_override"]["past_threshold"] is False
    assert "operator_request is the trusted task" not in by_id["injection_override"]["question"]
    assert by_id["semantic_risk"]["kind"] == "score"
    assert by_id["semantic_risk"]["reading"].startswith("Many customers are affected")


def test_at_verify_the_view_names_the_checks_a_lookup_should_make() -> None:
    view = reviewer_view(_record())
    assert view["decision"] == "VERIFY" and view["for"] == "verifier"
    checks = [f["check"] for f in view["verification_focus"]]
    assert checks == ["confirm_target", "confirm_scope", "confirm_intent"]
    assert view["verification_focus"][0]["why"].startswith("Look up the identifiers")


def test_any_injection_answer_names_the_untrusted_text_as_not_a_source() -> None:
    view = reviewer_view(_record(ANSWERS | {"injection_override": 0.8, "injection_instruction": 0.7}))
    focus = [f for f in view["verification_focus"] if f["check"] == "exclude_untrusted_text"]
    assert len(focus) == 1 and focus[0]["question_id"] == "injection_override"


def test_the_audience_follows_the_decision() -> None:
    record = _record()
    assert reviewer_view(record | {"actual_action": "ESCALATE"})["for"] == "approver"
    assert reviewer_view(record | {"actual_action": "ABSTAIN"})["for"] is None


def test_a_clean_reading_has_nothing_to_attend_to() -> None:
    clean = ANSWERS | {"intent_match": 0.97, "target_matches_request": 0.96, "scope_drift": 0.04}
    view = reviewer_view(_record(clean))
    assert view["attention"] == [] and view["would_change_to"] is None
    assert view["verification_focus"] == []


def test_a_failed_provider_is_shown_as_failed_not_as_clean() -> None:
    view = reviewer_view(_record(provider=DeterministicDecisionProvider({})))
    assert view["status"] == "failed" and view["attention"] == []
    assert "provider unavailable" in view["reason"]


def test_the_view_has_no_authority_bearing_field() -> None:
    forbidden = {"grant", "grant_id", "token", "execution_token", "lease", "approved", "allow",
                 "signature", "review_item_id", "capability"}
    assert not (set(reviewer_view(_record())) & forbidden)


# ── the read endpoint ───────────────────────────────────────────────────────

pytest.importorskip("fastapi")


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "review-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "review-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    for var in ("REMORA_TOOLSPEC_BUNDLE", "REMORA_TOOLSPEC_SIGNING_KEY", "REMORA_TOOLSPEC_TRUSTED_IDENTITIES"):
        monkeypatch.delenv(var, raising=False)

    import servers.api as api_mod
    import servers.execution_api as exec_mod

    state = {"tenant": "acme"}
    monkeypatch.setattr(api_mod, "_authenticate", lambda request: (state["tenant"], "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "agent-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    exec_mod._reset_toolspec_bundle()

    class _Inline:
        def submit(self, fn, *args):
            fn(*args)

    from servers.semantic_shadow import SemanticShadow

    shadow = SemanticShadow(
        provider=DeterministicDecisionProvider(ANSWERS, question_set_version=QUESTION_SET_VERSION_V2_1),
        engine=exec_mod._ENGINE, sink=JsonlShadowSink(tmp_path / "shadow.jsonl"), set_name="v2.1",
        thresholds=THRESHOLDS, tenants=frozenset({"acme"}), executor=_Inline(),
    )
    monkeypatch.setattr(exec_mod, "_SEMANTIC_SHADOW", shadow)
    return TestClient(api_mod.app), exec_mod, shadow, state


CALL = {"tool_name": "read_telemetry", "arguments": {"sensor": "P-1"},
        "target_environment": "prod", "schema_valid": True}


def _assess(client) -> str:
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    return r.json()["proposal_id"]


def _read(client, proposal_id):
    return client.get(f"/v1/execution/proposals/{proposal_id}/semantic-assessment")


def test_an_unknown_proposal_is_a_404(api) -> None:
    client, *_ = api
    assert _read(client, "no-such-proposal").status_code == 404


def test_not_enabled_when_the_shadow_is_off(api, monkeypatch) -> None:
    client, exec_mod, _shadow, _state = api
    monkeypatch.setattr(exec_mod, "_SEMANTIC_SHADOW", None)
    body = _read(client, _assess(client)).json()
    assert body["status"] == "not_enabled" and body["authoritative"] is False


def test_an_unresolved_request_says_why_it_was_not_evaluated(api) -> None:
    client, *_ = api
    body = _read(client, _assess(client)).json()
    assert body["status"] == "request_not_resolved"


def test_a_recorded_reading_is_returned_as_the_reviewer_view(api) -> None:
    client, _exec, shadow, _state = api
    proposal_id = _assess(client)
    shadow.sink.write(SimpleNamespace(as_dict=lambda: _record(proposal_id=proposal_id)))
    body = _read(client, proposal_id).json()
    assert body["status"] == "available"
    assert body["proposal_id"] == proposal_id
    assert len(body["attention"]) == 3


def test_another_tenants_reading_is_never_shown(api) -> None:
    client, _exec, shadow, state = api
    proposal_id = _assess(client)
    shadow.sink.write(SimpleNamespace(as_dict=lambda: _record(proposal_id=proposal_id, tenant="other")))
    assert _read(client, proposal_id).json()["status"] == "request_not_resolved"
    state["tenant"] = "other"
    assert _read(client, proposal_id).status_code == 404


def test_the_approval_and_execution_paths_never_read_the_semantic_assessment() -> None:
    """The reading is for the reviewer; no code that approves or executes uses it."""
    import servers.execution_api as exec_mod
    from remora.execution import service

    paths = (exec_mod.approve, exec_mod.execute, service.execute_approved_item,
             service.dispatch_pending_intent, service.redeem_accept_token)
    for fn in paths:
        source = inspect.getsource(fn)
        assert "semantic_assessment" not in source and "SEMANTIC_SHADOW" not in source, fn.__name__
        assert "reviewer_view" not in source, fn.__name__


def test_records_written_by_the_shadow_include_their_thresholds(tmp_path) -> None:
    record = _record()
    assert record["thresholds"] == {"intent_match": 0.85, "target_matches_request": 0.85,
                                    "possible_injection": 0.5, "scope_drift": 0.5}
    json.dumps(record)
