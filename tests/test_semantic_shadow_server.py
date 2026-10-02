# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The semantic shadow on the enforcing assess path changes nothing it touches.

Pins the configuration contract (off by default, refused when half set), the
gates in front of the provider (tenant opt-in, a server-resolved operator
request), the bounded queue, and, through the real ``/v1/execution/assess``
route, that the response is the same with the shadow on, off or failing.

Scope (declared, not exhaustive): deterministic providers and a synchronous
executor. Nothing here is evidence about a live model.
"""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest

from remora.decision_providers import DeterministicDecisionProvider
from remora.decision_providers.enrich import SemanticThresholds
from remora.decision_providers.questions import QUESTION_SET_VERSION_V2_1, REMORA_QUESTIONS_V2_1
from remora.decision_providers.shadow import JsonlShadowSink
from remora.policy.decision_engine import DecisionAction, RemoraDecisionEngine
from remora.policy.observation import PolicyObservation
from servers import semantic_shadow as ss

ENV = {
    "REMORA_SEMANTIC_SHADOW": "1",
    "REMORA_SEMANTIC_SHADOW_TENANTS": "acme, beta",
    "REMORA_SEMANTIC_SHADOW_QUESTIONS": "v2.1",
    "REMORA_SEMANTIC_SHADOW_THRESHOLDS": "intent=0.85,target=0.85,injection=0.5,drift=0.5",
}
CLEAN = {q.id: 0.02 for q in REMORA_QUESTIONS_V2_1} | {
    "intent_match": 0.95, "target_matches_request": 0.95, "scope_drift": 0.05,
    "action_reversibility": 0.2, "semantic_risk": 1.0,
}


class _Inline:
    """Runs submitted work at once, so a test can read the record."""

    def submit(self, fn, *args):
        fn(*args)


def _factory(answers=CLEAN):
    return lambda version, model: DeterministicDecisionProvider(answers, question_set_version=version)


def _env(monkeypatch, tmp_path, **overrides):
    for key in list(ENV) + ["REMORA_SEMANTIC_SHADOW_LOG", "REMORA_SEMANTIC_SHADOW_MODEL"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in (ENV | {"REMORA_SEMANTIC_SHADOW_LOG": str(tmp_path / "shadow.jsonl")} | overrides).items():
        if value is not None:
            monkeypatch.setenv(key, value)


# ── configuration ───────────────────────────────────────────────────────────


def test_off_unless_switched_on(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, REMORA_SEMANTIC_SHADOW=None)
    assert ss.build_semantic_shadow_from_env(engine=object()) is None


@pytest.mark.parametrize(
    ("unset", "message"),
    [
        ("REMORA_SEMANTIC_SHADOW_TENANTS", "names no tenant"),
        ("REMORA_SEMANTIC_SHADOW_QUESTIONS", "must be one of"),
        ("REMORA_SEMANTIC_SHADOW_LOG", "LOG is not set"),
        ("REMORA_SEMANTIC_SHADOW_THRESHOLDS", "no threshold has a default"),
    ],
)
def test_switched_on_without_its_configuration_is_refused(monkeypatch, tmp_path, unset, message) -> None:
    _env(monkeypatch, tmp_path, **{unset: None})
    with pytest.raises(ValueError, match=message):
        ss.build_semantic_shadow_from_env(engine=object(), provider_factory=_factory())


def test_an_unknown_threshold_entry_is_refused(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, REMORA_SEMANTIC_SHADOW_THRESHOLDS="intent=0.8,target=0.8,injection=0.5,drift=0.5,accept=0.1")
    with pytest.raises(ValueError, match="unknown entry"):
        ss.build_semantic_shadow_from_env(engine=object(), provider_factory=_factory())


def test_the_model_is_pinned_by_default_never_an_alias(monkeypatch, tmp_path) -> None:
    seen = {}
    _env(monkeypatch, tmp_path)
    ss.build_semantic_shadow_from_env(
        engine=object(), provider_factory=lambda v, m: seen.setdefault("model", m) or object()
    )
    assert seen["model"] == "jev-1.13.0"


def test_a_full_configuration_builds_the_shadow(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    shadow = ss.build_semantic_shadow_from_env(engine=object(), provider_factory=_factory())
    assert shadow.tenants == frozenset({"acme", "beta"})
    assert shadow.questions is REMORA_QUESTIONS_V2_1
    assert shadow.thresholds == SemanticThresholds(0.85, 0.85, 0.5, 0.5)


# ── the gates in front of the provider ──────────────────────────────────────


def _shadow(tmp_path, answers=CLEAN, **kw):
    engine = RemoraDecisionEngine(execution_profile=True)
    return ss.SemanticShadow(
        provider=DeterministicDecisionProvider(answers, question_set_version=QUESTION_SET_VERSION_V2_1),
        engine=engine, sink=JsonlShadowSink(tmp_path / "s.jsonl"), set_name="v2.1",
        thresholds=SemanticThresholds(0.85, 0.85, 0.5, 0.5), tenants=frozenset({"acme"}),
        tool_description=lambda name: "Disables one switch port.", executor=_Inline(), **kw,
    ), engine


def _context(engine, *, tenant="acme", resolved=True, arguments=None, untrusted="Storm on port 7."):
    obs = PolicyObservation(
        question="Shut down port sw-1/0/7 per incident I-77.", risk_tier="high",
        action_type="configuration_change", target_environment="prod",
        intent_authority_present=True if resolved else None,
    )
    action = engine.decide(obs).action
    return {
        "tenant": tenant, "proposal_id": "p-1", "observation": obs,
        "proposal": SimpleNamespace(tool_name="network.shutdown_port",
                                    arguments=arguments or {"port": "sw-1/0/7"},
                                    untrusted_context=untrusted),
        "engine_action": action, "final_action": action,
    }


def _records(tmp_path):
    path = tmp_path / "s.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_a_tenant_that_did_not_opt_in_is_never_sent(tmp_path) -> None:
    shadow, engine = _shadow(tmp_path)
    shadow(_context(engine, tenant="other"))
    assert shadow.skipped_tenant == 1 and _records(tmp_path) == []


def test_an_unresolved_operator_request_is_not_evaluated(tmp_path) -> None:
    shadow, engine = _shadow(tmp_path)
    shadow(_context(engine, resolved=False))
    assert shadow.skipped_unresolved == 1 and _records(tmp_path) == []


def test_a_resolved_request_is_recorded_with_the_signed_description(tmp_path) -> None:
    sent = []

    class _Spy(DeterministicDecisionProvider):
        def evaluate(self, *, state, questions, timeout_s):
            sent.append(state)
            return super().evaluate(state=state, questions=questions, timeout_s=timeout_s)

    shadow, engine = _shadow(tmp_path)
    shadow.provider = _Spy(CLEAN | {"injection_extra_action": 0.9}, question_set_version=QUESTION_SET_VERSION_V2_1)
    shadow(_context(engine))
    [record] = _records(tmp_path)
    assert record["tenant"] == "acme" and record["tool_name"] == "network.shutdown_port"
    assert record["actual_action"] == "VERIFY" and record["shadow_action"] == "ESCALATE"
    assert record["would_change"] is True
    assert sent[0]["proposed_call"]["tool_description"] == "Disables one switch port."
    assert sent[0]["untrusted_content"] == {"text": "Storm on port 7."}


def test_a_credential_shaped_argument_is_recorded_as_refused_and_never_sent(tmp_path) -> None:
    shadow, engine = _shadow(tmp_path)
    shadow(_context(engine, arguments={"port": "sw-1/0/7", "admin_password": "x"}))
    [record] = _records(tmp_path)
    assert record["error"].startswith("ValueError: refusing to send credential-shaped keys")
    assert record["shadow_action"] is None


def test_a_full_queue_drops_instead_of_waiting(tmp_path) -> None:
    class _Parked:
        def submit(self, fn, *args):
            pass  # never runs, so nothing is released

    shadow, engine = _shadow(tmp_path, max_pending=2)
    shadow._executor = _Parked()
    for _ in range(5):
        shadow(_context(engine))
    assert shadow.submitted == 2 and shadow.dropped == 3


# ── through the real assess route ───────────────────────────────────────────

pytest.importorskip("fastapi")


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from remora.governance.tenant_chain import TenantAuditChain

    monkeypatch.setenv("REMORA_PDP_SIGNING_KEY", "shadow-pdp-key")
    monkeypatch.setenv("REMORA_LEASE_SIGNING_KEY", "shadow-lease-key")
    monkeypatch.setenv("REMORA_ENV", "development")
    monkeypatch.setenv("REMORA_TOOL_REGISTRY_MODULE", "servers.tool_registry_research")
    monkeypatch.setenv("REMORA_EXECUTION_ARTIFACT_DIR", str(tmp_path / "art"))
    monkeypatch.delenv("REMORA_SEMANTIC_BUNDLE_MODULE", raising=False)
    for var in ("REMORA_TOOLSPEC_BUNDLE", "REMORA_TOOLSPEC_SIGNING_KEY", "REMORA_TOOLSPEC_TRUSTED_IDENTITIES"):
        monkeypatch.delenv(var, raising=False)

    import servers.api as api_mod
    import servers.execution_api as exec_mod

    monkeypatch.setattr(api_mod, "_authenticate", lambda request: ("acme", "reviewer"))
    monkeypatch.setattr(api_mod, "_authenticated_principal", lambda request: "agent-1")
    monkeypatch.setattr(api_mod, "_require_tenant_capability", lambda role, tenant, cap: None)
    exec_mod._QUEUES.clear()
    exec_mod._ITEM_TENANT.clear()
    exec_mod._CHAIN = TenantAuditChain()
    exec_mod._reset_semantic_bundle()
    exec_mod._reset_tool_dispatcher()
    exec_mod._reset_outbox()
    exec_mod._reset_toolspec_bundle()
    return TestClient(api_mod.app), exec_mod


CALL = {"tool_name": "read_telemetry", "arguments": {"sensor": "P-1"},
        "target_environment": "prod", "schema_valid": True}


def _assess(client):
    r = client.post("/v1/execution/assess", json=CALL)
    assert r.status_code == 200, r.text
    body = r.json()
    for volatile in ("proposal_id", "audit", "lineage", "review_item_id", "resolution_plan"):
        body.pop(volatile, None)
    return body


def test_the_shadow_receives_both_actions_after_the_record_is_durable(api, monkeypatch) -> None:
    client, exec_mod = api
    seen = []
    monkeypatch.setattr(exec_mod, "_SEMANTIC_SHADOW",
                        lambda ctx: seen.append((ctx, len(exec_mod._CHAIN.entries("acme")))))
    _assess(client)
    [(ctx, chain_length)] = seen
    assert chain_length == 1, "the shadow ran before the audit record was appended"
    assert isinstance(ctx["engine_action"], DecisionAction)
    assert isinstance(ctx["final_action"], DecisionAction)
    assert ctx["proposal"].tool_name == "read_telemetry"


def test_the_response_is_the_same_with_the_shadow_off_on_or_failing(api, monkeypatch) -> None:
    client, exec_mod = api
    monkeypatch.setattr(exec_mod, "_SEMANTIC_SHADOW", None)
    off = _assess(client)

    monkeypatch.setattr(exec_mod, "_SEMANTIC_SHADOW", lambda ctx: None)
    on = _assess(client)

    def _explodes(ctx):
        raise RuntimeError("sensor down")

    monkeypatch.setattr(exec_mod, "_SEMANTIC_SHADOW", _explodes)
    failing = _assess(client)
    assert off == on == failing


def test_the_shadow_cannot_mutate_what_was_decided(api, monkeypatch) -> None:
    client, exec_mod = api

    def _vandal(ctx):
        ctx["observation"] = dataclasses.replace(ctx["observation"], adversarial_detected=True)
        ctx["final_action"] = DecisionAction.ACCEPT

    monkeypatch.setattr(exec_mod, "_SEMANTIC_SHADOW", None)
    before = _assess(client)
    monkeypatch.setattr(exec_mod, "_SEMANTIC_SHADOW", _vandal)
    assert _assess(client) == before
