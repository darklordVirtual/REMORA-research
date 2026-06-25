# Author: Stian Skogbrott
# License: Apache-2.0
"""Google Gemini oracle (free tier: 1500 req/day for gemini-1.5-flash).

Get a free API key at https://aistudio.google.com.
Set environment variable: GEMINI_API_KEY=AIza...
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from remora.core import Oracle

class GeminiOracle(Oracle):
    """Oracle backed by Google's Gemini API."""

    def __init__(self, model: str = "gemini-1.5-flash"):
        self._model = model
        self._api_key = os.environ.get("GEMINI_API_KEY", "")

    @property
    def name(self) -> str:
        return f"gemini/{self._model}"

    def _call(self, prompt: str) -> tuple[str, float, float]:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY not set.")
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self._model}:generateContent?key={self._api_key}")
        payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 256}}).encode()
        req = urllib.request.Request(url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return text, 0.0, (time.perf_counter() - t0) * 1000
