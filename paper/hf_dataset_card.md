---
language:
  - en
license: apache 2
tags:
  - ai-safety
  - agent-governance
  - agentic-ai
  - benchmarks
  - policy-engine
  - uncertainty-quantification
  - human-in-the-loop
task_categories:
  - text-classification
  - question-answering
size_categories:
  - n<1K
---

# REMORA Governance Benchmark Results

Benchmark artifacts and evaluation results for **REMORA** (Reasoning Ensemble Multi-Oracle Routing Architecture): a research-grade pre-execution governance overlay for autonomous AI agents.

## Repository

[github.com/darklordVirtual/REMORA](https://github.com/darklordVirtual/REMORA)

Live governance worker: [aromer.razorsharp.workers.dev](https://aromer.razorsharp.workers.dev)

## What REMORA Does

REMORA intercepts proposed agent actions before execution and routes each through:
1. Parallel multi-oracle consensus (3 Workers AI models)
2. Thermodynamic uncertainty observables (entropy H, dissensus D, trust score τ)
3. Domain evidence layer (cyber / AI governance / financial)
4. Policy engine with hard-block precedence rules

Output: one of four structured verdicts (**ACCEPT / VERIFY / ABSTAIN / ESCALATE**) with a SHA-256 audit hash chain.

## Benchmark Results

### AgentHarm External Benchmark (N=88)

Source: [ai-safety-institute/AgentHarm](https://huggingface.co/datasets/ai-safety-institute/AgentHarm)
Reference: Andriushchenko et al., arXiv:2410.09024 (2024)

| Mode | Recall | FPR | Blocked Recall | Coverage |
|---|---|---|---|---|
| Mode 1, Oracle-only | 1.000 | 0.318 | 1.000 | 0.989 |
| Mode 2, Harm-specific oracle | 1.000 | 0.114 | 1.000 | 0.989 |
| Mode 3, Full REMORA gate | 0.114 | **0.023** | **0.977** | 0.977 |

All three deployment goals met under blocked-recall definition:
blocked_recall ≥ 0.95 ✓ · FPR < 0.10 ✓ · coverage ≥ 0.95 ✓

Artifact: `artifacts/agentharm_trimode_results.json`

### Cross-Domain Evidence Benchmark (N=36)

| Domain | N | Precision | Escalation Recall | Critical Failures |
|---|---|---|---|---|
| Cybersecurity (CVE/KEV/CWE) | 12 | 1.000 | 1.000 | 0 |
| AI Governance (ATLAS/OWASP) | 12 | 1.000 | 1.000 | 0 |
| Financial (FATF/SDN) | 12 | 1.000 | 1.000 | 0 |

Fully deterministic: reproducible without API keys.
Artifact: `artifacts/domain_benchmark_results.json`

### QA Selective Accuracy (N=544)

| Method | Coverage | Accuracy | Lift |
|---|---|---|---|
| Majority vote (baseline) | 100% | 41.18% |, |
| REMORA neg-temperature | 18% | **88.78%** | +47.6 pp |
| REMORA (held-out) | 23.2% | **88.00%** | +41.7 pp |

### Replay Arena (N=96)

96 fixed governance cases across 9 categories. Accuracy: **87.5%** (84/96).
False accept rate: **0.0%**. Transfer category accuracy: **100%** (4/4).

## AROMER: Learning Extension (Experimental)

Live AII (Autonomous Intelligence Index), current state (2026-07-01):
- AII: **0.9895** (structural ceiling 0.9922) [TRAINED, shadow-only mode]
- ECE: 0.0052 (T1=0.9741; T2=T3=T4=T5=1.000)
- False accept rate: **0.000** (n_operational_fa=0; REM-020 longitudinal stability closed 2026-07-17 under the 7-day criterion)
- safety_certification: CERTIFIED_INDEPENDENT_HOLDOUT (n=814 operational harmful; CP upper bound 0.367%)
- Open gaps: MCE bucket selection bias (§15, structural); live cross-domain episodes absent (§16, interpretation ceiling)
- One production gate remains: REM-021 (independent human review). REM-020 closed 2026-07-17 (7-day criterion, fail-closed tooling; self-reported values pending REM-021 verification). REM-022 DONE with recorded deviation (REM-023).

## Test Suite

3333 passing tests · 14 skipped · pre-push quality gate active

## Limitations

- AgentHarm evaluation uses research oracle setup (not production deployment)
- AROMER results are preliminary observations from live but uncontrolled deployment
- QA benchmark in-sample results; held-out validation reported separately
- No production safety certification

## Citation

```bibtex
@software{remora2026,
  author = {Skogbrott, Stian},
  title = {REMORA: Thermodynamic Governance Overlay for Autonomous AI Agents},
  year = {2026},
  url = {https://github.com/darklordVirtual/REMORA}
}
```
