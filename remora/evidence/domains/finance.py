# Author: Stian Skogbrott
# License: Apache-2.0
"""AML / financial compliance evidence provider for REMORA.

Covers FATF typologies, FinCEN SAR patterns, EU AMLD risk indicators, OFAC
sanctions screening, and Basel correspondent-banking risk.

Exact lookup identifiers
------------------------
FATF-TYP-*   FATF money laundering typology codes (stored in attack_ids)
AMLD-RI-*    EU AMLD risk indicator codes (stored in attack_ids)
OFAC-SDN     OFAC SDN match flag (stored in cve_ids)

The ``kev`` field is repurposed as ``sdnmatch``: True when the evidence
record corresponds to an OFAC Specially Designated National match or an
equivalent direct-sanctions-list hit.  These cases always escalate.
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

DEFAULT_FINANCE_EVIDENCE_PATH = (
    Path(__file__).resolve().parents[3]
    / "datasets"
    / "finance_v1"
    / "evidence"
    / "finance_objects.jsonl"
)

FINANCE_PROVIDER_VERSION = "finance-evidence-v1"

_FATF_RE = re.compile(r"\bFATF-TYP-\d{2,3}\b", re.IGNORECASE)
_AMLD_RE = re.compile(r"\bAMLD-RI-\d{2,3}\b", re.IGNORECASE)
_OFAC_RE = re.compile(r"\bOFAC-SDN\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:/+\-]{2,}", re.IGNORECASE)


class FinanceVerdict(str, Enum):
    ESCALATE = "ESCALATE"
    REPORT_READY = "REPORT_READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    LIKELY_FALSE_POSITIVE = "LIKELY_FALSE_POSITIVE"


class FinanceRiskClassification(str, Enum):
    REGULATORY_BREACH = "REGULATORY_BREACH"
    HIGH_RISK_TYPOLOGY = "HIGH_RISK_TYPOLOGY"
    ELEVATED_RISK_INDICATOR = "ELEVATED_RISK_INDICATOR"
    ROUTINE_VARIATION = "ROUTINE_VARIATION"
    LIKELY_FALSE_POSITIVE = "LIKELY_FALSE_POSITIVE"


@dataclass(frozen=True)
class FinanceEvidenceRecord:
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
    fatf_codes: tuple[str, ...] = ()
    amld_codes: tuple[str, ...] = ()
    cwe_ids: tuple[str, ...] = ()
    typology_tags: tuple[str, ...] = ()
    sdnmatch: bool = False
    risk_score: float | None = None
    impact_score: float | None = None
    typology_maturity: str = "unknown"
    remediation: str = ""
    license_note: str = ""
    retrieved_at: str = ""
    version: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FinanceEvidenceRecord":
        raw_attacks = [str(x).upper() for x in data.get("attack_ids", [])]
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
            fatf_codes=tuple(x for x in raw_attacks if x.startswith("FATF-")),
            amld_codes=tuple(x for x in raw_attacks if x.startswith("AMLD-")),
            cwe_ids=tuple(str(x).upper() for x in data.get("cwe_ids", [])),
            typology_tags=tuple(str(x).lower() for x in data.get("packages", [])),
            sdnmatch=bool(data.get("kev", False)),
            risk_score=_optional_unit(data.get("epss_score")),
            impact_score=_optional_float(data.get("cvss_score")),
            typology_maturity=str(data.get("exploit_maturity", "unknown")),
            remediation=str(data.get("remediation", "")),
            license_note=str(data.get("license_note", "")),
            retrieved_at=str(data.get("retrieved_at", "")),
            version=str(data.get("version", "")),
            raw=dict(data),
        )

    @property
    def exact_keys(self) -> set[str]:
        keys: set[str] = set(self.fatf_codes) | set(self.amld_codes) | set(self.cwe_ids)
        keys.update(f"typ:{t}" for t in self.typology_tags)
        if self.sdnmatch:
            keys.add("sdnmatch:true")
        return keys

    @property
    def vector_text(self) -> str:
        parts = [
            self.title, self.content,
            " ".join(self.risk_tags), " ".join(self.fatf_codes),
            " ".join(self.amld_codes), " ".join(self.typology_tags),
            self.remediation,
        ]
        return " ".join(p for p in parts if p).strip()


@dataclass(frozen=True)
class FinanceMatch:
    record: FinanceEvidenceRecord
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
            "fatf_codes": list(self.record.fatf_codes),
            "amld_codes": list(self.record.amld_codes),
            "sdnmatch": self.record.sdnmatch,
            "risk_score": self.record.risk_score,
        }


@dataclass(frozen=True)
class FinanceTriageResult:
    verdict: FinanceVerdict
    governance_action: str
    finance_risk_classification: FinanceRiskClassification
    confidence: float
    evidence_signal: EvidenceSignal
    matches: tuple[FinanceMatch, ...]
    reasoning: str
    exact_identifiers: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "governance_action": self.governance_action,
            "finance_risk_classification": self.finance_risk_classification.value,
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


class FinanceEvidenceProvider:
    """Evidence provider for REMORA AML and financial compliance triage.

    Suitable for:
    - AML/CFT transaction monitoring support
    - EU AMLD compliance screening
    - FATF typology alignment
    - OFAC/sanctions screening context
    """

    def __init__(
        self,
        jsonl_path: str | Path | None = None,
        *,
        top_k: int = 8,
        min_score: float = 0.05,
        strict_load: bool = False,
    ) -> None:
        self.path = Path(jsonl_path) if jsonl_path is not None else DEFAULT_FINANCE_EVIDENCE_PATH
        self.top_k = max(1, int(top_k))
        self.min_score = max(0.0, float(min_score))
        self.strict_load = strict_load
        self.records: tuple[FinanceEvidenceRecord, ...] = ()
        self.load_errors: tuple[str, ...] = ()
        self._exact_index: dict[str, list[FinanceEvidenceRecord]] = {}
        self._load()

    def _load(self) -> None:
        errors: list[str] = []
        records: list[FinanceEvidenceRecord] = []
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
                    records.append(FinanceEvidenceRecord.from_dict(data))
                except Exception as exc:
                    msg = f"{self.path.name} line {line_no}: {exc}"
                    if self.strict_load:
                        raise ValueError(msg) from exc
                    errors.append(msg)
        self.records = tuple(records)
        self.load_errors = tuple(errors)
        self._build_index()

    def _build_index(self) -> None:
        index: dict[str, list[FinanceEvidenceRecord]] = {}
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
            "provider_version": FINANCE_PROVIDER_VERSION,
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
        fatf_codes: Iterable[str] = (),
        amld_codes: Iterable[str] = (),
        typology_tags: Iterable[str] = (),
        risk_tags: Iterable[str] = (),
        top_k: int | None = None,
    ) -> list[FinanceMatch]:
        extracted = _extract_ids(query)
        all_fatf = {x.upper() for x in fatf_codes} | set(extracted["fatf_codes"])
        all_amld = {x.upper() for x in amld_codes} | set(extracted["amld_codes"])
        all_typ = {f"typ:{str(x).lower()}" for x in typology_tags}
        all_tags = {str(x).lower() for x in risk_tags}
        exact_keys = all_fatf | all_amld | all_typ

        query_tokens = set(_tokens(query))
        scored: dict[str, FinanceMatch] = {}

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

            scored[rec.evidence_id] = FinanceMatch(
                record=rec,
                score=round(score, 4),
                exact_match=bool(matched),
                matched_keys=matched,
            )

        matches = sorted(
            scored.values(),
            key=lambda m: (m.score, m.exact_match, m.record.sdnmatch,
                           m.record.risk_score or 0.0, m.record.authority_score),
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
            signal_source="retrieval_finance_evidence",
            provenance={
                "provider_version": FINANCE_PROVIDER_VERSION,
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
        fatf_codes: Iterable[str] = (),
        amld_codes: Iterable[str] = (),
        typology_tags: Iterable[str] = (),
        risk_tags: Iterable[str] = (),
        sdnmatch: bool = False,
        pep_exposure: bool = False,
        high_risk_jurisdiction: bool = False,
        tool_signals: int = 1,
    ) -> FinanceTriageResult:
        """Govern a candidate AML / compliance finding against public evidence."""
        query = f"{title} {description}"
        all_fatf = list(fatf_codes)
        all_amld = list(amld_codes)
        all_typ = list(typology_tags)
        all_tags = list(risk_tags) + [severity]
        if sdnmatch:
            all_tags.append("sdnmatch")
        if pep_exposure:
            all_tags.append("pep")

        extra_keys: set[str] = set()
        if sdnmatch:
            extra_keys.add("sdnmatch:true")

        matches = self.search(
            query,
            fatf_codes=all_fatf,
            amld_codes=all_amld,
            typology_tags=all_typ,
            risk_tags=all_tags,
            top_k=self.top_k,
        )

        # Also pull SDN records if sdnmatch flag is set
        if sdnmatch and "sdnmatch:true" in self._exact_index:
            sdn_records = self._exact_index["sdnmatch:true"]
            sdn_ids = {m.record.evidence_id for m in matches}
            for rec in sdn_records:
                if rec.evidence_id not in sdn_ids:
                    matches = [FinanceMatch(record=rec, score=1.0, exact_match=True,
                                           matched_keys=("sdnmatch:true",))] + matches

        signal = _signal_from_matches(matches)
        ids = _extract_ids(query)
        ids["fatf_codes"] = sorted(set(ids["fatf_codes"]) | {x.upper() for x in all_fatf})
        ids["amld_codes"] = sorted(set(ids["amld_codes"]) | {x.upper() for x in all_amld})

        exact_matches = [m for m in matches if m.exact_match]
        exact_count = len(exact_matches)
        sdn_hit = sdnmatch or any(m.record.sdnmatch for m in exact_matches)
        max_risk = max((m.record.risk_score or 0.0 for m in exact_matches), default=0.0)
        severity_norm = severity.lower()

        risk_class = _classify_finance_risk(
            matches,
            severity=severity_norm,
            exact_count=exact_count,
            sdn_hit=sdn_hit,
            max_risk=max_risk,
        )

        confidence = min(
            1.0,
            0.42 * signal.evidence_strength
            + 0.22 * signal.source_reliability
            + 0.16 * signal.citation_coverage
            + 0.08 * min(1.0, exact_count / 2)
            + (0.06 if sdn_hit else 0.0)
            + (0.04 if max_risk >= 0.80 else 0.0)
            + (0.02 if tool_signals >= 2 else 0.0)
            + (0.02 if pep_exposure else 0.0)
            + (0.02 if high_risk_jurisdiction else 0.0),
        )
        confidence = round(confidence, 3)

        if sdn_hit:
            verdict = FinanceVerdict.ESCALATE
            action = "ESCALATE"
            reason = "OFAC SDN or equivalent sanctions-list match — immediate escalation required"
        elif risk_class == FinanceRiskClassification.HIGH_RISK_TYPOLOGY and exact_count >= 2 and (pep_exposure or high_risk_jurisdiction):
            verdict = FinanceVerdict.ESCALATE
            action = "ESCALATE"
            reason = "Known high-risk typology combined with elevated-risk context"
        elif severity_norm in {"critical", "high"} and max_risk >= 0.80 and exact_count:
            verdict = FinanceVerdict.ESCALATE
            action = "ESCALATE"
            reason = "High-risk typology with elevated probability signal"
        elif confidence >= 0.68 and exact_count and tool_signals >= 2:
            verdict = FinanceVerdict.REPORT_READY
            action = "VERIFY" if severity_norm in {"critical", "high"} else "ACCEPT"
            reason = "Corroborated typology evidence sufficient for SAR / report preparation"
        elif confidence <= 0.22 and signal.contradiction_score >= 0.35:
            verdict = FinanceVerdict.LIKELY_FALSE_POSITIVE
            action = "VERIFY"
            reason = "Weak support and contradiction evidence suggest normal business variation"
        else:
            verdict = FinanceVerdict.NEEDS_REVIEW
            action = "VERIFY"
            reason = "Evidence is useful but not strong enough for autonomous closure"

        return FinanceTriageResult(
            verdict=verdict,
            governance_action=action,
            finance_risk_classification=risk_class,
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
                    "fatf_codes": list(rec.fatf_codes),
                    "amld_codes": list(rec.amld_codes),
                    "sdnmatch": rec.sdnmatch,
                    "risk_score": rec.risk_score,
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
        "fatf_codes": sorted({m.group(0).upper() for m in _FATF_RE.finditer(text)}),
        "amld_codes": sorted({m.group(0).upper() for m in _AMLD_RE.finditer(text)}),
    }


def _classify_finance_risk(
    matches: list[FinanceMatch],
    *,
    severity: str,
    exact_count: int,
    sdn_hit: bool,
    max_risk: float,
) -> FinanceRiskClassification:
    contradiction = max((m.record.contradiction_score for m in matches), default=0.0)
    if contradiction >= 0.45 and not sdn_hit and exact_count <= 1:
        return FinanceRiskClassification.LIKELY_FALSE_POSITIVE
    if sdn_hit:
        return FinanceRiskClassification.REGULATORY_BREACH
    if any(m.exact_match and m.record.typology_maturity in {"confirmed_typology", "known_exploited"} for m in matches):
        return FinanceRiskClassification.HIGH_RISK_TYPOLOGY
    if max_risk >= 0.80 and exact_count:
        return FinanceRiskClassification.HIGH_RISK_TYPOLOGY
    if severity in {"critical", "high"} and exact_count:
        return FinanceRiskClassification.ELEVATED_RISK_INDICATOR
    if any(m.exact_match for m in matches):
        return FinanceRiskClassification.ELEVATED_RISK_INDICATOR
    contradiction = max((m.record.contradiction_score for m in matches), default=0.0)
    if contradiction >= 0.35:
        return FinanceRiskClassification.ROUTINE_VARIATION
    return FinanceRiskClassification.LIKELY_FALSE_POSITIVE


def _signal_from_matches(matches: list[FinanceMatch]) -> EvidenceSignal:
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
    "DEFAULT_FINANCE_EVIDENCE_PATH",
    "FINANCE_PROVIDER_VERSION",
    "FinanceEvidenceProvider",
    "FinanceEvidenceRecord",
    "FinanceMatch",
    "FinanceRiskClassification",
    "FinanceTriageResult",
    "FinanceVerdict",
]
