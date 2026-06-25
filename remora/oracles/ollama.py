# Author: Stian Skogbrott
# License: Apache-2.0
"""Ollama local oracle (completely free, no API key required).

Install: https://ollama.com
Pull a model: ollama pull llama3.2
Start server: ollama serve
"""
from __future__ import annotations
import json
import time
import urllib.request
from remora.core import Oracle

class OllamaOracle(Oracle):
    """Oracle backed by a locally running Ollama server."""

    def __init__(self, model: str = "llama3.2", host: str = "http://localhost:11434"):
        self._model = model
        self._host = host.rstrip("/")

    @property
    def name(self) -> str:
        return f"ollama/{self._model}"

    def _call(self, prompt: str) -> tuple[str, float, float]:
        payload = json.dumps({"model": self._model, "prompt": prompt,
            "stream": False, "options": {"temperature": 0.3, "num_predict": 256}}).encode()
        req = urllib.request.Request(f"{self._host}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        return data.get("response", ""), 0.0, (time.perf_counter() - t0) * 1000
