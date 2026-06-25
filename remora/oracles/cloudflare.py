# Author: Stian Skogbrott
# License: Apache-2.0
"""Cloudflare Workers AI oracle (supports native Fine-tunes/LoRA).

Allows using native Cloudflare models (@cf/meta/...) and custom LoRAs
without routing through AI Gateway, saving quota.

Requires:
  CLOUDFLARE_API_TOKEN or equivalent
  CLOUDFLARE_ACCOUNT_ID
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from typing import Optional

from remora.core import Oracle

class CloudflareOracle(Oracle):
    """Oracle backed directly by Cloudflare Workers AI REST API."""

    def __init__(
        self,
        model: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        temperature: float = 0.0,
        lora: Optional[str] = None
    ):
        self._model = model
        self._temperature = max(0.0, min(2.0, temperature))
        self._lora = lora or os.environ.get("CF_AIG_LORA")

        self._api_key = (
            os.environ.get("CF_AIG_TOKEN")
            or os.environ.get("CLOUDFLARE_API_TOKEN")
            or os.environ.get("CF_AI_GATEWAY_KEY")
        )
        self._account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or os.environ.get("CF_ACCOUNT_ID")

    @property
    def name(self) -> str:
        base = self._model.split('/')[-1]
        if self._lora:
            return f"cf/{base}-lora"
        return f"cf/{base}"

    def _call(self, prompt: str) -> tuple[str, float, float]:
        if not self._api_key:
            raise RuntimeError("Cloudflare API token not set. Set CLOUDFLARE_API_TOKEN.")
        if not self._account_id:
            raise RuntimeError("Cloudflare Account ID not set. Set CLOUDFLARE_ACCOUNT_ID.")

        url = f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}/ai/v1/chat/completions"

        payload_dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature,
            "max_tokens": 512,
        }

        # Add LoRA ID if requested (REST format expects it at the top level for CF Workers AI)
        if self._lora:
            payload_dict["lora"] = self._lora

        payload = json.dumps(payload_dict).encode()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }

        # Optional: AI Gateway routing if CF_GATEWAY_ID is given and we want to use the compat endpoint
        # But this Oracle is specifically designed to hit Workers AI native if desired.
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        elapsed_ms = (time.perf_counter() - t0) * 1000

        # Cloudflare might wrap response depending on endpoint
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
        elif "result" in data and "response" in data["result"]:
            content = data["result"]["response"]
        else:
            raise ValueError(f"Unexpected Cloudflare response format: {data}")

        return content, 0.0, elapsed_ms
