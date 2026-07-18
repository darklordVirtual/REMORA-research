# AI Governance Evidence Pack, v1

Public REMORA evidence corpus for AI/ML governance triage.  Covers OWASP LLM
Top 10, MITRE ATLAS, EU AI Act, and NIST AI RMF.  No proprietary model
evaluation tools or scanner internals are included.

## Why This Exists

AI systems fail in ways that require domain-specific governance decisions:

- A prompt injection attack on a production chatbot is not the same as a
  software vulnerability, it has no CVE, but it has a confirmed OWASP LLM
  attack pattern and an exploitability signal.
- An EU AI Act prohibited use case (real-time biometric surveillance) requires
  immediate escalation regardless of attack probability.
- A hallucination risk in a medical AI deployment requires a report, not
  dismissal, even without a CVE.

REMORA uses this evidence pack to answer domain-appropriate questions:

```
Which OWASP LLM risk applies?
Does the EU AI Act prohibit this practice?
Is this a MITRE ATLAS technique on a production AI system?
Is this a benign test artefact or a real governance issue?
```

## Evidence Sources

| Source | Records | Coverage |
|---|---|---|
| OWASP LLM Top 10 | 6 | LLM01 prompt injection, LLM02 insecure output, LLM03 training poisoning, LLM06 PII disclosure, LLM08 excessive agency, LLM09 overreliance |
| MITRE ATLAS | 4 | AML.T0018 backdoor, AML.T0019 poisoned datasets, AML.T0020 poison training data, AML.T0012 model inversion |
| EU AI Act | 5 | Art.5 prohibited (biometric, social scoring, subliminal), Annex III high-risk (medical, employment) |
| NIST AI RMF | 3 | Hallucination measurement gap, clinical overreliance, algorithmic bias |
| REMORA seed | 1 | Benign test/sandbox false-positive pattern |

## Schema

Evidence objects use the same JSONL schema as `cyber_evidence_v1`, with these
field semantics:

| Field | AI governance meaning |
|---|---|
| `cve_ids` | OWASP LLM IDs (LLM01–LLM10) or EU AI Act category codes (EUAIA-*) |
| `attack_ids` | MITRE ATLAS technique IDs (AML.T****) |
| `kev` | `true` = EU AI Act Article 5 prohibited practice |
| `epss_score` | Risk priority score (exploitation likelihood analogue, 0–1) |
| `cvss_score` | Impact severity score (0–10) |
| `exploit_maturity` | `known_exploited_in_wild` / `actively_demonstrated` / `widely_documented` / `regulatory_prohibition` |
| `packages` | AI framework or model family names |

## Triage Rules

The `AIGovernanceEvidenceProvider.triage()` method applies these rules in
order:

1. **Prohibited**, `kev=true` (EU AI Act Art.5) → ESCALATE
2. **Known attack on production**, KNOWN_ATTACK_PATTERN classification
   AND `in_production=True` AND exact identifier match → ESCALATE
3. **High-priority confirmed risk**, severity high/critical AND risk_priority
   ≥ 0.80 AND exact match → ESCALATE
4. **Report ready**, confidence ≥ 0.68 AND exact match AND tool_signals ≥ 2
   → REPORT_READY
5. **Likely false positive**, confidence ≤ 0.22 AND contradiction ≥ 0.35
   → LIKELY_FALSE_POSITIVE
6. **Default**, NEEDS_REVIEW

## Quick Start

```python
from remora.evidence.domains.ai_governance import AIGovernanceEvidenceProvider

provider = AIGovernanceEvidenceProvider()

# EU AI Act prohibited practice
result = provider.triage(
    title="Real-time facial recognition in shopping centre",
    description="No judicial authorisation. EUAIA-PROHIBITED-BIOMETRIC.",
    severity="critical",
    euaia_ids=["EUAIA-PROHIBITED-BIOMETRIC"],
    in_production=True,
    tool_signals=2,
)
print(result.verdict.value)               # ESCALATE
print(result.risk_classification.value)   # PROHIBITED_USE_CASE

# Known attack pattern on production AI
result = provider.triage(
    title="Prompt injection confirmed in production chatbot",
    description="Document injection overrides system instructions. LLM01.",
    severity="critical",
    llm_ids=["LLM01", "LLM08"],
    in_production=True,
    exposed_endpoint=True,
    tool_signals=3,
)
print(result.verdict.value)  # ESCALATE
```

## Benchmark Cases

10 cases in `cases/ai_governance_cases.jsonl`.  Run with:

```bash
python scripts/run_domain_benchmark.py --domain ai_governance
```

| Expected verdict | Count |
|---|---|
| ESCALATE | 5 |
| REPORT_READY | 2 |
| NEEDS_REVIEW | 2 |
| LIKELY_FALSE_POSITIVE | 1 |

## Claim Status

Supported:
- Evidence loads from JSONL and passes schema validation.
- Exact LLM-ID, ATLAS, and EUAIA identifier lookup is deterministic.
- Prohibited use cases (kev=true) always produce ESCALATE on any context.
- Known attack patterns on production AI endpoints produce ESCALATE.
- All 10 benchmark cases pass with 100% precision and escalation recall.

Not claimed:
- This is not a complete AI safety evaluation framework.
- This does not prove model robustness or red-team coverage.
- This does not replace a formal EU AI Act conformity assessment.
- Accuracy on real-world AI governance findings is not measured here.

## Extending

To add a new evidence record, append a JSONL line to
`evidence/ai_governance_objects.jsonl` following the schema above.  Use
the validation check:

```bash
make ai-governance-evidence
```
