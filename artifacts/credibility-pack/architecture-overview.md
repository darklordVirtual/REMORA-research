# REMORA Enterprise Architecture

## Positioning

REMORA is not a model, a chatbot, or an AI application. It is a **control plane**: a governance and trust layer that sits between the consumers of AI (users, applications, agents) and the producers of AI output (models, tools, data sources).

The question REMORA answers is not "what is the answer?" but "should this answer be trusted, acted on, escalated, or rejected?"

---

## Target Architecture

```
User / Application / Agent
           │
           ▼
┌─────────────────────────┐
│      REMORA Gateway     │  Single API entry point for all AI requests.
│                         │  Authentication, rate limiting, tenant routing.
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Intent Classification │  Task type, domain, complexity, sensitivity.
│                         │  Routes to the correct risk profile.
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Risk + Domain Policy   │  Selects oracle tier, evidence requirements,
│                         │  action permissions, escalation thresholds.
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│      Oracle Router      │  Selects models by task, cost, risk level,
│                         │  and required capability. Enforces budget.
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│    Evidence Retrieval   │  RAG against authoritative sources:
│                         │  procedures, regulations, asset data,
│                         │  engineering documents, live process data.
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Consensus + Phase      │  Multi-oracle disagreement measurement.
│  Analysis               │  Thermodynamic phase: ordered / critical /
│                         │  disordered. Trust score computation.
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│     Decision Gate       │  Policy-gated verdict:
│                         │  ACCEPT / RETRIEVE / DEBATE /
│                         │  ESCALATE / ABSTAIN / ACT
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Answer / Action /      │  Structured output with confidence,
│  Escalation             │  evidence, critique, and policy trace.
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Audit + Telemetry +    │  Immutable decision log: input, models,
│  Learning Loop          │  evidence, scores, verdict, outcome.
│                         │  Feeds back to eval harness.
└─────────────────────────┘
```

---

## Enterprise Component Map

| Component | Location | Role |
|---|---|---|
| **REMORA Gateway** | `remora/cascade/engine.py` + API layer | Single entry point; tenant routing; rate limiting |
| **Policy Engine** | `remora/policy/decision_engine.py` | Risk tier selection; domain rules; action boundaries |
| **Oracle Router** | `remora/cascade/stages.py` (FastGate, ConsensusGate) | Model selection by task, cost, risk, criticality |
| **Consensus Engine** | `remora/engine.py`, `remora/thermodynamics.py` | Disagreement, phase, entropy, trust score |
| **Evidence Layer** | `workers/rag-oracle/`, `workers/law-search/` | RAG against authoritative sources |
| **Action Gate** | `remora/cascade/stages.py` (VerifierGate, CritiqueRevision) | Verifies answer before output or action |
| **Audit Ledger** | `remora/assurance/` + `docs/thermodynamics/claim_ledger.yaml` | Full decision trace |
| **Evaluation Harness** | `experiments/`, `tests/`, `artifacts/` | Continuous benchmark against golden datasets |
| **AROMER Learning Loop** *(experimental)* | `remora/aromer/` + `workers/aromer/` | Closed-loop meta-learning from governance outcomes; AII intelligence index; causal PS/PN attribution (Bjøru 2026, Paper IV §4.2.2) |

---

## Design Principles

### 1. Separation of concerns

The control plane does not compete with the model layer. It orchestrates trust between the model layer and the business layer. Existing model infrastructure (Azure OpenAI, Bedrock, internal LLM deployments) can be wired in as oracles without displacement.

### 2. Fail-closed behavior

When evidence is insufficient, models disagree, or budget is exhausted, REMORA defaults to `ABSTAIN` or `ESCALATE`, not to a forced low-confidence answer. This is analogous to a circuit breaker: the safe failure mode is to stop, not to guess.

### 3. Policy before execution

Every request is evaluated against a policy profile before any model call is made. Domain, risk tier, data access rules, and action permissions are resolved at the gateway, not at the application layer.

### 4. Auditability is structural

The decision trace, inputs, models used, evidence retrieved, scores computed, verdict issued, is not optional telemetry. It is an architectural output of every request. This makes REMORA usable in regulated environments where decisions must be explainable.

### 5. Model diversity as a safety mechanism

Independent oracles from different model families are not used for capability redundancy: they are used to detect failure modes. A judge oracle from a different family than the consensus oracles cannot share the same systematic errors, making its disagreement a reliable signal.

---

## The Circuit Breaker Analogy

Enterprise networks use multiple control layers: firewalls, load balancers, intrusion detection systems, access control lists. None of these run the application: they control what reaches it and what it can do.

REMORA applies the same pattern to AI systems:

| Network control | REMORA equivalent |
|---|---|
| Firewall | Confidence gate (ABSTAIN on low trust) |
| Load balancer | Oracle router (task → model selection) |
| IDS/IPS | Adversarial input detection, prompt injection guard |
| Access control | Policy engine (domain + role + risk tier) |
| Audit log | Decision ledger (immutable trace) |
| Circuit breaker | Phase gate (disordered phase → escalate) |

The goal is not to replace AI infrastructure. The goal is to make it governable.

---

## Related Documents

- [`enterprise/remora-control-plane.md`](remora-control-plane.md), multi-tenant deployment model
- [`enterprise/policy-model.md`](policy-model.md), risk tiers and decision outcomes
- [`enterprise/risk-profiles.yaml`](risk-profiles.yaml), machine-readable profile configuration
- [`enterprise/policy_as_code_example.yaml`](policy_as_code_example.yaml) - concrete fail-closed policy-as-code example
- [`enterprise/nested_governance_layers.yaml`](nested_governance_layers.yaml) - multi-frequency memory and governance layers
- [`enterprise/threat-model.md`](threat-model.md) - threat model and security controls
- [`enterprise/production-readiness.md`](production-readiness.md) - production readiness gates
- [`enterprise/deployment-runbook.md`](deployment-runbook.md) - secure deployment and operations runbook
- [`enterprise/observability.md`](observability.md) - SLOs, safety metrics, and alerts
- [`enterprise/human-approval-workflow.md`](human-approval-workflow.md) - approval workflow and authority boundaries
- [`enterprise/integration-patterns.md`](integration-patterns.md), enterprise stack integration
- [`enterprise/audit-ledger-schema.sql`](audit-ledger-schema.sql), audit trail schema
- [`enterprise/sector-use-cases.md`](sector-use-cases.md), domain-specific use cases
- [`enterprise/executive-brief.md`](executive-brief.md), strategic positioning
