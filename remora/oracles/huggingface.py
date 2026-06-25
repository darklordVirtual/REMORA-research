# Author: Stian Skogbrott
# License: Apache-2.0
"""HuggingFace Inference API oracle (free tier).

Get a free token at https://huggingface.co/settings/tokens.
Set environment variable: HF_TOKEN=hf_...
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from remora.core import Oracle

class HuggingFaceOracle(Oracle):
    """Oracle backed by the HuggingFace Inference API."""

    def __init__(self, model: str = "Qwen/Qwen2.5-7B-Instruct"):
        self._model = model
        self._api_key = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "")

    @property
    def name(self) -> str:
        return f"hf/{self._model.split('/')[-1][:20]}"

    def _call(self, prompt: str) -> tuple[str, float, float]:
        if not self._api_key:
            raise RuntimeError("HF_TOKEN not set.")
        payload = json.dumps({"inputs": prompt, "parameters": {
            "max_new_tokens": 200, "temperature": 0.3, "return_full_text": False}}).encode()
        req = urllib.request.Request(
            f"https://api-inference.huggingface.co/models/{self._model}", data=payload,
            headers={"Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"}, method="POST")
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        text = (data[0].get("generated_text", "") if isinstance(data, list)
                else data.get("generated_text", ""))
        return text, 0.0, (time.perf_counter() - t0) * 1000
