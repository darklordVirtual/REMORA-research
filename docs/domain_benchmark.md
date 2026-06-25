# REMORA Cross-Domain Governance Benchmark

## Purpose

This document describes the multi-domain evidence benchmark that validates
REMORA's governance verdicts across three distinct operational domains.  The
benchmark is deterministic, requires no API keys, and produces a machine-
readable result artifact at `artifacts/domain_benchmark_results.json`.

## Architecture

REMORA governs agent actions through evidence-backed, human-reviewable
decisions.  The evidence layer is organised as a **registry of domain
providers** — each provider specialises in one risk domain while sharing
the same four-verdict governance interface.

```
                ┌─────────────────────────────────┐
                │      Agent action / finding      │
                └────────────────┬────────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │      Domain evidence provider        │
              │                                      │
              │  cyber          →  CyberEvidenceProvider   │
              │  ai_governance  →  AIGovernanceProvider    │
              │  finance        →  FinanceEvidenceProvider │
              └──────────────────┬──────────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │         Evidence retrieval           │
              │                                      │
              │  1. Exact lookup — CVE/CWE/ATLAS/    │
              │     FATF/LLM-ID/KEV/SDN match        │
              │                                      │
              │  2. Lexical / RAG search — BM25-     │
              │     style token Jaccard over the     │
              │     curated evidence JSONL corpus    │
              └──────────────────┬──────────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │         EvidenceSignal               │
              │                                      │
              │  evidence_strength   (0–1)           │
              │  contradiction_score (0–1)           │
              │  citation_coverage   (0–1)           │
              │  cross_evidence_consistency (0–1)    │
              │  source_reliability  (0–1)           │
              └──────────────────┬──────────────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │         Governance verdict           │
              │                                      │
              │  ESCALATE            →  ESCALATE     │
              │  REPORT_READY        →  VERIFY       │
              │  NEEDS_REVIEW        →  VERIFY       │
              │  LIKELY_FALSE_POSITIVE → VERIFY      │
              └─────────────────────────────────────┘
```

## How Evidence Retrieval Works

### Step 1 — Exact identifier lookup

Each provider indexes its evidence corpus by domain-specific identifiers:

| Domain | Exact identifiers |
|---|---|
| Cyber | CVE-YYYY-NNNNN, CWE-NNN, ATT&CK T-ID, package name, KEV flag |
| AI governance | OWASP LLM01–LLM10, MITRE ATLAS AML.T****, EU AI Act EUAIA-*, prohibited flag |
| Finance | FATF-TYP-NN, AMLD-RI-NN, sdnmatch flag, typology tags |

An exact match contributes `score = 0.58 + 0.12 × number_of_matching_keys`,
capped at 1.0.  This ensures that a CVE with both NVD and CISA KEV records
ranks above a generic CWE taxonomy entry.

### Step 2 — Lexical search

Query tokens (lowercase, 3+ characters) are Jaccard-scored against each
evidence record's `vector_text` field.  Tag similarity and source authority
add further signal.  Final score:

```
score = exact_score
      + 0.22 × tag_jaccard
      + 0.30 × token_jaccard
      + 0.10 × (authority_score × freshness_score)
```

### Step 3 — Signal aggregation

The top-K matches are aggregated into an `EvidenceSignal`:

- `evidence_strength` — authority-weighted mean score of top-3 matches
- `contradiction_score` — mean contradiction score of all matches
- `citation_coverage` — matches / 5 (normalised)
- `cross_evidence_consistency` — pairwise tag Jaccard across all matches
- `source_reliability` — mean authority score

### Step 4 — Governance decision

Confidence is a weighted sum of the signal components plus bonuses:

```
confidence = 0.42 × evidence_strength
           + 0.22 × source_reliability
           + 0.16 × citation_coverage
           + 0.08 × min(1, exact_count / 2)
           + 0.06 if known_exploited_flag (kev / prohibited / sdnmatch)
           + 0.04 if max_priority_score ≥ 0.80 (EPSS / risk priority)
           + 0.02 if tool_signals ≥ 2
```

Verdict rules (in priority order, same logic in all three providers):

| Condition | Verdict |
|---|---|
| known_exploited_flag AND (exposed OR production OR in_production) | ESCALATE |
| known_attack_pattern AND (in_production OR exposed_endpoint) AND exact match | ESCALATE |
| severity high AND max_priority ≥ 0.80 AND exact match | ESCALATE |
| confidence ≥ 0.68 AND exact match AND tool_signals ≥ 2 | REPORT_READY |
| confidence ≤ 0.22 AND contradiction ≥ 0.35 | LIKELY_FALSE_POSITIVE |
| (all other cases) | NEEDS_REVIEW |

## Domains

### Cyber (vulnerability management)

**Evidence corpus**: `datasets/cyber_evidence_v1/`

Sources: NVD CVE API, CISA KEV, FIRST EPSS, GitHub Advisory Database,
CWE taxonomy, MITRE ATT&CK, OWASP GenAI.

Key escalation signal: `kev=true` (CISA Known Exploited Vulnerability).

Identifiers: CVE-YYYY-NNNNNN, CWE-NNN, T-NNNN (ATT&CK), package names.

### AI Governance

**Evidence corpus**: `datasets/ai_governance_v1/`

Sources: OWASP LLM Top 10, MITRE ATLAS, EU AI Act, NIST AI RMF, WHO.

Key escalation signal: `kev=true` repurposed as `prohibited=true` (EU AI Act
Article 5 prohibited practice).  Known attack patterns on production AI
endpoints also trigger escalation regardless of KEV status.

Identifiers: LLM01–LLM10 (OWASP), AML.T**** (MITRE ATLAS), EUAIA-* (EU AI Act).

### Finance / AML

**Evidence corpus**: `datasets/finance_v1/`

Sources: FATF typologies, FinCEN SAR guidance, EU AMLD, OFAC, Basel.

Key escalation signal: `kev=true` repurposed as `sdnmatch=true` (OFAC
Specially Designated National match).  Confirmed typologies with elevated-
risk context also escalate.

Identifiers: FATF-TYP-NN, AMLD-RI-NN, typology tags (structuring, round_tripping, etc.).

## GO-STAR Bridge

For the cyber domain, findings from the GO-STAR proprietary scanner enter
REMORA through `CyberFindingEnvelope` — see `docs/go_star_bridge.md`.

The envelope carries:
- `TargetScanProfile` — authorised scope and scan mode
- Finding fields — title, CWEs, CVEs, source/sink, tool signal count
- `DisclosureLedger` — 6-stage capability ladder
- `ResearchArtifactRef[]` — metadata-only references to private PoC vault

```python
from remora.evidence.finding_envelope import (
    CyberFindingEnvelope, TargetScanProfile, DisclosureLedger, DisclosureStatus
)
from remora.evidence.cyber import CyberEvidenceProvider

provider = CyberEvidenceProvider()
env = CyberFindingEnvelope(
    finding_id="find-001",
    target_profile=TargetScanProfile(...),
    title="SQL injection in login path",
    severity="high",
    cwe_ids=("CWE-89",), cve_ids=(), attack_ids=("T1190",),
    packages=(), source_file="api/auth.py", sink_file="api/auth.py",
    tool_signals=2, exposed=True, production=True,
)

env = env.apply_remora(provider)
print(env.verdict())            # "REPORT_READY"
print(env.governance_action())  # "VERIFY"
```

## Benchmark Cases

Each domain has a JSONL file of benchmark cases:

| Domain | File | Cases |
|---|---|---|
| Cyber | `datasets/cyber_evidence_v1/cases/security_cases.jsonl` | 12 |
| AI governance | `datasets/ai_governance_v1/cases/ai_governance_cases.jsonl` | 10 |
| Finance | `datasets/finance_v1/cases/finance_cases.jsonl` | 10 |

Case format:

```json
{
  "case_id": "finance_case_sdn_match_001",
  "domain": "finance",
  "title": "OFAC SDN list match on pending wire transfer",
  "triage_kwargs": {
    "title": "...", "description": "...", "severity": "critical",
    "sdnmatch": true, "tool_signals": 3
  },
  "expected_verdict": "ESCALATE",
  "acceptable_verdicts": [],
  "must_not_verdict": "LIKELY_FALSE_POSITIVE",
  "tags": ["sdn_match", "sanctions"],
  "reason": "Direct OFAC SDN match is a regulatory breach"
}
```

`expected_verdict` is the ideal outcome.
`acceptable_verdicts` are also considered passing (e.g. a KEV case that gets
REPORT_READY when ESCALATE was expected, but ESCALATE is listed as acceptable).
`must_not_verdict` is a hard failure regardless — a KEV finding classified as
LIKELY_FALSE_POSITIVE is a critical governance error.

## Pass / Fail Rules

```
passed = (actual == expected OR actual in acceptable_verdicts)
         AND actual != must_not_verdict

critical_fail = actual == must_not_verdict
```

## Metrics

| Metric | Definition |
|---|---|
| precision | passed / total |
| escalation_recall | (actual==ESCALATE for ESCALATE-expected) / total ESCALATE-expected |
| fp_suppression_rate | (LIKELY_FP or NEEDS_REVIEW for LIKELY_FP-expected) / total LIKELY_FP-expected |
| report_ready_precision | correct REPORT_READY predictions / all REPORT_READY predictions |
| critical_failure_rate | must_not violations / total |

## Benchmark Results

Results are stored in `artifacts/domain_benchmark_results.json` and are
produced by:

```bash
make domain-benchmark
```

The results below are derived from that artifact and are machine-verifiable.

| Domain | Cases | Precision | Escalation Recall | FP Suppression | Report-ready Prec |
|---|---|---|---|---|---|
| Cyber | 12 | 100% | 100% | 100% | 100% |
| AI governance | 10 | 100% | 100% | 100% | 100% |
| Finance | 10 | 100% | 100% | 100% | 100% |
| **Overall** | **32** | **100%** | **100%** | **100%** | **100%** |

### What these numbers mean

**100% precision** means every case in the benchmark dataset receives
the expected or an explicitly acceptable verdict.  It does not mean the
system is infallible on unseen data — it means the benchmark cases are
well-calibrated and the evidence corpus supports them.

**100% escalation recall** means every case that a security analyst would
flag as requiring immediate action (KEV, prohibited practice, SDN match,
confirmed attack on production) was escalated.  Missing an escalation on
a critical case is the most dangerous governance error; this metric
measures whether the system avoids that failure mode on the test cases.

**100% FP suppression** means placeholder secrets, sandbox test prompts,
and normal recurring payments are never escalated or sent directly to
REPORT_READY.  They land in NEEDS_REVIEW (appropriate review trigger) or
LIKELY_FALSE_POSITIVE, not in the high-priority queue.

**100% report-ready precision** means when REMORA predicts REPORT_READY,
it is correct — no false REPORT_READY verdicts on this dataset.

### What these numbers do not mean

- This is not a production accuracy claim.  The benchmark covers 32 curated
  cases designed to be illustrative, not a representative sample.
- Confidence scores are calibrated against the seed evidence corpus only.
- The evidence corpus is not a complete vulnerability or regulatory database.
- GO-STAR scanner accuracy and false-positive rates are separately tracked
  in the GO-STAR artifacts and are not captured here.

## Running the Benchmark

```bash
# All domains
make domain-benchmark

# Single domain
python scripts/run_domain_benchmark.py --domain cyber
python scripts/run_domain_benchmark.py --domain ai_governance
python scripts/run_domain_benchmark.py --domain finance

# Validate evidence packs without running benchmark
make ai-governance-evidence
make finance-evidence
make cyber-evidence
```

## Claim Hygiene

Per `docs/claim_hygiene.md`:

- Numbers in this document are derived from `artifacts/domain_benchmark_results.json`.
- The benchmark is deterministic.  Running `make domain-benchmark` must
  reproduce the exact numbers above on any machine with the same codebase.
- No numbers in this document may be updated without re-running the benchmark
  and committing the updated artifact.
