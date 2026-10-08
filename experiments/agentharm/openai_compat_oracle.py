# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""An oracle for any OpenAI-compatible chat-completions endpoint.

The AgentHarm harness routes its oracles through Cloudflare AI Gateway or an
OpenAI base URL (``cf_compat``). It imported ``remora.oracles.OpenAIOracle``,
which does not exist, so every oracle-backed arm fell back to hard blocks.
This is the experiment's own client, kept out of ``remora.oracles`` because
no product path needs it.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from remora.core import Oracle


class OpenAICompatOracle(Oracle):
    """POST {base_url}/chat/completions with a bearer token."""

    def __init__(self, model: str, api_key: str, base_url: str = "https://api.openai.com/v1",
                 temperature: float = 0.0, timeout_s: float = 30.0) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        self._model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._temperature = max(0.0, min(2.0, temperature))
        self._timeout = timeout_s

    @property
    def name(self) -> str:
        return f"openai-compat/{self._model.split('/')[-1]}"

    @property
    def model_id(self) -> str:
        return self._model

    def _call(self, prompt: str) -> tuple[str, float, float]:
        payload = json.dumps({"model": self._model,
                              "messages": [{"role": "user", "content": prompt}],
                              "temperature": self._temperature, "max_tokens": 512}).encode()
        req = urllib.request.Request(
            self._url, data=payload, method="POST",
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json", "User-Agent": "REMORA/0.1"})
        t0 = time.perf_counter()
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
        return data["choices"][0]["message"]["content"], 0.0, (time.perf_counter() - t0) * 1000
