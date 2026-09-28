# Evidence of Capability

This document explains what REMORA demonstrates as an engineering and research
portfolio project. It is deliberately conservative: simulator results are not
production proof, internal theory tests are not peer review, and deployed
enterprise safety still requires external validation.

## What REMORA Proves

REMORA proves that the repository contains a working, test-backed execution
assurance kernel for tool-using agents:

- a proposed tool call gets one of four decisions (`ACCEPT`, `VERIFY`,
  `ABSTAIN`, `ESCALATE`) from a policy engine whose deterministic hard guards
  outrank model-derived signals,
- tool meaning, target and risk come from deployment-owned sources such as a
  Signed ToolSpec, never from the calling agent,
- an `ACCEPT` becomes a short-lived, single-use grant bound to the exact
  proposal and consumed once at the policy-enforcement point,
- dispatch runs under an `ExecutionLease` through `GovernedToolDispatcher`,
  with a durable intent recorded before the side effect,
- authorized, dispatched, executed and verified effect are separate recorded
  states, so a transport success is never counted as a completed effect,
- claims are tied to committed artifacts, tests and explicit limitations, and
  CI checks that binding.

The strongest current claim is not "REMORA is production safe." The stronger
and more defensible claim is:

> REMORA is a reproducible governed-execution prototype that turns policy,
> authoritative tool context and action risk into auditable, single-use
> execution decisions before an agent's tool call takes effect.

## What Is Implemented

The execution kernel is listed module by module in
[DEVELOPER_OVERVIEW.md](../DEVELOPER_OVERVIEW.md#core-modules); the main areas:

- `remora/policy/`: the decision engine and its hard-guard floor.
- `remora/toolcall/`: deployment tool authority, Signed ToolSpec, and the
  deterministic tool-call benchmark schemas, simulators and baselines.
- `remora/enforcement/`: PDP-to-PEP grants, the one-time-grant gate, execution
  leases and the dispatch outbox.
- `remora/execution/` and `servers/execution_api.py`: the `POST /v1/execution/*`
  surface that joins review, re-gating, dispatch and audit.
- `remora/governance/`: review queue, lifecycle, tenant audit chain and effect
  verification.
- `remora/agent_hook/`: local PreToolUse-style hook for classifying proposed
  tool calls and fail-closing risky operations.

Outside the kernel, the `/v1/assess` research surface (`remora/cascade/`,
oracles, evidence and uncertainty modules) is optional and cannot override the
hard-guard floor. `remora/research_attic/theory/` keeps the earlier MaxEnt,
joint-convergence and scaling-analysis work as history, and `docs/enterprise/`
holds deployment and rollout material.

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

- `results/routing_bench_bfcl_v4_cext3_results.json` (BFCL v4 C-ext3, sealed once; utility targets missed, see NEGATIVE_RESULTS §39)
- `results/external_benchmark_agentharm_v1.json` (AgentHarm; every benign twin was blocked too)
- `results/end_to_end_n500_v3_policy_v5.json` (current policy; the SAP v2 round record `results/end_to_end_n500_v3.json` is frozen)
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
- that the gate tells harmful from benign requests on AgentHarm: it blocked
  all 208 benign twins as well as the 208 harmful scenarios,
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

For external review, use a clean checkout of `master`, run the commands above,
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
