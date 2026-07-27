# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Model-family taxonomy and cross-family consensus enforcement.

Pre-registered for the 2026-07 clean benchmark round (SAP v2): a consensus
ensemble must never contain two oracles whose models share a weight family.
Within-family inter-oracle correlation (ρ̄) inflates effective agreement —
the retired Groq swarm was three Meta LLaMA models, so its "3-oracle
consensus" was closer to an effective N of 2 (see the old warning in
remora/oracles/factory.py history).

Family = weight ancestry, not hosting provider. Distilled models are pinned
to their BACKBONE family (a deepseek-r1 distill of qwen-32b shares qwen
weights and failure modes, whoever taught it).
"""
from __future__ import annotations

from collections.abc import Iterable

# Explicit pins take precedence over pattern rules (distills, ambiguous ids).
_EXPLICIT: dict[str, str] = {
    "deepseek-r1-distill-qwen-32b": "qwen",
    "deepseek-r1-distill-llama-70b": "meta-llama",
}

# Ordered pattern → family rules, matched against the lowercased id.
_PATTERNS: tuple[tuple[str, str], ...] = (
    ("gpt-oss", "openai"),
    ("gpt-", "openai"),
    ("openai/", "openai"),
    ("llama", "meta-llama"),
    ("qwen", "qwen"),
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    ("gemma", "google"),
    ("gemini", "google"),
    ("claude", "anthropic"),
    ("anthropic", "anthropic"),
    ("deepseek", "deepseek"),
    ("kimi", "moonshot"),
    ("moonshot", "moonshot"),
    ("allam", "allam"),
    ("bge-", "baai"),
    ("command", "cohere"),
    ("phi-", "microsoft"),
)

# The originally pre-registered trio, all hosted on Groq (availability +
# JSON compliance live-verified 2026-07-27; the old meta-llama/llama-4-scout
# id is gone from the Groq catalog entirely). Superseded for the live
# segment by CROSS_FAMILY_CF_MODELS (SAP v2 §2 amendment, 2026-07-27,
# recorded before the first live benchmark call): the Groq free-tier daily
# token quota is shared with the deployed workers and was exhausted.
CROSS_FAMILY_GROQ_MODELS: list[str] = [
    "llama-3.3-70b-versatile",   # Meta LLaMA
    "openai/gpt-oss-120b",       # OpenAI open-weight
    "qwen/qwen3.6-27b",          # Alibaba Qwen
]

# The Cloudflare Workers AI cross-family trio for the 2026-07 round's live
# segment. Selection basis (declared before any benchmark evaluation):
# Workers AI catalog availability + a 3-prompt JSON-compliance smoke test
# through the same prompt template the benchmark uses (2026-07-27, 3/3 for
# every candidate; @cf/openai/gpt-oss-120b is the documented reserve for
# the qwen slot). No benchmark items or labels were used.
CROSS_FAMILY_CF_MODELS: list[str] = [
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",      # Meta LLaMA
    "@cf/qwen/qwen3-30b-a3b-fp8",                    # Alibaba Qwen
    "@cf/mistralai/mistral-small-3.1-24b-instruct",  # Mistral
]


def model_family(model_id: str) -> str:
    """Classify a model id into its weight family ('unknown' if unmatched)."""
    low = model_id.lower()
    for key, family in _EXPLICIT.items():
        if key in low:
            return family
    for pattern, family in _PATTERNS:
        if pattern in low:
            return family
    return "unknown"


def validate_cross_family(model_ids: Iterable[str]) -> None:
    """Raise ValueError if two models share a family, or a family is unknown.

    Unknown families fail closed: an unclassifiable model cannot be shown to
    be diverse, so it must be added to the taxonomy first.
    """
    seen: dict[str, str] = {}
    for mid in model_ids:
        fam = model_family(mid)
        if fam == "unknown":
            raise ValueError(
                f"cross-family validation: {mid!r} has unknown family — add "
                f"it to remora/oracles/families.py before using it in a "
                f"consensus ensemble"
            )
        if fam in seen:
            raise ValueError(
                f"cross-family validation: {mid!r} and {seen[fam]!r} are both "
                f"{fam} — same-family oracles are not allowed in a consensus "
                f"ensemble (SAP v2)"
            )
        seen[fam] = mid
