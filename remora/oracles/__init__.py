# Author: Stian Skogbrott
# License: Apache-2.0
"""Oracle backends for REMORA."""
from remora.oracles.groq import GroqOracle
from remora.oracles.ollama import OllamaOracle
from remora.oracles.gemini import GeminiOracle
from remora.oracles.mock import MockOracle
from remora.oracles.huggingface import HuggingFaceOracle
from remora.oracles.openrouter import OpenRouterOracle
from remora.oracles.cloudflare_rag import CloudflareRAGOracle
from remora.oracles.cloudflare import CloudflareOracle
from remora.oracles.roles import (
    OracleRole, RoleOracle, make_role_swarm,
)

__all__ = [
    "GroqOracle", "OllamaOracle", "GeminiOracle", "MockOracle",
    "HuggingFaceOracle", "OpenRouterOracle", "CloudflareRAGOracle",
    "CloudflareOracle",
    "OracleRole", "RoleOracle", "make_role_swarm",
]
