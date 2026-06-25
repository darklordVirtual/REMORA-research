# RAG Critical Router v1 — Results Summary

**Dataset**: MultiNLI validation_matched (used in place of FEVER — see metadata)
**N**: 3000 critical-phase items

## Routing Distribution

| Label | evidence_accept | abstain | escalate |
|-------|----------------|---------|----------|
| entailment | 304 | 3 | 735 |
| neutral | 0 | 3 | 930 |
| contradiction | 0 | 846 | 179 |

## Key Metrics

| Metric | Value |
|--------|-------|
| Resolution rate (no escalation) | 38.5% |
| Escalation reduction vs trust-only baseline | 38.5% |
| evidence_accept precision (entailment) | 100.0% |
| false_accept rate (contradiction) | 0.0% |
| oracle accuracy on evidence_accept items | 72.7% |
| abstain precision (contradiction) | 99.3% |

## Comparison: Trust-only vs Evidence-guided

| | Trust-only (baseline) | Evidence-guided |
|-|-----------------------|-----------------|
| Critical-phase coverage | 0 % | 38.5% |
| Evidence-accept precision | N/A | 100.0% |
| Escalation rate | 100 % | 61.5% |

## Interpretation

The evidence channel resolves a substantial fraction of critical-phase items without human
escalation.  Items routed to `evidence_accept` have 100% precision (label=entailment),
compared with the trust-only oracle accuracy of ~62.5 % in the critical zone
(NEGATIVE_RESULTS.md Finding 3).  The false-accept rate for contradicted claims is low,
confirming that the contradiction gate correctly routes refuted claims to ABSTAIN rather
than spuriously accepting them.

## Risk-Coverage Curve (sampled)

| Threshold | Coverage | Risk (1−precision) |
|-----------|----------|--------------------|
| 0.50 | 20.7% | 1.6% |
| 0.60 | 18.5% | 0.9% |
| 0.70 | 15.7% | 0.2% |
| 0.80 | 11.0% | 0.0% |
| 0.90 | 4.2% | 0.0% |
| 1.00 | 0.0% | N/A |
