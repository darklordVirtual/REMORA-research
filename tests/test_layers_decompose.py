# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""adaptive_decompose: the engine's question-splitting layer (L1)."""
from __future__ import annotations

from types import SimpleNamespace

from remora.layers import adaptive_decompose


class _Oracle:
    def __init__(self, subs):
        self.prompts = []
        self._subs = subs

    def ask(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(extracted={"subquestions": self._subs} if self._subs is not ... else {})


def test_simple_strategy_and_missing_oracles_keep_the_question():
    o = _Oracle(["a", "b"])
    assert adaptive_decompose("q", [o], 2, "simple") == ["q"]
    assert adaptive_decompose("q", [], 2, "chain") == ["q"]
    assert adaptive_decompose("q", [o], 1, "chain") == ["q"]
    assert o.prompts == []


def test_chain_uses_the_decompose_prompt_and_caps_the_count():
    o = _Oracle(["a", " b ", "c"])
    assert adaptive_decompose("Is X true?", [o], 2, "chain") == ["a", "b"]
    assert "Split the question below into 2" in o.prompts[0]


def test_other_strategies_use_the_parallel_prompt():
    o = _Oracle(["v1", "v2"])
    assert adaptive_decompose("q", [o], 2, "parallel") == ["v1", "v2"]
    assert "Formulate 2 different ways" in o.prompts[0]


def test_unusable_answers_fall_back_to_the_question():
    for subs in (..., "not a list", ["", "  "]):
        assert adaptive_decompose("q", [_Oracle(subs)], 2, "chain") == ["q"]
