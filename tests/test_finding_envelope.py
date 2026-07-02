from __future__ import annotations

import hashlib
import json

import pytest

from remora.evidence.finding_envelope import (
    CyberFindingEnvelope,
    DisclosureLedger,
    DisclosureStatus,
    ResearchArtifactRef,
    TargetScanProfile,
)


def _profile() -> TargetScanProfile:
    return TargetScanProfile(
        target_id="test-target-001",
        repo_url="https://github.com/example/repo",
        language="python",
        threat_model="web_api",
        allowed_scope=("src/", "api/"),
        authorization_ref="hackerone:12345",
        scan_mode="MODE2",
        created_at="2026-06-03T00:00:00Z",
    )


def _envelope() -> CyberFindingEnvelope:
    return CyberFindingEnvelope(
        finding_id="find-001",
        target_profile=_profile(),
        title="SQL injection in login path",
        description="CWE-89 unsanitized query",
        severity="high",
        cwe_ids=("CWE-89",),
        cve_ids=(),
        attack_ids=("T1190",),
        packages=(),
        source_file="api/auth.py",
        sink_file="api/auth.py",
        tool_signals=2,
        exposed=True,
        production=True,
    )


def test_target_scan_profile_to_dict() -> None:
    p = _profile()
    d = p.to_dict()
    assert d["target_id"] == "test-target-001"
    assert d["scan_mode"] == "MODE2"
    assert "src/" in d["allowed_scope"]


def test_disclosure_status_ordering() -> None:
    assert DisclosureStatus.COVERAGE_HIT.stage_index() == 0
    assert DisclosureStatus.REPORT_READY.stage_index() == 5
    assert DisclosureStatus.COVERAGE_HIT.can_advance_to(DisclosureStatus.REACHABLE_SINK)
    assert DisclosureStatus.COVERAGE_HIT.can_advance_to(DisclosureStatus.CONTROLLED_REPRO)
    assert not DisclosureStatus.REPORT_READY.can_advance_to(DisclosureStatus.COVERAGE_HIT)


def test_disclosure_ledger_advance() -> None:
    content = {"finding_id": "find-001", "title": "test"}
    ledger = DisclosureLedger.new("find-001", content, "2026-06-03T00:00:00Z")
    assert ledger.status == DisclosureStatus.COVERAGE_HIT

    ledger.advance(DisclosureStatus.REACHABLE_SINK, note="taint confirmed")
    assert ledger.status == DisclosureStatus.REACHABLE_SINK
    assert "taint confirmed" in ledger.notes

    ledger.advance(DisclosureStatus.CONTROLLED_REPRO)
    assert ledger.status == DisclosureStatus.CONTROLLED_REPRO
    assert not ledger.is_complete()

    ledger.advance(DisclosureStatus.REPORT_READY)
    assert ledger.is_complete()


def test_disclosure_ledger_rejects_backward_advance() -> None:
    ledger = DisclosureLedger.new("find-001", {}, "2026-06-03T00:00:00Z")
    ledger.advance(DisclosureStatus.REACHABLE_SINK)
    with pytest.raises(ValueError, match="forward"):
        ledger.advance(DisclosureStatus.COVERAGE_HIT)


def test_disclosure_ledger_locked() -> None:
    ledger = DisclosureLedger.new("find-001", {}, "2026-06-03T00:00:00Z")
    ledger.disclosure_locked = True
    with pytest.raises(ValueError, match="locked"):
        ledger.advance(DisclosureStatus.REACHABLE_SINK)


def test_disclosure_ledger_commitment_hash() -> None:
    content = {"finding_id": "find-001", "title": "SQL injection"}
    ledger = DisclosureLedger.new("find-001", content, "2026-06-03T00:00:00Z")
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256(payload.encode()).hexdigest()
    assert ledger.commitment_hash == expected


def test_research_artifact_ref_to_dict() -> None:
    ref = ResearchArtifactRef(
        artifact_hash="abc" * 21,
        artifact_type="crash_log",
        sandbox_environment="docker-isolated",
        preconditions=("python 3.11", "service running"),
        reviewer="security-lead",
        vault_ref="go-star://vault/repros/find-001",
        created_at="2026-06-03T00:00:00Z",
    )
    d = ref.to_dict()
    assert d["artifact_type"] == "crash_log"
    assert "vault_ref" in d
    assert "payload" not in d


def test_cyber_finding_envelope_to_dict() -> None:
    env = _envelope()
    d = env.to_dict()
    assert d["finding_id"] == "find-001"
    assert d["severity"] == "high"
    assert d["triage_result"] is None


def test_cyber_finding_envelope_apply_remora() -> None:
    from remora.evidence.cyber import CyberEvidenceProvider

    provider = CyberEvidenceProvider()
    env = _envelope()
    updated = env.apply_remora(provider)

    assert updated.triage_result is not None
    assert updated.verdict() in {"ESCALATE", "REPORT_READY", "NEEDS_REVIEW", "LIKELY_FALSE_POSITIVE"}
    assert updated.governance_action() in {"ESCALATE", "VERIFY", "ACCEPT"}
    assert env.triage_result is None  # original unchanged


def test_cyber_finding_envelope_from_gostar_finding() -> None:
    from remora.integrations.gostar import GoStarFinding, OracleSignal, Severity

    finding = GoStarFinding(
        finding_id="gf-001",
        title="Path traversal",
        description="CWE-22 path traversal in file upload",
        severity=Severity.HIGH,
        cwe="CWE-22",
        file_path="api/upload.py",
        sink="open(",
        oracle_signals=[
            OracleSignal(tool="semgrep", family="static", evidence_role="primary", confidence=0.8),
            OracleSignal(tool="codegraph", family="graph", evidence_role="corroborating", confidence=0.75),
        ],
    )
    profile = _profile()
    env = CyberFindingEnvelope.from_gostar_finding(finding, profile)
    assert env.finding_id == "gf-001"
    assert env.cwe_ids == ("CWE-22",)
    assert env.tool_signals == 2
    assert env.target_profile is profile
