# Author: Stian Skogbrott
# License: Apache-2.0
"""GO-STAR cybersecurity integration for REMORA governance.

This module bridges GO-STAR's vulnerability research pipeline into
REMORA's DecisionEnvelope governance framework. It enables REMORA to
govern security-critical decisions: whether a finding is real, whether
it's exploitable, and what action to take.

GO-STAR provides:
- Multi-tool scanning (Semgrep, CodeGraph taint, OSV)
- Evidence fusion across oracle signals
- Exploitability assessment via multi-LLM consensus
- False positive filtering

REMORA adds:
- Governance gating (ACCEPT/VERIFY/ABSTAIN/ESCALATE)
- Tamper-evident audit trail (DecisionEnvelope + hash chain)
- Policy enforcement (hard blocks, risk tiers)
- Adaptive threshold calibration
- Explainable decision narratives

Architecture
------------
GO-STAR finding → GoStarBridge.govern() → DecisionEnvelope
                                        → SecurityGovernanceResult
                                        → Provenance DAG node

The bridge can operate in two modes:
1. **Local mode**: uses REMORA's own oracle consensus engine
2. **MCP mode**: calls GO-STAR's remora_* MCP tools (which run
   REMORA consensus on Cloudflare Workers with live LLM oracles)

Status: Research prototype. This integration demonstrates that REMORA's
governance framework generalises to cybersecurity domains. It is not a
production vulnerability scanner.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# GO-STAR data types (standalone — no GO-STAR import required)
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingVerdict(str, Enum):
    """REMORA governance verdict for a security finding."""
    REPORT_READY = "REPORT_READY"  # confirmed real + exploitable → file report
    NEEDS_REVIEW = "NEEDS_REVIEW"  # uncertain → human security researcher reviews
    FALSE_POSITIVE = "FALSE_POSITIVE"  # confirmed FP → discard
    ESCALATE = "ESCALATE"  # critical risk → escalate to security lead


@dataclass
class OracleSignal:
    """A signal from one analysis tool (Semgrep, CodeGraph, OSV, etc.)."""
    tool: str  # "semgrep", "codegraph", "osv", "fuzzer", "taint"
    family: str  # "static", "dynamic", "supply_chain", "graph"
    evidence_role: str  # "primary", "corroborating", "contradicting"
    result: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class GoStarFinding:
    """A security finding from GO-STAR's scan pipeline."""
    finding_id: str
    title: str
    description: str
    severity: Severity
    cwe: str = ""
    file_path: str = ""
    symbol: str = ""
    source: str = ""  # attacker-controlled input
    sink: str = ""  # dangerous function
    repo: str = ""
    commit_sha: str = ""
    oracle_signals: list[OracleSignal] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        payload = json.dumps({
            "id": self.finding_id,
            "title": self.title,
            "cwe": self.cwe,
            "file": self.file_path,
            "symbol": self.symbol,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class GoStarScanResult:
    """Aggregated result from a GO-STAR repo scan."""
    repo: str
    findings: list[GoStarFinding]
    scan_duration_ms: float = 0.0
    tools_used: list[str] = field(default_factory=list)
    commit_sha: str = ""


# ---------------------------------------------------------------------------
# Evidence fusion result (mirrors GO-STAR's EvidenceFusionResult)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FusionResult:
    """Result of fusing multiple oracle signals for a finding."""
    verdict: bool | None  # True=real, False=FP, None=uncertain
    confidence: float
    oracle_agreement: float
    signals_used: int
    reasoning: str = ""
    provenance_hash: str = ""


# ---------------------------------------------------------------------------
# Security governance result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecurityGovernanceResult:
    """Complete governance result for a security finding.

    Combines GO-STAR's evidence fusion with REMORA's governance decision.
    """
    finding: GoStarFinding
    verdict: FindingVerdict
    fusion: FusionResult
    risk_tier: str
    confidence: float
    governance_action: str  # ACCEPT, VERIFY, ABSTAIN, ESCALATE
    reasoning: str
    envelope_hash: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding.finding_id,
            "verdict": self.verdict.value,
            "governance_action": self.governance_action,
            "risk_tier": self.risk_tier,
            "confidence": self.confidence,
            "fusion_confidence": self.fusion.confidence,
            "reasoning": self.reasoning,
            "envelope_hash": self.envelope_hash,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# MCP client protocol (for calling GO-STAR's remora_* tools)
# ---------------------------------------------------------------------------

class MCPClient(Protocol):
    """Protocol for calling MCP tools."""
    def call_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# GO-STAR Bridge
# ---------------------------------------------------------------------------

_SEVERITY_TO_RISK = {
    Severity.CRITICAL: "critical",
    Severity.HIGH: "high",
    Severity.MEDIUM: "medium",
    Severity.LOW: "low",
    Severity.INFO: "low",
}


class GoStarBridge:
    """Bridge between GO-STAR vulnerability findings and REMORA governance.

    This is the primary integration point. It takes GO-STAR findings and
    produces REMORA-governed security decisions with full audit trail.

    Parameters
    ----------
    evidence_threshold : float
        Minimum fusion confidence to auto-accept a finding. Default 0.70.
    fp_threshold : float
        Maximum fusion confidence below which to mark as FP. Default 0.30.
    require_corroboration : bool
        Require at least 2 oracle signals to auto-accept. Default True.
    mcp_client : MCPClient | None
        Optional MCP client for calling GO-STAR's remora_* tools.
        If None, uses local heuristic fusion.
    """

    def __init__(
        self,
        *,
        evidence_threshold: float = 0.70,
        fp_threshold: float = 0.30,
        require_corroboration: bool = True,
        mcp_client: MCPClient | None = None,
    ) -> None:
        self._evidence_threshold = evidence_threshold
        self._fp_threshold = fp_threshold
        self._require_corroboration = require_corroboration
        self._mcp = mcp_client
        self._history: list[SecurityGovernanceResult] = []

    @property
    def history(self) -> list[SecurityGovernanceResult]:
        return list(self._history)

    # ----- Evidence fusion -----

    def _fuse_local(self, finding: GoStarFinding) -> FusionResult:
        """Local evidence fusion without MCP (deterministic heuristic).

        Uses signal agreement, severity weighting, and corroboration
        count to produce a fusion confidence score.
        """
        signals = finding.oracle_signals
        if not signals:
            return FusionResult(
                verdict=None, confidence=0.0, oracle_agreement=0.0,
                signals_used=0, reasoning="No oracle signals available",
            )

        # Count roles
        primary = [s for s in signals if s.evidence_role == "primary"]
        corroborating = [s for s in signals if s.evidence_role == "corroborating"]
        contradicting = [s for s in signals if s.evidence_role == "contradicting"]

        n_support = len(primary) + len(corroborating)
        n_contra = len(contradicting)
        n_total = len(signals)

        # Weighted confidence from individual signals
        weights = {"primary": 1.0, "corroborating": 0.7, "contradicting": -0.5}
        weighted_sum = sum(
            s.confidence * weights.get(s.evidence_role, 0.5)
            for s in signals
        )
        max_possible = sum(
            abs(weights.get(s.evidence_role, 0.5))
            for s in signals
        )
        normalized_conf = max(0.0, min(1.0, weighted_sum / max_possible)) if max_possible > 0 else 0.0

        # Agreement ratio
        agreement = n_support / n_total if n_total > 0 else 0.0

        # Severity bonus
        sev_bonus = {"critical": 0.05, "high": 0.03}.get(finding.severity.value, 0.0)
        confidence = min(1.0, normalized_conf + sev_bonus)

        support_conf = (
            sum(s.confidence for s in primary + corroborating) / n_support
            if n_support else 0.0
        )
        contra_conf = (
            sum(s.confidence for s in contradicting) / n_contra
            if n_contra else 0.0
        )

        # Verdict
        if confidence >= self._evidence_threshold and n_contra == 0:
            verdict = True
            reasoning = f"{n_support}/{n_total} signals support finding (conf={confidence:.2f})"
        elif (
            confidence <= self._fp_threshold
            and n_contra > 0
            and contra_conf > support_conf
        ):
            verdict = False
            reasoning = f"{n_contra} contradicting signals, low confidence ({confidence:.2f})"
        else:
            verdict = None
            reasoning = f"Uncertain: {n_support} support, {n_contra} contradict (conf={confidence:.2f})"

        provenance = hashlib.sha256(json.dumps({
            "finding_id": finding.finding_id,
            "signals": n_total,
            "confidence": confidence,
        }, sort_keys=True).encode()).hexdigest()

        return FusionResult(
            verdict=verdict,
            confidence=round(confidence, 3),
            oracle_agreement=round(agreement, 3),
            signals_used=n_total,
            reasoning=reasoning,
            provenance_hash=provenance,
        )

    def _fuse_mcp(self, finding: GoStarFinding) -> FusionResult:
        """Evidence fusion via GO-STAR's remora_evidence_fusion MCP tool."""
        assert self._mcp is not None
        signal_dicts = [
            {"tool": s.tool, "family": s.family,
             "evidence_role": s.evidence_role, "result": s.result}
            for s in finding.oracle_signals
        ]
        try:
            result = self._mcp.call_tool("remora_evidence_fusion", {
                "description": finding.description,
                "oracle_signals": signal_dicts,
            })
            verdict_raw = result.get("verdict")
            verdict = True if verdict_raw is True else (False if verdict_raw is False else None)
            return FusionResult(
                verdict=verdict,
                confidence=float(result.get("confidence", 0.0)),
                oracle_agreement=float(result.get("oracle_agreement", 0.0)),
                signals_used=len(finding.oracle_signals),
                reasoning=str(result.get("reasoning", "")),
                provenance_hash=str(result.get("provenance_hash", "")),
            )
        except Exception as e:
            # Fail-closed: if MCP call fails, mark as uncertain
            return FusionResult(
                verdict=None, confidence=0.0, oracle_agreement=0.0,
                signals_used=0, reasoning=f"MCP fusion failed: {e}",
            )

    def fuse(self, finding: GoStarFinding) -> FusionResult:
        """Fuse evidence for a finding using available backend."""
        if self._mcp is not None:
            return self._fuse_mcp(finding)
        return self._fuse_local(finding)

    # ----- Governance decision -----

    def _map_to_governance(
        self, finding: GoStarFinding, fusion: FusionResult,
    ) -> tuple[FindingVerdict, str, str]:
        """Map fusion result to REMORA governance action.

        Returns (verdict, governance_action, reasoning).
        """
        risk_tier = _SEVERITY_TO_RISK[finding.severity]

        # Hard block: critical severity always escalates regardless of fusion
        if risk_tier == "critical" and fusion.verdict is not True:
            return (
                FindingVerdict.ESCALATE, "ESCALATE",
                f"Critical severity finding with uncertain evidence (conf={fusion.confidence:.2f}) → mandatory human review",
            )

        # Corroboration check
        if (self._require_corroboration
                and fusion.signals_used < 2
                and fusion.verdict is True):
            return (
                FindingVerdict.NEEDS_REVIEW, "VERIFY",
                f"Finding confirmed but only {fusion.signals_used} signal(s) — corroboration required",
            )

        # Confident real finding
        if fusion.verdict is True and fusion.confidence >= self._evidence_threshold:
            action = "ACCEPT" if risk_tier in ("low", "medium") else "VERIFY"
            return (
                FindingVerdict.REPORT_READY, action,
                f"Multi-oracle evidence confirms finding (conf={fusion.confidence:.2f}, "
                f"agreement={fusion.oracle_agreement:.2f})",
            )

        # Confident false positive. High-risk findings still need review before
        # closure because a mistaken discard can be materially harmful.
        if fusion.verdict is False and fusion.confidence <= self._fp_threshold:
            if risk_tier in ("high", "critical"):
                return (
                    FindingVerdict.NEEDS_REVIEW, "VERIFY",
                    f"Likely false positive for {risk_tier}-risk finding; human review required before discard",
                )
            return (
                FindingVerdict.FALSE_POSITIVE, "ACCEPT",
                f"Multi-oracle evidence indicates false positive (conf={fusion.confidence:.2f})",
            )

        # Uncertain → route by severity
        if risk_tier in ("high", "critical"):
            return (
                FindingVerdict.NEEDS_REVIEW, "VERIFY",
                f"Uncertain evidence for {risk_tier}-risk finding → human review required",
            )

        return (
            FindingVerdict.NEEDS_REVIEW, "ABSTAIN",
            f"Insufficient evidence to decide (conf={fusion.confidence:.2f})",
        )

    def govern(self, finding: GoStarFinding) -> SecurityGovernanceResult:
        """Run full governance pipeline for a single finding.

        1. Fuse evidence from oracle signals
        2. Apply REMORA governance policy
        3. Produce auditable result with hash chain
        """
        fusion = self.fuse(finding)
        verdict, action, reasoning = self._map_to_governance(finding, fusion)
        risk_tier = _SEVERITY_TO_RISK[finding.severity]

        envelope_hash = hashlib.sha256(json.dumps({
            "finding": finding.content_hash(),
            "fusion": fusion.provenance_hash,
            "action": action,
            "timestamp": time.time(),
        }, sort_keys=True).encode()).hexdigest()

        result = SecurityGovernanceResult(
            finding=finding,
            verdict=verdict,
            fusion=fusion,
            risk_tier=risk_tier,
            confidence=fusion.confidence,
            governance_action=action,
            reasoning=reasoning,
            envelope_hash=envelope_hash,
        )
        self._history.append(result)
        return result

    def govern_scan(self, scan: GoStarScanResult) -> list[SecurityGovernanceResult]:
        """Govern all findings from a GO-STAR scan."""
        return [self.govern(f) for f in scan.findings]

    def summary(self) -> dict[str, Any]:
        """Produce a summary report of all governed findings."""
        if not self._history:
            return {"total": 0}

        verdicts = [r.verdict.value for r in self._history]
        actions = [r.governance_action for r in self._history]
        return {
            "total": len(self._history),
            "report_ready": verdicts.count(FindingVerdict.REPORT_READY.value),
            "needs_review": verdicts.count(FindingVerdict.NEEDS_REVIEW.value),
            "false_positive": verdicts.count(FindingVerdict.FALSE_POSITIVE.value),
            "escalated": verdicts.count(FindingVerdict.ESCALATE.value),
            "actions": {a: actions.count(a) for a in set(actions)},
            "mean_confidence": round(
                sum(r.confidence for r in self._history) / len(self._history), 3
            ),
        }
