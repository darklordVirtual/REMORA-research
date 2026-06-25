from __future__ import annotations

from remora.evidence.domains.ai_governance import (
    AIGovernanceClassification,
    AIGovernanceEvidenceProvider,
    AIGovernanceVerdict,
)


def test_ai_governance_provider_loads_dataset() -> None:
    provider = AIGovernanceEvidenceProvider()
    summary = provider.summary()
    assert provider.store_size >= 15
    assert not summary["load_errors"]
    assert summary["domains"]


def test_exact_llm_id_lookup() -> None:
    provider = AIGovernanceEvidenceProvider()
    matches = provider.search("LLM01 prompt injection attack on AI endpoint", llm_ids=["LLM01"], top_k=5)
    assert matches
    assert any(m.exact_match for m in matches)
    assert any("LLM01" in m.matched_keys for m in matches)


def test_atlas_id_lookup() -> None:
    provider = AIGovernanceEvidenceProvider()
    matches = provider.search("AML.T0020 training data poisoning deployed model", atlas_ids=["AML.T0020"], top_k=5)
    assert matches
    assert any(m.exact_match for m in matches)


def test_prohibited_eu_ai_act_escalates() -> None:
    provider = AIGovernanceEvidenceProvider()
    result = provider.triage(
        title="Real-time biometric surveillance in public space",
        description="AI system performs real-time facial recognition of individuals in public spaces without judicial authorisation. EUAIA-PROHIBITED-BIOMETRIC.",
        severity="critical",
        euaia_ids=["EUAIA-PROHIBITED-BIOMETRIC"],
        in_production=True,
        tool_signals=2,
    )
    assert result.verdict == AIGovernanceVerdict.ESCALATE
    assert result.governance_action == "ESCALATE"
    assert result.risk_classification == AIGovernanceClassification.PROHIBITED_USE_CASE


def test_known_attack_on_production_escalates() -> None:
    provider = AIGovernanceEvidenceProvider()
    result = provider.triage(
        title="Prompt injection on production customer chatbot",
        description="Production chatbot accepts raw document uploads as context. Adversarial documents override system instructions.",
        severity="critical",
        llm_ids=["LLM01", "LLM08"],
        in_production=True,
        exposed_endpoint=True,
        tool_signals=3,
    )
    assert result.verdict == AIGovernanceVerdict.ESCALATE
    assert result.risk_classification in {
        AIGovernanceClassification.KNOWN_ATTACK_PATTERN,
        AIGovernanceClassification.PROHIBITED_USE_CASE,
    }


def test_training_poisoning_confirmed_escalates() -> None:
    provider = AIGovernanceEvidenceProvider()
    result = provider.triage(
        title="Training data poisoning confirmed in production model",
        description="Backdoor trigger identified post-deployment via evaluation. Fine-tuning dataset sourced from unverified repository. AML.T0020 confirmed.",
        severity="critical",
        llm_ids=["LLM03"],
        atlas_ids=["AML.T0020"],
        in_production=True,
        tool_signals=2,
    )
    assert result.verdict == AIGovernanceVerdict.ESCALATE


def test_benign_test_prompt_not_escalated() -> None:
    provider = AIGovernanceEvidenceProvider()
    result = provider.triage(
        title="Red-team test harness prompt",
        description="Automated red-team evaluation test prompt in isolated sandbox. Example test fixture content for evaluation purposes.",
        severity="low",
        risk_tags=["test_artifact", "sandbox", "benign_context"],
        tool_signals=1,
    )
    assert result.verdict != AIGovernanceVerdict.ESCALATE


def test_fetch_returns_evidence_provider_result() -> None:
    provider = AIGovernanceEvidenceProvider()
    result = provider.fetch(
        question="Is LLM08 excessive agency a risk for production autonomous agents?",
        domain="ai_governance",
        risk_tier="high",
        action_type="triage",
        target_environment="production",
        oracle_responses=[],
    )
    assert result.signal_source == "retrieval_ai_governance_evidence"
    assert result.signal.evidence_strength > 0.0
    assert result.provenance is not None


def test_vector_records_metadata_only() -> None:
    provider = AIGovernanceEvidenceProvider()
    records = provider.to_vector_records()
    assert len(records) >= 15
    for rec in records:
        assert "id" in rec
        assert "text" in rec
        assert "metadata" in rec
        assert "source" in rec["metadata"]
        assert "prohibited" in rec["metadata"]


def test_medical_ai_without_conformity_report_ready_or_escalate() -> None:
    provider = AIGovernanceEvidenceProvider()
    result = provider.triage(
        title="Medical AI deployed without conformity assessment",
        description="AI system providing medical diagnosis deployed without CE marking or conformity assessment. EUAIA-HIGHRISK-MEDICAL applies.",
        severity="high",
        euaia_ids=["EUAIA-HIGHRISK-MEDICAL"],
        llm_ids=["LLM09"],
        in_production=True,
        tool_signals=2,
    )
    assert result.verdict in {AIGovernanceVerdict.ESCALATE, AIGovernanceVerdict.REPORT_READY}
    assert result.verdict != AIGovernanceVerdict.LIKELY_FALSE_POSITIVE
