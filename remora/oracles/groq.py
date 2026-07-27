# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Groq Inference API oracle (free tier).

Get a free API key at https://console.groq.com.
Set environment variable: GROQ_API_KEY=gsk_...
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
import urllib.error
from remora.core import Oracle

class GroqOracle(Oracle):
    """Oracle backed by Groq's fast inference API."""

    # Cross-family trio (SAP v2, 2026-07-27). The former all-LLaMA list is
    # retired: same-family consensus is forbidden, and llama-4-scout no
    # longer exists in the Groq catalog.
    DEFAULT_MODELS = [
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-120b",
        "qwen/qwen3.6-27b",
    ]

    # Reasoning-style models need explicit handling or they either stream
    # chain-of-thought into the message body or burn the whole max_tokens
    # budget thinking and return empty content (observed live 2026-07-27:
    # qwen3.6 returned "" on 2/3 benchmark prompts with reasoning_format=
    # hidden + 1024 tokens; reasoning_effort=none gives clean JSON at 256).
    _REASONING_EFFORT_NONE = ("qwen3",)
    _REASONING_HIDDEN = ("deepseek-r1",)

    def __init__(self, model: str = "llama-3.3-70b-versatile", temperature: float = 0.3):
        self._model = model
        self._temperature = max(0.0, min(2.0, temperature))
        self._api_key = os.environ.get("GROQ_API_KEY", "")

    @property
    def name(self) -> str:
        parts = self._model.split("/")[-1].split("-")
        return f"groq/{parts[0]}-{parts[-1]}"

    @property
    def model_id(self) -> str:
        """Full model identifier (used for family-diversity validation)."""
        return self._model

    def _call(self, prompt: str) -> tuple[str, float, float]:
        if not self._api_key:
            raise RuntimeError("GROQ_API_KEY not set. Export: export GROQ_API_KEY=gsk_...")
        body = {"model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature, "max_tokens": 1024}
        low = self._model.lower()
        if any(marker in low for marker in self._REASONING_EFFORT_NONE):
            body["reasoning_effort"] = "none"
        elif any(marker in low for marker in self._REASONING_HIDDEN):
            body["reasoning_format"] = "hidden"
        payload = json.dumps(body).encode()
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions", data=payload,
            headers={"Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json", "User-Agent": "REMORA/0.1"},
            method="POST")
        t0 = time.perf_counter()
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    time.sleep(2 ** (attempt + 1)); continue
                raise
        return data["choices"][0]["message"]["content"], 0.0, (time.perf_counter() - t0) * 1000
