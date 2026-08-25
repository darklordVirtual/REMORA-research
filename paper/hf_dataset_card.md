---
language:
  - en
license: other
license_name: busl-1.1
license_link: https://github.com/darklordVirtual/REMORA-research/blob/master/LICENSE
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

Benchmark artifacts and evaluation results for **REMORA**: a research-grade,
policy-gated pre-execution governance overlay for autonomous AI agents.

## Repository

[github.com/darklordVirtual/REMORA-research](https://github.com/darklordVirtual/REMORA-research)
— every number below links to a committed, provenance-stamped artifact there;
claim status is machine-checked in CI against
`docs/assurance/claim_register_v1.yaml`.

## What REMORA Does

REMORA intercepts proposed agent actions before execution and routes each through:
1. Deterministic admission firewall (adversarial / coercion screening)
2. Parallel multi-oracle consensus with disagreement diagnostics (entropy H,
   dissensus D, trust — **diagnostic-grade only**; falsified as selection
   signals in the pre-registered SAP v3 round, CLAIM-012)
3. Domain evidence layer (cyber / AI governance / financial)
4. Policy engine with hard-block precedence rules — the safety floor

Output: one of four structured verdicts (**ACCEPT / VERIFY / ABSTAIN /
ESCALATE**) with a SHA-256 tamper-evident audit chain.

## Current headline results

Every caveat is part of the claim; full tables in the repository's
`docs/02-evidence-and-claims.md` and `NEGATIVE_RESULTS.md`.

| Result | Value | Key caveat | Artifact |
|---|---|---|---|
| AgentHarm external benchmark | FAR **0.0%**, Wilson 95% CI [0.00%, 1.81%], N=208 | intent-gating, not interception; companion FBR 100% | `results/external_benchmark_agentharm_v1.json` |
| Adversarial tool-call simulator v2 | **0.0%** unsafe execution (0/70 templates; effective N=70 of 700 tasks) | simulator-scoped; unsafe-rate Δ vs baselines not significant (p=0.50) | `results/toolcall_benchmark_v2_results.json` |
| Calibrated confidence-weighted voting (SAP v3) | **87.8%** vs majority 85.1%, McNemar p=0.0064, N=368 | significant vs majority only; not integrated into the engine from this round | `results/sap_v3_round_results.json` |

## Historical studies (superseded or scoped — labelled, not hidden)

### Trimode AgentHarm study (N=88, research oracle setup)

An earlier three-mode study; the N=208 FAR result above is the current
headline. Artifact: `artifacts/agentharm_trimode_results.json`.

| Mode | Recall | FPR | Blocked Recall | Coverage |
|---|---|---|---|---|
| Mode 1, Oracle-only | 1.000 | 0.318 | 1.000 | 0.989 |
| Mode 2, Harm-specific oracle | 1.000 | 0.114 | 1.000 | 0.989 |
| Mode 3, Full REMORA gate | 0.114 | **0.023** | **0.977** | 0.977 |

### Cross-domain evidence benchmark (N=36, deterministic)

| Domain | N | Precision | Escalation Recall | Critical Failures |
|---|---|---|---|---|
| Cybersecurity (CVE/KEV/CWE) | 12 | 1.000 | 1.000 | 0 |
| AI Governance (ATLAS/OWASP) | 12 | 1.000 | 1.000 | 0 |
| Financial (FATF/SDN) | 12 | 1.000 | 1.000 | 0 |

Reproducible without API keys. Artifact: `artifacts/domain_benchmark_results.json`.

### QA selective accuracy (retired Groq round — superseded)

The 88.78% @ 18% figures came from the retired single-family Groq round and
are **superseded** by the 2026-07 cross-family clean round (SAP v3, above).
Kept for the record; do not cite as current.

### Replay arena (N=93)

93 fixed governance cases across 14 categories: accuracy **87.1%**, false
accept rate **0.0%**. Artifact: `artifacts/aromer/replay_arena_report.json`.

## AROMER: Learning Extension (Experimental)

AROMER is the experimental learning layer; its metrics are **not** evidence
for the core governance system. Snapshot dated 2026-07-01 (live values
drift; see the repository's telemetry branch for current):
- AII **0.9895** (structural ceiling 0.9922) [TRAINED, shadow-only mode]
- ECE 0.0052; false accept rate 0.000 (n_operational_fa=0)
- Open gaps and review status: see `docs/assurance/remediation_register.yaml`
  (REM-021 independent human review remains open)

## Test Suite

3,700+ passing deterministic tests, no API keys required; quality gates
(lint, claim consistency, paper sync, wheel contract) enforced in CI.

## Limitations

- AgentHarm evaluation is intent-gating with a research oracle setup, not
  production tool-call interception
- Simulator results are synthetic; real tool ecosystems may differ
- AROMER results are preliminary observations from a live but uncontrolled
  deployment
- No production safety certification; deployment profile is SHADOW_ONLY

## Citation

```bibtex
@misc{remora2026,
  title  = {REMORA: Governed Execution Assurance for Tool-Using AI Agents},
  author = {Skogbrott, Stian},
  year   = {2026},
  url    = {https://github.com/darklordVirtual/REMORA-research}
}
```
