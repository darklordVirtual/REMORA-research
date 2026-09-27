# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The live Claude decision path: schema-bound action, and a refusal is not an ABSTAIN."""
from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest

from experiments.evaluate_toolcall_benchmark_v2_live import ACTIONS, _anthropic_live_decide
from remora.toolcall.benchmark_v2 import load_benchmark_v2


def _install_fake_anthropic(monkeypatch, response):
    calls = []

    class _Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_Client))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    return calls


def _text(payload: str):
    return SimpleNamespace(type="text", text=payload)


def test_action_comes_from_the_schema_bound_json(monkeypatch):
    task = load_benchmark_v2()[0]
    response = SimpleNamespace(stop_reason="end_turn", stop_details=None,
                               content=[SimpleNamespace(type="thinking", thinking=""),
                                        _text(json.dumps({"action": "ESCALATE"}))])
    calls = _install_fake_anthropic(monkeypatch, response)

    decision = _anthropic_live_decide(task, "claude-opus-5")

    assert decision.action == "ESCALATE"
    request = calls[0]
    schema = request["output_config"]["format"]["schema"]
    assert schema["properties"]["action"]["enum"] == list(ACTIONS)
    # Thinking counts toward max_tokens; a tiny cap would truncate every answer.
    assert request["max_tokens"] >= 1024


def test_refusal_is_reported_not_scored_as_abstain(monkeypatch):
    task = load_benchmark_v2()[0]
    response = SimpleNamespace(stop_reason="refusal",
                               stop_details=SimpleNamespace(category="cyber"), content=[])
    _install_fake_anthropic(monkeypatch, response)

    with pytest.raises(RuntimeError, match="declined"):
        _anthropic_live_decide(task, "claude-opus-5")
