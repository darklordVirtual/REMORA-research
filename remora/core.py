# Author: Stian Skogbrott
# License: Apache-2.0
"""REMORA core — base Oracle ABC and OracleResponse dataclass."""
from __future__ import annotations
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class OracleResponse:
    """Container for a single oracle response."""

    provider: str
    raw_text: str
    extracted: dict
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    error: Optional[str] = None


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from arbitrary text."""
    if not text:
        return {"unstructured": ""}
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"unstructured": text.strip()}


class Oracle(ABC):
    """Abstract base class for all REMORA oracle providers."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def _call(self, prompt: str) -> tuple[str, float, float]: ...

    def ask(self, prompt: str) -> OracleResponse:
        """Send prompt to the oracle and return a structured OracleResponse."""
        try:
            raw_text, cost, latency = self._call(prompt)
            return OracleResponse(
                provider=self.name,
                raw_text=raw_text,
                extracted=_extract_json(raw_text),
                cost_usd=cost,
                latency_ms=latency,
            )
        except Exception as e:
            return OracleResponse(
                provider=self.name,
                raw_text="",
                extracted={"unstructured": ""},
                error=str(e),
            )
