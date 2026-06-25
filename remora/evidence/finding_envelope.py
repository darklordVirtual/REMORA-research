# Author: Stian Skogbrott
# License: Apache-2.0
"""GO-STAR → REMORA finding bridge types.

These types form the authorised boundary between GO-STAR's proprietary scanner
output and REMORA's public governance layer.  They are side-effect-free: no
secrets, no payloads, no automatic policy mutation.

Architecture
------------
TargetScanProfile        authorised scope for a scan session
  ↓
CyberFindingEnvelope     structured scanner finding
  ↓
CyberEvidenceProvider.triage()  REMORA public governance verdict
  ↓
DisclosureLedger         6-stage capability-ladder tracking
  ↑
ResearchArtifactRef[]    metadata-only references to the GO-STAR private vault
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable

_STAGE_ORDER = [
    "coverage_hit",
    "reachable_sink",
    "reproducible_crash",
    "controlled_repro",
    "patch_validated",
    "report_ready",
]


class DisclosureStatus(str, Enum):
    """Six-stage capability ladder for vulnerability disclosure."""

    COVERAGE_HIT = "coverage_hit"
    REACHABLE_SINK = "reachable_sink"
    REPRODUCIBLE_CRASH = "reproducible_crash"
    CONTROLLED_REPRO = "controlled_repro"
    PATCH_VALIDATED = "patch_validated"
    REPORT_READY = "report_ready"

    def index(self) -> int:
        return _STAGE_ORDER.index(self.value)

    def can_advance_to(self, next_status: "DisclosureStatus") -> bool:
        return next_status.index() > self.index()


@dataclass(frozen=True)
class TargetScanProfile:
    """Authorised scope contract for a GO-STAR scan session.

    Only findings from targets listed in allowed_scope and authorised by
    authorization_ref should produce CyberFindingEnvelopes.
    """

    target_id: str
    repo_url: str
    language: str
    threat_model: str
    allowed_scope: tuple[str, ...]
    authorization_ref: str
    scan_mode: str  # "MODE1" | "MODE2" | "MODE3" | "MODE4"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "repo_url": self.repo_url,
            "language": self.language,
            "threat_model": self.threat_model,
            "allowed_scope": list(self.allowed_scope),
            "authorization_ref": self.authorization_ref,
            "scan_mode": self.scan_mode,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ResearchArtifactRef:
    """Metadata-only reference to a private GO-STAR vault artifact.

    This type deliberately stores only the hash and metadata of a research
    artifact — never the artifact content, exploit code, or reproduction
    payload itself.  The vault_ref identifies the artifact inside the
    GO-STAR controlled environment.
    """

    artifact_hash: str  # SHA-256 of private artifact; never the content
    artifact_type: str  # "repro_script"|"crash_log"|"network_trace"|"sbom_excerpt"|"patch"
    sandbox_environment: str
    preconditions: tuple[str, ...]
    reviewer: str
    vault_ref: str  # GO-STAR internal reference; never a payload
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_hash": self.artifact_hash,
            "artifact_type": self.artifact_type,
            "sandbox_environment": self.sandbox_environment,
            "preconditions": list(self.preconditions),
            "reviewer": self.reviewer,
            "vault_ref": self.vault_ref,
            "created_at": self.created_at,
        }


@dataclass
class DisclosureLedger:
    """Tracks a finding through the six-stage disclosure pipeline.

    Each advance is recorded with an optional note so the full provenance
    of how a finding reached report-ready is auditable.
    """

    finding_id: str
    status: DisclosureStatus
    commitment_hash: str  # HMAC/SHA-256 commitment of finding at initial assessment
    created_at: str
    maintainer_notified_at: str | None = None
    patch_expected_by: str | None = None
    patch_verified_at: str | None = None
    disclosure_locked: bool = False
    notes: str = ""
    _history: list[dict[str, str]] = field(default_factory=list, repr=False)

    def advance(self, new_status: DisclosureStatus, note: str = "") -> None:
        """Advance the pipeline status forward.  Raises ValueError for invalid transitions."""
        if self.disclosure_locked:
            raise ValueError("Ledger is locked; no further status changes are permitted.")
        if not self.status.can_advance_to(new_status):
            raise ValueError(
                f"Cannot advance from {self.status.value!r} to {new_status.value!r}. "
                "Only forward transitions are allowed."
            )
        self._history.append({"from": self.status.value, "to": new_status.value, "note": note})
        self.status = new_status
        if note:
            self.notes = f"{self.notes}\n[{new_status.value}] {note}".strip()

    def is_complete(self) -> bool:
        return self.status == DisclosureStatus.REPORT_READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "status": self.status.value,
            "commitment_hash": self.commitment_hash,
            "created_at": self.created_at,
            "maintainer_notified_at": self.maintainer_notified_at,
            "patch_expected_by": self.patch_expected_by,
            "patch_verified_at": self.patch_verified_at,
            "disclosure_locked": self.disclosure_locked,
            "notes": self.notes,
            "history": list(self._history),
        }

    @classmethod
    def new(
        cls,
        finding_id: str,
        content: dict[str, Any],
        created_at: str,
        *,
        initial_status: DisclosureStatus = DisclosureStatus.COVERAGE_HIT,
    ) -> "DisclosureLedger":
        """Create a new ledger with a SHA-256 commitment over the finding content."""
        payload = json.dumps(content, sort_keys=True, separators=(",", ":"))
        commitment = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return cls(
            finding_id=finding_id,
            status=initial_status,
            commitment_hash=commitment,
            created_at=created_at,
        )


@dataclass
class CyberFindingEnvelope:
    """Structured security finding at the GO-STAR → REMORA boundary.

    Combines the scanner's candidate finding with the authorised scope,
    optional vault artifact references, a disclosure ledger, and — after
    calling ``apply_remora`` — the REMORA governance verdict.
    """

    finding_id: str
    target_profile: TargetScanProfile
    title: str
    description: str
    severity: str
    cwe_ids: tuple[str, ...]
    cve_ids: tuple[str, ...]
    attack_ids: tuple[str, ...]
    packages: tuple[str, ...]
    source_file: str
    sink_file: str
    tool_signals: int
    exposed: bool
    production: bool
    artifact_refs: tuple[ResearchArtifactRef, ...] = ()
    ledger: DisclosureLedger | None = None
    triage_result: Any | None = None  # CyberTriageResult once apply_remora() is called

    def apply_remora(self, provider: Any) -> "CyberFindingEnvelope":
        """Run REMORA triage and return a new envelope with triage_result populated."""
        result = provider.triage(
            title=self.title,
            description=self.description,
            severity=self.severity,
            cve_ids=self.cve_ids,
            cwe_ids=self.cwe_ids,
            attack_ids=self.attack_ids,
            packages=self.packages,
            exposed=self.exposed,
            production=self.production,
            tool_signals=self.tool_signals,
        )
        return replace(self, triage_result=result)

    def verdict(self) -> str | None:
        return self.triage_result.verdict.value if self.triage_result else None

    def governance_action(self) -> str | None:
        return self.triage_result.governance_action if self.triage_result else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "target_profile": self.target_profile.to_dict(),
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "cwe_ids": list(self.cwe_ids),
            "cve_ids": list(self.cve_ids),
            "attack_ids": list(self.attack_ids),
            "packages": list(self.packages),
            "source_file": self.source_file,
            "sink_file": self.sink_file,
            "tool_signals": self.tool_signals,
            "exposed": self.exposed,
            "production": self.production,
            "artifact_refs": [r.to_dict() for r in self.artifact_refs],
            "ledger": self.ledger.to_dict() if self.ledger else None,
            "triage_result": self.triage_result.to_dict() if self.triage_result else None,
        }

    @classmethod
    def from_gostar_finding(
        cls,
        finding: Any,
        target_profile: TargetScanProfile,
        *,
        ledger: DisclosureLedger | None = None,
        artifact_refs: Iterable[ResearchArtifactRef] = (),
    ) -> "CyberFindingEnvelope":
        """Construct from a GoStarFinding and TargetScanProfile."""
        return cls(
            finding_id=finding.finding_id,
            target_profile=target_profile,
            title=finding.title,
            description=finding.description,
            severity=finding.severity.value if hasattr(finding.severity, "value") else str(finding.severity),
            cwe_ids=(finding.cwe,) if finding.cwe else (),
            cve_ids=(),
            attack_ids=(),
            packages=(),
            source_file=finding.file_path or "",
            sink_file=finding.sink or "",
            tool_signals=len(finding.oracle_signals),
            exposed=False,
            production=False,
            artifact_refs=tuple(artifact_refs),
            ledger=ledger,
        )


__all__ = [
    "CyberFindingEnvelope",
    "DisclosureLedger",
    "DisclosureStatus",
    "ResearchArtifactRef",
    "TargetScanProfile",
]
