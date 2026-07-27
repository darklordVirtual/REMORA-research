# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Tests for model-family taxonomy and cross-family consensus enforcement.

Pre-registered requirement for the 2026-07 clean benchmark round: the
consensus ensemble must not contain two oracles from the same model family
(within-family correlation inflates effective agreement — the old Groq swarm
was three Meta LLaMA models).
"""
from __future__ import annotations

import pytest

from remora.oracles.families import (
    CROSS_FAMILY_GROQ_MODELS,
    model_family,
    validate_cross_family,
)


def test_family_classification() -> None:
    assert model_family("llama-3.3-70b-versatile") == "meta-llama"
    assert model_family("llama-3.1-8b-instant") == "meta-llama"
    assert model_family("meta-llama/llama-4-scout-17b-16e-instruct") == "meta-llama"
    assert model_family("@cf/meta/llama-3.3-70b-instruct-fp8-fast") == "meta-llama"
    assert model_family("openai/gpt-oss-120b") == "openai"
    assert model_family("gpt-4o") == "openai"
    assert model_family("qwen/qwen3.6-27b") == "qwen"
    assert model_family("Qwen/Qwen2.5-7B-Instruct") == "qwen"
    assert model_family("mistralai/mistral-7b-instruct:free") == "mistral"
    assert model_family("@cf/mistralai/mistral-small-3.1-24b-instruct") == "mistral"
    assert model_family("google/gemma-3-27b-it") == "google"
    assert model_family("gemini-1.5-flash") == "google"
    assert model_family("anthropic/claude-3.5-haiku") == "anthropic"
    # Distills are classified by weight ancestry (backbone), pinned explicitly.
    assert model_family("@cf/deepseek-ai/deepseek-r1-distill-qwen-32b") == "qwen"
    assert model_family("deepseek-r1-distill-llama-70b") == "meta-llama"
    assert model_family("deepseek-v3") == "deepseek"


def test_unknown_family_is_flagged() -> None:
    assert model_family("totally-novel-model-9000") == "unknown"


def test_validate_cross_family_rejects_same_family() -> None:
    with pytest.raises(ValueError, match="meta-llama"):
        validate_cross_family([
            "llama-3.1-8b-instant",
            "llama-3.3-70b-versatile",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        ])


def test_validate_cross_family_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown"):
        validate_cross_family(["llama-3.3-70b-versatile", "mystery-model-x"])


def test_validate_cross_family_accepts_diverse_trio() -> None:
    validate_cross_family(CROSS_FAMILY_GROQ_MODELS)  # must not raise
    fams = {model_family(m) for m in CROSS_FAMILY_GROQ_MODELS}
    assert len(fams) == len(CROSS_FAMILY_GROQ_MODELS) == 3


def test_groq_swarm_is_cross_family() -> None:
    from remora.oracles.factory import build_groq_swarm

    swarm = build_groq_swarm()
    fams = [model_family(o.model_id) for o in swarm]
    assert len(set(fams)) == len(fams), f"same-family oracles in swarm: {fams}"
