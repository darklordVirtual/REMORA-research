# Author: Stian Skogbrott
# License: Apache-2.0
"""Factory helpers to build oracle swarms for REMORA."""
from __future__ import annotations
import os
import urllib.request
from typing import Optional
from remora.core import Oracle
from remora.oracles.groq import GroqOracle
from remora.oracles.ollama import OllamaOracle
from remora.oracles.gemini import GeminiOracle
from remora.oracles.openrouter import OpenRouterOracle
from remora.oracles.mock import MockOracle
from remora.oracles.cloudflare_rag import CloudflareRAGOracle


def build_mock_swarm(n: int = 3) -> list[Oracle]:
    """Return n deterministic mock oracles for testing."""
    configs = [("mock_optimist", True, 0.1), ("mock_pessimist", False, 0.1),
               ("mock_noisy", True, 0.4), ("mock_contrarian", False, 0.3)]
    return [MockOracle(name=name, bias=bias, noise=noise) for name, bias, noise in configs[:n]]


def build_groq_swarm() -> list[Oracle]:
    """Return a 3-oracle Groq swarm (requires GROQ_API_KEY).

    .. warning::
        All three models are from the Meta LLaMA family hosted on Groq.
        Within-family inter-oracle correlation (ρ̄) is likely higher than the
        0.15 assumed in the hallucination-risk proxy formula, making the
        effective oracle count closer to 2 than 3.  For genuine diversity,
        use :func:`build_recommended_swarm` instead.
    """
    return [GroqOracle("llama-3.1-8b-instant"),
            GroqOracle("llama-3.3-70b-versatile"),
            GroqOracle("meta-llama/llama-4-scout-17b-16e-instruct")]


def build_cloudflare_swarm(
    worker_url: Optional[str] = None,
    secret: Optional[str] = None,
) -> list[Oracle]:
    """
    Return a 3-oracle Cloudflare swarm exploiting all V2 Worker capabilities.

    Each oracle targets a different domain and routing profile, maximising
    orthogonality in REMORA's correlation matrix:

      oracle[0] — science domain, fast 8B model, reranking enabled
      oracle[1] — legal domain, strong 70B model, reranking enabled
      oracle[2] — general domain, dual-consensus (8B+70B), multilingual

    Requires CLOUDFLARE_WORKER_URL and optionally CLOUDFLARE_ORACLE_SECRET
    environment variables if worker_url / secret are not passed explicitly.
    """
    url = worker_url or os.environ.get("CLOUDFLARE_WORKER_URL", "")
    tok = secret    or os.environ.get("CLOUDFLARE_ORACLE_SECRET")
    if not url:
        raise RuntimeError(
            "build_cloudflare_swarm requires CLOUDFLARE_WORKER_URL to be set."
        )
    return [
        CloudflareRAGOracle(worker_url=url, domain="science",  secret=tok,
                            complexity="auto",  rerank=True,  dual_consensus=False),
        CloudflareRAGOracle(worker_url=url, domain="specialised", secret=tok,
                            complexity="high",  rerank=True,  dual_consensus=False),
        CloudflareRAGOracle(worker_url=url, domain=None,        secret=tok,
                            complexity="auto",  rerank=True,  dual_consensus=True,
                            multilingual=True),
    ]

def build_mixed_swarm() -> list[Oracle]:
    """Return a highly diverse 3-oracle swarm mixing Groq and OpenRouter models."""
    return [
        GroqOracle("llama-3.3-70b-versatile"),
        OpenRouterOracle("anthropic/claude-3.5-sonnet"),
        OpenRouterOracle("openai/gpt-4o")
    ]


def build_recommended_swarm() -> list[Oracle]:
    """Return the recommended production swarm: three heterogeneous model families.

    Pool composition
    ----------------
    - Groq  : Meta LLaMA 3.3 70B  (fast, strong general reasoning)
    - OpenRouter : Anthropic Claude 3.5 Haiku  (RLHF-aligned, different failure modes)
    - OpenRouter : Google Gemma 3 27B  (open-weights, distinct architecture)

    Using three distinct base-model families maximises the inter-oracle
    independence assumed by the hallucination-risk proxy formula
    (ρ̄ ≈ 0.15).  Requires GROQ_API_KEY and OPENROUTER_API_KEY.
    """
    return [
        GroqOracle("llama-3.3-70b-versatile"),
        OpenRouterOracle("anthropic/claude-3.5-haiku"),
        OpenRouterOracle("google/gemma-3-27b-it"),
    ]

def build_swarm(backend: str = "auto") -> list[Oracle]:
    """Build an oracle swarm. backend: auto|groq|gemini|ollama|mock|mixed|recommended|cloudflare."""
    if backend == "auto":
        backend = _detect_backend()
    if backend in {"mixed", "recommended"}:
        return build_recommended_swarm()
    if backend == "groq":
        return build_groq_swarm()
    if backend == "cloudflare":
        return build_cloudflare_swarm()
    if backend == "gemini":
        return [GeminiOracle("gemini-1.5-flash"), GeminiOracle("gemini-1.5-flash-8b")]
    if backend == "ollama":
        return [OllamaOracle("llama3.2"), OllamaOracle("mistral")]
    if backend == "mock":
        return build_mock_swarm(3)
    raise ValueError(f"Unknown backend: {backend!r}")


def _detect_backend() -> str:
    # Prefer 'recommended' (multi-family) when both required keys are present.
    # Using only GROQ_API_KEY falls back to 'groq' (single-family pool).
    if os.environ.get("GROQ_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        return "recommended"
    if os.environ.get("GROQ_API_KEY"): return "groq"
    if os.environ.get("GEMINI_API_KEY"): return "gemini"
    if _ollama_running(): return "ollama"
    return "mock"


def _ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False
