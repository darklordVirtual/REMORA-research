# Author: Stian Skogbrott
# License: Apache-2.0
"""Anthropic (Claude) adapter for REMORA.

Requirements:
    pip install anthropic
"""
from __future__ import annotations

from remora.adapters.llm import LLMAdapter, LLMResponse


class AnthropicAdapter(LLMAdapter):
    """Adapter for the Anthropic Messages API."""

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str | None = None):
        self._model = model
        self._api_key = api_key

    def complete(self, prompt: str, *, max_tokens: int = 512, temperature: float = 0.0) -> LLMResponse:
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)
        resp = client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        return LLMResponse(
            text=text,
            model=resp.model,
            usage_prompt_tokens=resp.usage.input_tokens,
            usage_completion_tokens=resp.usage.output_tokens,
        )

    def model_id(self) -> str:
        return f"anthropic/{self._model}"
