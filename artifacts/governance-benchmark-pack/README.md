# REMORA: Policy-Gated Governance for Operational AI Agents

[![Paper (PDF)](https://img.shields.io/badge/paper-PDF-b31b1b.svg)](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/paper/remora_paper.pdf) [![CI — Deterministic Test Suite](https://github.com/darklordVirtual/REMORA-research/actions/workflows/ci.yml/badge.svg)](https://github.com/darklordVirtual/REMORA-research/actions/workflows/ci.yml) [![Quality Gates](https://github.com/darklordVirtual/REMORA-research/actions/workflows/quality-gates.yml/badge.svg)](https://github.com/darklordVirtual/REMORA-research/actions/workflows/quality-gates.yml) [![License: BUSL-1.1](https://img.shields.io/badge/License-BUSL--1.1-blue.svg)](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/LICENSE)

REMORA is a **policy-gated execution assurance layer for operational AI agents**: a governance overlay placed between an agent proposal and the protected tool path. An agent proposes a tool call; REMORA evaluates the exact action before execution and returns one of four outcomes:

| Decision | Meaning |
|---|---|
| **ACCEPT** | The action may proceed under the current policy and context. |
| **VERIFY** | A defined check or review is required before execution. |
| **ABSTAIN** | Required information is missing or insufficient. |
| **ESCALATE** | The action requires a higher-authority decision. |

The enforcing surface is `POST /v1/execution/*`. Authorization is bound to the approved proposal and consumed at the policy-enforcement point before governed dispatch.

> **Status:** research/shadow-mode software with no production certification. External replication is pending; deployment-specific validation remains required.

```bash
python -m pip install -e ".[dev]"
python -m remora try
```

**Start here.** This is the one ordered reading path; the other documents point back here rather than proposing their own.

1. [Developer handoff](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/DEVELOPER_OVERVIEW.md) — shortest technical path through the repository
2. [Architecture](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/ARCHITECTURE.md) — canonical components, data flow and module stability
3. [Execution quickstart](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/deployment/execution-quickstart.md) — configure and run the enforcing path
4. [API reference](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/07-api-reference.md) — public interfaces, with a `curl` round-trip; wire contract in [`schemas/openapi.json`](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/schemas/openapi.json)
5. [Python SDK](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/sdk.md) — the one namespace with a backward-compatibility guarantee
6. [Evidence and claims](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/02-evidence-and-claims.md) — what each result establishes, and what it does not
7. [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md) — failed hypotheses and limitations, kept permanently

[Documentation index](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/README.md) lists the complete registered set.

---

## Execution path

The operational path is intentionally small:

1. **Authoritative context** — tool meaning, target, risk and approved intent come from deployment-owned sources such as Signed ToolSpec, not from the calling agent.
2. **Policy decision** — deterministic hard guards have precedence over model-derived signals.
3. **Review or grant** — `VERIFY`/`ESCALATE` enters bounded review; `ACCEPT` receives a short-lived, single-use grant bound to the proposal.
4. **PEP and dispatch** — the grant is consumed, an `ExecutionLease` binds policy identity and call identity, and `GovernedToolDispatcher` invokes the deployment-owned callable.
5. **Lifecycle and evidence** — dispatch intent, outcome, effect verification and audit records remain joinable by proposal identity.

The separate `/v1/assess` research surface can use oracle, evidence and uncertainty components. Those components are not prerequisites for the execution kernel and cannot override its deterministic hard-guard floor.

See [DEVELOPER_OVERVIEW.md](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/DEVELOPER_OVERVIEW.md) for the CORE / OPTIONAL / EXPERIMENTAL / HISTORICAL boundary, the machine-checked [product truth contract](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/product/product_truth_contract.yaml) for the per-capability classification, and [docs/deployment/execution-quickstart.md](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/deployment/execution-quickstart.md) for a deployment-shaped walkthrough.

---

## Evidence

Headline values are governed by the [claim register](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/assurance/claim_register_v1.yaml) and must remain tied to committed result artifacts and scope caveats. Reported empirical results are **bounded by documented assumptions**, benchmark populations and evaluation protocols; they are not general safety guarantees.

<!-- claim:CLAIM-002 far_pct far_ci_high_pct fbr_pct n -->
<!-- claim:CLAIM-001 far_pct n_effective n -->
<!-- claim:CLAIM-019 wrong_call_accept_pct wrong_call_wilson_upper_pct irrelevance_abstain_pct required_unknown_accept_pct -->
<!-- claim:CLAIM-003 far_pct n -->
| # | Benchmark | Result | Scope |
|---|---|---|---|
| 1 | **AgentHarm** | **0.0%** wrongly allowed (0/208); 95% upper bound 1.81% | Intent classification; harmless-twin refusal **100.0%** |
| 2 | **Adversarial simulator** | **0.0%** unsafe runs (0/70 templates; 700 tasks); 95% cluster-level Wilson upper bound **5.2%**; utility +0.456 | Simulated; effective N = 70 (70 templates × 10 cosmetic variants); unsafe-rate gap Δ=0.0143 vs. baseline, not statistically significant |
| 3 | **BFCL v4 (C-ext3)** | Native wrong-call acceptance **0.0%** (0/500; Wilson 95% upper bound **0.76%**); irrelevant-tool refusal **100.0%** (300/300); required-input guessing **0.0%** (0/398) | Sealed once, 2,799 episodes, frozen semantic bundle + authority floor; utility targets missed — see NEGATIVE_RESULTS §39 |
| 4 | **Historical regression** | **0.0%** wrongly allowed (0/167) | Previously observed failures only |

Interpret these values narrowly:

- AgentHarm also blocks the harmless twin set, so the result does not establish fine-grained harmful/harmless discrimination.
- The deterministic simulator has 70 independent templates; cosmetic variants do not increase the effective sample size.
- BFCL v4 C-ext3 measures the safety axis only: declared semantic authority takes native wrong-call acceptance 24/500 → 6 → **0** across the ablation arms. The utility side of the same run (read autonomy, argument routing) missed its pre-registered targets; those findings and the permanent 10.9% baseline live in NEGATIVE_RESULTS §39 and CLAIM-019's caveat, not here.
- Historical regression demonstrates that known failures remain fixed; it does not bound unseen failures.
- Internal reproducibility is not external replication or field validation.

Replaced claims are retained in [superseded claims](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/assurance/superseded_claims.md). Failed hypotheses and limitations are retained in [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md).

---

## Run it

```bash
python -m remora assess drop_database
python -m pytest tests/ -q
python scripts/demo_industrial_maintenance.py
python -m remora doctor
```

`assess_tool_call(...)` is an advisory library surface. It evaluates the context supplied by the caller; it does not itself control downstream credentials. For enforcement, route the call through `/v1/execution/*` and make the governed dispatcher the authority path to the protected tool.

```python
from remora import assess_tool_call

assessment = assess_tool_call(
    "drop_database",
    {"db": "prod-main"},
    risk_tier="critical",
    action_type="destructive_write",
)
```

For external review or pilot work, use `REMORA_RUNTIME_PROFILE=review` or `controlled_pilot`; those profiles require the stronger Signed ToolSpec and durable-state prerequisites described in the [execution quickstart](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/deployment/execution-quickstart.md).

---

## Repository map

| Path | Purpose |
|---|---|
| `remora/policy/` | Policy observation and decision logic |
| `remora/toolcall/` | Tool authority, ToolSpec and routing contracts |
| `remora/enforcement/` | PDP→PEP grant, lease, dispatcher and outbox |
| `remora/governance/` | Review, lifecycle, audit and effect verification |
| `servers/` | HTTP surfaces and deployment wiring |
| `tests/` | Deterministic regression and contract tests |
| `docs/assurance/` | Claims, capabilities, release gates and review records |
| `docs/research/` | Active research material and benchmark design |
| `docs/archive/` | Superseded or historical material |
| `paper/` | Research paper and supporting publication artifacts |

Research modules, AROMER, older thermodynamic/statistical-physics work and historical design documents remain in the repository for reproducibility and audit history. Their presence does **not** imply that they are part of the enforcing runtime path. Use the [capability register](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/assurance/capability_register_v1.yaml) for wiring status.

---

## Current boundaries

REMORA cannot enforce against a credential path that bypasses its dispatcher. Deployment identity, credential custody, downstream authorization and operational controls remain deployment responsibilities. Capability maturity is tracked explicitly in `docs/assurance/capability_register_v1.yaml`.

The `servers/execution_api.py` decomposition is complete (issue #241, closed): contracts, persistence, authorization, dispatch, projections and all use-case orchestration live under `remora/execution/` and `remora/persistence/`, verified against a byte-identical OpenAPI schema at every step. Dispatch still runs inside the API process — the decoupled dispatch worker is tracked in issue #82.

For product-oriented integration, see [Assured Agent Execution](https://github.com/darklordVirtual/assured-agent-execution), which consumes pinned REMORA artifacts rather than copying the governance core.

---

## Research, AI use and citation

The current research-to-control mapping is maintained in [docs/research/research_control_matrix.generated.md](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/research/research_control_matrix.generated.md). Related work is summarized in [docs/09-related-work.md](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/09-related-work.md).

Generative-AI tools have been used during development. AI-generated text or code is not treated as evidence by itself; claims must resolve to committed artifacts, tests or verified sources. Disclosure: [docs/AI_USE.md](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/AI_USE.md).

```bibtex
@misc{remora2026,
  title  = {REMORA: A Policy-Gated Multi-Oracle Assurance Architecture for Agentic AI},
  author = {Skogbrott, Stian},
  year   = {2026},
  url    = {https://github.com/darklordVirtual/REMORA-research},
  note   = {Research-grade reference architecture; external replication pending.}
}
```

---

## License and contributions

REMORA versions from `v0.10.0` are source-available under the [Business Source License 1.1](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/LICENSE), with separate commercial licensing available under [REMORA Commercial License](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/COMMERCIAL_LICENSE.md). Research, benchmarking and reproducibility work are permitted within the terms described in [LICENSING.md](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/LICENSING.md).

Contribution requirements, branch lifecycle, documentation style and claim hygiene are defined in [CONTRIBUTING.md](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/CONTRIBUTING.md) and [docs/10-contributing.md](https://github.com/darklordVirtual/REMORA-research/blob/ea18018fcb04884ba969938e88b41ef0185e4e11/docs/10-contributing.md).
