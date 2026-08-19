# Multi-tenant security model

Defines the tenant boundaries REMORA enforces today, the mechanisms that
carry them, and the adversarial tests that pin each one. Where a boundary is
not yet enforced or not yet tested, this document says so explicitly — the
threat table below is the burn-down list, not a claim of completeness.

Current deployment reality: the recommended Shadow Pilot deployment is
**customer-hosted, one deployment per customer** (see
`../commercial/DEPLOYMENT_OPTIONS.md`), so the strongest isolation available
today is deployment-level. The in-deployment `tenant_id` scoping below is the
foundation for future shared-infrastructure operation, and is enforced and
tested now so it does not have to be retrofitted.

## Tenant identity

- The tenant is resolved server-side from the authenticated bearer principal
  (`servers/api.py::_authenticate`); it is never taken from the request body.
- Every audit-chain entry binds the tenant it was written under; the chain is
  keyed and verified per tenant (`remora/governance/tenant_chain.py`).
- Review queues, idempotency, outbox intents, grants and leases all carry
  `tenant_id` in their identity/binding.

## Isolation domains

| Domain | Mechanism | Status |
|---|---|---|
| Data (audit chain) | per-tenant hash chain, `UNIQUE (tenant_id, sequence_no)` fork guard | enforced + tested |
| Review state | per-tenant queue + `global_state` row per tenant (`remora/persistence/execution_state.py`) | enforced + tested |
| Policy | policy bundle hash bound into every lease and approval | enforced + tested |
| ToolSpec | signed bundle, hash bound at assess and re-checked at execute/approval consumption | enforced + tested |
| Credentials | dispatcher-held callables only; callers and tenants never hold downstream credentials | enforced by construction |
| Evidence | per-tenant chain + export endpoints scoped by authenticated tenant | enforced + tested |
| Audit visibility | RBAC capability per tenant (`read`/`review`/`assess`/`execute`) | enforced + tested |
| Rate limits | edge concern (agent-control / Cloudflare ingress) | deferred — Phase 5 scope |
| Billing | usage events schema planned (Analytics Engine) | deferred — Phase 5 scope |
| Admin / support / break-glass | no shared-operator surface exists in the customer-hosted model; any future hosted operation requires an explicit access-and-audit design **before** launch | deferred, blocking for hosted operation |

## Threat model

| Threat | Mechanism | Test evidence |
|---|---|---|
| Cross-tenant IDOR on proposals/lifecycle/evidence reads | reads are scoped by the authenticated tenant; foreign ids resolve 404 | `tests/test_lifecycle_read_apis.py`, `tests/test_execution_api.py` |
| Wrong-tenant approval | approval bound to tenant; grant and consumption refuse on `TENANT_MISMATCH` | `tests/test_agent_control_approvals.py` (grant + consumption), review-path tests |
| Shared credential leakage | dispatcher holds callables/credentials; request payloads can never register or replace them | `tests/test_execution_lease.py`, dispatcher registration contract |
| Policy substitution | `policy_bundle_hash` bound into lease and approval; mismatch refuses | `tests/test_execution_lease.py`, `tests/test_agent_control_approvals.py` |
| ToolSpec substitution | toolspec hash recorded at assess, read back from the chain (never from the request), compared at execute | `tests/test_toolspec_binding_chain.py`, `tests/test_authorization_extraction.py` |
| Cross-tenant nonce/grant replay | one-time jti ledger + lease nonce, tenant in the binding; audience-scoped tokens | `tests/test_gate_replay_properties.py`, `tests/test_token_hardening.py` |
| RBAC bleed between tenants | per-tenant capability check on every route | `tests/test_rbac_isolation.py` |
| R2 prefix escape | R2 evidence keying (`/{tenant_id}/...`) is the Phase 5 design; worker-side R2 use today is single-tenant | **untested — deferred with Phase 5** |
| D1 query missing tenant filter | agent-control D1 queries carry `tenant_id`; no automated linter yet | partially tested (envelope list/verify by tenant); **query-shape guard is open** |
| Cache key tenant omission | no security-relevant KV/cache state on the authoritative path (ADR: security state never in eventual-consistent cache) | by-construction; re-verify at Phase 5 |
| Operator support privilege | not applicable in customer-hosted model; blocking design item for hosted | open |

## Rules for new code

1. Every new persistent table or key namespace carries `tenant_id` from day
   one, even while deployments are single-tenant.
2. Reads resolve foreign-tenant identifiers as *not found*, never as
   *forbidden* — existence itself is tenant-scoped information.
3. No security-relevant state in eventual-consistent caches
   (ADR-single-authoritative-execution-path).
4. A new cross-tenant surface lands together with its adversarial test, in
   the table above.
