---
id: nist_ai_rmf_summary
title: NIST AI Risk Management Framework (AI RMF 1.0) — REMORA Summary
source: NIST AI RMF 1.0 + Generative AI Profile (NIST AI 600-1)
source_url: https://www.nist.gov/itl/ai-risk-management-framework
version_or_accessed_date: AI RMF 1.0 (January 2023), NIST AI 600-1 (July 2024)
license_note: NIST publications are in the public domain (17 U.S.C. § 105).
intended_use: EvidenceProvider retrieval, policy gate rules, audit evidence trail
---

## 1. What this source says

NIST AI RMF defines a framework for managing AI risk across four core functions:

- **GOVERN** — establish policies, roles, oversight, accountability
- **MAP** — identify and categorize AI risk context
- **MEASURE** — analyze and assess risks using metrics and testing
- **MANAGE** — prioritize and treat identified risks

The Generative AI Profile (NIST AI 600-1) extends this with 12 GenAI-specific risks:
CBRN information, confabulation, data privacy, data poisoning, homogeneity,
human-AI configuration, information integrity, information security,
intellectual property, obscene/abusive content, offensive cyber capabilities,
and value chain/component integration.

Key principles relevant to autonomous agents:
- Human oversight must be maintained for high-consequence actions
- AI systems should be explainable and auditable
- Uncertainty in AI outputs must be communicated and acted upon
- Governance requires continuous measurement and feedback loops

## 2. Why it matters for REMORA

REMORA's ACCEPT/VERIFY/ABSTAIN/ESCALATE gate directly implements the MANAGE function.
The DecisionEnvelope audit trail satisfies GOVERN requirements for accountability.
Thermodynamic uncertainty quantification (H, D, trust_score) maps to MEASURE.
The shadow replay system provides the feedback loop NIST requires for MANAGE.

## 3. Gate rules derived from this source

| Condition | Gate | Rationale |
|-----------|------|-----------|
| High-consequence action, no human review path | ESCALATE | GOVERN: human oversight required |
| AI output uncertainty above threshold | VERIFY | MEASURE: communicate uncertainty |
| Action affects critical infrastructure | ESCALATE | MAP: high-risk AI context |
| No explainability/audit trail available | VERIFY | GOVERN: accountability |
| GenAI confabulation risk detected | VERIFY | AI 600-1: confabulation risk |
| Data privacy impact possible | VERIFY or ESCALATE | AI 600-1: data privacy |

## 4. Evidence fields REMORA should require

- `human_oversight_documented`: change ticket or approval reference
- `risk_category`: mapped to NIST AI RMF risk taxonomy
- `explainability_available`: audit chain hash present
- `uncertainty_quantified`: trust_score and phase present

## 5. Example scenarios

- Deploy ML model to production → VERIFY (measurement/oversight required)
- Read-only metrics query by approved agent → ACCEPT (low risk, mapped)
- Autonomous agent modifies access controls → ESCALATE (GOVERN: critical)

## 6. Limitations / do-not-overclaim notes

This summary is a curated extract for REMORA evidence retrieval.
It does not constitute a compliance certification or audit.
Organizations using REMORA for regulated AI deployments must perform their own
NIST AI RMF conformance assessment.
REMORA does not claim to be NIST AI RMF compliant.
