# Nested Governance for Agentic AI

*(Some code examples below contain Norwegian legal text by design — the demonstration domain is Norwegian debt-collection law, `inkassoloven`.)*

## Purpose

REMORA treats long-running agentic AI as a nested control system. The system is
not governed by one generic "memory" concept. Each layer has:

- its own context flow,
- its own update frequency,
- its own trust boundary,
- its own audit requirement,
- and its own failure mode.

This is inspired by the Nested Learning view that complex AI systems can be
understood as multiple connected learning or optimization problems with
different information flows and update rates. In REMORA, the translation is
governance-oriented rather than model-training-oriented.

Primary attribution:

- Behrouz, Razaviyayn, Zhong, and Mirrokni, "Nested Learning: The Illusion of
  Deep Learning Architecture", PDF: https://abehrouz.github.io/files/NL.pdf.
- Google Research, "Introducing Nested Learning: A new ML paradigm for
  continual learning", November 7, 2025.

## Governance Layers

```text
User / Agent Request
   |
   v
L0 Runtime Context
   - prompt
   - current context
   - tool output

   |
   v
L1 Trust Evaluation
   - multi-oracle agreement
   - disagreement
   - entropy
   - phase

   |
   v
L2 Evidence Memory
   - retrieval
   - authoritative sources
   - source freshness

   |
   v
L3 Policy Memory
   - authority boundaries
   - allowed actions
   - escalation rules

   |
   v
L4 Audit Memory
   - immutable decision ledger
   - model outputs
   - scores
   - approvals

   |
   v
L5 Governance Learning
   - what failed
   - what should be adjusted
   - new tests or policies
```

## Memory And Update Frequencies

| Layer | Update frequency | Writable by agent | Retention | Risk |
|---|---|---:|---|---|
| Runtime context | per request | yes | short | low |
| Session memory | per session | yes | short | medium |
| Trust memory | per decision | no | medium | medium |
| Evidence memory | per retrieval | no | medium | medium |
| Project memory | reviewed change | no | long | high |
| Policy memory | reviewed change | no | long | high |
| Audit ledger | append only | no | permanent | critical |
| Architecture baseline | reviewed change | no | permanent | critical |

Canonical machine-readable profile: not yet published — the layer profile
lives in code (`remora/governance/nested_governance.py`); a committed YAML
profile is roadmap, not an existing artifact.

## Governance Forgetting

In agent systems, the risk is not only catastrophic forgetting of model
knowledge. A governed system can forget why a rule exists.

Examples:

- a temporary policy exception becomes normal behavior,
- an agent starts ignoring `ABSTAIN` or `ESCALATE`,
- previous failures stop influencing future decisions,
- policy overrides become routine,
- memory files store unsafe instructions,
- a convenience pattern becomes an authority boundary violation.

REMORA models this as **governance forgetting**.

Implemented component:

```text
remora/governance/nested_governance.py
  - NestedGovernanceModel
  - GovernanceLayer
  - GovernanceForgettingDetector
remora/governance/context_flow.py
  - ContextFlowRegistry
  - ContextFlowUpdate
remora/governance/memory_layers.py
  - MemoryPolicyRegistry
  - MemoryLayerUpdate
remora/governance/policy_proposals.py
  - PolicyProposalEngine
```

## Route Semantics

| Condition | Route |
|---|---|
| No layer violation | `ACCEPT` |
| Missing audit trace or reviewed-change approval | `VERIFY` |
| Agent writes to policy memory | `ESCALATE` |
| Mutation attempted on append-only audit ledger | `ESCALATE` |
| Unknown governance layer | `ABSTAIN` |
| Temporary exception became pattern | `VERIFY` |
| Ignored abstain/escalate plus unapproved override | `ESCALATE` |

## Non-Claims

This module does not claim:

- to train or modify foundation models,
- to prove continual learning,
- to solve catastrophic forgetting,
- or to validate drift prediction on live enterprise agents.

The current claim is structural and testable: REMORA can represent nested memory
layers, enforce update boundaries, and detect governance-forgetting patterns in
deterministic event streams.

## Access Control for RAG and Tool Calls

### Problem

In multi-user deployments, different principals have access to different
information. A query from an analyst should never surface documents classified
above their clearance, and a tool call from a tenant should never affect another
tenant's data. The LLM synthesis prompt must never receive document context the
user is not authorised to see — not even for the model to "summarise and
redact" — because the act of summarisation can leak structure and content.

### Two attack surfaces

| Surface | Attack | Mitigation |
|---------|--------|-----------|
| **RAG retrieval** | User crafts query that, by vector proximity, retrieves restricted documents | Pre-retrieval Vectorize filter (clearance + tenant) |
| **RAG synthesis** | Restricted chunk slips through retrieval filter; LLM synthesises it | Post-retrieval ACL group check in Worker before prompt build |
| **Tool calls** | Agent invokes tool outside role/clearance scope | Pre-execution role + clearance gate in CascadeEngine |
| **KV cache** | Cached response for user A served to user B | Cache key partitioned by clearance + groups + tenant |

### Data storage locations

| Data | Where stored | Access control applied |
|------|-------------|------------------------|
| Document vectors | Cloudflare Vectorize (`remora-knowledge`) | `clearance_level`, `tenant_id` metadata filter |
| Document metadata | Cloudflare D1 (`remora-rag-meta`) | Domain/source/title only; no clearance column yet (schema migration needed for full audit) |
| Query cache | Cloudflare KV (`REMORA_RAG_CACHE`) | Key includes `clearance:groups:tenant` partition |
| Identity/roles | JWT claims (Entra ID / Keycloak / custom OIDC) | Validated at Python layer before oracle is called |
| Tool call policy | `enterprise/policy_as_code_example.yaml` | Governed change — not writable by agent |
| Audit events | Append-only audit ledger | Immutable; retention permanent |

### Implementation — RAG (optional extension)

Access control is **opt-in**. Without `AccessContext`, the oracle behaves
exactly as before. With it, every query is automatically filtered.

```python
from remora.adapters.identity import AccessContext
from remora.adapters.identity.jwt import JWTAdapter
from remora.oracles.cloudflare_rag import CloudflareRAGOracle

# 1. Validate the incoming bearer token
adapter = JWTAdapter(secret_or_key=PUBLIC_KEY, algorithms=["RS256"])
identity = adapter.validate(request.headers["Authorization"].removeprefix("Bearer "))

# 2. Build an access context from the identity
ctx = AccessContext.from_identity(identity)
# ctx.clearance_level  ← from JWT claim "clearance"
# ctx.acl_groups       ← from Identity.roles
# ctx.tenant_id        ← from JWT claim "tid" (Entra ID) or "tenant_id"

# 3. Scope the oracle to this context — returns a NEW instance (thread-safe)
base_oracle  = CloudflareRAGOracle(domain="specialised")
user_oracle  = base_oracle.with_access(ctx)

# 4. Query — Vectorize filter and cache partition applied automatically
response = user_oracle.ask("What is the penalty under inkassoloven § 17?")
```

What happens internally:

```
user_oracle.ask(prompt)
  │
  ├── payload["access"] = {
  │     "clearance_levels": ["public", "internal"],   # cumulative
  │     "acl_groups":       ["legal", "finance"],
  │     "tenant_id":        "org_acme"
  │   }
  ├── payload["cache_partition"] = "internal:finance:legal:org_acme"
  │
  └── Worker /query
        ├── cache key = SHA-256(query + "::" + cache_partition)
        ├── Vectorize filter: clearance_level $in ["public","internal"]
        │                   + tenant_id $eq "org_acme"
        │                   + domain $eq "specialised"    (if set)
        ├── POST-retrieval: drop chunks where acl_groups ∩ user_groups = ∅
        └── LLM synthesis on filtered context only
```

### Ingest with access labels

```python
oracle.ingest(
    content="Inkassoloven § 17 fastsetter ...",
    source="Inkassoloven — LOV-1988-05-13-26",
    domain="dce",
    confidence_weight=2.0,
    clearance_level="internal",      # only visible to internal+ users
    acl_groups=["legal"],            # additionally restricted to legal group
    tenant_id="org_acme",            # only visible within org_acme
)
```

### Implementation — Tool Calls (optional extension)

Tool call access control is policy-as-code and enforced pre-execution.

```yaml
# enterprise/policy_as_code_example.yaml — extend with tool ACL
tool_access_rules:
  - tool: execute_sql
    minimum_clearance: internal
    allowed_roles: [db_operator, db_admin, sre]
  - tool: search_classified_documents
    minimum_clearance: restricted
    allowed_roles: [legal, compliance]
  - tool: send_external_notification
    minimum_clearance: public
    allowed_roles: [any]
    tenant_scoped: true              # call scoped to requester's tenant_id
```

The CascadeEngine checks `AccessContext.allows(tool.minimum_clearance)` and
`any(r in ctx.acl_groups for r in tool.allowed_roles)` before permitting
execution. Denied calls are routed `ESCALATE` and logged to the audit ledger.

### Clearance levels

```
public      ← all authenticated users
internal    ← employees / service accounts
restricted  ← approved personnel (sensitive business data)
secret      ← highest grade (legal, regulatory, classified)
```

Each level is cumulative: a `restricted` user sees `public` + `internal` +
`restricted` documents. Separate Vectorize indices (hard boundaries) are
recommended when information is legally classified (NSM, GDPR high-risk).

### Non-claims

- This implementation does not provide NSM-certified information classification.
- Separation relies on Vectorize metadata filter correctness; a Cloudflare
  platform bug could bypass the filter. Hard boundary (separate indices) is
  required for formally classified information.
- ACL group post-filter is best-effort for the array-JSON limitation in
  Vectorize metadata; the primary access gate is clearance_level + tenant_id.

---

## Source Boundary

Nested Learning motivates the context-flow, update-frequency, continuum-memory,
and reviewed self-modification vocabulary used here. REMORA does not implement
the paper's optimizer formulations, Hope architecture, or model-training
results. REMORA uses the concepts as a governance design pattern for deployed
agentic systems.
