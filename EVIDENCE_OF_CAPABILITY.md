# Evidence of Capability

This document explains what REMORA demonstrates as an engineering and research
portfolio project. It is deliberately conservative: simulator results are not
production proof, internal theory tests are not peer review, and deployed
enterprise safety still requires external validation.

## What REMORA Proves

REMORA proves that the repository contains a working, test-backed architecture
for AI assurance:

- multi-oracle agreement can be measured and used for selective acceptance,
- low-trust cases can be routed to `VERIFY`, `ABSTAIN`, or `ESCALATE`,
- proposed tool calls can be evaluated in deterministic dry-run simulators,
- agent tool calls can be intercepted before execution by a local hook,
- claims can be tied to committed artifacts, tests, and explicit limitations.

The strongest current claim is not "REMORA is production safe." The stronger
and more defensible claim is:

> REMORA is a reproducible AI assurance prototype that turns uncertainty,
> disagreement, evidence, policy, and action risk into auditable routing
> decisions before AI output is trusted or executed.

## What Is Implemented

Core implementation areas:

- `remora/cascade/`: six-stage adaptive routing from fast acceptance to
  consensus, verification, critique-revision, self-consistency, and optional
  Mixture-of-Agents synthesis.
- `remora/policy/`: `ACCEPT`, `VERIFY`, `ABSTAIN`, and `ESCALATE` decision
  engine with structured reports.
- `remora/toolcall/`: deterministic tool-call benchmark schemas, simulators,
  baselines, scoring, and REMORA gates.
- `remora/agent_hook/`: local PreToolUse-style safety hook for classifying
  proposed tool calls, checking drift, and fail-closing risky operations.
- `remora/governance/`: memory layers, context flow, drift monitoring,
  governance-forgetting metrics, and policy proposal primitives.
- `remora/theory/`: MaxEnt, joint-convergence, and scaling-analysis modules
  used to document current theoretical assumptions and numerical checks.
- `enterprise/`: policy-as-code examples, audit schema, threat model,
  deployment runbooks, observability model, and production-readiness plan.

## What Is Tested

The committed quality gate runs:

- `ruff check .`
- canonical result snapshot generation,
- claim consistency checks,
- the full deterministic `pytest` suite.

The suite is intentionally API-free by default. It tests deterministic
behaviour, benchmark artifacts, policy routing, tool-call simulators, evidence
interfaces, governance primitives, theory utilities, and documentation
invariants. Use the GitHub Actions "Quality Gates" workflow as the current
source of truth for the exact collected and selected test count.

Recent review-hardening tests also cover:

- shell red-team patterns such as simple quote/backslash splitting and
  `base64 --decode | bash` execution chains,
- explicit distribution-shift handling before calibrated temperature thresholds
  are allowed to accept,
- conformal calibration failure under non-exchangeable shifted test data,
- adversarial low-confidence three-way thermodynamic pre-sweeps,
- aggregate `V(t)` trajectory summaries instead of single canonical Lyapunov
  values.

Representative tested artifacts include:

- `results/end_to_end_n500_v3.json`
- `results/conformal_guardrail_holdout.json`
- `results/toolcall_benchmark_v2_results.json`
- `results/toolcall_benchmark_v2_significance.json`
- `experiments/results/ablation_adaptation.json`
- `docs/thermodynamics/claim_ledger.yaml`

## What Is Not Claimed

REMORA does not currently claim:

- production safety certification,
- live enterprise deployment validation,
- peer-reviewed theorem status,
- universal hallucination prevention,
- semantic entailment quality from the default lexical evidence verifier,
- real tool-call execution safety from simulator-only benchmarks,
- external replication on public agent benchmarks.

Tool-call v2 is best described as a **controlled deterministic safety simulation**:
valuable for testing policy logic and failure modes, but not a
substitute for live model evaluation, red-team testing, or production telemetry.

## How To Reproduce

```bash
pip install -e ".[dev]"
make test
make report
python experiments/end_to_end_n500_v3.py
python experiments/evaluate_toolcall_benchmark_v2.py
python experiments/toolcall_v2_significance.py
```

For external review, use a clean checkout of `main`, run the commands above,
and compare regenerated artifacts against the committed `results/` and
`artifacts/` files.

## Why This Matters For Enterprise AI

Enterprise AI systems need more than model access. They need operating
boundaries:

- when to answer,
- when to verify,
- when to abstain,
- when to escalate,
- when tool execution is allowed,
- how decisions are logged,
- which claims are supported by evidence.

REMORA demonstrates that these concerns can be implemented as a control layer
rather than left as prompt instructions. That is the portfolio signal: the
project combines research framing, implementation, tests, auditability,
deployment thinking, and honest claim management in one coherent architecture.

## Capability Summary

REMORA is strong evidence of the ability to:

- design original AI governance architecture,
- implement production-shaped Python systems,
- build deterministic benchmarks and artifacts,
- connect research claims to tests,
- model agentic tool-use risk,
- reason about enterprise deployment, audit, and policy,
- separate supported claims from promising but unvalidated ideas.

It should be presented as a research-grade AI assurance prototype and
enterprise control-plane candidate, not as a finished production product.
