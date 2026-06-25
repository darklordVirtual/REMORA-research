# Author: Stian Skogbrott
# License: Apache-2.0
"""Agent framework adapter gateway — Protocol-based integration interface.

PR-9: Defines a ``RemoraGateway`` Protocol so any agent framework
(LangChain, AutoGen, CrewAI, custom) can integrate REMORA with a
minimal shim.

Design
------
The gateway exposes a single ``assess()`` coroutine (async) and a
``assess_sync()`` fallback for synchronous callers.  Concrete
implementations must only implement ``_run_engine()``.

Included implementations
------------------------
- ``LocalGateway``   — wraps the in-process ``Remora`` engine
- ``HttpGateway``    — calls the ``/v1/assess`` REST endpoint (PR-7)

Usage
-----
    from remora.adapters.gateway import LocalGateway
    from remora.genome import Genome
    from remora.engine import Remora
    from remora.oracles.mock import MockOracle

    engine = Remora(oracles=[MockOracle(f"m{i}") for i in range(3)], genome=Genome())
    gateway = LocalGateway(engine=engine)

    result = gateway.assess_sync(
        question="Deploy to production?",
        risk_tier="high",
    )
    print(result.action, result.human_review_required)
"""
from __future__ import annotations

import json
import os
import hashlib
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Gateway result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GatewayResult:
    """Minimal structured result returned by any gateway implementation."""

    action: str               # "accept" | "verify" | "abstain" | "escalate"
    human_review_required: bool
    evidence_required: bool
    explanation: str
    confidence: Optional[float]
    risk_estimate: Optional[float]
    require_rag: bool
    refuse_parametric_verdict: bool
    source_of_decision: str
    state_hash: str
    fallback_used: bool = False

    @property
    def is_safe_to_proceed(self) -> bool:
        """True only when action is ACCEPT and no human review is required."""
        return self.action == "accept" and not self.human_review_required


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class RemoraGateway(Protocol):
    """Protocol that all REMORA gateway adapters must satisfy.

    Any object implementing ``assess_sync()`` qualifies as a RemoraGateway.
    """

    def assess_sync(
        self,
        question: str,
        *,
        context: Optional[str] = None,
        domain: Optional[str] = None,
        risk_tier: Optional[str] = None,
        action_type: Optional[str] = None,
        target_environment: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> GatewayResult:
        ...


class EngineLike(Protocol):
    """Minimal protocol required by LocalGateway."""

    def run(
        self,
        question: str,
        context: Optional[str] = None,
        *,
        domain: Optional[str] = None,
        risk_tier: Optional[str] = None,
        action_type: Optional[str] = None,
        target_environment: Optional[str] = None,
    ) -> object:
        ...

    def report(self, state) -> dict:
        ...


# ---------------------------------------------------------------------------
# LocalGateway — in-process engine
# ---------------------------------------------------------------------------

class LocalGateway:
    """Wraps the in-process ``Remora`` engine as a RemoraGateway.

    This is the recommended integration for latency-sensitive deployments
    where the engine runs in the same process as the agent framework.
    """

    def __init__(
        self,
        engine: EngineLike,
        *,
        enable_cache: bool = True,
        cache_namespace: str = "policy-v1",
    ) -> None:
        self._engine = engine
        self._enable_cache = enable_cache
        self._cache_namespace = cache_namespace
        self._decision_cache: dict[str, GatewayResult] = {}
        self._cache_stats_by_risk: dict[str, dict[str, int]] = {}

    def _risk_key(self, risk_tier: Optional[str]) -> str:
        risk = (risk_tier or "unknown").strip().lower()
        return risk or "unknown"

    def _record_cache_event(self, risk_tier: Optional[str], *, hit: bool) -> None:
        key = self._risk_key(risk_tier)
        stats = self._cache_stats_by_risk.setdefault(key, {"requests": 0, "hits": 0})
        stats["requests"] += 1
        if hit:
            stats["hits"] += 1

    def _cache_key(
        self,
        *,
        question: str,
        context: Optional[str],
        domain: Optional[str],
        risk_tier: Optional[str],
        action_type: Optional[str],
        target_environment: Optional[str],
        tenant_id: Optional[str],
    ) -> str:
        payload = {
            "tenant_id": tenant_id or "default",
            "policy_namespace": self._cache_namespace,
            "question": question,
            "context": context,
            "domain": domain,
            "risk_tier": risk_tier,
            "action_type": action_type,
            "target_environment": target_environment,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def cache_metrics(self) -> dict[str, dict[str, float | int]]:
        out: dict[str, dict[str, float | int]] = {}
        for risk, stats in self._cache_stats_by_risk.items():
            requests = stats.get("requests", 0)
            hits = stats.get("hits", 0)
            hit_rate = (hits / requests) if requests > 0 else 0.0
            out[risk] = {
                "requests": requests,
                "hits": hits,
                "hit_rate": round(hit_rate, 3),
            }
        return out

    def assess_sync(
        self,
        question: str,
        *,
        context: Optional[str] = None,
        domain: Optional[str] = None,
        risk_tier: Optional[str] = None,
        action_type: Optional[str] = None,
        target_environment: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> GatewayResult:
        cache_key = self._cache_key(
            question=question,
            context=context,
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
            tenant_id=tenant_id,
        )
        if self._enable_cache:
            cached = self._decision_cache.get(cache_key)
            if cached is not None:
                self._record_cache_event(risk_tier, hit=True)
                return cached

        self._record_cache_event(risk_tier, hit=False)
        state = self._engine.run(
            question=question,
            context=context,
            domain=domain,
            risk_tier=risk_tier,
            action_type=action_type,
            target_environment=target_environment,
        )
        report = self._engine.report(state)
        pd = report["policy_decision"]
        result = GatewayResult(
            action=pd["action"],
            human_review_required=pd["human_review_required"],
            evidence_required=pd["evidence_required"],
            explanation=pd["explanation"],
            confidence=pd.get("confidence"),
            risk_estimate=pd.get("risk_estimate"),
            require_rag=report["require_rag"],
            refuse_parametric_verdict=report["refuse_parametric_verdict"],
            source_of_decision=pd["source_of_decision"],
            state_hash=report["state_hash"],
            fallback_used=pd.get("fallback_used", False),
        )
        if self._enable_cache:
            self._decision_cache[cache_key] = result
        return result


# ---------------------------------------------------------------------------
# HttpGateway — calls /v1/assess REST endpoint
# ---------------------------------------------------------------------------

class HttpGateway:
    """Calls the REMORA REST API (PR-7 ``/v1/assess``) over HTTP.

    Use when the agent framework runs in a different process or container
    from the REMORA engine.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout_seconds: float = 30.0,
        bearer_token: str | None = None,
    ) -> None:
        # Basic scheme validation — same pattern as OPAAdapter SEC-4
        import urllib.parse
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"HttpGateway base_url scheme must be http/https, got '{parsed.scheme}'")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._bearer_token = bearer_token or os.getenv("REMORA_API_BEARER_TOKEN")

    def assess_sync(
        self,
        question: str,
        *,
        context: Optional[str] = None,
        domain: Optional[str] = None,
        risk_tier: Optional[str] = None,
        action_type: Optional[str] = None,
        target_environment: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> GatewayResult:
        payload = json.dumps({
            "question": question,
            "context": context,
            "domain": domain,
            "risk_tier": risk_tier,
            "action_type": action_type,
            "target_environment": target_environment,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        if tenant_id:
            headers["X-Remora-Tenant"] = tenant_id

        req = urllib.request.Request(
            f"{self._base_url}/v1/assess",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError(
                f"HttpGateway: REMORA API unreachable at {self._base_url}: {exc}"
            ) from exc

        pd = body["policy_decision"]
        return GatewayResult(
            action=pd["action"],
            human_review_required=pd["human_review_required"],
            evidence_required=pd["evidence_required"],
            explanation=pd["explanation"],
            confidence=pd.get("confidence"),
            risk_estimate=pd.get("risk_estimate"),
            require_rag=body["require_rag"],
            refuse_parametric_verdict=body["refuse_parametric_verdict"],
            source_of_decision=pd["source_of_decision"],
            state_hash=body["state_hash"],
            fallback_used=pd.get("fallback_used", False),
        )


def _typecheck_gateway_impl(_: RemoraGateway) -> None:
    """No-op helper for static type-checking of gateway implementations."""


_typecheck_gateway_impl(HttpGateway())
