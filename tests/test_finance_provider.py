from __future__ import annotations

from remora.evidence.domains.finance import (
    FinanceEvidenceProvider,
    FinanceRiskClassification,
    FinanceVerdict,
)


def test_finance_provider_loads_dataset() -> None:
    provider = FinanceEvidenceProvider()
    summary = provider.summary()
    assert provider.store_size >= 15
    assert not summary["load_errors"]
    assert summary["domains"]


def test_sdn_match_always_escalates() -> None:
    provider = FinanceEvidenceProvider()
    result = provider.triage(
        title="OFAC SDN match on pending wire transfer",
        description="Customer matches OFAC SDN entry. Wire transfer USD 250,000 pending.",
        severity="critical",
        sdnmatch=True,
        tool_signals=3,
    )
    assert result.verdict == FinanceVerdict.ESCALATE
    assert result.governance_action == "ESCALATE"
    assert result.finance_risk_classification == FinanceRiskClassification.REGULATORY_BREACH


def test_confirmed_structuring_escalates_with_sar() -> None:
    provider = FinanceEvidenceProvider()
    result = provider.triage(
        title="Confirmed structuring pattern",
        description="14 cash deposits between USD 4200-4900 over 8 days. Below CTR threshold. FATF-TYP-01.",
        severity="high",
        fatf_codes=["FATF-TYP-01"],
        amld_codes=["AMLD-RI-05"],
        typology_tags=["structuring", "cash_deposits"],
        risk_tags=["structuring", "sar_required"],
        tool_signals=3,
    )
    assert result.verdict == FinanceVerdict.ESCALATE


def test_shell_company_round_trip_escalates() -> None:
    provider = FinanceEvidenceProvider()
    result = provider.triage(
        title="Shell company round-tripping via offshore jurisdictions",
        description="Funds traced through three shell entities in BVI, Cayman, Liechtenstein back to originating owner.",
        severity="critical",
        fatf_codes=["FATF-TYP-02", "FATF-TYP-03"],
        amld_codes=["AMLD-RI-06", "AMLD-RI-04"],
        typology_tags=["round_tripping", "shell_company"],
        high_risk_jurisdiction=True,
        tool_signals=2,
    )
    assert result.verdict == FinanceVerdict.ESCALATE


def test_normal_payroll_not_escalated() -> None:
    provider = FinanceEvidenceProvider()
    result = provider.triage(
        title="Regular monthly payroll disbursement",
        description="Employer account with documented payroll mandate. Regular monthly salary to 45 employees. Amounts match contracts.",
        severity="low",
        risk_tags=["routine_transaction", "payroll", "recurring_payment", "low_risk"],
        tool_signals=1,
    )
    assert result.verdict != FinanceVerdict.ESCALATE


def test_pep_exposure_with_adverse_media_report_ready() -> None:
    provider = FinanceEvidenceProvider()
    result = provider.triage(
        title="PEP high-value transfer with adverse media",
        description="PEP tier 1 customer. Wire transfer EUR 800,000 to real estate entity. Recent adverse media: financial investigation.",
        severity="high",
        amld_codes=["AMLD-RI-01", "AMLD-RI-02"],
        typology_tags=["pep_screening", "real_estate"],
        pep_exposure=True,
        tool_signals=2,
    )
    assert result.verdict in {FinanceVerdict.REPORT_READY, FinanceVerdict.ESCALATE}
    assert result.verdict != FinanceVerdict.LIKELY_FALSE_POSITIVE


def test_exact_fatf_code_lookup() -> None:
    provider = FinanceEvidenceProvider()
    matches = provider.search("structuring smurfing FATF-TYP-01", fatf_codes=["FATF-TYP-01"], top_k=5)
    assert matches
    assert any(m.exact_match for m in matches)
    assert any("FATF-TYP-01" in m.matched_keys for m in matches)


def test_fetch_returns_evidence_provider_result() -> None:
    provider = FinanceEvidenceProvider()
    result = provider.fetch(
        question="Is structuring with FATF-TYP-01 a SAR filing trigger?",
        domain="aml_compliance",
        risk_tier="high",
        action_type="triage",
        target_environment="production",
        oracle_responses=[],
    )
    assert result.signal_source == "retrieval_finance_evidence"
    assert result.signal.evidence_strength >= 0.0
    assert result.provenance is not None


def test_vector_records_have_correct_fields() -> None:
    provider = FinanceEvidenceProvider()
    records = provider.to_vector_records()
    assert len(records) >= 15
    for rec in records:
        assert "id" in rec
        assert "text" in rec
        assert "metadata" in rec
        assert "sdnmatch" in rec["metadata"]
        assert "fatf_codes" in rec["metadata"]


def test_crypto_mixing_report_ready() -> None:
    provider = FinanceEvidenceProvider()
    result = provider.triage(
        title="Crypto assets routed through known mixer",
        description="Customer routes digital assets through Tornado Cash successor address before fiat conversion. FATF-TYP-05.",
        severity="high",
        fatf_codes=["FATF-TYP-05"],
        typology_tags=["cryptocurrency", "virtual_assets"],
        risk_tags=["crypto_mixing", "obfuscation"],
        tool_signals=2,
    )
    assert result.verdict in {FinanceVerdict.REPORT_READY, FinanceVerdict.ESCALATE}
    assert result.verdict != FinanceVerdict.LIKELY_FALSE_POSITIVE
