"""Pluggable evidence providers for REMORA policy routing.

The default provider derives an evidence signal from oracle response
distributions ("oracle_proxy"). Production integrations should supply a
retrieval-backed provider that returns source="retrieval".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, Sequence

from remora.core import OracleResponse
from remora.canonical import phi
from remora.evidence.evidence_types import EvidenceSignal


@dataclass(frozen=True)
class EvidenceProviderResult:
    """Container returned by an EvidenceProvider."""

    signal: EvidenceSignal
    signal_source: str = "oracle_proxy"
    provenance: dict[str, Any] | None = None


class EvidenceProvider(Protocol):
    """Interface for external evidence backends."""

    def fetch(
        self,
        *,
        question: str,
        domain: str | None,
        risk_tier: str | None,
        action_type: str | None,
        target_environment: str | None,
        oracle_responses: Sequence[OracleResponse],
    ) -> EvidenceProviderResult:
        ...


class OracleProxyEvidenceProvider:
    """Default provider using oracle-distribution proxies as evidence signals."""

    def __init__(self, mean_rho_fn: Optional[Callable[[list[str]], float]] = None) -> None:
        self._mean_rho_fn = mean_rho_fn

    def _mean_rho(self, providers: list[str]) -> tuple[float, bool]:
        """Return (mean rho, from_model). from_model=False marks the 0.5
        uninformative fallback (no model supplied, or the model failed)."""
        if self._mean_rho_fn is None:
            # Conservative fallback when no correlation model is supplied.
            return 0.5, False
        try:
            return float(self._mean_rho_fn(providers)), True
        except Exception:
            return 0.5, False

    def fetch(
        self,
        *,
        question: str,
        domain: str | None,
        risk_tier: str | None,
        action_type: str | None,
        target_environment: str | None,
        oracle_responses: Sequence[OracleResponse],
    ) -> EvidenceProviderResult:
        del question, domain, risk_tier, action_type, target_environment

        valid = [r for r in oracle_responses if r.error is None and r.extracted is not None]
        n_valid = len(valid)
        n_total = len(oracle_responses)

        if n_valid == 0:
            return EvidenceProviderResult(
                signal=EvidenceSignal(
                    evidence_strength=0.0,
                    contradiction_score=0.0,
                    citation_coverage=0.0,
                    cross_evidence_consistency=0.0,
                    source_reliability=0.0,
                ),
                signal_source="oracle_proxy",
            )

        polarity_counts: dict = {}
        for r in valid:
            v = phi(r.extracted)
            polarity_counts[v.polarity] = polarity_counts.get(v.polarity, 0) + 1

        max_count = max(polarity_counts.values()) if polarity_counts else 0
        majority_fraction = max_count / n_valid
        contradiction = 1.0 - majority_fraction

        coverage = n_valid / n_total if n_total > 0 else 0.0
        providers = [r.provider for r in valid]
        consistency, rho_from_model = self._mean_rho(providers)
        # Reliability of a PROXY source must not report 1.0 when no
        # correlation model backs it (external review 2026-07-28, N5): with
        # a real model, consistency+0.5 caps at 1.0 as before; on the
        # uninformative fallback, report the fallback value itself (0.5).
        if rho_from_model:
            reliability = max(0.0, min(1.0, consistency + 0.5))
        else:
            reliability = consistency
        strength = majority_fraction * consistency

        return EvidenceProviderResult(
            signal=EvidenceSignal(
                evidence_strength=round(strength, 3),
                contradiction_score=round(contradiction, 3),
                citation_coverage=round(coverage, 3),
                cross_evidence_consistency=round(consistency, 3),
                source_reliability=round(reliability, 3),
            ),
            signal_source="oracle_proxy",
        )
