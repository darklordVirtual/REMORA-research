# Author: Stian Skogbrott
# License: Apache-2.0
"""OpenAI API adapter for REMORA.

Connects to the standard OpenAI API (api.openai.com).
For Azure-hosted OpenAI, use azure_openai.py instead.

Requirements:
    pip install openai
"""
from __future__ import annotations

from remora.adapters.llm import LLMAdapter, LLMResponse


class OpenAIAdapter(LLMAdapter):
    """Adapter for the OpenAI completions API."""

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None, base_url: str | None = None):
        self._model = model
        self._api_key = api_key
        self._base_url = base_url

    def complete(self, prompt: str, *, max_tokens: int = 512, temperature: float = 0.0) -> LLMResponse:
        import openai

        client = openai.OpenAI(api_key=self._api_key, base_url=self._base_url)
        resp = client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            text=choice.message.content or "",
            model=resp.model,
            usage_prompt_tokens=usage.prompt_tokens if usage else 0,
            usage_completion_tokens=usage.completion_tokens if usage else 0,
        )

    def model_id(self) -> str:
        return f"openai/{self._model}"
