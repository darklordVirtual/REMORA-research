# Author: Stian Skogbrott
# License: Apache-2.0
"""AI/ML governance evidence provider for REMORA.

Covers the OWASP LLM Top 10, MITRE ATLAS, EU AI Act risk categories, and
NIST AI RMF.  The provider is independent of any specific AI platform and
does not import proprietary model evaluation tools.

Exact lookup identifiers
------------------------
LLM01 … LLM10    OWASP LLM Top 10 IDs (stored in cve_ids field)
AML.T****        MITRE ATLAS technique IDs (stored in attack_ids field)
EUAIA-*          EU AI Act risk category codes (stored in cve_ids field)

The ``kev`` field is repurposed as ``prohibited``: True when the EU AI Act
explicitly prohibits the practice (Article 5).  These cases always escalate.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

from remora.core import OracleResponse
from remora.evidence.evidence_types import EvidenceSignal
from remora.evidence.provider import EvidenceProviderResult

DEFAULT_AI_GOV_EVIDENCE_PATH = (
    Path(__file__).resolve().parents[3]
    / "datasets"
    / "ai_governance_v1"
    / "evidence"
    / "ai_governance_objects.jsonl"
)

AI_GOV_PROVIDER_VERSION = "ai-governance-v1"

_LLM_RE = re.compile(r"\bLLM\d{2}\b", re.IGNORECASE)
_ATLAS_RE = re.compile(r"\bAML\.T\d{4}\b", re.IGNORECASE)
_EUAIA_RE = re.compile(r"\bEUAIA-[A-Z0-9-]+\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:/+\-]{2,}", re.IGNORECASE)


class AIGovernanceVerdict(str, Enum):
    ESCALATE = "ESCALATE"
    REPORT_READY = "REPORT_READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    LIKELY_FALSE_POSITIVE = "LIKELY_FALSE_POSITIVE"


class AIGovernanceClassification(str, Enum):
    PROHIBITED_USE_CASE = "PROHIBITED_USE_CASE"
    KNOWN_ATTACK_PATTERN = "KNOWN_ATTACK_PATTERN"
    HIGH_RISK_UNMITIGATED = "HIGH_RISK_UNMITIGATED"
    EMERGING_RISK = "EMERGING_RISK"
    WEAK_OR_UNCORROBORATED = "WEAK_OR_UNCORROBORATED"
    LIKELY_FALSE_POSITIVE = "LIKELY_FALSE_POSITIVE"


@dataclass(frozen=True)
class AIGovernanceRecord:
    evidence_id: str
    source: str
    source_url: str
    source_type: str
    title: str
    content: str
    domain: str
    risk_tags: tuple[str, ...]
    authority_score: float
    freshness_score: float
    coverage_score: float
    contradiction_score: float
    llm_ids: tuple[str, ...] = ()
    atlas_ids: tuple[str, ...] = ()
    euaia_ids: tuple[str, ...] = ()
    cwe_ids: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()
    prohibited: bool = False
    risk_priority_score: float | None = None
    impact_score: float | None = None
    risk_evidence_maturity: str = "unknown"
    remediation: str = ""
    license_note: str = ""
    retrieved_at: str = ""
    version: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AIGovernanceRecord":
        return cls(
            evidence_id=str(data["evidence_id"]),
            source=str(data["source"]),
            source_url=str(data.get("source_url", "")),
            source_type=str(data.get("source_type", "static_rag")),
            title=str(data["title"]),
            content=str(data["content"]),
            domain=str(data["domain"]),
            risk_tags=tuple(str(x).lower() for x in data.get("risk_tags", [])),
            authority_score=_unit(data.get("authority_score", 0.0)),
            freshness_score=_unit(data.get("freshness_score", 0.0)),
            coverage_score=_unit(data.get("coverage_score", 0.0)),
            contradiction_score=_unit(data.get("contradiction_score", 0.0)),
            llm_ids=tuple(str(x).upper() for x in data.get("cve_ids", []) if str(x).upper().startswith("LLM")),
            atlas_ids=tuple(str(x).upper() for x in data.get("attack_ids", []) if str(x).upper().startswith("AML.")),
            euaia_ids=tuple(str(x).upper() for x in data.get("cve_ids", []) if str(x).upper().startswith("EUAIA")),
            cwe_ids=tuple(str(x).upper() for x in data.get("cwe_ids", [])),
            packages=tuple(str(x).lower() for x in data.get("packages", [])),
            prohibited=bool(data.get("kev", False)),
            risk_priority_score=_optional_unit(data.get("epss_score")),
            impact_score=_optional_float(data.get("cvss_score")),
            risk_evidence_maturity=str(data.get("exploit_maturity", "unknown")),
            remediation=str(data.get("remediation", "")),
            license_note=str(data.get("license_note", "")),
            retrieved_at=str(data.get("retrieved_at", "")),
            version=str(data.get("version", "")),
            raw=dict(data),
        )

    @property
    def exact_keys(self) -> set[str]:
        keys = set(self.llm_ids) | set(self.atlas_ids) | set(self.euaia_ids) | set(self.cwe_ids)
        keys.update(f"pkg:{p}" for p in self.packages)
        if self.prohibited:
            keys.add("prohibited:true")
        return keys

    @property
    def vector_text(self) -> str:
        parts = [
            self.title, self.content,
            " ".join(self.risk_tags), " ".join(self.llm_ids),
            " ".join(self.atlas_ids), " ".join(self.euaia_ids),
            " ".join(self.cwe_ids), " ".join(self.packages),
            self.remediation,
        ]
        return " ".join(p for p in parts if p).strip()


@dataclass(frozen=True)
class AIGovernanceMatch:
    record: AIGovernanceRecord
    score: float
    exact_match: bool
    matched_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.record.evidence_id,
            "source": self.record.source,
            "source_url": self.record.source_url,
            "title": self.record.title,
            "domain": self.record.domain,
            "risk_tags": list(self.record.risk_tags),
            "score": round(self.score, 4),
            "exact_match": self.exact_match,
            "matched_keys": list(self.matched_keys),
            "llm_ids": list(self.record.llm_ids),
            "atlas_ids": list(self.record.atlas_ids),
            "euaia_ids": list(self.record.euaia_ids),
            "prohibited": self.record.prohibited,
            "risk_priority_score": self.record.risk_priority_score,
        }


@dataclass(frozen=True)
class AIGovernanceTriageResult:
    verdict: AIGovernanceVerdict
    governance_action: str
    risk_classification: AIGovernanceClassification
    confidence: float
    evidence_signal: EvidenceSignal
    matches: tuple[AIGovernanceMatch, ...]
    reasoning: str
    exact_identifiers: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "governance_action": self.governance_action,
            "risk_classification": self.risk_classification.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "exact_identifiers": self.exact_identifiers,
            "evidence_signal": {
                "evidence_strength": self.evidence_signal.evidence_strength,
                "contradiction_score": self.evidence_signal.contradiction_score,
                "citation_coverage": self.evidence_signal.citation_coverage,
                "cross_evidence_consistency": self.evidence_signal.cross_evidence_consistency,
                "source_reliability": self.evidence_signal.source_reliability,
            },
            "evidence": [m.to_dict() for m in self.matches],
        }


class AIGovernanceEvidenceProvider:
    """Evidence provider for REMORA AI/ML governance triage.

    Suitable for:
    - AI safety assessment without proprietary evaluation tools
    - EU AI Act compliance screening
    - OWASP LLM Top 10 and MITRE ATLAS alignment
    """

    def __init__(
        self,
        jsonl_path: str | Path | None = None,
        *,
        top_k: int = 8,
        min_score: float = 0.05,
        strict_load: bool = False,
    ) -> None:
        self.path = Path(jsonl_path) if jsonl_path is not None else DEFAULT_AI_GOV_EVIDENCE_PATH
        self.top_k = max(1, int(top_k))
        self.min_score = max(0.0, float(min_score))
        self.strict_load = strict_load
        self.records: tuple[AIGovernanceRecord, ...] = ()
        self.load_errors: tuple[str, ...] = ()
        self._exact_index: dict[str, list[AIGovernanceRecord]] = {}
        self._load()

    def _load(self) -> None:
        errors: list[str] = []
        records: list[AIGovernanceRecord] = []
        if not self.path.exists():
            self.records = ()
            self.load_errors = (f"file not found: {self.path}",)
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    data = json.loads(line)
                    _validate_required(data)
                    records.append(AIGovernanceRecord.from_dict(data))
                except Exception as exc:
                    msg = f"{self.path.name} line {line_no}: {exc}"
                    if self.strict_load:
                        raise ValueError(msg) from exc
                    errors.append(msg)
        self.records = tuple(records)
        self.load_errors = tuple(errors)
        self._build_index()

    def _build_index(self) -> None:
        index: dict[str, list[AIGovernanceRecord]] = {}
        for rec in self.records:
            for key in rec.exact_keys:
                index.setdefault(key.lower(), []).append(rec)
        self._exact_index = index

    @property
    def store_size(self) -> int:
        return len(self.records)

    def summary(self) -> dict[str, Any]:
        sources: dict[str, int] = {}
        domains: dict[str, int] = {}
        for rec in self.records:
            sources[rec.source] = sources.get(rec.source, 0) + 1
            domains[rec.domain] = domains.get(rec.domain, 0) + 1
        return {
            "provider_version": AI_GOV_PROVIDER_VERSION,
            "path": str(self.path),
            "store_size": self.store_size,
            "sources": dict(sorted(sources.items())),
            "domains": dict(sorted(domains.items())),
            "load_errors": list(self.load_errors),
        }

    def search(
        self,
        query: str,
        *,
        llm_ids: Iterable[str] = (),
        atlas_ids: Iterable[str] = (),
        euaia_ids: Iterable[str] = (),
        cwe_ids: Iterable[str] = (),
        risk_tags: Iterable[str] = (),
        top_k: int | None = None,
    ) -> list[AIGovernanceMatch]:
        extracted = _extract_ids(query)
        all_llm = {x.upper() for x in llm_ids} | set(extracted["llm_ids"])
        all_atlas = {x.upper() for x in atlas_ids} | set(extracted["atlas_ids"])
        all_euaia = {x.upper() for x in euaia_ids} | set(extracted["euaia_ids"])
        all_cwe = {x.upper() for x in cwe_ids}
        all_tags = {str(x).lower() for x in risk_tags}
        exact_keys = all_llm | all_atlas | all_euaia | all_cwe

        query_tokens = set(_tokens(query))
        scored: dict[str, AIGovernanceMatch] = {}

        for rec in self.records:
            rec_keys = {k.lower() for k in rec.exact_keys}
            matched = tuple(sorted(k for k in exact_keys if k.lower() in rec_keys))
            exact_score = min(1.0, 0.58 + 0.12 * len(matched)) if matched else 0.0

            tag_score = _jaccard(all_tags, set(rec.risk_tags)) if all_tags else 0.0
            token_score = _jaccard(query_tokens, set(_tokens(rec.vector_text))) if query_tokens else 0.0
            authority = rec.authority_score * rec.freshness_score

            score = min(1.0, exact_score + 0.22 * tag_score + 0.30 * token_score + 0.10 * authority)
            if score < self.min_score:
                continue

            scored[rec.evidence_id] = AIGovernanceMatch(
                record=rec,
                score=round(score, 4),
                exact_match=bool(matched),
                matched_keys=matched,
            )

        matches = sorted(
            scored.values(),
            key=lambda m: (m.score, m.exact_match, m.record.prohibited,
                           m.record.risk_priority_score or 0.0, m.record.authority_score),
            reverse=True,
        )
        return matches[: (top_k or self.top_k)]

    def fetch(
        self,
        *,
        question: str,
        domain: str | None = None,
        risk_tier: str | None = None,
        action_type: str | None = None,
        target_environment: str | None = None,
        oracle_responses: Sequence[OracleResponse] = (),
    ) -> EvidenceProviderResult:
        del oracle_responses
        query = " ".join(x for x in [question, domain, risk_tier, action_type, target_environment] if x)
        matches = self.search(query)
        signal = _signal_from_matches(matches)
        return EvidenceProviderResult(
            signal=signal,
            signal_source="retrieval_ai_governance_evidence",
            provenance={
                "provider_version": AI_GOV_PROVIDER_VERSION,
                "evidence": [m.to_dict() for m in matches],
                "query": query,
            },
        )

    def triage(
        self,
        *,
        title: str,
        description: str,
        severity: str = "medium",
        llm_ids: Iterable[str] = (),
        atlas_ids: Iterable[str] = (),
        euaia_ids: Iterable[str] = (),
        cwe_ids: Iterable[str] = (),
        risk_tags: Iterable[str] = (),
        in_production: bool = False,
        exposed_endpoint: bool = False,
        tool_signals: int = 1,
    ) -> AIGovernanceTriageResult:
        """Govern a candidate AI governance finding against public evidence."""
        query = f"{title} {description}"
        all_llm = list(llm_ids)
        all_atlas = list(atlas_ids)
        all_euaia = list(euaia_ids)
        all_cwe = list(cwe_ids)
        all_tags = list(risk_tags) + [severity]

        matches = self.search(
            query,
            llm_ids=all_llm,
            atlas_ids=all_atlas,
            euaia_ids=all_euaia,
            cwe_ids=all_cwe,
            risk_tags=all_tags,
            top_k=self.top_k,
        )
        signal = _signal_from_matches(matches)
        ids = _extract_ids(query)
        ids["llm_ids"] = sorted(set(ids["llm_ids"]) | {x.upper() for x in all_llm})
        ids["atlas_ids"] = sorted(set(ids["atlas_ids"]) | {x.upper() for x in all_atlas})
        ids["euaia_ids"] = sorted(set(ids["euaia_ids"]) | {x.upper() for x in all_euaia})

        exact_matches = [m for m in matches if m.exact_match]
        exact_count = len(exact_matches)
        prohibited_hit = any(m.record.prohibited for m in exact_matches)
        max_priority = max((m.record.risk_priority_score or 0.0 for m in exact_matches), default=0.0)
        severity_norm = severity.lower()

        risk_class = _classify_risk(
            matches,
            severity=severity_norm,
            exact_count=exact_count,
            prohibited_hit=prohibited_hit,
            max_priority=max_priority,
        )

        confidence = min(
            1.0,
            0.42 * signal.evidence_strength
            + 0.22 * signal.source_reliability
            + 0.16 * signal.citation_coverage
            + 0.08 * min(1.0, exact_count / 2)
            + (0.06 if prohibited_hit else 0.0)
            + (0.04 if max_priority >= 0.80 else 0.0)
            + (0.02 if tool_signals >= 2 else 0.0),
        )
        confidence = round(confidence, 3)

        if prohibited_hit:
            verdict = AIGovernanceVerdict.ESCALATE
            action = "ESCALATE"
            reason = "EU AI Act prohibited practice identified — no deployment permitted"
        elif risk_class == AIGovernanceClassification.KNOWN_ATTACK_PATTERN and (in_production or exposed_endpoint) and exact_count:
            verdict = AIGovernanceVerdict.ESCALATE
            action = "ESCALATE"
            reason = "Known AI attack pattern confirmed on production or exposed AI system"
        elif severity_norm in {"critical", "high"} and max_priority >= 0.80 and exact_count:
            verdict = AIGovernanceVerdict.ESCALATE
            action = "ESCALATE"
            reason = "High attack-probability confirmed AI risk pattern"
        elif confidence >= 0.68 and exact_count and tool_signals >= 2:
            verdict = AIGovernanceVerdict.REPORT_READY
            action = "VERIFY" if severity_norm in {"critical", "high"} else "ACCEPT"
            reason = "Corroborated evidence sufficient for risk report"
        elif confidence <= 0.22 and signal.contradiction_score >= 0.35:
            verdict = AIGovernanceVerdict.LIKELY_FALSE_POSITIVE
            action = "VERIFY"
            reason = "Weak support and contradiction evidence suggest false positive"
        else:
            verdict = AIGovernanceVerdict.NEEDS_REVIEW
            action = "VERIFY"
            reason = "Evidence is useful but not strong enough for autonomous closure"

        return AIGovernanceTriageResult(
            verdict=verdict,
            governance_action=action,
            risk_classification=risk_class,
            confidence=confidence,
            evidence_signal=signal,
            matches=tuple(matches),
            reasoning=reason,
            exact_identifiers=ids,
        )

    def to_vector_records(self) -> list[dict[str, Any]]:
        return [
            {
                "id": rec.evidence_id,
                "text": rec.vector_text,
                "metadata": {
                    "source": rec.source,
                    "source_url": rec.source_url,
                    "domain": rec.domain,
                    "risk_tags": list(rec.risk_tags),
                    "llm_ids": list(rec.llm_ids),
                    "atlas_ids": list(rec.atlas_ids),
                    "euaia_ids": list(rec.euaia_ids),
                    "prohibited": rec.prohibited,
                    "risk_priority_score": rec.risk_priority_score,
                    "license_note": rec.license_note,
                },
            }
            for rec in self.records
        ]


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------

def _validate_required(data: dict[str, Any]) -> None:
    required = {"evidence_id", "source", "source_url", "title", "content", "domain",
                "risk_tags", "authority_score", "freshness_score", "coverage_score", "contradiction_score"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"missing required fields {sorted(missing)}")


def _extract_ids(text: str) -> dict[str, list[str]]:
    return {
        "llm_ids": sorted({m.group(0).upper() for m in _LLM_RE.finditer(text)}),
        "atlas_ids": sorted({m.group(0).upper() for m in _ATLAS_RE.finditer(text)}),
        "euaia_ids": sorted({m.group(0).upper() for m in _EUAIA_RE.finditer(text)}),
    }


def _classify_risk(
    matches: list[AIGovernanceMatch],
    *,
    severity: str,
    exact_count: int,
    prohibited_hit: bool,
    max_priority: float,
) -> AIGovernanceClassification:
    contradiction = max((m.record.contradiction_score for m in matches), default=0.0)
    if contradiction >= 0.45 and not prohibited_hit and exact_count <= 1:
        return AIGovernanceClassification.LIKELY_FALSE_POSITIVE
    if prohibited_hit:
        return AIGovernanceClassification.PROHIBITED_USE_CASE
    if any(m.exact_match and m.record.risk_evidence_maturity in {"known_exploited_in_wild", "actively_demonstrated"} for m in matches):
        return AIGovernanceClassification.KNOWN_ATTACK_PATTERN
    if max_priority >= 0.80 and exact_count:
        return AIGovernanceClassification.KNOWN_ATTACK_PATTERN
    if severity in {"critical", "high"} and exact_count:
        if any(m.exact_match and ("euaia" in m.record.evidence_id or "high_risk" in m.record.risk_tags) for m in matches):
            return AIGovernanceClassification.HIGH_RISK_UNMITIGATED
        return AIGovernanceClassification.EMERGING_RISK
    if any(m.exact_match for m in matches):
        return AIGovernanceClassification.EMERGING_RISK
    return AIGovernanceClassification.WEAK_OR_UNCORROBORATED


def _signal_from_matches(matches: list[AIGovernanceMatch]) -> EvidenceSignal:
    if not matches:
        return EvidenceSignal(evidence_strength=0.0, contradiction_score=0.0,
                              citation_coverage=0.0, cross_evidence_consistency=0.0, source_reliability=0.0)
    top = list(matches)
    strengths = [m.record.authority_score * m.record.freshness_score * m.score for m in top]
    window = strengths[:3]
    return EvidenceSignal(
        evidence_strength=round(min(1.0, sum(window) / len(window)), 3),
        contradiction_score=round(min(1.0, sum(m.record.contradiction_score for m in top) / len(top)), 3),
        citation_coverage=round(min(1.0, len(top) / 5), 3),
        cross_evidence_consistency=round(_tag_consistency([set(m.record.risk_tags) for m in top]), 3),
        source_reliability=round(sum(m.record.authority_score for m in top) / len(top), 3),
    )


def _tag_consistency(tag_sets: list[set[str]]) -> float:
    if len(tag_sets) < 2:
        return 1.0 if tag_sets else 0.0
    scores = [_jaccard(a, b) for i, a in enumerate(tag_sets) for b in tag_sets[i + 1:]]
    return sum(scores) / len(scores) if scores else 0.0


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _unit(v: Any) -> float:
    return max(0.0, min(1.0, _optional_float(v) or 0.0))


def _optional_unit(v: Any) -> float | None:
    f = _optional_float(v)
    return max(0.0, min(1.0, f)) if f is not None else None


def _optional_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


__all__ = [
    "AI_GOV_PROVIDER_VERSION",
    "DEFAULT_AI_GOV_EVIDENCE_PATH",
    "AIGovernanceClassification",
    "AIGovernanceEvidenceProvider",
    "AIGovernanceMatch",
    "AIGovernanceRecord",
    "AIGovernanceTriageResult",
    "AIGovernanceVerdict",
]
