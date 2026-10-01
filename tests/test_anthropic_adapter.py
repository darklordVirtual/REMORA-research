# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for the Anthropic adapter's request shape and response parsing."""
import sys
import types

import pytest

from remora.adapters.llm.anthropic import AnthropicAdapter


def _install_fake(monkeypatch, content, stop_reason="end_turn"):
    calls = {}

    class _Messages:
        def create(self, **kw):
            calls.update(kw)
            return types.SimpleNamespace(
                content=content,
                model=kw["model"],
                stop_reason=stop_reason,
                stop_details=None,
                usage=types.SimpleNamespace(input_tokens=3, output_tokens=5),
            )

    fake = types.SimpleNamespace(
        Anthropic=lambda api_key=None: types.SimpleNamespace(messages=_Messages())
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return calls


def _block(kind, **kw):
    return types.SimpleNamespace(type=kind, **kw)


def test_skips_thinking_blocks_and_omits_sampling(monkeypatch):
    calls = _install_fake(monkeypatch, [_block("thinking", thinking=""), _block("text", text="ok")])
    resp = AnthropicAdapter().complete("q", temperature=0.7)
    assert resp.text == "ok"
    assert "temperature" not in calls
    assert calls["max_tokens"] == 16000
    assert calls["model"] == "claude-opus-5"


def test_refusal_fails_closed(monkeypatch):
    _install_fake(monkeypatch, [], stop_reason="refusal")
    with pytest.raises(RuntimeError, match="declined"):
        AnthropicAdapter().complete("q")
