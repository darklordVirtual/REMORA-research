# REMORA — Executive Brief

## The strategic problem

Enterprise AI adoption is accelerating. The governance infrastructure for it is not.

Models are deployed in production workflows. Agents are given tool access. Outputs influence decisions. But the fundamental question — **how do we know when to trust AI output?** — is answered inconsistently, if at all.

The common approaches are insufficient:

- **Single-model confidence scores** are unreliable. A model can be confident and wrong.
- **Human review of every output** does not scale. It defeats the purpose of automation.
- **Prompt engineering and guardrails** address input filtering, not output quality.
- **Model evaluation** tells you about average performance, not about individual decision reliability.

What is missing is a **runtime governance layer** — a system that evaluates the quality of AI output at the point of decision, and routes it accordingly before it reaches a user or triggers an action.

---

## What REMORA is

REMORA is an enterprise AI control plane.

It is positioned between the consumers of AI output (users, applications, agents) and the model infrastructure that produces it. It does not replace models. It governs when and how their output is used.

Every request that enters REMORA:

1. Is classified by intent, domain, and risk
2. Is routed to the appropriate oracle tier and evidence sources
3. Is evaluated for consensus quality and uncertainty
4. Is gated against a risk policy before output is returned
5. Is recorded in a full, immutable decision trace

The output of REMORA is not just an answer. It is a **governed decision**: an answer (or abstention, or escalation) with a confidence score, evidence citations, a policy trace, and a full audit record.

---

## The key insight

Disagreement between independently operating models is a stronger and more reliable signal of uncertainty than any single model's self-reported confidence.

REMORA demonstrated this on research benchmarks:

- On N=544 items, the most-agreed-upon 18% of answers reached **88.8% accuracy** against a 41.2% full-coverage baseline — a +47.6 percentage point improvement. *Caveat: the 18% coverage threshold is optimised on the same dataset used to report accuracy (in-sample). A calibration/evaluation split is required before treating this as a generalising result.*
- On tool-call safety: REMORA's full policy gate measured **0% unsafe execution** across 700 adversarial tasks in a controlled deterministic simulator, compared to 10-20% for the tested heuristic baselines. *Caveat: all decisions are made by deterministic heuristic classifiers on pre-labelled tasks, not by live LLM calls. This is a benchmark-scoped result, not a production safety measurement.*

The implication for enterprise AI: a system that can reliably identify *which* AI outputs to trust is more valuable than a system that slightly improves the average quality of all outputs.

---

## Why this matters for enterprise

### 1. Risk-proportionate governance

Not all AI questions carry the same risk. An HR FAQ and a production setpoint recommendation are not the same. REMORA applies proportionate governance: low-risk questions get fast, low-cost answers; high-risk questions go through full multi-oracle consensus, evidence verification, and human approval workflows.

### 2. Abstention is a feature, not a failure

In regulated industries, forcing a low-confidence answer is worse than saying "I don't know." REMORA treats abstention as a valid, first-class policy outcome. When models disagree severely, REMORA escalates to a human rather than guessing. This is directly relevant to OT/SCADA, HSE, legal, and financial decision domains.

### 3. Fail-closed behaviour

When confidence is insufficient, budget is exhausted, or the oracle pool disagrees beyond a threshold, REMORA defaults to abstention or escalation — not to a forced answer. This is analogous to a circuit breaker: the safe failure mode is to stop.

### 4. Auditability is structural

REMORA's decision trace — inputs, models used, evidence retrieved, scores, verdict — is a structural output of every request. It is not optional telemetry added after the fact. This makes REMORA deployable in regulated environments (energy, legal, finance) where decisions must be explainable and auditable.

### 5. Model diversity as safety infrastructure

A judge model from a different family than the consensus oracles cannot share the same systematic failures. Diversity is not a capability choice — it is a structural error-detection mechanism.

---

## Enterprise positioning

REMORA is not:

- A chatbot or an AI application
- A model fine-tuning or alignment solution
- A replacement for existing AI infrastructure
- A prompt filtering or input sanitisation tool

REMORA is:

> **An enterprise control layer for trustworthy agentic AI. It evaluates uncertainty, routes tasks by risk, retrieves authoritative evidence, gates autonomous actions, and produces auditable decisions before AI output reaches business-critical workflows.**

This positions REMORA as infrastructure — analogous to a firewall, a load balancer, or an access control layer — not as an AI product.

---

## Applicability

REMORA is applicable to any organisation that:

- Has deployed or is deploying AI in consequential workflows
- Operates in a regulated domain (energy, finance, legal, healthcare, OT/ICS)
- Requires auditability of AI-assisted decisions
- Is building or evaluating agentic AI systems with tool access
- Has multiple business units with different risk tolerances for AI output

---

## Current state

REMORA is a research-grade system. It is not a finished enterprise product.

What is complete and tested:

| Capability | Status |
|---|---|
| 5-stage adaptive cascade pipeline | Complete; covered by the committed deterministic quality gate |
| Multi-oracle consensus with thermodynamic phase | Complete |
| LLM-as-judge verification | Complete |
| Constitutional AI critique-revision loop | Complete |
| Self-consistency verification | Complete |
| Policy engine (ACCEPT/VERIFY/ABSTAIN/ESCALATE) | Complete |
| Conformal prediction risk control | Complete |
| MCP server (12 tools: 8 core + 3 agent control + 1 session monitor) | Complete (agent control tools require agent-control worker deployment) |
| AROMER closed-loop learning (AII intelligence index, MetaJudge, world model, Thompson-bandit oracle selection) | Complete — experimental. Peak AII=0.844 TRAINED_SHADOW_ONLY (12+ cycles, cycle 12 12:04 UTC); current AII=0.7894 CAPABLE_SHADOW_ONLY (organic brr regression ~13:00 UTC; recovery in progress; FAR=0 throughout). See `NEGATIVE_RESULTS.md §12–§13` and `paper/remora_paper.md Appendix F.6`. Three production gates remain: longitudinal audit, human review, RBAC. |
| Cloudflare Workers (RAG, law search, agent control, AROMER) | Complete |
| Audit ledger schema | Designed (enterprise/audit-ledger-schema.sql) |
| Risk profiles (machine-readable) | Designed (enterprise/risk-profiles.yaml) |
| Policy-as-code example | Designed (enterprise/policy_as_code_example.yaml) |
| Nested governance layer policy | Designed (enterprise/nested_governance_layers.yaml) |
| Threat model | Designed (enterprise/threat-model.md) |
| Production readiness plan | Designed (enterprise/production-readiness.md) |
| Secure deployment runbook | Designed (enterprise/deployment-runbook.md) |
| Observability and SLO model | Designed (enterprise/observability.md) |
| Human approval workflow | Designed (enterprise/human-approval-workflow.md) |
| Multi-tenant architecture | Designed (enterprise/remora-control-plane.md) |
| Production deployment | Not attempted |

What is not yet built:

- Production API gateway
- Temporal workflow orchestration
- Enterprise identity integration (OIDC)
- Live evaluation harness with production feedback
- Multi-tenant deployment infrastructure

---

## The opportunity

Every major enterprise AI deployment eventually encounters the same problem: the model is fast and fluent, and wrong in ways that are hard to detect until the damage is done.

REMORA addresses this problem at the architectural level, not at the model level. It is the governance layer that enterprise AI deployments are missing — and it is grounded in measurable, reproducible results.

---

## Further reading

| Document | Purpose |
|---|---|
| [`enterprise/architecture.md`](architecture.md) | Full control plane architecture and circuit breaker analogy |
| [`enterprise/remora-control-plane.md`](remora-control-plane.md) | Multi-tenant deployment model and maturity roadmap |
| [`enterprise/policy-model.md`](policy-model.md) | Risk tiers, decision outcomes, policy-as-code |
| [`enterprise/risk-profiles.yaml`](risk-profiles.yaml) | Machine-readable risk profile configuration |
| [`enterprise/policy_as_code_example.yaml`](policy_as_code_example.yaml) | Concrete fail-closed policy example |
| [`enterprise/nested_governance_layers.yaml`](nested_governance_layers.yaml) | Multi-frequency memory and governance layers |
| [`enterprise/threat-model.md`](threat-model.md) | Threat model and security controls |
| [`enterprise/production-readiness.md`](production-readiness.md) | Production readiness gates and rollout stages |
| [`enterprise/deployment-runbook.md`](deployment-runbook.md) | Secure deployment, scaling, rollback, and operations runbook |
| [`enterprise/observability.md`](observability.md) | Safety metrics, SLOs, alerts, and continuous evaluation |
| [`enterprise/human-approval-workflow.md`](human-approval-workflow.md) | Human approval state model and authority boundaries |
| [`enterprise/industrial-use-case.md`](industrial-use-case.md) | Generic industrial maintenance recommendation gate |
| [`enterprise/integration-patterns.md`](integration-patterns.md) | Integration with enterprise systems (ITSM, CMMS, SIEM, OT) |
| [`enterprise/sector-use-cases.md`](sector-use-cases.md) | Domain-specific use cases across energy, HSE, cyber, procurement, legal |
| [`enterprise/audit-ledger-schema.sql`](audit-ledger-schema.sql) | Audit trail schema (PostgreSQL) |
| [`README.md`](../README.md) | Technical architecture and benchmark results |
| [`ARCHITECTURE.md`](../ARCHITECTURE.md) | Detailed data flow and per-iteration sequence |
| [`paper/whitepaper.md`](../paper/whitepaper.md) | Full technical paper |
