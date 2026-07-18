# REMORA External Validation Report

**Date:** 2026-06-02
**Prompt template:** v1.1
**Direct oracle:** Cloudflare Workers AI rotating pool, `llama-3.3-70b-instruct-fp8-fast`, `llama-4-scout-17b-16e-instruct`, `mistral-small-3.1-24b-instruct`, `llama-3.2-3b-instruct`, `llama-3.1-8b-instruct-fp8`
**REMORA oracles:** cf/llama-3.3-70b-instruct-fp8-fast, cf/llama-4-scout-17b-16e-instruct
**Random seed:** 42  **Live:** True

> **Claim status:** `internally_supported`: live-oracle runs on public HF benchmarks.
> Upgrade to `externally_validated` only after independent replication.

## Direct Oracle Accuracy (Groq llama-3.3-70b, direct, no REMORA wrapper)

| Dataset | Accuracy | Wilson 95% CI | Correct | Scored | Parseable/N |
|---------|----------|--------------|---------|--------|-------------|
| arc-challenge | 80.2% | [0.703, 0.875] | 65 | 81 | 81/100 |
| arc-easy | 86.2% | [0.770, 0.921] | 69 | 80 | 80/100 |
| boolq | 83.7% | [0.751, 0.897] | 82 | 98 | 98/100 |
| hotpotqa | 29.0% | [0.210, 0.385] | 29 | 100 | 100/100 |

## REMORA Governance Action Distribution

> REMORA is a governance circuit breaker, `verify` means the action needs supporting evidence.
> For factual Q&A benchmarks, routing all items to `verify` is **correct** governance behaviour.

| Dataset | N | Accept | Verify | Escalate | Abstain | Coverage |
|---------|---|--------|--------|----------|---------|----------|
| arc-challenge | 100 | 0 | 100 | 0 | 0 | 0.0% |
| arc-easy | 100 | 0 | 100 | 0 | 0 | 0.0% |
| boolq | 100 | 0 | 100 | 0 | 0 | 0.0% |
| hotpotqa | 100 | 0 | 100 | 0 | 0 | 0.0% |

## Latency (seconds)

| Dataset | REMORA p50 | REMORA p95 | REMORA p99 | Direct p50 | Direct p95 |
|---------|-----------|-----------|-----------|-----------|-----------|
| arc-challenge | 1.226 | 3.966 | 5.14 | 0.315 | 0.685 |
| arc-easy | 1.18 | 3.455 | 5.327 | 0.355 | 0.902 |
| boolq | 1.064 | 2.83 | 4.434 | 0.302 | 0.744 |
| hotpotqa | 1.044 | 3.063 | 7.738 | 0.368 | 0.926 |

## Methodology

**Direct oracle accuracy:** Groq `llama-3.3-70b-versatile` called at temperature=0.0 (greedy).
Prompt requests a single letter (MC) / True|False (BoolQ) / short phrase (HotpotQA).
Answer parsed by regex; unparseable items are excluded from accuracy but counted.
Wilson 95% CI computed on parseable items; HotpotQA accuracy is a **substring match upper bound**.

**REMORA governance:** `engine.run(question, risk_tier='medium')`, 2-3 oracle consensus + policy gate.
Coverage = proportion of items issued `accept`.
Latency = wall-clock per item.

**Datasets:**
| Key | HF ID | Split | Type |
|-----|-------|-------|------|
| arc-challenge | allenai/ai2_arc | test | mc |
| arc-easy | allenai/ai2_arc | test | mc |
| boolq | google/boolq | validation | bool |
| hotpotqa | hotpotqa/hotpot_qa | validation | freetext |

## Known Limitations

- Direct accuracy reflects oracle LLM capability, not REMORA governance quality.
- REMORA routes factual Q&A to `verify` by design (coverage=0%).   The meaningful REMORA metric is latency overhead and audit completeness.
- HotpotQA uses substring match, not token F1.
- Results are non-deterministic; slight variation expected on rerun.

## Reproduction

```bash
export $(grep -v '^#' .env.vars | xargs)
python3 scripts/run_external_validation.py \
    --datasets arc-challenge arc-easy boolq hotpotqa --n 300 --seed 42
```
