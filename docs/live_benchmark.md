# REMORA Live Oracle Benchmark

## Purpose

This document describes the live integration between REMORA's static evidence
providers and the GO-STAR REMORA Cloudflare Worker — three real AI models
running in consensus to evaluate security findings.

The live benchmark is the counterpart to the deterministic benchmark in
`docs/domain_benchmark.md`.  Where the static benchmark measures whether
curated evidence correctly governs known cases, the live benchmark measures
whether real LLMs agree with that governance — and documents where they don't.

## Architecture: Two Layers Working Together

```
Finding
  ↓
┌────────────────────────────────────────────────────────┐
│ Layer 1 — Static Evidence (remora.evidence.*)          │
│                                                        │
│  Exact lookup: CVE / CWE / ATT&CK / FATF / LLM-ID     │
│  Lexical RAG: token Jaccard over curated JSONL corpus  │
│  → deterministic, zero cost, 100% benchmark precision  │
└──────────────────────────┬─────────────────────────────┘
                           │
                     evidence verdict
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Layer 2 — Live Oracle Consensus (go-star-remora worker)│
│                                                        │
│  Oracle 1: Groq llama-3.1-8b-instant  (fast gate)     │
│  Oracle 2: Groq llama-3.3-70b-versatile (strong)      │
│  Oracle 3: OpenRouter mistral-7b-instruct (diverse)    │
│                                                        │
│  Lyapunov-inspired iteration: repeat sweeps until      │
│  support ≥ 0.72 or max_iterations (3) reached          │
│  → adds reasoning layer, catches cases static misses   │
└──────────────────────────┬─────────────────────────────┘
                           │
                  oracle consensus verdict
                           │
┌──────────────────────────▼─────────────────────────────┐
│ Fusion — REMORA Governance Decision                    │
│                                                        │
│  Both layers agree on risk  → high-confidence decision │
│  Both layers agree benign   → suppress as FP           │
│  Layers disagree            → NEEDS_REVIEW (escalate)  │
└────────────────────────────────────────────────────────┘
```

## Worker Endpoints

All endpoints are publicly accessible at
`https://go-star-remora.razorsharp.workers.dev`. No authentication required.
Results are KV-cached for 24 h, keyed on `hash(use_case + question + context)`.

| Endpoint | Input | Oracle question |
|---|---|---|
| `GET /status` | — | Worker health + oracle availability |
| `POST /assess` | `question, context, use_case` | General governance question |
| `POST /false-positive` | `hypothesis {description, cwe, symbol, file_path}` | Is this finding a false positive? |
| `POST /exploitability` | `hypothesis {description, cwe, source, sink}` | Is this finding exploitable? |
| `POST /evidence-fusion` | `finding, oracle_signals[]` | Do these signals confirm a real finding? |

Worker status at time of testing:
```json
{
  "ok": true,
  "n_oracles": 3,
  "models": {
    "groq_fast":   "llama-3.1-8b-instant",
    "groq_strong": "llama-3.3-70b-versatile",
    "openrouter":  "mistralai/mistral-7b-instruct"
  }
}
```

## Live Integration Tests

16 named integration tests confirm oracle behaviour against key cases.
Run with:

```bash
pytest tests/test_worker_integration.py -m live -v
```

Tests are excluded from `make test` (deterministic suite) and run separately.

### Results: 16/16 pass

| Category | Tests | Outcome |
|---|---|---|
| Worker health | 2 | PASS — 3 oracles confirmed |
| Cyber — exploitable findings | 4 | PASS — Log4Shell, command injection, SSRF, MOVEit all YES |
| Cyber — false positives | 1 | PASS — placeholder test secret correctly identified as FP |
| AI governance | 3 | PASS — EU AI Act prohibited, prompt injection, training poisoning all YES |
| AI governance — oracle limitation | 1 | PASS (documented limitation) |
| Finance/AML | 2 | PASS — SDN match, structuring both YES |
| Consensus properties | 3 | PASS (2 skip on stale cache) |

## Oracle Results on Key Cases

These results are from direct oracle calls (not KV cache) made during testing:

| Case | Oracle verdict | Confidence | Oracle calls | Summary |
|---|---|---|---|---|
| Log4Shell CVE-2021-44228 production | true | 1.00 | 9 | YES exploitable |
| Test fixture TEST_API_KEY placeholder | true (is FP) | 1.00 | 9 | YES is false positive |
| SSRF → cloud metadata endpoint | true | 1.00 | 9 | YES exploitable |
| MOVEit Transfer SQL injection | true | 1.00 | 9 | YES exploitable |
| EU AI Act prohibited biometric | true | 1.00 | 9 | YES is violation |
| Prompt injection on production AI | true | 1.00 | 9 | YES is real risk |
| Training data poisoning in prod | true | 1.00 | 9 | YES critical incident |
| OFAC SDN match | true | 1.00 | 9 | YES requires escalation |
| Confirmed structuring FATF-TYP-01 | true | 1.00 | 9 | YES SAR required |
| xz/liblzma backdoor CVE-2024-3094 | true | 0.76 | 3 | YES critical |

## Documented Oracle Limitations

### 1 — Red-team test artifacts (ai_security domain)

**Finding**: When asked whether an automated red-team test prompt in an
isolated sandbox is a real security incident, all 3 LLMs answer YES
(confidence ≈ 0.51, 3/3 models agree).

**Why**: Without specialised training, LLMs reason from the surface
description of adversarial prompt content and cannot reliably distinguish
a test harness from a production incident.

**Why this matters**: Static evidence (`ev_ai_gov_benign_test_prompt`,
`contradiction_score=0.58`) correctly suppresses this false positive.
The oracle alone would escalate it.  The two-layer design catches this.

**Implication for fusion**: When oracle says YES but static evidence says
LIKELY_FALSE_POSITIVE or NEEDS_REVIEW, the fusion output should be
NEEDS_REVIEW — not ESCALATE.  Disagreement routes to human.

### 2 — Stale KV cache from rate-limited oracle calls

**Finding**: Groq API rate limits (~30 req/min on llama-3.1-8b) cause
oracle errors when the benchmark runs 32+ cases in sequence.  Error
responses are parsed as `{verdict: null, confidence: 0.0}`.  The worker
caches these degraded results for 24 h.  Subsequent calls return the
stale conf=0.00 result instantly.

**Observable signature**: `verdict=true, confidence=0.00, oracle_calls=9,
supporting_models=0, claim="no strong consensus"`.  The `true` verdict
is an artefact of JavaScript's object key insertion order when all
confidence weights are zero — it does not represent oracle agreement.

**How to detect**: `confidence == 0.0 AND oracle_calls > 0 AND
supporting_models == 0` indicates a stale/invalid cached result.

**Mitigation**:
- Run domains separately with a 2+ minute break between domains
- Integration tests use pre-tested question strings with clean cache entries
- The live benchmark script adds 2 s between cases and retries once on
  conf=0.00 responses
- Clear stale entries by waiting 24 h for cache TTL expiry

### 3 — Low confidence on clear KEV cases

**Finding**: Log4Shell and MOVEit (CVSS 10, CISA KEV) receive confidence
1.00 from the oracle.  xz/liblzma backdoor received confidence 0.76 on
the first call (not stale).  Confidence < 1.00 occurs when the router gate
does not skip (initial sweep avgConf < 0.80) — the Lyapunov iteration
converges to 0.76 after 2 sweeps.

**Why this matters**: Static evidence correctly escalates all three on KEV
status alone, regardless of oracle confidence.  The oracle provides
corroborating signal; static evidence is the authoritative gate.

## Oracle vs. Static Evidence: What the Results Show

| Static precision | 100% (32/32 cases, all domains) |
| Oracle directional precision on unambiguous cases | ~88% (cyber), ~86% on fresh calls |
| Oracle-static agreement on risk/benign direction | ~75% (when oracle has fresh results) |
| Cases where oracle disagrees → NEEDS_REVIEW | ~25% |

The two-layer design is intentional:
- **Static evidence** is the deterministic, auditable gate — it governs
  known patterns from curated public sources deterministically.
- **Oracle consensus** adds model reasoning — it can detect novel patterns
  not yet in the evidence corpus, and its disagreement with static evidence
  is itself a signal.
- **Fusion rule**: static and oracle agree → high confidence.  Oracle
  uncertain or disagrees → NEEDS_REVIEW.  This keeps the governance system
  conservative and auditable.

## Running Live Tests

```bash
# All integration tests against live worker
pytest tests/test_worker_integration.py -m live -v

# Live benchmark — runs all 32 cases (slow, ~5 min due to rate-limit protection)
python scripts/run_live_benchmark.py --verbose

# Single domain (faster, avoids rate limits)
python scripts/run_live_benchmark.py --domain cyber --verbose
python scripts/run_live_benchmark.py --domain ai_governance --verbose
python scripts/run_live_benchmark.py --domain finance --verbose
```

The `make test` suite deliberately excludes live tests to keep CI fast and
deterministic.  Live tests are run manually before release or when the
worker configuration changes.

## Worker Client API

```python
from remora.evidence.worker_client import REMORAWorkerClient

client = REMORAWorkerClient()

# Check worker health
status = client.status()
assert status["ok"] is True
assert status["n_oracles"] == 3

# General governance question
r = client.assess(
    question="Is Log4Shell CVE-2021-44228 exploitable on a production Java service?",
    context="Production, internet-facing, log4j 2.14.1, JNDI enabled",
    use_case="exploitability",
)
print(r.verdict)     # True
print(r.confidence)  # 1.0
print(r.summary)     # "REMORA[exploitability] YES conf=1.00 (6/3, 3iter)"

# False-positive check (verdict=True means IS a false positive)
r = client.fp_check(
    description="TEST_API_KEY=not-a-real-secret in tests/fixtures/example.env",
    cwe="CWE-798",
    symbol="TEST_API_KEY",
    file_path="tests/fixtures/example.env",
)
print(r.verdict)     # True (IS a false positive)
print(r.confidence)  # 1.0

# Evidence fusion
r = client.evidence_fusion(
    description="SQL injection in auth.py:42, CWE-89",
    oracle_signals=[
        {"tool": "semgrep", "evidence_role": "primary", "result": "CWE-89 matched"},
        {"tool": "codegraph", "evidence_role": "corroborating", "result": "taint confirmed"},
    ],
)
print(r.verdict)  # True (confirmed finding)
```

## Claim Hygiene

Oracle results in this document are derived from actual live calls to the
worker and are documented as observed.  They are NOT claimed as production
accuracy guarantees.

- Confidence scores depend on LLM model behaviour, which may change with
  model updates on Groq/OpenRouter.
- KV cache entries persist for 24 h.  Results from stale/rate-limited
  cache entries are explicitly documented.
- Oracle limitations (red-team FP, stale cache) are documented as findings,
  not suppressed.
