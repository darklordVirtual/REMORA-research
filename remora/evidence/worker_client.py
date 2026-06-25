# Author: Stian Skogbrott
# License: Apache-2.0
"""HTTP client for the GO-STAR REMORA Cloudflare Worker.

The worker runs three AI oracle models in multi-round consensus:
- Groq fast   : llama-3.1-8b-instant
- Groq strong : llama-3.3-70b-versatile
- OpenRouter  : mistralai/mistral-7b-instruct

It is publicly accessible at https://go-star-remora.razorsharp.workers.dev
and requires no authentication.  Responses are KV-cached for 24 h keyed on
a hash of the prompt, so repeated calls with identical inputs are free.

Response schema (ConsensusVerdict)
------------------------------------
  verdict             bool | None    true/false/null (model answer)
  confidence          float          0–1 weighted agreement
  oracle_calls        int            total LLM API calls made
  routed_fast         bool           true when router gate skipped full sweep
  lyapunov_converged  bool           true when Δsupport converged
  supporting_models   int            oracles supporting winning polarity
  total_models        int            total oracles (always 3)
  iterations          int            number of 3-oracle sweeps
  degraded            bool           true when GROQ_API_KEY is missing
  error               str | None     error message if degraded
  summary             str            human-readable verdict summary

Thresholds (from worker /status)
------------------------------------
  router_confidence_min : 0.80  — fast-path gate
  fp_confidence_min     : 0.75  — false-positive endpoint
  exploit_confidence_min: 0.70  — exploitability endpoint
  fuse_confidence_min   : 0.65  — evidence-fusion endpoint
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_WORKER_URL = "https://go-star-remora.razorsharp.workers.dev"

# Workers AI model IDs used by the deployed worker (informational — actual IDs
# are configured via wrangler.toml [vars] and resolved by the worker at runtime).
WORKER_MODELS = {
    "cf_fast":    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "cf_strong":  "@cf/qwen/qwen3-30b-a3b-fp8",
    "cf_diverse": "@cf/mistralai/mistral-small-3.1-24b-instruct",
}
_SSL_CTX = ssl.create_default_context()


@dataclass(frozen=True)
class OracleConsensus:
    """Parsed response from any worker endpoint."""

    verdict: bool | None
    confidence: float
    oracle_calls: int
    routed_fast: bool
    lyapunov_converged: bool
    supporting_models: int
    total_models: int
    iterations: int
    degraded: bool
    error: str | None
    summary: str
    claim: str
    use_case: str
    latency_ms: int

    @classmethod
    def from_dict(cls, data: dict[str, Any], latency_ms: int) -> "OracleConsensus":
        v = data.get("verdict")
        if v is True or v is False:
            verdict: bool | None = bool(v)
        else:
            verdict = None
        return cls(
            verdict=verdict,
            confidence=float(data.get("confidence", 0.0)),
            oracle_calls=int(data.get("oracle_calls", 0)),
            routed_fast=bool(data.get("routed_fast", False)),
            lyapunov_converged=bool(data.get("lyapunov_converged", False)),
            supporting_models=int(data.get("supporting_models", 0)),
            total_models=int(data.get("total_models", 3)),
            iterations=int(data.get("iterations", 0)),
            degraded=bool(data.get("degraded", False)),
            error=data.get("error"),
            summary=str(data.get("summary", "")),
            claim=str(data.get("claim", "")),
            use_case=str(data.get("use_case", "")),
            latency_ms=latency_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence": round(self.confidence, 4),
            "oracle_calls": self.oracle_calls,
            "routed_fast": self.routed_fast,
            "lyapunov_converged": self.lyapunov_converged,
            "supporting_models": self.supporting_models,
            "total_models": self.total_models,
            "iterations": self.iterations,
            "degraded": self.degraded,
            "error": self.error,
            "summary": self.summary,
            "claim": self.claim,
            "use_case": self.use_case,
            "latency_ms": self.latency_ms,
        }


class REMORAWorkerClient:
    """HTTP client for the GO-STAR REMORA consensus worker."""

    def __init__(
        self,
        base_url: str = DEFAULT_WORKER_URL,
        timeout: int = 90,  # Workers AI 70B models: ~2s/call × 9 calls = ~18s worst case
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "REMORA-test/1.0"},
            method="POST",
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL_CTX) as r:
                data = json.loads(r.read().decode("utf-8"))
                return data, int((time.time() - t0) * 1000)
        except urllib.error.HTTPError as exc:
            raise ConnectionError(f"Worker HTTP {exc.code}: {exc.read().decode()[:200]}") from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Worker unreachable: {exc.reason}") from exc

    def status(self) -> dict[str, Any]:
        """Return worker health and oracle availability."""
        req = urllib.request.Request(
            self.base_url + "/status",
            headers={"User-Agent": "REMORA-test/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
            return json.loads(r.read().decode("utf-8"))

    def assess(
        self,
        question: str,
        context: str = "",
        use_case: str = "general",
    ) -> OracleConsensus:
        """General governance question — answer true/false/null."""
        data, ms = self._post("/assess", {
            "question": question,
            "context": context,
            "use_case": use_case,
        })
        return OracleConsensus.from_dict(data, ms)

    def fp_check(
        self,
        description: str,
        cwe: str = "",
        symbol: str = "",
        file_path: str = "",
        context: str = "",
    ) -> OracleConsensus:
        """Is this finding a false positive?  verdict=true means IS a false positive."""
        data, ms = self._post("/false-positive", {
            "hypothesis": {
                "description": description,
                "cwe": cwe,
                "symbol": symbol,
                "file_path": file_path,
            },
            "context": context,
        })
        return OracleConsensus.from_dict(data, ms)

    def exploitability(
        self,
        description: str,
        cwe: str = "",
        source: str = "",
        sink: str = "",
        signals: list[dict[str, Any]] | None = None,
    ) -> OracleConsensus:
        """Is this finding exploitable?  verdict=true means IS exploitable."""
        data, ms = self._post("/exploitability", {
            "hypothesis": {
                "description": description,
                "cwe": cwe,
                "source": source,
                "sink": sink,
            },
            "signals": signals or [],
        })
        return OracleConsensus.from_dict(data, ms)

    def evidence_fusion(
        self,
        description: str,
        oracle_signals: list[dict[str, Any]],
    ) -> OracleConsensus:
        """Fuse multiple oracle signals — verdict=true means finding is confirmed."""
        data, ms = self._post("/evidence-fusion", {
            "finding": {"description": description},
            "oracle_signals": oracle_signals,
        })
        return OracleConsensus.from_dict(data, ms)

    def is_available(self) -> bool:
        """Return True if the worker is reachable and has oracles configured."""
        try:
            s = self.status()
            return s.get("ok", False) is True
        except Exception:
            return False


__all__ = ["DEFAULT_WORKER_URL", "OracleConsensus", "REMORAWorkerClient"]
