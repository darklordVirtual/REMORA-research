# REMORA as an Enterprise Control Plane

## The Problem with AI at Scale

When an organization deploys AI across multiple business domains, the failure modes multiply:

- Different teams use different models with no consistency guarantees
- There is no shared understanding of when AI output should be trusted
- Autonomous agents can take consequential actions without governance
- No unified audit trail exists across AI touchpoints
- Risk thresholds vary by intuition rather than policy

The solution is not to standardize on one model. The solution is to add a control plane.

---

## What a Control Plane Does

A control plane does not process the work. It governs *how* the work is processed.

In AI terms, REMORA as a control plane:

1. **Classifies** incoming requests by intent, domain, and risk
2. **Selects** the appropriate oracle tier and evidence sources
3. **Measures** uncertainty and consensus quality
4. **Gates** output against policy — before it reaches the user or triggers an action
5. **Records** every decision with full traceability

The underlying models — whether cloud APIs, fine-tuned domain models, or retrieval systems — remain unchanged. REMORA adds a layer of governance above them.

---

## Multi-Tenant Architecture

In a large organization, different business units have different data, policies, risk tolerances, and approval workflows. A single shared AI gateway must isolate these.

REMORA supports a tenant-per-domain model:

```
REMORA Core
 ├── tenant: exploration
 │    ├── data sources: well logs, seismic, reservoir models
 │    ├── policy: medium–high risk, RAG required
 │    ├── approval: senior geoscientist for high-risk
 │    └── eval set: domain-specific golden QA
 │
 ├── tenant: production
 │    ├── data sources: process historians, sensor data, procedures
 │    ├── policy: high risk, multi-oracle required
 │    ├── approval: production engineer + operations manager
 │    └── eval set: production optimization scenarios
 │
 ├── tenant: maintenance
 │    ├── data sources: CMMS, asset register, maintenance history
 │    ├── policy: medium risk, evidence from procedure docs
 │    ├── approval: maintenance supervisor for corrective actions
 │    └── eval set: work order and defect classification
 │
 ├── tenant: hse
 │    ├── data sources: incident reports, regulations, barrier matrices
 │    ├── policy: critical — recommend only, never ACT autonomously
 │    ├── approval: HSE manager always in the loop
 │    └── eval set: barrier management and risk classification
 │
 ├── tenant: cybersecurity
 │    ├── data sources: SIEM events, CVE feeds, threat intel
 │    ├── policy: high risk, fast path for triage, human for response
 │    ├── approval: SOC analyst for any recommended action
 │    └── eval set: incident classification, CVE impact scoring
 │
 ├── tenant: procurement
 │    ├── data sources: contracts, supplier registry, spend data
 │    ├── policy: medium risk, evidence from contracts
 │    ├── approval: category manager for contract recommendations
 │    └── eval set: contract clause extraction, supplier scoring
 │
 └── tenant: legal-compliance
      ├── data sources: regulations, internal policies, case law
      ├── policy: high risk — answer only, no autonomous action
      ├── approval: legal counsel for binding interpretations
      └── eval set: regulatory Q&A, policy conflict detection
```

Each tenant is independently configured with:

| Configuration dimension | Per-tenant |
|---|---|
| Data sources | Yes — isolated namespaces |
| Risk thresholds | Yes — policy profile per tenant |
| Oracle selection | Yes — model tier per domain |
| Approval workflows | Yes — escalation routing |
| Evaluation datasets | Yes — domain-specific golden sets |
| Oracle budget | Yes — cost controls per unit |
| Telemetry namespace | Yes — isolated dashboards |

---

## Deployment Model

REMORA is designed to slot into an existing enterprise AI architecture without requiring replacement of current infrastructure.

```
Existing AI Infrastructure
  (Azure OpenAI / Bedrock / internal LLM / vector DB)
             ↑  (oracle calls)
             │
   ┌─────────┴──────────┐
   │   REMORA Core      │  ← This is what you deploy
   │   Control Plane    │
   └─────────┬──────────┘
             │  (governed output)
             ↓
   Applications / Agents / Users
```

### Deployment options

**Option A — Sidecar gateway:** REMORA deployed as a proxy in front of existing model endpoints. Minimal integration effort. Works with any model API.

**Option B — SDK integration:** REMORA embedded in the application layer. Gives more flexibility for custom oracle routing. Requires code changes in each consumer.

**Option C — Event-driven:** Requests submitted to a queue (Kafka, NATS, SQS). REMORA workers consume, process, and publish governed decisions. Best for async workflows, long-running agentic tasks, and human-approval flows.

---

## Technical Stack Recommendation

| Layer | Recommended options | Notes |
|---|---|---|
| API gateway | FastAPI / Cloudflare Workers / Kubernetes ingress | Cloudflare Workers already in use |
| Message queue | Kafka / NATS / Amazon SQS | Required for async + human-approval flows |
| Orchestration | Temporal / Celery / Kubernetes Jobs | Temporal preferred for long-running agentic tasks |
| Policy engine | OPA / Cedar / REMORA native policy | OPA integrates cleanly with Kubernetes |
| Audit store | PostgreSQL + object storage (S3/R2) | See `audit-ledger-schema.sql` |
| Vector / RAG | pgvector / Qdrant / Weaviate | Cloudflare Vectorize already in use |
| Observability | OpenTelemetry + Grafana | Structured traces per decision |
| Evaluation | Pytest + golden datasets + scheduled runs | Already established in this repo |
| Secrets | HashiCorp Vault / cloud KMS | API keys, tenant credentials |

### Why Temporal for agentic workflows

Agentic AI tasks are often long-running, asynchronous, and require human checkpoints. Temporal provides:

- **Durable execution** — a task survives restarts, crashes, and network failures
- **Human-in-the-loop** — workflow pauses at decision gates and resumes on approval
- **Retry semantics** — model call failures are retried with backoff, not silently dropped
- **Full audit history** — every workflow step is recorded with inputs and outputs

This maps directly to the REMORA cascade: each stage is a Temporal activity, and the action gate can pause for human approval before continuing.

---

## Maturity Roadmap

### Phase 1 — Control Layer MVP

**Goal:** prove that REMORA governs answer quality on real requests.

- Single-tenant API gateway
- 2–3 oracle tiers
- Basic consensus scoring and phase classification
- RAG against one document corpus
- Structured audit log
- Simple risk policy (low / medium / high)
- Evaluation set for one domain

**Target use case:** technical document Q&A or engineering support queries.
**Success metric:** measurable accuracy improvement over single-model baseline on domain eval set.

---

### Phase 2 — Domain Pilots

**Goal:** demonstrate value across multiple business units.

- Domain-specific risk profiles and data sources
- Escalation routing to subject-matter experts
- Trust and cost dashboards per tenant
- Comparative benchmarks (single model vs REMORA) per domain
- Human feedback loop feeding evaluation harness

**Target use cases:** maintenance support, HSE guidance, procurement analysis, cyber triage.
**Success metric:** measurable reduction in escalations that required manual correction.

---

### Phase 3 — Action-Gated Agents

**Goal:** move from governed answers to governed actions.

- Tool-use through action gates (REMORA controls what agents can execute)
- Human-in-the-loop approval for consequential actions
- Integration with workflow systems (ServiceNow, Jira, SAP)
- Policy-as-code for action permissions
- Tenant-specific action budgets and hard limits

**Target use cases:** work order creation, change request drafting, anomaly response recommendations.
**Success metric:** zero unauthorized autonomous actions reaching production systems.

---

### Phase 4 — Enterprise AI Governance Runtime

**Goal:** REMORA becomes the standard runtime for all agentic AI in the organization.

- Full multi-tenant deployment
- Continuous evaluation against production-sampled feedback
- Compliance reporting (decision logs for regulatory audit)
- Risk dashboards for AI governance committees
- Model cost optimization across tenants
- Red-team test harness integrated into CI/CD
- SLO definitions for AI quality (accuracy, abstention rate, escalation rate)

**Success metric:** REMORA decision ledger accepted as evidence in internal audits and regulatory reviews.
