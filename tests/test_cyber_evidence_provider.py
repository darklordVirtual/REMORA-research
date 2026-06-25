from __future__ import annotations

from pathlib import Path

from remora.evidence.cyber import (
    CyberEvidenceProvider,
    CyberTriageVerdict,
    ExploitClassification,
    PoCReadiness,
    DEFAULT_CYBER_EVIDENCE_PATH,
)


def test_cyber_provider_loads_public_dataset() -> None:
    provider = CyberEvidenceProvider()
    summary = provider.summary()
    assert provider.store_size >= 15
    assert summary["domains"]
    assert not summary["load_errors"]


def test_exact_cve_lookup_prioritizes_known_exploited_record() -> None:
    provider = CyberEvidenceProvider()
    matches = provider.search("production service runs CVE-2021-44228 log4j", top_k=3)
    assert matches
    assert matches[0].record.evidence_id in {
        "ev_nvd_CVE_2021_44228",
        "ev_cisa_kev_CVE_2021_44228",
    }
    assert matches[0].exact_match
    assert "CVE-2021-44228" in matches[0].matched_keys


def test_cwe_lookup_returns_sql_injection_context() -> None:
    provider = CyberEvidenceProvider()
    matches = provider.search("unsanitized login query CWE-89", cwe_ids=["CWE-89"], top_k=3)
    evidence_ids = {m.record.evidence_id for m in matches}
    assert "ev_cwe_89_sql_injection" in evidence_ids


def test_fetch_returns_remora_evidence_provider_result() -> None:
    provider = CyberEvidenceProvider()
    result = provider.fetch(
        question="Should we treat CVE-2024-3094 in production xz as critical?",
        domain="supply_chain_security",
        risk_tier="critical",
        action_type="triage",
        target_environment="production",
        oracle_responses=[],
    )
    assert result.signal_source == "retrieval_cyber_evidence"
    assert result.signal.evidence_strength > 0.2
    assert result.provenance is not None
    assert result.provenance["evidence"]


def test_known_exploited_production_case_escalates() -> None:
    provider = CyberEvidenceProvider()
    result = provider.triage(
        title="Internet-facing Log4j dependency",
        description="Production service includes log4j 2.14.1 and CVE-2021-44228",
        severity="critical",
        cve_ids=["CVE-2021-44228"],
        packages=["log4j"],
        exposed=True,
        production=True,
        tool_signals=3,
    )
    assert result.verdict == CyberTriageVerdict.ESCALATE
    assert result.governance_action == "ESCALATE"
    assert result.exploit_classification == ExploitClassification.KNOWN_EXPLOITED
    assert result.confidence > 0.5
    assert result.poc_plan is not None
    assert result.poc_plan.readiness == PoCReadiness.HUMAN_REVIEW_REQUIRED
    assert "third-party systems" in " ".join(result.poc_plan.blocked_actions)


def test_correlated_sql_injection_case_is_report_ready_or_reviewable() -> None:
    provider = CyberEvidenceProvider()
    result = provider.triage(
        title="Unsanitized login SQL query",
        description="User-controlled username is concatenated into SELECT query. CWE-89.",
        severity="high",
        cwe_ids=["CWE-89"],
        attack_ids=["T1190"],
        exposed=True,
        production=True,
        tool_signals=2,
    )
    assert result.verdict in {
        CyberTriageVerdict.REPORT_READY,
        CyberTriageVerdict.NEEDS_REVIEW,
        CyberTriageVerdict.ESCALATE,
    }
    assert result.verdict != CyberTriageVerdict.LIKELY_FALSE_POSITIVE
    assert result.governance_action in {"VERIFY", "ESCALATE"}
    assert result.exploit_classification in {
        ExploitClassification.EMERGING_OR_UNKNOWN,
        ExploitClassification.PUBLIC_EXPLOIT_LIKELY,
        ExploitClassification.KNOWN_EXPLOITED,
    }


def test_vector_records_are_public_rag_ready() -> None:
    provider = CyberEvidenceProvider()
    records = provider.to_vector_records()
    assert records
    first = records[0]
    assert {"id", "text", "metadata"} <= first.keys()
    assert first["text"]
    assert "source_url" in first["metadata"]
    assert "cve_ids" in first["metadata"]


def test_unknown_high_risk_weakness_is_not_known_exploited() -> None:
    provider = CyberEvidenceProvider()
    result = provider.triage(
        title="Potential SSRF against cloud metadata service",
        description="URL fetcher may reach 169.254.169.254. CWE-918.",
        severity="high",
        cwe_ids=["CWE-918"],
        exposed=True,
        production=True,
        tool_signals=1,
    )
    assert result.exploit_classification == ExploitClassification.EMERGING_OR_UNKNOWN
    assert result.verdict in {
        CyberTriageVerdict.NEEDS_REVIEW,
        CyberTriageVerdict.REPORT_READY,
        CyberTriageVerdict.ESCALATE,
    }
    assert result.poc_plan is not None
    assert result.poc_plan.review_required


def test_poc_plan_is_defensive_and_non_weaponizing() -> None:
    provider = CyberEvidenceProvider()
    result = provider.triage(
        title="Shell command injection",
        description="User input reaches shell command construction. CWE-78.",
        severity="high",
        cwe_ids=["CWE-78"],
        attack_ids=["T1059"],
        exposed=False,
        production=False,
        tool_signals=2,
    )
    assert result.poc_plan is not None
    plan_text = " ".join(result.poc_plan.steps + result.poc_plan.blocked_actions).lower()
    assert "synthetic data" in plan_text or "non-production" in plan_text or "sandbox" in plan_text
    assert "do not run exploit payloads" in plan_text


def test_cyber_provider_does_not_depend_on_gostar_classes() -> None:
    source = Path("remora/evidence/cyber.py").read_text(encoding="utf-8")
    assert "from remora.integrations" not in source
    assert "GoStarBridge" not in source
    assert "GoStarFinding" not in source


def test_importable_from_public_api() -> None:
    from remora import CyberEvidenceProvider as PublicProvider
    from remora import ExploitClassification as PublicClassification

    assert PublicProvider is CyberEvidenceProvider
    assert PublicClassification is ExploitClassification
    assert DEFAULT_CYBER_EVIDENCE_PATH.exists()
