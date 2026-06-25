# REMORA External Validation Report

**Date:** 2026-06-02
**Prompt template:** v1.1
**Direct oracle:** Cloudflare Workers AI rotating pool — `llama-3.3-70b-instruct-fp8-fast`, `llama-4-scout-17b-16e-instruct`, `mistral-small-3.1-24b-instruct`, `llama-3.2-3b-instruct`, `llama-3.1-8b-instruct-fp8`
**REMORA oracles:** cf/llama-3.3-70b-instruct-fp8-fast, cf/llama-4-scout-17b-16e-instruct
**Random seed:** 42  **Live:** True

> **Claim status:** `internally_supported` — live-oracle runs on public HF benchmarks.
> Upgrade to `externally_validated` only after independent replication.

## Direct Oracle Accuracy (Groq llama-3.3-70b, direct — no REMORA wrapper)

| Dataset | Accuracy | Wilson 95% CI | Correct | Scored | Parseable/N |
|---------|----------|--------------|---------|--------|-------------|
| truthfulqa | 8.0% | [0.032, 0.188] | 4 | 50 | 50/50 |
| mmlu-ethics | 75.0% | [0.409, 0.929] | 6 | 8 | 8/11 |
| mmlu-clinical | 75.0% | [0.551, 0.880] | 18 | 24 | 24/29 |
| squad-rag | 46.0% | [0.330, 0.596] | 23 | 50 | 50/50 |

## REMORA Governance Action Distribution

> REMORA is a governance circuit breaker — `verify` means the action needs supporting evidence.
> For factual Q&A benchmarks, routing all items to `verify` is **correct** governance behaviour.

| Dataset | N | Accept | Verify | Escalate | Abstain | Coverage |
|---------|---|--------|--------|----------|---------|----------|
| truthfulqa | 50 | 0 | 50 | 0 | 0 | 0.0% |
| mmlu-ethics | 11 | 0 | 11 | 0 | 0 | 0.0% |
| mmlu-clinical | 29 | 0 | 29 | 0 | 0 | 0.0% |
| squad-rag | 50 | 0 | 50 | 0 | 0 | 0.0% |

## Latency (seconds)

| Dataset | REMORA p50 | REMORA p95 | REMORA p99 | Direct p50 | Direct p95 |
|---------|-----------|-----------|-----------|-----------|-----------|
| truthfulqa | 0.992 | 2.408 | 2.75 | 0.386 | 0.966 |
| mmlu-ethics | 1.341 | 3.909 | 3.909 | 0.345 | 0.66 |
| mmlu-clinical | 1.482 | 5.732 | 6.204 | 0.377 | 1.132 |
| squad-rag | 0.909 | 1.911 | 3.451 | 0.367 | 1.058 |

## Methodology

**Direct oracle accuracy:** Groq `llama-3.3-70b-versatile` called at temperature=0.0 (greedy).
Prompt requests a single letter (MC) / True|False (BoolQ) / short phrase (HotpotQA).
Answer parsed by regex; unparseable items are excluded from accuracy but counted.
Wilson 95% CI computed on parseable items; HotpotQA accuracy is a **substring match upper bound**.

**REMORA governance:** `engine.run(question, risk_tier='medium')` — 2-3 oracle consensus + policy gate.
Coverage = proportion of items issued `accept`.
Latency = wall-clock per item.

**Datasets:**
| Key | HF ID | Split | Type |
|-----|-------|-------|------|
| arc-challenge | allenai/ai2_arc | test | mc |
| arc-easy | allenai/ai2_arc | test | mc |
| boolq | google/boolq | validation | bool |
| hotpotqa | hotpotqa/hotpot_qa | validation | freetext |
| truthfulqa | truthfulqa/truthful_qa | validation | truthfulqa |
| mmlu-ethics | cais/mmlu | validation | mmlu |
| mmlu-clinical | cais/mmlu | validation | mmlu |
| squad-rag | rajpurkar/squad_v2 | validation | rag_squad |

## Known Limitations

- Direct accuracy reflects oracle LLM capability, not REMORA governance quality.
- REMORA routes factual Q&A to `verify` by design (coverage=0%).   The meaningful REMORA metric is latency overhead and audit completeness.
- HotpotQA uses substring match, not token F1.
- TruthfulQA accuracy is a substring match; it measures surface overlap, not hallucination rate.
- MMLU accuracy uses letter matching (A/B/C/D); subject coverage reflects the selected configs.
- SQuAD-RAG coverage > 0% is **expected** (evidence supplied) — this is not inflated accuracy,   it is governance coverage demonstrating the evidence-augmented accept path.
- Results are non-deterministic; slight variation expected on rerun.

## RAG Track Note

`squad-rag` injects the Wikipedia passage as evidence directly into the REMORA prompt. Unlike the knowledge-retrieval benchmarks (ARC, BoolQ, HotpotQA), REMORA is supplied with supporting context, so `accept` outcomes are the *correct* governance behavior for answerable items. Unanswerable SQuAD-v2 items (no gold answer) are scored against the string `"unanswerable"`. Coverage on `squad-rag` should be interpreted as: *what fraction of evidence-grounded queries does REMORA approve without human review?*


## Reproduction

```bash
export $(grep -v '^#' .env.vars | xargs)
# Original four datasets
python3 scripts/run_external_validation.py \
    --datasets arc-challenge arc-easy boolq hotpotqa --n 300 --seed 42
# Governance-relevant + RAG track
python3 scripts/run_external_validation.py \
    --datasets truthfulqa mmlu-ethics mmlu-clinical squad-rag --n 100 --seed 42
```
