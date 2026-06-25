# Author: Stian Skogbrott
# License: Apache-2.0
"""OpenRouter oracle (access to many free and paid models).

Get an API key at https://openrouter.ai.
Set environment variable: OPENROUTER_API_KEY=sk-or-...
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from remora.core import Oracle

class OpenRouterOracle(Oracle):
    """Oracle backed by the OpenRouter API."""

    def __init__(self, model: str = "google/gemma-4-27b-it:free", temperature: float = 0.3):
        self._model = model
        self._temperature = max(0.0, min(2.0, temperature))
        self._api_key = os.environ.get("OPENROUTER_API_KEY", "")

    @property
    def name(self) -> str:
        return f"openrouter/{self._model.split('/')[-1].replace(':free', '')[:20]}"

    def _call(self, prompt: str) -> tuple[str, float, float]:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set.")
        payload = json.dumps({"model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature, "max_tokens": 256}).encode()
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
            data=payload, headers={"Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/darklordVirtual/REMORA",
                "X-Title": "REMORA"}, method="POST")
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"], 0.0, (time.perf_counter() - t0) * 1000
