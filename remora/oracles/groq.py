# Author: Stian Skogbrott
# License: Apache-2.0
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

    DEFAULT_MODELS = [
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
        "meta-llama/llama-4-scout-17b-16e-instruct",
    ]

    def __init__(self, model: str = "llama-3.3-70b-versatile", temperature: float = 0.3):
        self._model = model
        self._temperature = max(0.0, min(2.0, temperature))
        self._api_key = os.environ.get("GROQ_API_KEY", "")

    @property
    def name(self) -> str:
        parts = self._model.split("/")[-1].split("-")
        return f"groq/{parts[0]}-{parts[-1]}"

    def _call(self, prompt: str) -> tuple[str, float, float]:
        if not self._api_key:
            raise RuntimeError("GROQ_API_KEY not set. Export: export GROQ_API_KEY=gsk_...")
        payload = json.dumps({"model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature, "max_tokens": 256}).encode()
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
