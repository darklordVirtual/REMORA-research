# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The AgentHarm gate reaches the engine, and an unreadable verdict is never ACCEPT.

``RemoraGate.assess`` called ``assess_sync`` on the bare ``Remora`` engine,
which has only ``run``/``report``. Every oracle-backed assessment raised and
was recorded as VERIFY, so the ``remora_full`` and ``single_oracle`` arms
measured the error path, not REMORA. Had the call succeeded, the verdict was
read from a non-existent ``outcome`` attribute with an ACCEPT default: the
gate would have passed everything. Both paths are pinned here.
"""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

from remora.adapters.gateway import LocalGateway
from tests.test_agentharm_solvers import _install_fake_inspect_ai


class _Engine:
    """run()/report() like remora.engine.Remora, with a scripted decision."""

    def __init__(self, action: str, risk: float | None = 0.9) -> None:
        self.action, self.risk = action, risk
        self.calls: list[tuple[str, dict]] = []

    def run(self, question, context=None, **kw):
        self.calls.append((question, kw))
        return SimpleNamespace()

    def report(self, state):
        return {
            "policy_decision": {
                "action": self.action, "human_review_required": self.action != "accept",
                "evidence_required": False, "explanation": "scripted",
                "confidence": 0.4, "risk_estimate": self.risk,
                "source_of_decision": "scripted",
            },
            "require_rag": False, "refuse_parametric_verdict": False,
            "state_hash": "h",
        }


@pytest.fixture()
def mod(monkeypatch, tmp_path):
    _install_fake_inspect_ai(monkeypatch)
    sys.modules.pop("experiments.agentharm.remora_mediated_solver", None)
    m = importlib.import_module("experiments.agentharm.remora_mediated_solver")
    monkeypatch.setattr(m, "ENVELOPE_LOG", str(tmp_path / "envelopes.jsonl"))
    return m


def _gate(mod, engine):
    gate = mod.RemoraGate(mode="hardblocks_only")
    gate.engine = LocalGateway(engine, enable_cache=False)
    gate.effective_mode = "full"
    return gate


@pytest.mark.parametrize("action", ["accept", "verify", "abstain", "escalate"])
def test_the_engine_decision_reaches_the_envelope(mod, action) -> None:
    engine = _Engine(action)
    env = _gate(mod, engine).assess("get_weather", {"city": "Oslo"}, session_id="s")
    assert env["assess_error"] is None, env["assess_error"]
    assert env["gate"]["outcome"] == action.upper()
    assert env["gate"]["risk_estimate"] == 0.9
    assert len(engine.calls) == 1
    question, kw = engine.calls[0]
    assert question.startswith("get_weather(")
    assert set(kw) >= {"domain", "risk_tier", "action_type"}


def test_an_unrecognised_or_missing_action_is_verify_never_accept(mod) -> None:
    assert mod._outcome_of(SimpleNamespace(action="ship_it")) == "VERIFY"
    assert mod._outcome_of(SimpleNamespace()) == "VERIFY"
    assert mod._outcome_of(SimpleNamespace(outcome="ACCEPT")) == "VERIFY"


def test_an_engine_error_is_recorded_and_verify(mod) -> None:
    class Broken(_Engine):
        def run(self, question, context=None, **kw):
            raise RuntimeError("oracle down")

    env = _gate(mod, Broken("accept")).assess("get_weather", {}, session_id="s")
    assert env["gate"]["outcome"] == "VERIFY"
    assert "oracle down" in env["assess_error"]


def test_the_engine_builder_returns_a_gateway(mod, monkeypatch) -> None:
    import experiments.agentharm.cf_compat as cf

    monkeypatch.setattr(cf, "resolve_api_key", lambda: "k")
    monkeypatch.setattr(cf, "resolve_base_url", lambda: "http://127.0.0.1:9")
    built, reason = mod._build_remora_engine(single_oracle=False)
    assert reason is None, reason
    assert callable(getattr(built, "assess_sync", None))
    # One oracle cannot form a consensus: the arm degrades, and says why.
    single, why = mod._build_remora_engine(single_oracle=True)
    assert single is None and why.startswith("single_oracle_unsupported")


def test_the_oracle_client_posts_to_the_configured_endpoint(monkeypatch) -> None:
    import io
    import json
    import urllib.request

    from experiments.agentharm.openai_compat_oracle import OpenAICompatOracle

    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["auth"] = req.full_url, req.headers["Authorization"]
        seen["body"] = json.loads(req.data)
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    o = OpenAICompatOracle(model="gpt-4o-mini", api_key="k", base_url="http://gw.example/v1/")
    text, _, _ = o._call("hello")
    assert text == "ok"
    assert seen["url"] == "http://gw.example/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "gpt-4o-mini"
    with pytest.raises(ValueError):
        OpenAICompatOracle(model="m", api_key="")
