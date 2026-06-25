# Author: Stian Skogbrott
# License: Apache-2.0
"""Deterministic mock oracle for testing REMORA without API keys."""
from __future__ import annotations
import json
import random
import time
from remora.core import Oracle

class MockOracle(Oracle):
    """Deterministic mock oracle. bias=True tends toward True answers, noise adds uncertainty."""

    def __init__(self, name: str = "mock_a", bias: bool = True, noise: float = 0.2):
        self._name = name
        self._bias = bias
        self._noise = noise
        self._rng = random.Random(abs(hash(name)) % 2 ** 32)

    @property
    def name(self) -> str:
        return self._name

    def _call(self, prompt: str) -> tuple[str, float, float]:
        r = self._rng.random()
        if r < self._noise:
            answer, claim = None, "Uncertain"
        elif self._bias:
            answer, claim = True, "The claim is likely correct"
        else:
            answer, claim = False, "The claim is likely incorrect"
        response = json.dumps({"answer": answer, "claim": claim,
            "confidence": round(self._rng.uniform(0.6, 0.95), 2)})
        time.sleep(0.01)
        return response, 0.0, 10.0
