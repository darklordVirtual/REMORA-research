# Capability-Minimized Verified Execution v1

Status: implemented 2026-09-28 as quality program WS8 (Q8.1 to Q8.9; see the
resolution notes in docs/design/remora-quality-program-v1.md and RES-020). Source: an
owner-supplied software design document ("Capability-Minimized Verified
Execution for REMORA"). This document maps that proposal onto the code that
exists, records where REMORA deviates from it, and fixes what "done" means
for each part.

## The gap, stated exactly

REMORA enforces authority after the agent has proposed an action. It does not
reduce what the agent can propose in the first place. Checked against master
at `3e48d24`:

| Concern | Today | Gap |
|---|---|---|
| Which tools a principal may use for a task | RBAC decides which API actions a role may call (`servers/api.py`); ToolSpecs declare per-tool scope | No tool allowlist keyed by principal, task, tenant and environment |
| Which tools the agent sees | Whole tool sets switched on or off per deployment (MCP gateway, `deploy/gateway/registry.py`) | No per-principal or per-task filtering; `SurfaceRuntime` offers every registered tool |
| Tool outside the allowed set | `tool_not_in_available_set` exists, but on the execution API the set is the whole registry, the check yields VERIFY, and it is skipped without a semantic bundle | Not a refusal, and not scoped |
| Nested tool calls | The A2A delegation chain attenuates scope, on the interop path only | No confused-deputy check when a tool calls another |
| Revocation | Principals (approvers) and signing keys | No epoch that invalidates a capability set issued earlier |

What already exists, and is reused rather than rebuilt:

| SDD section | Existing mechanism |
|---|---|
| §14 one-time execution lease | `ExecutionLease`: single-use nonce, expiry, signed binding of tool, full arguments, tenant, target, policy bundle, ToolSpec, task, resolved effect, plan and surface |
| §15 fresh policy check | the execution re-gate in `execute_approved_item`, and the policy bundle hash compared at dispatch |
| §13 attenuation | `DelegationLink` scope narrowing in `a2a_envelope.py` |
| §22 role separation | RBAC roles and the authority/executor custody split (`custody.py`) |
| §23 effect verification | `EffectStatus`, `PostconditionContract`, effect receipts |
| §19 evidence export | `GET /proposals/{id}/evidence` with its hashed manifest and evidence coverage (Q7.3) |

## Deviations from the proposal

1. **No second lease class.** The SDD defines an `ExecutionLease` model. REMORA
   has one, and every guarantee in SDD §14 already holds for it except the
   capability digest. The digest is added to the existing lease, signed only
   when set, so leases issued before WS8 still verify.
2. **Refusal reasons are lower-case codes.** REMORA's refusal codes are
   `snake_case` strings (`task_mismatch`, `stale_plan`). The SDD's
   `CAPABILITY_NOT_ALLOWED` becomes `capability_not_allowed`, and so on.
3. **"REFUSED" is a dispatch outcome, not a decision.** The engine decides
   ACCEPT, VERIFY, ABSTAIN or ESCALATE. A capability violation at assessment
   is ABSTAIN with a capability reason; at dispatch it is a named refusal.
4. **The research questions about model behaviour need a live model.** RQ1
   to RQ3 ask whether exposure changes what a model proposes. The benchmark
   in this program measures enforcement outcomes on a fixed proposal corpus.
   The model-behaviour arms wait for the live-run budget (owner decision 2).

## Requirements

Each requirement is a quality program item (WS8) with a gate.

| ID | Requirement | Acceptance criterion |
|---|---|---|
| Q8.1 | A capability set is derived from trusted state, never from the agent. | `EffectiveCapabilitySet` has a canonical digest over principal, tenant, environment, task, allowed tools, policy and registry versions, epochs and expiry. `CapabilityResolver` computes the intersection of the requested, principal, task, tenant, environment and ToolSpec sets, and denies by default. |
| Q8.2 | A tool outside the set cannot run. | The lease carries the capability digest. The dispatcher refuses a tool outside the set, an expired set, and a tenant or environment mismatch. `/assess` returns ABSTAIN for a tool outside the set when the call carries one. The assessed record carries the capability block. |
| Q8.3 | The agent sees only the tools in its set. | A projector turns a set into an OpenAI tool list, an MCP `tools/list` result and a filtered runtime surface. The execution API serves the projection. The capability exposure ratio (exposed over registered) is reported. |
| Q8.4 | An allowed tool cannot exceed its argument scope. | Level 2 (allowed fields) and level 3 (constraints against trusted state) refuse out-of-scope arguments. A constraint never reads the agent's own assertion. |
| Q8.5 | A tool cannot hand its caller more authority than it had. | A delegated capability is a subset of its parent's, purpose-bound, short-lived and non-transitive unless policy says otherwise. A nested call outside the delegation refuses. |
| Q8.6 | A capability set can be revoked. | Principal, tenant, policy and ToolSpec epochs are part of the set. A set whose epoch is behind the current one refuses as `capability_stale`, and an explicitly revoked set as `capability_revoked`. |
| Q8.7 | Success is established, not reported. | The evidence export carries the capability decision. A coverage contract `success_established_v1` requires the capability decision, the authorization, the execution and a verified effect. |
| Q8.8 | The layers are measured separately. | A pre-registered deterministic benchmark compares full exposure, a name allowlist, task-scoped projection, projection with semantic authorization, with a lease, and with effect verification. It reports the metrics in SDD §28 on a fixed proposal corpus that includes injected instructions. |
| Q8.9 | The work is traceable. | A research-control entry, shelf status, capability register entries, related work and resolution notes. |

## What this does not establish

Capability minimization reduces what an agent can reach. An agent's
reasoning can still be wrong inside that set, and an injected instruction can
still use a tool the task legitimately needs. That residual is what semantic
authorization, the lease and effect verification remain for. Nothing here is
production evidence: every capability in the register keeps its current
status until a deployment runs it.
