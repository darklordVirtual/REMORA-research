# Author: Stian Skogbrott
# License: Apache-2.0
"""Local model adapter for REMORA.

Supports Ollama, vLLM, and any OpenAI-compatible local server.
These endpoints follow the OpenAI API format but run locally,
enabling air-gapped and on-premises deployment.

Requirements:
    pip install openai  (uses the OpenAI client with a custom base_url)
"""
from __future__ import annotations

from remora.adapters.llm import LLMAdapter, LLMResponse


class LocalVLLMAdapter(LLMAdapter):
    """Adapter for local model servers (Ollama, vLLM, llama.cpp server).

    Parameters
    ----------
    model:
        Model name as recognised by the local server (e.g. 'llama3.1:8b').
    base_url:
        Server URL. Defaults to Ollama's default (http://localhost:11434/v1).
    """

    def __init__(self, model: str = "llama3.1:8b", base_url: str = "http://localhost:11434/v1"):
        self._model = model
        self._base_url = base_url

    def complete(self, prompt: str, *, max_tokens: int = 512, temperature: float = 0.0) -> LLMResponse:
        import openai

        client = openai.OpenAI(api_key="not-needed", base_url=self._base_url)
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
            model=self._model,
            usage_prompt_tokens=usage.prompt_tokens if usage else 0,
            usage_completion_tokens=usage.completion_tokens if usage else 0,
        )

    def model_id(self) -> str:
        return f"local/{self._model}"
