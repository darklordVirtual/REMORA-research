# Cloudflare state architecture (design)

Status: **design** (Phase 5 of the productization remediation). Nothing in
this document is implemented unless it cites code; it fixes the state
placement rules BEFORE more Cloudflare surface is built, so security state
never lands in the wrong primitive. Binding constraint from
[`ADR-single-authoritative-execution-path.md`](ADR-single-authoritative-execution-path.md):
security-relevant state never depends on eventual-consistent cache semantics.

## Placement rules

| Primitive | Use for | Never for |
|---|---|---|
| Durable Objects | strong serialization: nonce/approval consumption, idempotency, review lifecycle, outbox claim coordination, per-tenant sequence ownership, tenant degradation state | bulk storage, analytics |
| D1 | audit index, queryable lifecycle history, read models, billing references, config metadata | the *only* copy of a consumed-grant ledger (needs the DO's serialized write in front) |
| R2 | evidence/artifact blobs under `/{tenant_id}/evidence|effects|exports|attestations/...` | anything queried by content |
| KV | non-authoritative caches and display state only | ANY security state (eventual consistency = replayable grants) |
| Workflows | durable HITL lifecycle: proposal → policy → wait-for-review → expiry → re-gate → dispatch → effect verification | replacing the outbox semantics (UNKNOWN stays terminal, never auto-retried) |
| Analytics Engine | usage events (schema below) for reporting and eventual usage billing | audit (the immutable governance chain is the audit; analytics is lossy by design) |

## Durable Object coordinator

One coordinator instance keyed `tenant_id` (evaluate
`tenant_id + protected_execution_domain` if a single tenant's write volume
serializes too much; measure first). It owns exactly the operations whose
correctness requires strong serialization; everything else reads D1/R2.
Current status: the agent-control worker uses D1 `UNIQUE` constraints as the
fork guard (`workers/agent-control/schema.sql`); adequate at pilot volume;
the DO is the scale-out path, not a correctness fix.

## Tenant keying

Every D1 table and R2 key carries `tenant_id` from day one (rule 1 of
[`multi_tenant_security_model.md`](multi_tenant_security_model.md)). R2 key
structure is fixed as `/{tenant_id}/{evidence|effects|exports|attestations}/...`.
Database-per-enterprise-tenant vs row-level partitioning: start with strict
row-level partitioning (one schema, mandatory tenant column, adversarial
tests); move a tenant to a dedicated D1 database only when contractually
required; D1 has no cross-database queries, so per-tenant databases also
delete the class of missing-tenant-filter bugs at the cost of fleet
management. Decision deferred until a second enterprise tenant exists;
row-level is the default.

## Usage event schema (Analytics Engine)

Stable, additive-only:

```
tenant_id, proposal_id, decision, risk_tier, tool_id, latency_ms,
review_required, review_duration_ms, dispatch_outcome, effect_status,
policy_version, model_cost_estimate
```

`proposal_id` is the same FT-01 join key the audit chain and the
`X-Remora-Proposal-Id` header carry, so a usage row can always be traced
back to its governed record; but never the other way: analytics rows are
lossy and non-authoritative.

## Secrets custody

Downstream tool credentials move toward centralized custody (Workers
Secrets / Secrets Store), owned by the dispatcher; never by callers,
never per-agent. Required documentation per secret, kept with the
deployment config: who can read it, which tool may use it, which tenant
owns it, rotation process, revocation path, and what the audit records on
use. The worker already enforces the caller-never-holds-credentials rule
(`workers/agent-control`, `GovernedToolDispatcher` on the Python side);
this section fixes the operational metadata that has to exist before a
second tenant's credentials enter the system.

## Migration order

1. (done) Approval/no-self-approval state in D1 with UNIQUE fork guards.
2. Workflows prototype for the HITL lifecycle in shadow mode; must
   preserve outbox semantics exactly (UNKNOWN terminal, absorbing states).
3. DO coordinator for nonce/approval consumption when volume warrants.
4. Analytics Engine emission from the settle path.
5. R2 evidence store with the fixed key structure + prefix-escape tests
   (open item in the tenant model's threat table).
