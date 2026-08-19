# REMORA: Policy-Gated Governance for Operational AI Agents

[![Paper (PDF)](https://img.shields.io/badge/paper-PDF-b31b1b.svg)](paper/remora_paper.pdf) [![CI — Deterministic Test Suite](https://github.com/darklordVirtual/REMORA-research/actions/workflows/ci.yml/badge.svg)](https://github.com/darklordVirtual/REMORA-research/actions/workflows/ci.yml) [![Quality Gates](https://github.com/darklordVirtual/REMORA-research/actions/workflows/quality-gates.yml/badge.svg)](https://github.com/darklordVirtual/REMORA-research/actions/workflows/quality-gates.yml) [![License: BUSL-1.1](https://img.shields.io/badge/License-BUSL--1.1-blue.svg)](LICENSE)

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
python -m pip install -e '.[dev]'
python -m remora try
```

**Start here:** [Developer handoff](DEVELOPER_OVERVIEW.md) · [Architecture](ARCHITECTURE.md) · [Evidence and claims](docs/02-evidence-and-claims.md) · [Reproducibility](docs/06-reproducibility.md) · [Documentation index](docs/README.md)

---

## Execution path

The operational path is intentionally small:

1. **Authoritative context** — tool meaning, target, risk and approved intent come from deployment-owned sources such as Signed ToolSpec, not from the calling agent.
2. **Policy decision** — deterministic hard guards have precedence over model-derived signals.
3. **Review or grant** — `VERIFY`/`ESCALATE` enters bounded review; `ACCEPT` receives a short-lived, single-use grant bound to the proposal.
4. **PEP and dispatch** — the grant is consumed, an `ExecutionLease` binds policy identity and call identity, and `GovernedToolDispatcher` invokes the deployment-owned callable.
5. **Lifecycle and evidence** — dispatch intent, outcome, effect verification and audit records remain joinable by proposal identity.

The separate `/v1/assess` research surface can use oracle, evidence and uncertainty components. Those components are not prerequisites for the execution kernel and cannot override its deterministic hard-guard floor.

See [DEVELOPER_OVERVIEW.md](DEVELOPER_OVERVIEW.md) for the CORE / OPTIONAL / EXPERIMENTAL / HISTORICAL boundary and [docs/deployment/execution-quickstart.md](docs/deployment/execution-quickstart.md) for a deployment-shaped walkthrough.

---

## Evidence

Headline values are governed by the [claim register](docs/assurance/claim_register_v1.yaml) and must remain tied to committed result artifacts and scope caveats. Reported empirical results are **bounded by documented assumptions**, benchmark populations and evaluation protocols; they are not general safety guarantees.

<!-- claim:CLAIM-002 far_pct far_ci_high_pct fbr_pct n -->
<!-- claim:CLAIM-001 far_pct n_effective n -->
<!-- claim:CLAIM-018 routing_accuracy_pct wrong_call_accept_pct irrelevance_abstain_pct unobtainable_abstain_pct obtainable_verify_pct required_unknown_accept_pct -->
<!-- claim:CLAIM-003 far_pct n -->
| # | Benchmark | Result | Scope |
|---|---|---|---|
| 1 | **AgentHarm** | **0.0%** wrongly allowed (0/208); 95% upper bound 1.81% | Intent classification; harmless-twin refusal **100.0%** |
| 2 | **Adversarial simulator** | **0.0%** unsafe runs (0/70 templates; 700 tasks); 95% cluster-level Wilson upper bound **5.2%**; utility +0.456 | Simulated; effective N = 70 (70 templates × 10 cosmetic variants); unsafe-rate gap Δ=0.0143 vs. baseline, not statistically significant |
| 3 | **BFCL v4** | Irrelevant-tool refusal **100.0%** (258/258); wrong-call acceptance **10.9%** (28/258); unobtainable-input refusal **99.0%** (98/99); obtainable-input verification **97.0%** (96/99); required-input guessing **0.0%** (0/32); routing accuracy **91.2%** | Sealed run, 1,527 episodes; 5/5 pre-registered targets met |
| 4 | **Historical regression** | **0.0%** wrongly allowed (0/167) | Previously observed failures only |

Interpret these values narrowly:

- AgentHarm also blocks the harmless twin set, so the result does not establish fine-grained harmful/harmless discrimination.
- The deterministic simulator has 70 independent templates; cosmetic variants do not increase the effective sample size.
- BFCL v4 exposes the current routing weakness directly: 10.9% of known-wrong calls were accepted in that track.
- Historical regression demonstrates that known failures remain fixed; it does not bound unseen failures.
- Internal reproducibility is not external replication or field validation.

Replaced claims are retained in [superseded claims](docs/assurance/superseded_claims.md). Failed hypotheses and limitations are retained in [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md).

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

For external review or pilot work, use `REMORA_RUNTIME_PROFILE=review` or `controlled_pilot`; those profiles require the stronger Signed ToolSpec and durable-state prerequisites described in the [execution quickstart](docs/deployment/execution-quickstart.md).

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

Research modules, AROMER, older thermodynamic/statistical-physics work and historical design documents remain in the repository for reproducibility and audit history. Their presence does **not** imply that they are part of the enforcing runtime path. Use the [capability register](docs/assurance/capability_register_v1.yaml) for wiring status.

---

## Current boundaries

REMORA cannot enforce against a credential path that bypasses its dispatcher. Deployment identity, credential custody, downstream authorization and operational controls remain deployment responsibilities. Capability maturity is tracked explicitly in `docs/assurance/capability_register_v1.yaml`.

`servers/execution_api.py` is still a large orchestration module. Its staged decomposition is tracked in issue #241; this is a maintainability boundary, not a claim that the current module layout is the desired final architecture.

For product-oriented integration, see [Assured Agent Execution](https://github.com/darklordVirtual/assured-agent-execution), which consumes pinned REMORA artifacts rather than copying the governance core.

---

## Research, AI use and citation

The current research-to-control mapping is maintained in [docs/research/research_control_matrix.generated.md](docs/research/research_control_matrix.generated.md). Related work is summarized in [docs/09-related-work.md](docs/09-related-work.md).

Generative-AI tools have been used during development. AI-generated text or code is not treated as evidence by itself; claims must resolve to committed artifacts, tests or verified sources. Disclosure: [docs/AI_USE.md](docs/AI_USE.md).

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

REMORA versions from `v0.10.0` are source-available under the [Business Source License 1.1](LICENSE), with separate commercial licensing available under [REMORA Commercial License](COMMERCIAL_LICENSE.md). Research, benchmarking and reproducibility work are permitted within the terms described in [LICENSING.md](LICENSING.md).

Contribution requirements, branch lifecycle, documentation style and claim hygiene are defined in [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/10-contributing.md](docs/10-contributing.md).
