<img width="2172" height="724" alt="image" src="https://github.com/user-attachments/assets/8b0c400e-963c-46da-aed3-3007f430f0b3" />


# REMORA: Governed Execution Assurance for Tool-Using AI Agents

[![Paper (PDF)](https://img.shields.io/badge/paper-PDF-b31b1b.svg)](paper/remora_paper.pdf) [![CI: Deterministic Test Suite](https://github.com/darklordVirtual/REMORA-research/actions/workflows/ci.yml/badge.svg)](https://github.com/darklordVirtual/REMORA-research/actions/workflows/ci.yml) [![Quality Gates](https://github.com/darklordVirtual/REMORA-research/actions/workflows/quality-gates.yml/badge.svg)](https://github.com/darklordVirtual/REMORA-research/actions/workflows/quality-gates.yml) [![License: BUSL-1.1](https://img.shields.io/badge/License-BUSL--1.1-blue.svg)](LICENSE)

Policy-gated control between an agent's intent and a real-world effect.

An agent proposes a tool call. REMORA is a governance overlay between that proposal and the protected tool: it evaluates the exact action before it runs, and returns one of four decisions:

| Decision | Meaning |
|---|---|
| **ACCEPT** | The action may proceed under the current policy and context. |
| **VERIFY** | A defined check or review is required before execution. |
| **ABSTAIN** | Required information is missing or insufficient. |
| **ESCALATE** | The action requires a higher-authority decision. |

The enforcing surface is `POST /v1/execution/*`. An approval is bound to the exact proposal it was given for and is consumed once, at the policy-enforcement point, before governed dispatch.

> **Status:** research and shadow-mode software with no production certification. External replication is pending; every deployment still needs its own validation.

```bash
python -m pip install -e ".[dev]"
python -m remora try
```

## Where to start

One ordered reading path. Every other document points back here.

1. [Developer handoff](DEVELOPER_OVERVIEW.md): the shortest technical path through the repository
2. [Architecture](ARCHITECTURE.md): components, data flow, module stability
3. [Execution quickstart](docs/deployment/execution-quickstart.md): configure and run the enforcing path
4. [API reference](docs/07-api-reference.md): public interfaces with a `curl` round-trip; wire contract in [`schemas/openapi.json`](schemas/openapi.json)
5. [Python SDK](docs/sdk.md): the one namespace with a backward-compatibility guarantee
6. [Evidence and claims](docs/02-evidence-and-claims.md): what each result establishes, and what it does not
7. [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md): failed hypotheses and limitations, kept permanently

The [documentation index](docs/README.md) lists the complete registered set.

## How an action gets through

Five steps, deliberately few.

1. Authoritative context. Tool meaning, target, risk and approved intent come from deployment-owned sources such as a Signed ToolSpec, never from the calling agent.
2. Policy decision. Deterministic hard guards outrank model-derived signals.
3. Review or grant. `VERIFY` and `ESCALATE` enter bounded review; `ACCEPT` receives a short-lived, single-use grant bound to the proposal.
4. PEP and dispatch. The grant is consumed, an `ExecutionLease` binds policy identity to call identity, and `GovernedToolDispatcher` invokes the deployment-owned callable.
5. Lifecycle and evidence. Dispatch intent, outcome, effect verification and audit records stay joinable by proposal identity.

<details>
<summary>What sits outside that path</summary>

The separate `/v1/assess` research surface can use oracle, evidence and uncertainty components. They are not prerequisites for the execution kernel and cannot override its deterministic hard-guard floor.

[DEVELOPER_OVERVIEW.md](DEVELOPER_OVERVIEW.md) draws the CORE / OPTIONAL / EXPERIMENTAL / HISTORICAL boundary; the machine-checked [product truth contract](docs/product/product_truth_contract.yaml) classifies every capability; the [execution quickstart](docs/deployment/execution-quickstart.md) walks a deployment-shaped example.

</details>

## Evidence

Headline values are governed by the [claim register](docs/assurance/claim_register_v1.yaml) and stay tied to committed result artifacts and scope caveats. Every number below is bounded by documented assumptions, benchmark populations and evaluation protocols. None is a general safety guarantee.

<!-- claim:CLAIM-002 far_pct far_ci_high_pct fbr_pct n -->
<!-- claim:CLAIM-001 far_pct n_effective n -->
<!-- claim:CLAIM-019 wrong_call_accept_pct wrong_call_wilson_upper_pct irrelevance_abstain_pct required_unknown_accept_pct -->
<!-- claim:CLAIM-003 far_pct n -->
| # | Benchmark | Result | Scope |
|---|---|---|---|
| 1 | **AgentHarm** | **0.0%** wrongly allowed (0/208); 95% upper bound 1.81% | Intent classification; harmless-twin refusal **100.0%** |
| 2 | **Adversarial simulator** | **0.0%** unsafe runs (0/70 templates; 700 tasks); 95% cluster-level Wilson upper bound **5.2%**; utility +0.456 | Simulated; effective N = 70 (70 templates × 10 cosmetic variants); unsafe-rate gap Δ=0.0143 vs. baseline, not statistically significant |
| 3 | **BFCL v4 (C-ext3)** | Native wrong-call acceptance **0.0%** (0/500; Wilson 95% upper bound **0.76%**); irrelevant-tool refusal **100.0%** (300/300); required-input guessing **0.0%** (0/398) | Sealed once, 2,799 episodes, frozen semantic bundle + authority floor; utility targets missed; see NEGATIVE_RESULTS §39 |
| 4 | **Historical regression** | **0.0%** wrongly allowed (0/167) | Previously observed failures only |

<details>
<summary>How to read those numbers</summary>

- AgentHarm also blocks the harmless twin set, so the result does not establish fine-grained harmful/harmless discrimination.
- The deterministic simulator has 70 independent templates; cosmetic variants do not increase the effective sample size.
- BFCL v4 C-ext3 measures the safety axis only: declared semantic authority takes native wrong-call acceptance from 24/500 to 6 to **0** across the ablation arms. The utility side of the same run (read autonomy, argument routing) missed its pre-registered targets; those findings and the permanent 10.9% baseline live in NEGATIVE_RESULTS §39 and CLAIM-019's caveat, not here.
- Historical regression shows that known failures stay fixed; it does not bound unseen failures.
- Internal reproducibility is not external replication or field validation.

Replaced claims are kept in [superseded claims](docs/assurance/superseded_claims.md). Failed hypotheses and limitations are kept in [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md).

</details>

## Run it

```bash
python -m remora assess drop_database
python -m pytest tests/ -q
python scripts/demo_industrial_maintenance.py
python -m remora doctor
```

<details>
<summary>Library call, and why it is advisory</summary>

`assess_tool_call(...)` evaluates the context the caller supplies. It does not control downstream credentials. For enforcement, route the call through `/v1/execution/*` and make the governed dispatcher the only path to the protected tool.

```python
from remora import assess_tool_call

assessment = assess_tool_call(
    "drop_database",
    {"db": "prod-main"},
    risk_tier="critical",
    action_type="destructive_write",
)
```

For external review or pilot work, set `REMORA_RUNTIME_PROFILE=review` or `controlled_pilot`. Those profiles require the Signed ToolSpec and durable-state prerequisites described in the [execution quickstart](docs/deployment/execution-quickstart.md).

</details>

## What REMORA cannot do

It cannot enforce against a credential path that bypasses its dispatcher. Deployment identity, credential custody, downstream authorization and operational controls stay with the deployment. Capability maturity is tracked, per capability, in the [capability register](docs/assurance/capability_register_v1.yaml).

<details>
<summary>Repository map and current engineering state</summary>

| Path | Purpose |
|---|---|
| `remora/policy/` | Policy observation and decision logic |
| `remora/toolcall/` | Tool authority, ToolSpec and routing contracts |
| `remora/enforcement/` | PDP-to-PEP grant, lease, dispatcher and outbox |
| `remora/governance/` | Review, lifecycle, audit and effect verification |
| `servers/` | HTTP surfaces and deployment wiring |
| `tests/` | Deterministic regression and contract tests |
| `docs/assurance/` | Claims, capabilities, release gates and review records |
| `docs/research/` | Active research material and benchmark design |
| `docs/archive/` | Superseded or historical material |
| `paper/` | Research paper and supporting publication artifacts |

Research modules, AROMER, the older statistical-physics work and historical design documents stay in the repository for reproducibility and audit history. Their presence does not make them part of the enforcing runtime path; the capability register says what is wired.

The `servers/execution_api.py` decomposition is complete (issue #241, closed): contracts, persistence, authorization, dispatch, projections and all use-case orchestration live under `remora/execution/` and `remora/persistence/`, verified against a byte-identical OpenAPI schema at every step. Dispatch runs inside the API process by default. A decoupled dispatch worker exists behind `REMORA_ASYNC_DISPATCH` (issue #82, closed: 202 after durable authorization, exclusive claim before grant, persisted authorization expiry, idempotent terminal projection), but it is not enabled in any reference profile; activation waits on the operational hardening tracked in issue #423.

For product-oriented integration see [Assured Agent Execution](https://github.com/darklordVirtual/assured-agent-execution), which consumes pinned REMORA artifacts rather than copying the governance core.

</details>

## Research, AI use and citation

The research-to-control mapping lives in [docs/research/research_control_matrix.generated.md](docs/research/research_control_matrix.generated.md); related work in [docs/09-related-work.md](docs/09-related-work.md).

Generative-AI tools were used during development. AI-generated text or code is not evidence by itself; claims must resolve to committed artifacts, tests or verified sources. Disclosure: [docs/AI_USE.md](docs/AI_USE.md).

<details>
<summary>BibTeX</summary>

```bibtex
@misc{remora2026,
  title  = {REMORA: Governed Execution Assurance for Tool-Using AI Agents},
  author = {Skogbrott, Stian},
  year   = {2026},
  url    = {https://github.com/darklordVirtual/REMORA-research},
  note   = {Research-grade reference architecture; external replication pending.}
}
```

</details>

## License and contributions

REMORA versions from `v0.10.0` are source-available under the [Business Source License 1.1](LICENSE), with commercial licensing under the [REMORA Commercial License](legal/COMMERCIAL_LICENSE.md). Research, benchmarking and reproducibility work are permitted within the terms in [LICENSING.md](legal/LICENSING.md).

Contribution requirements, branch lifecycle, documentation style and claim hygiene are defined in [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/10-contributing.md](docs/10-contributing.md).
