# Enterprise Rollout Architecture — TOGAF-Aligned Plan for a REMORA-class Agent Governance Platform

**Status:** Reference architecture plan (documentation). Not a claim about the
current repository. It describes how an enterprise would take a REMORA-*class*
agent-action governance capability from research prototype to a governed,
multi-team production platform.
**Framework:** TOGAF 10 ADM (Architecture Development Method).
**Audience:** Enterprise/Chief Architect (accountable owner) distributing the
architecture to complementary delivery teams.
**Grounding:** Uses REMORA's real building blocks — the deterministic PDP
(`RemoraDecisionEngine`), the `DecisionEnvelope` contract, policy-as-code,
the claim-provenance discipline — and the open remediation items (REM-013,
REM-020…REM-031) as the concrete backlog. See
`docs/assurance/external_security_audit_v1.md` and
`docs/assurance/remediation_register.yaml`.

---

## 0. How to read this document

TOGAF's ADM is a cycle of phases (Preliminary → A…H) with Requirements
Management at the centre. This plan walks the phases once for a REMORA-class
rollout and, in each, names **the deliverable, the accountable owner, and the
executing team(s)**. The Enterprise Architect owns the *whole* and delegates
each phase's execution — that delegation is the point of §3 (Business
Architecture / org) and §12 (RACI).

```
        Preliminary  ──►  A. Vision
             ▲                 │
   H. Change  │                ▼
   Mgmt   ┌───┴──────── Requirements ────────┐   B. Business
          │             Management            │      │
   G. Impl │                                  │      ▼
   Gov.    └──── F. Migration ◄── E. Opps ◄── D. Tech ◄── C. Info Systems
```

---

## 1. Preliminary Phase — Establish the EA capability and principles

**Purpose:** stand up the architecture function and the rules everyone will be
held to before any solution work.

**Deliverables**
- **Architecture governance framework**: an Architecture Review Board (ARB),
  an Architecture Repository, and the Architecture Contract template each
  executing team signs (Phase G).
- **Architecture principles** (tailored to agent governance):
  1. *Deterministic safety floor first.* A hard policy layer decides
     execution permission; no probabilistic/learned component may override it.
     (REMORA's canonical claim; keep it as principle #1.)
  2. *Deny-by-default for actuation.* Unknown = not authorized (unknown action
     type, unverified schema, missing evidence → VERIFY/ABSTAIN, never ACCEPT).
  3. *Enforcement is mandatory and inseparable from execution.* No tool runs
     without a valid, bound authorization lease (REM-024).
  4. *Every decision is an auditable, hash-chained `DecisionEnvelope`.*
  5. *Claims require artifacts.* No number ships without a committed,
     verifiable artifact (the claim-provenance gate is a platform control, not
     a research nicety).
  6. *Identity is bound at authentication, never re-read from a header.*
     (Security audit A-1.)
  7. *Policy is code, versioned, signed, and promoted through GitOps.*

**Owner:** Enterprise/Chief Architect (accountable).
**Executes:** EA team + Security/Risk (CISO office) co-author principles;
ARB ratifies.

---

## 2. Phase A — Architecture Vision

**Purpose:** agree scope, value, stakeholders, and success criteria before
detailed design.

**Deliverables**
- **Statement of Architecture Work** and **Architecture Vision** document.
- **Stakeholder map & concerns** (see table).
- **Value proposition**: govern autonomous agent actions in consequential
  systems so that unsafe execution is blocked deterministically, every
  decision is auditable/replayable, and human oversight is enforced where risk
  demands — mapped to regulatory obligations (EU AI Act Art. 12 logging,
  Art. 14 human oversight).
- **SMART target measures** (Architecture Requirements): e.g. *0 unsafe
  autonomous executions in shadow-replay over the release-gate window with an
  anytime-valid bound*; *100% of tool calls pass through the PEP*; *p95 PDP
  latency < 150 ms*; *0 cross-tenant data-access events in isolation tests*.

| Stakeholder | Primary concern | Architecture answer |
|---|---|---|
| Board / Risk (CISO, CRO) | Unsafe autonomous action; auditability | Deterministic floor + hash-chained envelope + SIEM (REM-029) |
| Regulators / DPO | AI Act / GDPR evidence | Logging (Art. 12), human oversight (Art. 14), DPIA (REM-031) |
| Product / Business units | Time-to-value, low friction | Selective autonomy: ACCEPT low-risk, escalate the rest |
| Platform / SRE | Availability, latency, scale | Stateless PDP, circuit breakers (REM-028) |
| Agent developers | Simple integration | One `authorize_tool_call()` API + SDK |
| Auditors | Independent verifiability | Replay engine + claim-provenance gate |

**Owner:** Enterprise Architect. **Approves:** ARB + executive sponsor.

---

## 3. Phase B — Business Architecture (capabilities, value streams, org)

This is where the architecture is **distributed to teams**. It defines the
business capabilities, the value stream a governed action flows through, and
the team topology that owns each capability.

### 3.1 Business capability map (what must exist)
1. Policy authoring & lifecycle (author, review, sign, promote, roll back).
2. Runtime decisioning (PDP).
3. Runtime enforcement (PEP + dispatcher/proxy).
4. Evidence & retrieval.
5. Oracle/model operations.
6. Audit, assurance & replay.
7. Identity, tenancy & access.
8. Observability, SRE & incident response.
9. Assurance, claims & compliance.
10. Agent developer enablement.

### 3.2 Value stream (one governed action)
```
Agent proposes action
  → Identity/tenant bound (verified claims, not headers)
  → Observation assembled from TRUSTED server-side sources
  → PDP decision (hard blocks → uncertainty routing → outcome)
  → ACCEPT: signed execution lease (tenant, tool, full-args hash, policy
            version, nonce, expiry) → PEP verifies → dispatcher executes
  → VERIFY/ESCALATE: workflow binds reviewer, expiry, one-time nonce
  → DecisionEnvelope emitted, hash-chained, streamed to SIEM + replay store
```

### 3.3 Team topology (Team Topologies mapping)
The Enterprise Architect delegates capabilities to four team types so
responsibilities are complementary, not overlapping:

| Team (type) | Owns (capabilities) | REMORA components | Key backlog |
|---|---|---|---|
| **Platform team** (platform) | 2, 3, 7, 8 — the governance platform as a product | PDP service, PEP/lease service, gateway, audit chain, identity | REM-013, REM-024, REM-025, REM-026, REM-028, REM-029 |
| **Policy & Governance team** (complicated-subsystem) | 1, 9 — policy-as-code, claim discipline, compliance evidence | `remora/policy`, OPA/Rego bundles, claim-provenance gate, release gates | REM-020, REM-021, REM-023, REM-031 |
| **Decision Science team** (complicated-subsystem) | 4, 5 — oracles, uncertainty, evidence, conformal calibration | `remora/oracles`, `remora/selective`, `remora/evidence`, credal/conformal | REM-030, calibration & anytime-valid monitoring |
| **Stream-aligned product teams** (stream-aligned, many) | 10 + business use — integrate agents behind the platform | SDK/adapters (`remora/adapters`), tool contracts | per-domain onboarding |
| **Enabling team** (enabling) | temporary uplift — coaches the above on TOGAF, secure SDLC, TDD | — | reviews, pairing, standards |

**Conway alignment:** the platform is a product with an API; stream-aligned
teams consume it via a self-service SDK and never hold downstream tool
credentials (those live only in the PEP/proxy — security audit A-4/REM-024).

**Owner:** Enterprise Architect defines the topology; **Domain Architects**
embedded in each team execute detailed design under the Architecture Contract.

---

## 4. Phase C — Information Systems Architecture

### 4.1 Data architecture
- **Canonical contract: `DecisionEnvelope` (v2).** Stable, versioned,
  hash-chained. It is the single source of truth for every decision and the
  unit of audit, replay, and regulatory evidence. Schema changes go through
  ARB (Phase H) with a version bump and migration.
- **Authoritative data classification:** all safety-load-bearing observation
  fields (`risk_tier`, `action_type`, `target_environment`, `tool schema`,
  `argument_tainted`, `tenant_id`) are **server-derived from trusted sources
  (registries, verified identity, data-flow middleware)** — never
  agent-declared (security audit P1). Full-argument binding via
  `tool_call_hash`.
- **Stores:** policy bundle registry (signed OCI), decision/envelope store
  (append-only, per-tenant), audit anchor store (WORM + Merkle roots),
  evidence corpus (RAG), replay corpus. Tenant isolation via RLS (REM-026).
- **Retention & privacy:** field-level minimization, regional storage,
  deletion/legal-hold workflows (REM-031, GDPR).

### 4.2 Application architecture (services)
| Service | Responsibility | Owning team |
|---|---|---|
| **PDP service** | Stateless policy decisioning (`RemoraDecisionEngine`) | Platform |
| **PEP / lease service** | Issue & verify signed execution leases; deny without one | Platform |
| **Tool proxy / dispatcher middleware** | Only holder of downstream credentials; executes on valid lease | Platform |
| **Policy bundle service** | Signed policy-as-code, staged promotion, rollback | Policy & Governance |
| **Oracle orchestration** | Multi-oracle consensus, diversity, uncertainty | Decision Science |
| **Evidence service** | RAG/domain/cyber evidence providers | Decision Science |
| **Audit & replay service** | Hash-chain, anchoring, shadow-replay | Platform + Assurance |
| **Identity/tenancy service** | OIDC/workload JWT → immutable `Principal` | Platform |
| **Agent SDK/adapters** | `authorize_tool_call()`, framework adapters | Stream-aligned + enabling |

**Key design decisions (ADRs to record in the repository):**
- ADR-001 Deterministic-first ordering (accepted; it is REMORA's core).
- ADR-002 PEP is mandatory; the agent never calls tools directly (REM-024).
- ADR-003 Authorization from verified `Principal`, never headers (A-1).
- ADR-004 One `authorize_tool_call()` entry point; cascade/consensus is
  advisory only, never authorizing (security audit A-6).

---

## 5. Phase D — Technology Architecture

- **Runtime:** stateless PDP (horizontally scaled), PEP sidecar or gateway
  filter, tool proxy. Deadline propagation, circuit breakers, bounded oracle
  queues, local deterministic fallback only (REM-028).
- **Security zones:** agents run in a low-trust zone with no tool credentials;
  the PEP/proxy in a controlled zone holds credentials; audit anchors in an
  immutable zone. Byzantine/quorum sizing for oracles stated honestly
  (n ≥ 3f+1 for f Byzantine oracles).
- **Cryptography:** HMAC/asymmetric-signed leases and envelopes; KMS/HSM keys
  with rotation; RFC 3161 timestamps; transparency-log anchoring (REM-025).
- **Supply chain:** hash-pinned lockfile installed in CI, SBOM (CycloneDX/SPDX),
  SLSA provenance, Sigstore-signed images (REM-027).
- **Deployment topologies:** cloud reference (`docs/deployment/azure-reference-architecture.md`)
  and air-gapped/on-prem (`docs/deployment/onprem-airgapped.md`) already exist
  as starting points.

---

## 6. Phase E — Opportunities & Solutions (work packages)

Group the backlog into deliverable work packages, each with a clear owner:

| WP | Scope | Owner | Depends on |
|----|-------|-------|-----------|
| WP1 Identity & RBAC | OIDC/JWT, `Principal`, tenant mapping | Platform | A-1 (done), REM-023 |
| WP2 Mandatory PEP & leases | dispatcher/proxy, signed leases | Platform | REM-024 |
| WP3 Durable audit | transactional sequence, WORM, anchoring | Platform + Assurance | REM-025 |
| WP4 Tenant isolation | RLS, per-tenant crypto | Platform | REM-026 |
| WP5 Policy control plane | signed bundles, GitOps promotion | Policy & Gov | REM-013 |
| WP6 Resilience | HA, circuit breakers, SLOs | Platform/SRE | REM-028 |
| WP7 Observability & SIEM | OTel, immutable events, alerts | SRE + Security | REM-029 |
| WP8 Supply chain | lock/SBOM/SLSA/Sigstore | Platform + Enabling | REM-027 |
| WP9 Independent validation | tool-interception tests, red team | Assurance | REM-030, REM-021 |
| WP10 Compliance pack | DPIA, AI Act documentation | Policy & Gov + DPO | REM-031 |

---

## 7. Phase F — Migration Planning (transition architectures)

Incremental, gated increments — each a usable Transition Architecture:

- **T0 — Shadow-only research (current).** PDP decides; enforcement optional;
  claim-provenance gate green. Gates open: REM-020/021/023.
- **T1 — Governed pilot (single business unit).** WP1+WP2+WP5: mandatory PEP,
  signed leases, GitOps policy, real OIDC. Exit criteria: 100% of pilot tool
  calls through the PEP; RBAC isolation test passing; REM-021 external review
  started.
- **T2 — Multi-tenant GA.** WP3+WP4+WP6+WP7: durable audit, tenant isolation,
  HA, SIEM. Exit: cross-tenant isolation tests green; SLOs met; audit anchoring
  live.
- **T3 — Regulated / safety-critical.** WP8+WP9+WP10: supply-chain hardening,
  independent validation, compliance pack. Exit: external red team + AI Act
  evidence pack complete.

Each increment is a release gate with committed artifacts (the existing
release-gate + claim-provenance machinery is the enterprise gate mechanism,
scaled up).

---

## 8. Phase G — Implementation Governance (how teams stay aligned)

- **Architecture Contract** signed by each executing team, binding them to the
  §1 principles and the target measures. Non-conformance is raised to the ARB.
- **Automated architecture compliance** (fitness functions in CI): the
  claim-provenance gate, the explain/decide parity harness, the
  "no enforcement module imports the cascade" test, mypy on the core, and new
  fitness functions per increment (e.g. "no tool executes without a lease",
  "no authorization reads a header"). These make architectural principles
  *executable*, not aspirational.
- **Dispensations:** any deviation is a time-boxed, ARB-approved dispensation
  with a remediation date — never a silent exception (mirrors how REM-022's
  closure deviation was recorded rather than hidden).

---

## 9. Phase H — Architecture Change Management

- **Change drivers:** new oracle families, new regulation, new tool classes,
  incidents. **Envelope/schema and policy-bundle versioning** are the
  controlled surfaces; changes flow PR → simulation → test gate → canary →
  promote, with automatic rollback on a policy SLO breach.
- **Cadence:** ARB reviews the Architecture Repository quarterly; the claim
  register and remediation register are the living change log.

---

## 10. Requirements Management (continuous, central)

A single traceable backlog links **stakeholder concern → architecture
requirement → work package → REM item → artifact/test**. The remediation
register (`remediation_register.yaml`) and claim register are the requirements
store; the claim-provenance gate enforces traceability (no shipped claim
without an artifact).

---

## 11. Architecture Repository & ADRs

- **Repository contents:** principles, this plan, ADRs, the `DecisionEnvelope`
  and policy-bundle schemas, the reference deployments, the RACI, and the
  living registers.
- **ADR log:** record every load-bearing decision (ADR-001…004 above and
  onward) with status, context, decision, consequences.

---

## 12. RACI — distributing responsibility across teams

Legend: **R** responsible (executes), **A** accountable (one owner),
**C** consulted, **I** informed.

| ADM deliverable | Ent. Architect | Platform | Policy & Gov | Decision Sci | Stream teams | Security/Risk | SRE | Assurance/DPO |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Principles & governance (Prelim) | A | C | R | C | I | R | C | C |
| Architecture Vision (A) | A | C | C | C | C | C | C | C |
| Business arch & team topology (B) | A | R | R | R | C | C | C | C |
| Data/App architecture (C) | A | R | R | R | C | C | C | C |
| Technology architecture (D) | A | R | C | C | I | C | R | C |
| Work packages (E) | A | R | R | R | R | C | R | C |
| Migration increments (F) | A | R | R | C | R | C | R | C |
| Impl. governance & fitness fns (G) | A | R | R | C | R | R | C | R |
| Change management (H) | A | R | R | C | I | C | C | C |
| Requirements traceability | A | C | R | C | I | C | I | R |
| Identity/RBAC (WP1) | C | R | C | I | I | A | C | C |
| Mandatory PEP (WP2) | A | R | C | I | C | R | C | C |
| Durable audit (WP3) | C | R | C | I | I | C | C | A |
| Compliance pack (WP10) | C | I | R | I | I | C | I | A |

**Reading the matrix:** the Enterprise Architect is accountable for the
*architecture* (that it is coherent and delivered); individual capability
owners are accountable for their *slice* (e.g. Security owns identity/RBAC
outcomes, Assurance/DPO owns durable audit and the compliance pack). Exactly
one **A** per row — that is the enterprise expectation.

---

## 13. What REMORA already provides vs. what the enterprise must build

| Enterprise need | In REMORA today | To build (REM) |
|---|---|---|
| Deterministic PDP | ✅ `RemoraDecisionEngine` | — |
| Canonical decision contract | ✅ `DecisionEnvelope` v2 | schema governance |
| Claim/requirement traceability | ✅ claim-provenance gate | scale to platform |
| Deny-by-default incl. unknown action type | ✅ (security audit A-2) | — |
| Identity bound at auth | ✅ (A-1) | OIDC/JWT, rotation (WP1) |
| Full-args binding | ✅ `tool_call_hash` (A-5) | recompute-at-execute (WP2) |
| Mandatory PEP | ⚠ library + hook only | **REM-024 (WP2)** |
| Durable audit integrity | ⚠ in-proc lock only | REM-025 (WP3) |
| Tenant isolation | ⚠ id only | REM-026 (WP4) |
| HA / SIEM / supply chain | ⚠ partial | REM-027/028/029 |
| Independent validation | ⚠ intent-gating | REM-030, REM-021 |

**Bottom line for the accountable owner:** the intellectual core (deterministic
governance, the envelope contract, claim discipline) is in place and is the
hard part to get right. The enterprise programme is predominantly *platform and
assurance engineering* — mandatory enforcement placement, durable audit,
tenancy, resilience, supply chain — distributed across the four team types
above, sequenced through transition architectures T1→T3, and held together by
the Architecture Contract and automated fitness functions.
