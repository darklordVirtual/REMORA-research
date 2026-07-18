# Finance / AML Evidence Pack, v1

Public REMORA evidence corpus for AML, sanctions screening, and financial
compliance triage.  Covers FATF typologies, FinCEN SAR guidance, EU AMLD
risk indicators, and OFAC sanctions.

## Why This Exists

Financial crime triage shares the same structural problem as vulnerability
triage: high false-positive rates, expensive analyst time, and catastrophic
consequences for missed escalations.

REMORA governs financial risk findings the same way it governs software
vulnerabilities: evidence retrieval → signal aggregation → verdict.  The
key domain adaptations are:

- **OFAC SDN match** (`kev=true` analogue) always escalates, regardless
  of transaction size or apparent legitimacy.
- **Confirmed FATF typologies** with elevated-risk context (PEP, high-risk
  jurisdiction) trigger ESCALATE.
- **Normal business patterns** (documented payroll, known recurring payments)
  are clearly suppressed through a contradiction-scored false-positive record.

## Evidence Sources

| Source | Records | Coverage |
|---|---|---|
| FATF typologies | 8 | Structuring, round-tripping, shell layering, TBML, hawala, crypto mixing, real estate, layering |
| EU AMLD | 7 | PEP, adverse media, high-risk jurisdiction, beneficial ownership, real estate, new products, CDD triggers |
| FinCEN | 4 | Velocity anomaly, SAR obligation, high-risk account, layering indicators |
| OFAC | 1 | SDN match escalation behaviour |
| REMORA seed | 1 | Normal business variation false-positive pattern |

## Schema

Evidence objects use the same JSONL schema as `cyber_evidence_v1`, with
these field semantics:

| Field | Finance meaning |
|---|---|
| `attack_ids` | FATF typology codes (FATF-TYP-NN) and AMLD risk indicator codes (AMLD-RI-NN) |
| `packages` | Financial instrument / typology classification tags |
| `kev` | `true` = OFAC SDN or equivalent direct sanctions-list match |
| `epss_score` | Typology risk score (confirmed-typology likelihood, 0–1) |
| `exploit_maturity` | `confirmed_typology` / `regulatory_requirement` / `regulatory_guidance` |

## Triage Rules

The `FinanceEvidenceProvider.triage()` method applies these rules in order:

1. **SDN match**, `sdnmatch=True` → ESCALATE
2. **Known typology + elevated risk**, HIGH_RISK_TYPOLOGY AND exact_count ≥ 2
   AND (`pep_exposure=True` OR `high_risk_jurisdiction=True`) → ESCALATE
3. **High-risk signal**, severity high/critical AND risk_score ≥ 0.80 AND
   exact match → ESCALATE
4. **Report ready**, confidence ≥ 0.68 AND exact match AND tool_signals ≥ 2
   → REPORT_READY
5. **Likely false positive**, confidence ≤ 0.22 AND contradiction ≥ 0.35
   → LIKELY_FALSE_POSITIVE
6. **Default**, NEEDS_REVIEW

## Quick Start

```python
from remora.evidence.domains.finance import FinanceEvidenceProvider

provider = FinanceEvidenceProvider()

# OFAC SDN match — always ESCALATE
result = provider.triage(
    title="OFAC SDN match on pending wire transfer",
    description="Customer matches OFAC SDN entry. USD 250,000 pending.",
    severity="critical",
    sdnmatch=True,
    tool_signals=3,
)
print(result.verdict.value)                          # ESCALATE
print(result.finance_risk_classification.value)      # REGULATORY_BREACH

# Confirmed structuring
result = provider.triage(
    title="Confirmed structuring pattern",
    description="14 cash deposits between USD 4,200-4,900 over 8 days.",
    severity="high",
    fatf_codes=["FATF-TYP-01"],
    amld_codes=["AMLD-RI-05"],
    typology_tags=["structuring", "cash_deposits"],
    tool_signals=3,
)
print(result.verdict.value)  # ESCALATE

# Normal payroll — suppressed
result = provider.triage(
    title="Regular monthly payroll disbursement",
    description="Documented payroll mandate. 45 employees. Amounts match contracts.",
    severity="low",
    risk_tags=["routine_transaction", "payroll"],
    tool_signals=1,
)
print(result.verdict.value)  # LIKELY_FALSE_POSITIVE or NEEDS_REVIEW
```

## Benchmark Cases

10 cases in `cases/finance_cases.jsonl`.  Run with:

```bash
python scripts/run_domain_benchmark.py --domain finance
```

| Expected verdict | Count |
|---|---|
| ESCALATE | 3 |
| REPORT_READY | 4 |
| NEEDS_REVIEW | 2 |
| LIKELY_FALSE_POSITIVE | 1 |

## Claim Status

Supported:
- Evidence loads from JSONL and passes schema validation.
- Exact FATF and AMLD code lookup is deterministic.
- SDN match (`sdnmatch=True`) always produces ESCALATE.
- Confirmed typologies with high-risk context produce ESCALATE.
- All 10 benchmark cases pass with 100% precision, escalation recall,
  and FP suppression rate.

Not claimed:
- This is not a complete AML / KYC screening system.
- This does not replace OFAC screening software, SAR analysis, or legal review.
- Accuracy on real-world transaction monitoring findings is not measured here.
- This does not guarantee regulatory compliance in any jurisdiction.

## Extending

To add a new evidence record, append a JSONL line to
`evidence/finance_objects.jsonl` following the schema above.  Validate with:

```bash
make finance-evidence
```
