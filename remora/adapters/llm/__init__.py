# Author: Stian Skogbrott
# License: Apache-2.0
"""LLM adapters — platform-agnostic model access layer."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResponse:
    """Standardised response from any LLM adapter."""
    text: str
    model: str
    usage_prompt_tokens: int = 0
    usage_completion_tokens: int = 0


class LLMAdapter(ABC):
    """Abstract base class for LLM adapters.

    All REMORA oracle implementations can use any adapter that implements
    this interface. This decouples the consensus engine from any specific
    model provider.
    """

    @abstractmethod
    def complete(self, prompt: str, *, max_tokens: int = 512, temperature: float = 0.0) -> LLMResponse:
        """Send a completion request to the model."""
        ...

    @abstractmethod
    def model_id(self) -> str:
        """Return a unique identifier for the model (for audit and logging)."""
        ...
