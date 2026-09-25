# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Anthropic (Claude) adapter for REMORA.

Requirements:
    pip install anthropic
"""
from __future__ import annotations

from remora.adapters.llm import LLMAdapter, LLMResponse


class AnthropicAdapter(LLMAdapter):
    """Adapter for the Anthropic Messages API.

    ``temperature`` is accepted for LLMAdapter compatibility and not sent:
    current Claude models reject sampling parameters with a 400.
    """

    def __init__(self, model: str = "claude-opus-5", api_key: str | None = None):
        self._model = model
        self._api_key = api_key

    def complete(self, prompt: str, *, max_tokens: int = 16000, temperature: float = 0.0) -> LLMResponse:
        import anthropic

        del temperature  # not sent; see class docstring
        client = anthropic.Anthropic(api_key=self._api_key)
        resp = client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"Claude declined the request: {resp.stop_details}")
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResponse(
            text=text,
            model=resp.model,
            usage_prompt_tokens=resp.usage.input_tokens,
            usage_completion_tokens=resp.usage.output_tokens,
        )

    def model_id(self) -> str:
        return f"anthropic/{self._model}"
