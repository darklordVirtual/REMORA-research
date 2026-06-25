# Author: Stian Skogbrott
# License: Apache-2.0
"""Cyber evidence provider for REMORA.

This module is a public REMORA evidence layer for cybersecurity triage. It is
intentionally independent of proprietary scanners and does not import GO-STAR.

The provider combines two retrieval modes:
- exact lookup for cyber identifiers such as CVE, CWE, ATT&CK technique,
  package name, KEV status, and EPSS score;
- lexical retrieval over curated evidence text for RAG and vector-store demos.

The intended use is to help REMORA decide whether a security finding is
report-ready, needs review, is likely a false positive, or should be escalated.
Policy is never mutated automatically.
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


DEFAULT_CYBER_EVIDENCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "datasets"
    / "cyber_evidence_v1"
    / "evidence"
    / "cyber_evidence_objects.jsonl"
)

CYBER_PROVIDER_VERSION = "cyber-evidence-v1"

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_CWE_RE = re.compile(r"\bCWE-\d{1,5}\b", re.IGNORECASE)
_ATTACK_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:/+\-]{2,}", re.IGNORECASE)


class CyberTriageVerdict(str, Enum):
    """REMORA cyber triage verdict."""

    REPORT_READY = "REPORT_READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    LIKELY_FALSE_POSITIVE = "LIKELY_FALSE_POSITIVE"
    ESCALATE = "ESCALATE"


class ExploitClassification(str, Enum):
    """Exploit maturity classification for defensive triage."""

    KNOWN_EXPLOITED = "KNOWN_EXPLOITED"
    PUBLIC_EXPLOIT_LIKELY = "PUBLIC_EXPLOIT_LIKELY"
    EMERGING_OR_UNKNOWN = "EMERGING_OR_UNKNOWN"
    WEAK_OR_UNCORROBORATED = "WEAK_OR_UNCORROBORATED"
    LIKELY_FALSE_POSITIVE = "LIKELY_FALSE_POSITIVE"


class PoCReadiness(str, Enum):
    """Whether REMORA can propose a safe proof-of-concept validation path."""

    SAFE_REPRO_PLAN = "SAFE_REPRO_PLAN"
    EVIDENCE_ONLY = "EVIDENCE_ONLY"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


@dataclass(frozen=True)
class DefensivePoCPlan:
    """Non-weaponizing proof-of-concept plan for defensive validation.

    The plan intentionally avoids exploit payloads, destructive commands, and
    instructions against third-party systems. It describes safe validation
    requirements and evidence to collect in an owned sandbox.
    """

    readiness: PoCReadiness
    allowed_environment: str
    objective: str
    steps: tuple[str, ...]
    required_evidence: tuple[str, ...]
    blocked_actions: tuple[str, ...]
    review_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "readiness": self.readiness.value,
            "allowed_environment": self.allowed_environment,
            "objective": self.objective,
            "steps": list(self.steps),
            "required_evidence": list(self.required_evidence),
            "blocked_actions": list(self.blocked_actions),
            "review_required": self.review_required,
        }


@dataclass(frozen=True)
class CyberEvidenceRecord:
    """One normalized cyber evidence object."""

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
    cve_ids: tuple[str, ...] = ()
    cwe_ids: tuple[str, ...] = ()
    attack_ids: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()
    affected_versions: tuple[str, ...] = ()
    kev: bool = False
    epss_score: float | None = None
    cvss_score: float | None = None
    exploit_maturity: str = "unknown"
    remediation: str = ""
    license_note: str = ""
    retrieved_at: str = ""
    version: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CyberEvidenceRecord":
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
            cve_ids=tuple(_norm_cve(x) for x in data.get("cve_ids", [])),
            cwe_ids=tuple(_norm_cwe(x) for x in data.get("cwe_ids", [])),
            attack_ids=tuple(_norm_attack(x) for x in data.get("attack_ids", [])),
            packages=tuple(str(x).lower() for x in data.get("packages", [])),
            affected_versions=tuple(str(x).lower() for x in data.get("affected_versions", [])),
            kev=bool(data.get("kev", False)),
            epss_score=_optional_unit(data.get("epss_score")),
            cvss_score=_optional_float(data.get("cvss_score")),
            exploit_maturity=str(data.get("exploit_maturity", "unknown")),
            remediation=str(data.get("remediation", "")),
            license_note=str(data.get("license_note", "")),
            retrieved_at=str(data.get("retrieved_at", "")),
            version=str(data.get("version", "")),
            raw=dict(data),
        )

    @property
    def exact_keys(self) -> set[str]:
        keys = set(self.cve_ids) | set(self.cwe_ids) | set(self.attack_ids)
        keys.update(f"pkg:{p}" for p in self.packages)
        if self.kev:
            keys.add("kev:true")
        return keys

    @property
    def vector_text(self) -> str:
        parts = [
            self.title,
            self.content,
            " ".join(self.risk_tags),
            " ".join(self.cve_ids),
            " ".join(self.cwe_ids),
            " ".join(self.attack_ids),
            " ".join(self.packages),
            self.remediation,
        ]
        return " ".join(part for part in parts if part).strip()


@dataclass(frozen=True)
class CyberEvidenceMatch:
    """Ranked cyber evidence match."""

    record: CyberEvidenceRecord
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
            "cve_ids": list(self.record.cve_ids),
            "cwe_ids": list(self.record.cwe_ids),
            "attack_ids": list(self.record.attack_ids),
            "packages": list(self.record.packages),
            "kev": self.record.kev,
            "epss_score": self.record.epss_score,
            "cvss_score": self.record.cvss_score,
            "remediation": self.record.remediation,
        }


@dataclass(frozen=True)
class CyberTriageResult:
    """Complete cyber triage result."""

    verdict: CyberTriageVerdict
    governance_action: str
    exploit_classification: ExploitClassification
    confidence: float
    evidence_signal: EvidenceSignal
    matches: tuple[CyberEvidenceMatch, ...]
    reasoning: str
    exact_identifiers: dict[str, list[str]]
    poc_plan: DefensivePoCPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "governance_action": self.governance_action,
            "exploit_classification": self.exploit_classification.value,
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
            "poc_plan": self.poc_plan.to_dict() if self.poc_plan else None,
        }


class CyberEvidenceProvider:
    """EvidenceProvider for public cybersecurity evidence packs.

    The provider is suitable for:
    - REMORA-only demos without proprietary scanner dependencies;
    - GO-STAR extension demos where GO-STAR supplies candidate findings later;
    - vector-store preparation through ``to_vector_records``.
    """

    def __init__(
        self,
        jsonl_path: str | Path | None = None,
        *,
        top_k: int = 8,
        min_score: float = 0.05,
        strict_load: bool = False,
    ) -> None:
        self.path = Path(jsonl_path) if jsonl_path is not None else DEFAULT_CYBER_EVIDENCE_PATH
        self.top_k = max(1, int(top_k))
        self.min_score = max(0.0, float(min_score))
        self.strict_load = strict_load
        self.records: tuple[CyberEvidenceRecord, ...] = ()
        self.load_errors: tuple[str, ...] = ()
        self._exact_index: dict[str, list[CyberEvidenceRecord]] = {}
        self._load()

    def _load(self) -> None:
        errors: list[str] = []
        records: list[CyberEvidenceRecord] = []

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
                    _validate_required_fields(data)
                    records.append(CyberEvidenceRecord.from_dict(data))
                except Exception as exc:
                    msg = f"{self.path.name} line {line_no}: {exc}"
                    if self.strict_load:
                        raise ValueError(msg) from exc
                    errors.append(msg)

        self.records = tuple(records)
        self.load_errors = tuple(errors)
        self._build_index()

    def _build_index(self) -> None:
        index: dict[str, list[CyberEvidenceRecord]] = {}
        for record in self.records:
            for key in record.exact_keys:
                index.setdefault(key.lower(), []).append(record)
        self._exact_index = index

    @property
    def store_size(self) -> int:
        return len(self.records)

    def summary(self) -> dict[str, Any]:
        sources: dict[str, int] = {}
        domains: dict[str, int] = {}
        for record in self.records:
            sources[record.source] = sources.get(record.source, 0) + 1
            domains[record.domain] = domains.get(record.domain, 0) + 1
        return {
            "provider_version": CYBER_PROVIDER_VERSION,
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
        cve_ids: Iterable[str] = (),
        cwe_ids: Iterable[str] = (),
        attack_ids: Iterable[str] = (),
        packages: Iterable[str] = (),
        risk_tags: Iterable[str] = (),
        top_k: int | None = None,
    ) -> list[CyberEvidenceMatch]:
        identifiers = _extract_identifiers(query)
        cves = {_norm_cve(x) for x in cve_ids} | set(identifiers["cve_ids"])
        cwes = {_norm_cwe(x) for x in cwe_ids} | set(identifiers["cwe_ids"])
        attacks = {_norm_attack(x) for x in attack_ids} | set(identifiers["attack_ids"])
        pkgs = {str(x).lower() for x in packages}
        tags = {str(x).lower() for x in risk_tags}
        exact_keys = set(cves) | set(cwes) | set(attacks) | {f"pkg:{p}" for p in pkgs}

        query_tokens = set(_tokens(query))
        scored: dict[str, CyberEvidenceMatch] = {}

        for record in self.records:
            record_exact_keys = {key.lower() for key in record.exact_keys}
            matched_keys = tuple(sorted(k for k in exact_keys if k.lower() in record_exact_keys))
            exact_score = 0.0
            if matched_keys:
                exact_score = min(1.0, 0.58 + 0.12 * len(matched_keys))

            tag_score = _jaccard(tags, set(record.risk_tags)) if tags else 0.0
            token_score = _jaccard(query_tokens, set(_tokens(record.vector_text))) if query_tokens else 0.0
            authority = record.authority_score * record.freshness_score

            score = min(
                1.0,
                exact_score
                + 0.22 * tag_score
                + 0.30 * token_score
                + 0.10 * authority,
            )
            if score < self.min_score:
                continue

            match = CyberEvidenceMatch(
                record=record,
                score=round(score, 4),
                exact_match=bool(matched_keys),
                matched_keys=matched_keys,
            )
            scored[record.evidence_id] = match

        matches = sorted(
            scored.values(),
            key=lambda m: (
                m.score,
                m.exact_match,
                m.record.kev,
                m.record.epss_score or 0.0,
                m.record.authority_score,
            ),
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
            signal_source="retrieval_cyber_evidence",
            provenance={
                "provider_version": CYBER_PROVIDER_VERSION,
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
        cve_ids: Iterable[str] = (),
        cwe_ids: Iterable[str] = (),
        attack_ids: Iterable[str] = (),
        packages: Iterable[str] = (),
        exposed: bool = False,
        production: bool = False,
        tool_signals: int = 1,
    ) -> CyberTriageResult:
        """Govern a candidate security finding against public evidence."""
        query = f"{title} {description}"
        matches = self.search(
            query,
            cve_ids=cve_ids,
            cwe_ids=cwe_ids,
            attack_ids=attack_ids,
            packages=packages,
            risk_tags=[severity],
            top_k=self.top_k,
        )
        signal = _signal_from_matches(matches)
        ids = _extract_identifiers(query)
        ids["cve_ids"] = sorted(set(ids["cve_ids"]) | {_norm_cve(x) for x in cve_ids})
        ids["cwe_ids"] = sorted(set(ids["cwe_ids"]) | {_norm_cwe(x) for x in cwe_ids})
        ids["attack_ids"] = sorted(set(ids["attack_ids"]) | {_norm_attack(x) for x in attack_ids})

        exact_count = sum(1 for m in matches if m.exact_match)
        exact_matches = [m for m in matches if m.exact_match]
        kev_hit = any(m.record.kev for m in exact_matches)
        max_epss = max((m.record.epss_score or 0.0 for m in exact_matches), default=0.0)
        max_cvss = max((m.record.cvss_score or 0.0 for m in exact_matches), default=0.0)
        severity_norm = severity.lower()
        exploit_class = _classify_exploit_maturity(
            matches,
            severity=severity_norm,
            exact_count=exact_count,
            kev_hit=kev_hit,
            max_epss=max_epss,
        )

        confidence = min(
            1.0,
            0.42 * signal.evidence_strength
            + 0.22 * signal.source_reliability
            + 0.16 * signal.citation_coverage
            + 0.08 * min(1.0, exact_count / 2)
            + (0.06 if kev_hit else 0.0)
            + (0.04 if max_epss >= 0.80 else 0.0)
            + (0.02 if max_cvss >= 9.0 else 0.0)
            + (0.02 if tool_signals >= 2 else 0.0),
        )
        confidence = round(confidence, 3)

        if kev_hit and (exposed or production):
            verdict = CyberTriageVerdict.ESCALATE
            action = "ESCALATE"
            reason = "Known exploited vulnerability on exposed or production target"
        elif severity_norm in {"critical", "high"} and max_epss >= 0.80 and exact_count:
            verdict = CyberTriageVerdict.ESCALATE
            action = "ESCALATE"
            reason = "High exploit probability with exact vulnerability evidence"
        elif confidence >= 0.68 and exact_count and tool_signals >= 2:
            verdict = CyberTriageVerdict.REPORT_READY
            action = "VERIFY" if severity_norm in {"critical", "high"} else "ACCEPT"
            reason = "Corroborated evidence is strong enough for report preparation"
        elif confidence <= 0.22 and signal.contradiction_score >= 0.35:
            verdict = CyberTriageVerdict.LIKELY_FALSE_POSITIVE
            action = "VERIFY"
            reason = "Weak support and contradiction evidence suggest false positive"
        else:
            verdict = CyberTriageVerdict.NEEDS_REVIEW
            action = "VERIFY"
            reason = "Evidence is useful but not strong enough for autonomous closure"

        poc_plan = _build_defensive_poc_plan(
            verdict=verdict,
            exploit_classification=exploit_class,
            severity=severity_norm,
            exposed=exposed,
            production=production,
            identifiers=ids,
            matches=matches,
        )

        return CyberTriageResult(
            verdict=verdict,
            governance_action=action,
            exploit_classification=exploit_class,
            confidence=confidence,
            evidence_signal=signal,
            matches=tuple(matches),
            reasoning=reason,
            exact_identifiers=ids,
            poc_plan=poc_plan,
        )

    def to_vector_records(self) -> list[dict[str, Any]]:
        """Return RAG/vector-store ready records with public metadata only."""
        payload = []
        for record in self.records:
            payload.append({
                "id": record.evidence_id,
                "text": record.vector_text,
                "metadata": {
                    "source": record.source,
                    "source_url": record.source_url,
                    "domain": record.domain,
                    "risk_tags": list(record.risk_tags),
                    "cve_ids": list(record.cve_ids),
                    "cwe_ids": list(record.cwe_ids),
                    "attack_ids": list(record.attack_ids),
                    "packages": list(record.packages),
                    "kev": record.kev,
                    "epss_score": record.epss_score,
                    "cvss_score": record.cvss_score,
                    "license_note": record.license_note,
                },
            })
        return payload


def _validate_required_fields(data: dict[str, Any]) -> None:
    required = {
        "evidence_id",
        "source",
        "source_url",
        "title",
        "content",
        "domain",
        "risk_tags",
        "authority_score",
        "freshness_score",
        "coverage_score",
        "contradiction_score",
    }
    missing = required - data.keys()
    if missing:
        raise ValueError(f"missing required fields {sorted(missing)}")


def _extract_identifiers(text: str) -> dict[str, list[str]]:
    return {
        "cve_ids": sorted({_norm_cve(m.group(0)) for m in _CVE_RE.finditer(text)}),
        "cwe_ids": sorted({_norm_cwe(m.group(0)) for m in _CWE_RE.finditer(text)}),
        "attack_ids": sorted({_norm_attack(m.group(0)) for m in _ATTACK_RE.finditer(text)}),
    }


def _signal_from_matches(matches: Sequence[CyberEvidenceMatch]) -> EvidenceSignal:
    if not matches:
        return EvidenceSignal(
            evidence_strength=0.0,
            contradiction_score=0.0,
            citation_coverage=0.0,
            cross_evidence_consistency=0.0,
            source_reliability=0.0,
        )

    top = list(matches)
    strengths = [m.record.authority_score * m.record.freshness_score * m.score for m in top]
    strength_window = strengths[:3]
    authority = [m.record.authority_score for m in top]
    contradictions = [m.record.contradiction_score for m in top]
    tag_sets = [set(m.record.risk_tags) for m in top]
    consistency = _tag_consistency(tag_sets)

    return EvidenceSignal(
        evidence_strength=round(min(1.0, sum(strength_window) / len(strength_window)), 3),
        contradiction_score=round(min(1.0, sum(contradictions) / len(contradictions)), 3),
        citation_coverage=round(min(1.0, len(top) / 5), 3),
        cross_evidence_consistency=round(consistency, 3),
        source_reliability=round(sum(authority) / len(authority), 3),
    )


def _classify_exploit_maturity(
    matches: Sequence[CyberEvidenceMatch],
    *,
    severity: str,
    exact_count: int,
    kev_hit: bool,
    max_epss: float,
) -> ExploitClassification:
    contradiction = max((m.record.contradiction_score for m in matches), default=0.0)
    if contradiction >= 0.45 and not kev_hit and exact_count <= 1:
        return ExploitClassification.LIKELY_FALSE_POSITIVE
    known_exploited_exact = any(
        m.exact_match and (m.record.kev or m.record.exploit_maturity == "known_exploited")
        for m in matches
    )
    if kev_hit or known_exploited_exact:
        return ExploitClassification.KNOWN_EXPLOITED
    if max_epss >= 0.80 and exact_count:
        return ExploitClassification.PUBLIC_EXPLOIT_LIKELY
    if severity in {"critical", "high"} and exact_count:
        return ExploitClassification.EMERGING_OR_UNKNOWN
    if any(m.exact_match for m in matches):
        return ExploitClassification.EMERGING_OR_UNKNOWN
    return ExploitClassification.WEAK_OR_UNCORROBORATED


def _build_defensive_poc_plan(
    *,
    verdict: CyberTriageVerdict,
    exploit_classification: ExploitClassification,
    severity: str,
    exposed: bool,
    production: bool,
    identifiers: dict[str, list[str]],
    matches: Sequence[CyberEvidenceMatch],
) -> DefensivePoCPlan:
    exact_refs = identifiers["cve_ids"] or identifiers["cwe_ids"] or identifiers["attack_ids"]
    reference = ", ".join(exact_refs[:3]) if exact_refs else "the matched weakness pattern"

    blocked = (
        "Do not run exploit payloads against third-party systems.",
        "Do not attempt credential theft, persistence, lateral movement, or data exfiltration.",
        "Do not execute destructive proof steps in production.",
    )

    if verdict == CyberTriageVerdict.ESCALATE or severity in {"critical", "high"} and (exposed or production):
        return DefensivePoCPlan(
            readiness=PoCReadiness.HUMAN_REVIEW_REQUIRED,
            allowed_environment="owned isolated sandbox or approved staging only",
            objective=f"Validate exposure and affected-version evidence for {reference} without exploitation.",
            steps=(
                "Confirm affected asset, package, version, and exposure from inventory or SBOM.",
                "Collect source-linked evidence from advisory, KEV, EPSS, CWE, and ATT&CK records.",
                "If reproduction is required, create an isolated non-production clone with synthetic data.",
                "Run only non-destructive reachability or configuration checks approved by the security owner.",
                "Attach screenshots, command transcripts, SBOM excerpts, and reviewer sign-off to the case.",
            ),
            required_evidence=(
                "asset or repository identifier",
                "affected package or code path",
                "version or source-to-sink proof",
                "exposure or reachability context",
                "security-owner approval",
            ),
            blocked_actions=blocked,
            review_required=True,
        )

    if exploit_classification == ExploitClassification.LIKELY_FALSE_POSITIVE:
        return DefensivePoCPlan(
            readiness=PoCReadiness.EVIDENCE_ONLY,
            allowed_environment="review workflow",
            objective="Validate whether the finding is a benign placeholder, fixture, or unreachable code path.",
            steps=(
                "Confirm file path, branch, and runtime inclusion.",
                "Check whether the value is a placeholder, test fixture, or non-secret example.",
                "Require reviewer approval before closing the finding.",
            ),
            required_evidence=("file context", "runtime inclusion status", "reviewer note"),
            blocked_actions=blocked,
            review_required=True,
        )

    if matches:
        return DefensivePoCPlan(
            readiness=PoCReadiness.SAFE_REPRO_PLAN,
            allowed_environment="owned local sandbox",
            objective=f"Collect safe validation evidence for {reference}.",
            steps=(
                "Create a local sandbox with synthetic data and no external targets.",
                "Reproduce only the control-flow or configuration condition, not harmful impact.",
                "Capture before/after evidence and remediation recommendation.",
                "Route final decision through REMORA review before report submission.",
            ),
            required_evidence=("sandbox scope", "matched evidence IDs", "safe reproduction notes"),
            blocked_actions=blocked,
            review_required=True,
        )

    return DefensivePoCPlan(
        readiness=PoCReadiness.NOT_RECOMMENDED,
        allowed_environment="none",
        objective="Insufficient evidence for PoC planning.",
        steps=("Collect more evidence before attempting validation.",),
        required_evidence=("additional corroborating evidence",),
        blocked_actions=blocked,
        review_required=True,
    )


def _tag_consistency(tag_sets: list[set[str]]) -> float:
    if len(tag_sets) < 2:
        return 1.0 if tag_sets else 0.0
    scores = []
    for idx, left in enumerate(tag_sets):
        for right in tag_sets[idx + 1 :]:
            scores.append(_jaccard(left, right))
    return sum(scores) / len(scores) if scores else 0.0


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _norm_cve(value: Any) -> str:
    return str(value).upper()


def _norm_cwe(value: Any) -> str:
    return str(value).upper()


def _norm_attack(value: Any) -> str:
    return str(value).upper()


def _unit(value: Any) -> float:
    return max(0.0, min(1.0, _optional_float(value) or 0.0))


def _optional_unit(value: Any) -> float | None:
    parsed = _optional_float(value)
    if parsed is None:
        return None
    return max(0.0, min(1.0, parsed))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "CYBER_PROVIDER_VERSION",
    "DEFAULT_CYBER_EVIDENCE_PATH",
    "CyberEvidenceMatch",
    "CyberEvidenceProvider",
    "CyberEvidenceRecord",
    "DefensivePoCPlan",
    "ExploitClassification",
    "PoCReadiness",
    "CyberTriageResult",
    "CyberTriageVerdict",
]
