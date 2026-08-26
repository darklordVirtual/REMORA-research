# ADR: Single authoritative execution path

- Status: **accepted** (2026-08-19)
- Deciders: repository owner
- Related: `docs/product/product_truth_contract.yaml`,
  `docs/deployment/execution-quickstart.md`, `workers/agent-control/README.md`

## Context

REMORA has one canonical governed execution path; the `/v1/execution/*`
kernel (`servers/`, `remora/enforcement/`, `remora/governance/`):

```
Agent
→ Cloudflare ingress
→ canonical REMORA execution service
→ policy / review / grant / PEP / lease / outbox
→ dispatcher
→ tool adapter
```

Historically the Cloudflare `agent-control` worker was a second, independent
authorization/execution engine: its `runTool()` executed tools after its own
approval logic, with no REMORA decision, grant, PEP check or lease. Two
parallel engines mean a reviewer cannot answer "where is execution actually
enforced?" and a config or transport shortcut in one engine silently bypasses
the guarantees of the other.

## Decision

1. There is exactly one authoritative execution path: the canonical
   REMORA execution service. Every component that can reach a
   customer-impacting (write-effect) tool callable must obtain authorization
   from that path; a valid decision, execution grant, PEP check, exact-call
   lease and durable dispatch intent.
2. **`agent-control` is edge ingress, not an engine.** Its responsibilities
   are limited to: edge ingress, identity (workload bearer / Cloudflare
   Access reviewer), tenant resolution, rate limiting, request normalization
   and service routing. It must not provide an alternative execution path
   around canonical REMORA governance.
3. **Structural floor until the adapter lands** (see Migration): any
   write-effect tool in `agent-control` is *unconditionally* approval-gated
   by a hardcoded `WRITE_IMPACT_TOOLS` set in code. Deployment configuration
   (`APPROVAL_REQUIRED_TOOLS`) can only add gated tools, never remove one;
   an emptied or misconfigured variable can no longer turn a write tool into
   an ungoverned call. Approvals themselves are first-class, single-use,
   expiring records granted only by an authenticated independent human
   reviewer (Phase 1).
4. **Backward compatibility by adapter, not by parallel engine.** The legacy
   `/execute` endpoint is retained, but its write path is being converted
   into an adapter that internally invokes the canonical REMORA execution
   service (service binding to the execution API deployment). Until that
   binding exists in a deployment, write tools remain restricted to the
   structural floor in (3); read-only lookups (verification, law search) are
   not customer-impacting and stay on the thin proxy path.

## Consequences

- The product truth contract classifies `agent-control` as `legacy`; it is
  re-classified `optional` (ingress adapter) only when `runTool()` write
  dispatch goes through the canonical service.
- The acceptance property is testable and tested: no registered write-effect
  tool callable is reachable without a consumed approval bound to the exact
  call (`tests/test_agent_control_single_path.py` executes the real worker
  modules), and the gating cannot be disabled by configuration.
- New tools added to the worker catalog must declare read/write impact; a
  write tool missing from `WRITE_IMPACT_TOOLS` fails the structural test.

## Migration steps

1. Phase 1 (done): independent human approvals; no self-approval.
2. This ADR (Phase 2 slice 1): structural write floor; config can only widen.
3. Phase 2 slice 2 (implemented 2026-08-19, activation per deployment):
   `src/execution_adapter.ts` + the optional `EXECUTION_SERVICE` binding.
   When bound with `EXECUTION_API_TOKEN`, write-effect tools run the
   canonical assess, grant, PEP, lease path and never execute in-worker;
   verify/escalate surfaces the canonical review item, and no failure shape
   falls back to local execution
   (`tests/test_agent_control_canonical_adapter.py`). Unbound deployments
   keep the structural floor from step 2. The worker is re-classified from
   `legacy` in the product truth contract only when a deployment actually
   binds the service.
4. Phase 4/5: durable dispatch intent and outbox move behind the same
   service; the worker never holds the only record of a pending effect.
