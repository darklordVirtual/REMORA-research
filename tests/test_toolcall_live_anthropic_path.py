# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The live Claude decision path and the live cache it writes.

A live run must reach the model it names, keep what it paid for when it stops
early, and report a refusal or truncated answer as a non-answer instead of
letting it pass as an ordinary ABSTAIN.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import experiments.evaluate_toolcall_benchmark_v2_live as live
from experiments.evaluate_toolcall_benchmark_v2_live import ACTIONS, _anthropic_live_decide
from remora.toolcall.benchmark_v2 import load_benchmark_v2
from remora.toolcall.schema import ToolCallDecision


class _FakeClient:
    def __init__(self, response):
        self.calls: list[dict] = []
        self._response = response
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _text(payload: str):
    return SimpleNamespace(type="text", text=payload)


def _task():
    return load_benchmark_v2()[0]


def test_action_comes_from_the_schema_bound_json():
    client = _FakeClient(SimpleNamespace(
        stop_reason="end_turn", stop_details=None,
        content=[SimpleNamespace(type="thinking", thinking=""), _text(json.dumps({"action": "ESCALATE"}))]))

    decision = _anthropic_live_decide(_task(), "claude-opus-5", client)

    assert decision.action == "ESCALATE"
    request = client.calls[0]
    assert request["output_config"]["format"]["schema"]["properties"]["action"]["enum"] == list(ACTIONS)
    assert request["output_config"]["effort"] == "low"
    # Thinking counts toward max_tokens; a tiny cap would truncate every answer.
    assert request["max_tokens"] >= 1024


@pytest.mark.parametrize("response, reason", [
    (SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"), content=[]),
     "refusal"),
    (SimpleNamespace(stop_reason="max_tokens", stop_details=None,
                     content=[SimpleNamespace(type="thinking", thinking="")]),
     "max_tokens"),
    (SimpleNamespace(stop_reason="end_turn", stop_details=None, content=[_text('{"action": ')]),
     "invalid_output"),
])
def test_non_answers_are_recorded_not_raised(response, reason):
    decision = _anthropic_live_decide(_task(), "claude-opus-5", _FakeClient(response))

    assert decision.raw["non_answer"] == reason
    assert decision.raw["model"] == "claude-opus-5"
    assert decision.confidence == 0.0


def test_client_is_built_once_per_run(monkeypatch, tmp_path: Path):
    _stub_live(monkeypatch)
    built = []
    monkeypatch.setattr(live, "_new_anthropic_client", lambda: built.append(1) or object())
    live.build_decision_table(mode="live", cache_path=tmp_path / "cache.json")
    assert built == [1]


def test_default_client_is_built_from_the_sdk(monkeypatch):
    built = []

    class _Sdk:
        def __init__(self, api_key=None):
            built.append(api_key)
            self.messages = _FakeClient(SimpleNamespace(
                stop_reason="end_turn", stop_details=None, content=[_text('{"action": "VERIFY"}')]))

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_Sdk))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    assert _anthropic_live_decide(_task(), "claude-opus-5").action == "VERIFY"
    assert built == ["test-only"]


def _stub_live(monkeypatch, *, fail_after: int | None = None):
    """Replace the three provider calls; count how often each is reached."""
    seen: dict[str, int] = {"gpt": 0, "claude": 0, "gemini": 0}

    def make(name):
        def fn(task, model, *args):
            seen[name] += 1
            if fail_after is not None and seen[name] > fail_after:
                raise ConnectionError("provider went away")
            return ToolCallDecision(action="VERIFY", confidence=0.6, reasons=(f"{name}_live",),
                                    raw={"model": model})
        return fn

    monkeypatch.setattr(live, "_openai_live_decide", make("gpt"))
    monkeypatch.setattr(live, "_anthropic_live_decide", make("claude"))
    monkeypatch.setattr(live, "_gemini_live_decide", make("gemini"))
    monkeypatch.setattr(live, "_new_anthropic_client", lambda: object())
    monkeypatch.setattr(live, "load_benchmark_v2", lambda: load_benchmark_v2()[:5])
    return seen


def test_live_mode_does_not_reuse_replay_seeds(monkeypatch, tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    live.build_decision_table(mode="replay", cache_path=cache_path)
    seen = _stub_live(monkeypatch)

    _, decisions = live.build_decision_table(mode="live", cache_path=cache_path)

    assert seen == {"gpt": 5, "claude": 5, "gemini": 5}
    assert all(d.reasons == ("claude_live",) for d in decisions["single_model_claude"])
    cached = json.loads(cache_path.read_text(encoding="utf-8"))["decisions"]
    # Replay seeds stay where the committed replay reads them.
    assert all(v["raw"]["source"] == "replay_seed" for v in cached["single_model_claude"].values())
    assert set(cached[f"single_model_claude@{live.DEFAULT_ANTHROPIC_MODEL}"]) == {
        t.task_id for t in load_benchmark_v2()[:5]}


def test_live_cache_is_keyed_by_model(monkeypatch, tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    seen = _stub_live(monkeypatch)
    live.build_decision_table(mode="live", cache_path=cache_path)
    live.build_decision_table(mode="live", cache_path=cache_path)
    assert seen["claude"] == 5  # second run is served from the cache

    monkeypatch.setenv("REMORA_LIVE_ANTHROPIC_MODEL", "claude-sonnet-5")
    live.build_decision_table(mode="live", cache_path=cache_path)
    assert seen["claude"] == 10  # a different model is asked again


def test_paid_answers_survive_an_aborted_run(monkeypatch, tmp_path: Path):
    cache_path = tmp_path / "cache.json"
    _stub_live(monkeypatch, fail_after=3)

    with pytest.raises(ConnectionError):
        live.build_decision_table(mode="live", cache_path=cache_path)

    cached = json.loads(cache_path.read_text(encoding="utf-8"))["decisions"]
    assert len(cached[f"single_model_gpt@{live.DEFAULT_OPENAI_MODEL}"]) == 3


def test_live_result_reports_non_answers(monkeypatch, tmp_path: Path):
    _stub_live(monkeypatch)

    def refuse(task, model, *args):
        return ToolCallDecision(action="ABSTAIN", confidence=0.0, reasons=("anthropic_non_answer",),
                                raw={"model": model, "non_answer": "refusal"})

    monkeypatch.setattr(live, "_anthropic_live_decide", refuse)
    result = live.run(mode="live", cache_path=tmp_path / "cache.json")
    assert result["live_non_answers"]["single_model_claude"] == {"refusal": 5}
    assert result["live_non_answers"]["single_model_gpt"] == {}


def test_replay_result_shape_is_unchanged(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(live, "load_benchmark_v2", lambda: load_benchmark_v2()[:5])
    assert "live_non_answers" not in live.run(mode="replay", cache_path=tmp_path / "cache.json")


def test_decision_sources_name_seed_and_live(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(live, "load_benchmark_v2", lambda: load_benchmark_v2()[:5])
    _, replay = live.build_decision_table(mode="replay", cache_path=tmp_path / "r.json")
    assert live.decision_sources(replay)["single_model_claude"] == {
        "source": "replay_seed", "counts": {"replay_seed": 5}}
    _stub_live(monkeypatch)
    _, fresh = live.build_decision_table(mode="live", cache_path=tmp_path / "l.json")
    src = live.decision_sources(fresh)["single_model_claude"]
    assert src["source"] == f"live:{live.DEFAULT_ANTHROPIC_MODEL}"
