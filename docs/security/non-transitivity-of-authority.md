# Non-Transitivity of Authority (NTA-1, NTA-2)

**Status:** NTA-1 implemented and tested at the enforcement point (library and
dispatcher level). NTA-2 phase 1 implemented as a library in the research
profile, not wired into dispatch. Author-run conformance only, no external
replication.
**Canonical for:** the principle, its three forms, where it is enforced, and
what it does not cover. Earlier documents describe parts of it under other
names; the [terminology](#terminology) section maps them here.

## The principle

```text
NTA-1: Non-Transitivity of Authority

Authorization of capability A does not imply authorization of any
capability B reachable through A.

If A invokes, delegates to, wraps, routes to, or otherwise causes B to
execute, B MUST be independently authorized under the applicable
principal, task, target, arguments, policy and runtime context.

Authority may be attenuated through delegation. It MUST NOT widen
implicitly through composition.
```

## Threat model

A tool the agent may call often needs other tools to do its work. A report
generator reads a database and sends an email. If the inner call runs under the
wrapper's own authority, or under a credential the wrapper holds, the agent
reaches `email.send` through a tool it was allowed, with a scope nobody granted
for that purpose. That is the confused deputy: the wrapper is the deputy, and
the authority it lends is its own, not the caller's.

The same failure appears in tool runtimes generally, in one recognisable
shape:

```text
wrapper W            allowed for the caller
capability B         refused when the caller asks for it directly
W internally runs B  executed, because only W was checked
```

A policy that evaluates only the outermost call cannot see B. NTA-1 requires
that B is evaluated as B, for the principal on whose behalf it runs.

## Three forms

NTA-1 has three forms. They fail independently, so each has its own
enforcement and its own conformance vectors.

### 1. Reachability

```text
ALLOW(A)  and  A can reach B    does not imply    ALLOW(B)
```

An authority issued for one call cannot be spent on another. In REMORA every
`ExecutionLease` is bound to one tool name and one canonical argument hash; the
dispatcher recomputes both and refuses a mismatch (`tool_name_mismatch`,
`tool_args_hash_mismatch`). Independently of the lease, the dispatcher checks
the call against the principal's capability set, so a capability outside that
set refuses even with a lease issued for it (`capability_not_allowed`).

### 2. Argument authority

```text
ALLOW(B)    does not imply    ALLOW(B, arguments = X)
```

A capability set carries per-tool constraints: which argument fields may appear
and which conditions their values must meet. They are evaluated at dispatch
time against the arguments actually presented (`capability_argument_mismatch`).
A delegated set inherits its parent's constraints and can only add to them; a
field list offered by the delegator is intersected with the parent's, never
unioned.

### 3. Delegation transitivity

```text
A delegates to B    does not imply    B may delegate to C
```

A delegated set cannot be delegated again unless the link that created it
opted in (`transitive=True`), and that link's parent must itself permit it.
Even an unbroken chain of opt-ins stops at `MAX_DELEGATION_DEPTH` (3 hops).
Every link is a subset of its parent, is bound to one delegatee and one stated
purpose, cannot outlive its parent, and lives at most
`MAX_DELEGATION_TTL_SECONDS` (300 s). Revoking any ancestor revokes every set
derived from it.

## NTA-2: implementation reachability

```text
ALLOW(tool A)  and  A's implementation can reach effect B    does not imply    ALLOW(B)
```

NTA-1 governs calls that are REMORA capabilities. NTA-2 extends the principle
to what a tool's own code can reach: a filesystem, a database client, an HTTP
client, a secret store. The design is
[Authority-Preserving Capability Mediation v1](../design/authority-preserving-capability-mediation-v1.md).
Phase 1 is a library in the research profile:

| Property | Implementation |
|---|---|
| A tool's effects have a declared ceiling, which is a limit and not a grant | `DownstreamCeiling` in `remora/enforcement/effect_capability.py` |
| Effect authority exists only for a tool the caller's set authorizes, while that set is valid | `derive_effect_authority()` in the same module |
| Policy can narrow the ceiling, never widen it | `policy_allows` in `derive_effect_authority()` |
| A resource is compared in one canonical form; ambiguous forms are refused | `remora/capabilities/resource.py` |
| Resource patterns are Q8.4 constraints, bound into the authority's digest | the `within` operator in `remora/capabilities/constraints.py` |
| The authority context comes from enforcement, not from the tool | `ExecutionContext` in `remora/enforcement/execution_context.py` |
| Every effect request is checked, fails closed and is recorded | `CapabilityMediator` in `remora/enforcement/capability_mediator.py` |
| Revoking the caller's set revokes the tool's effect authority | the parent set is an ancestor of the effect authority |

Phase 1 demonstrates the authority semantics. It does not stop code that
ignores the mediator and uses a client directly. Stopping that needs the strict
profile's separation of effect credentials from tool workers (phase 3). Until
then, limitation 1 below applies to NTA-2 in full.

## Security invariant

For every call that reaches a governed tool through REMORA's enforcement point,
the first condition always holds, and the rest hold whenever the lease carries
a capability digest or the dispatcher is built with
`require_capability_set=True`:

1. the presented lease names exactly this tool and these arguments;
2. the tool is in the presenting principal's capability set, and that set is
   bound to the presenting actor;
3. the arguments satisfy the set's constraints for that tool;
4. if the set was delegated, it is a subset of every ancestor, within depth
   and lifetime, and neither it nor any ancestor has been revoked.

A call that fails any of these does not run. The lease and capability checks
run before the lease's nonce is consumed, so a refused call leaves its nonce
unspent. Revocation is read from the epoch source the deployment binds
(`bind_capability_epochs`); with none bound, no revocation is checked.

## Where it is enforced

| Property | Implementation |
|---|---|
| A lease authorizes one tool and one argument set | `ExecutionLease.verify` in `remora/enforcement/lease.py` (`tool_name_mismatch`, `tool_args_hash_mismatch`) |
| The capability set is checked at the PEP, independently of the lease | `GovernedToolDispatcher.dispatch` with `capability_set=` in `remora/enforcement/lease.py` |
| Argument scope is enforced at dispatch time | `EffectiveCapabilitySet.check_arguments` in `remora/capabilities/model.py`, constraints in `remora/capabilities/constraints.py` |
| Authority cannot widen by delegation | `delegate()` in `remora/capabilities/delegation.py` (child tools must be a subset of the parent's) |
| Constraints only narrow | `_narrowed()` in `remora/capabilities/delegation.py` |
| Delegation is non-transitive by default | `transitive=False` default in `delegate()` |
| Delegation depth and lifetime are bounded | `MAX_DELEGATION_DEPTH`, `MAX_DELEGATION_TTL_SECONDS` in `remora/capabilities/delegation.py` |
| A derived set is bound to its delegatee | `principal_id` of the child set, checked at dispatch (`capability_principal_mismatch`) |
| The chain cannot be rewritten | `parent_digest` and `ancestor_ids` enter the child's digest (`remora/capabilities/model.py`) |
| Revoking a parent revokes its descendants | `revocation_refusal()` walks `ancestor_ids` in `remora/capabilities/revocation.py` |

## Evidence

### Conformance vectors

[`conformance/non-transitivity-of-authority-v1/`](../../conformance/non-transitivity-of-authority-v1/)
states the principle as 24 implementation-agnostic vectors over a fixed world
(one principal, a wrapper `report.generate`, a downstream `email.send`, and the
wrapper's declared effect ceiling). A second system can run them by writing one
adapter.

| Vector | Form | Expectation |
|---|---|---|
| NTA-01 | reachability | a lease for the wrapper does not dispatch the downstream tool |
| NTA-02 | reachability | a wrapper cannot obtain by delegation a tool its caller lacks (the confused deputy) |
| NTA-03 | reachability | a tool outside the principal's set refuses even with a lease issued for it |
| NTA-04 | argument | an authorized downstream tool with out-of-scope arguments refuses |
| NTA-05 | argument | a lease for B(X) does not dispatch B(Y) |
| NTA-06 | argument | a delegation can narrow fields but never add one |
| NTA-07 | delegation | a delegated set cannot be delegated again by default |
| NTA-08 | delegation | re-delegation works only where the link opted in |
| NTA-09 | delegation | a re-delegation cannot add a tool the link above lacked |
| NTA-10 | delegation | depth is bounded even when every link opts in |
| NTA-11 | delegation | a derived set is bound to its delegatee |
| NTA-12 | delegation | revoking the parent revokes the child |
| NTA-13 | baseline | an explicitly delegated, in-scope downstream call executes |
| NTA2-01 | implementation | an effect outside the tool's declared ceiling is refused |
| NTA2-02 | implementation | a declared effect on a resource outside its patterns is refused |
| NTA2-03 | implementation | path traversal out of an authorized subtree is refused |
| NTA2-04 | implementation | a switched provider is a different resource and is refused |
| NTA2-05 | implementation | an effect with no resolved resource is refused |
| NTA2-06 | implementation | effect authority cannot be delegated on |
| NTA2-07 | implementation | a tool outside the caller's set yields no effect authority |
| NTA2-08 | implementation | an execution that has ended mediates nothing |
| NTA2-09 | implementation | revoking the caller's set revokes the tool's effect authority |
| NTA2-10 | implementation | deployment policy can narrow the ceiling but not widen it |
| NTA2-11 | baseline | a declared effect on an authorized resource executes |

```bash
python conformance/non-transitivity-of-authority-v1/run_conformance.py --adapter remora
```

The committed `run-record.json` is an author run with all 24 vectors matching.
`tests/test_conformance_non_transitivity.py` runs the suite in CI and also
checks that it can fail. A permissive adapter diverges on every refusal vector.
Weakening one guard at a time (depth cap, default transitivity, argument
constraints, ancestor revocation, resource patterns, traversal refusal, the
unresolved-resource check, closing an execution, policy narrowing) diverges on
exactly the vectors that name it.

### Unit and property tests

`tests/capabilities/test_capability_delegation.py` covers subset, narrowing,
lifetime, transitivity, the chained digest, a property test over two-link
chains, and the nested call enforced at `GovernedToolDispatcher`.
`tests/test_lease_verification_completeness.py` and
`tests/test_dispatcher_contract.py` cover the lease binding to tool and
arguments.

### Layer study

The pre-registered capability-minimization study
(`experiments/capability_minimization/PREREGISTERED.md`,
`results/capability_minimization_study_v1.json`) includes a `confused_deputy`
class: a read-only task whose report tool attempts `email.send`. Arms A to C
(full exposure, name allowlist, task-scoped projection) let all 4 proposals
through (0/4 stopped); arm D, which adds constraints and delegation, stops 4/4.
The corpus and labels are author-written and measure which REMORA layer stops
the class, not how often the pattern occurs in real systems.

## Known limitations

1. The enforcement boundary is REMORA's PEP. NTA-1 holds for calls that are
   dispatched through `GovernedToolDispatcher`. A wrapper that reaches B inside
   its own process, through a library call, a subprocess, or a network request
   made with a credential it holds, is invisible to REMORA. The principle is
   only as strong as the guarantee that downstream capabilities are reachable
   solely through the PEP, which is credential custody, not policy (REM-024;
   `docs/assurance/credential_topology.yaml`). NTA-2 is the design that narrows
   this limit; its phase 1 mediator is in-process and does not narrow it yet.
2. The capability layer is opt-in. Without a capability policy, forms 2
   and 3 are not in force: a lease issued without a capability set is checked
   for tool and argument binding only (form 1). A deployment that relies on
   NTA-1 sets a capability policy and builds its dispatcher with
   `require_capability_set=True`; the CAP-023 caveat says no deployment is
   claimed to run one yet.
3. Delegation is a library and dispatcher mechanism. No `/v1/execution/*`
   route derives a delegation on a wrapper's behalf. A wrapper that makes a
   nested call must call `delegate()` and dispatch the nested call under its
   own lease bound to the child set.
4. Transitive delegation exists by opt-in. It is bounded by depth,
   lifetime and subset rules, but a policy that opts in widens who may act,
   never what may be done.
5. Reachability through data is out of scope. If A writes state that B
   later reads under its own, separately granted authority, each call is
   authorized on its own terms. Multi-step and data-flow analysis is the open
   gap G-2 in `docs/14-remora-prime-architecture.md`.
6. The evidence is author-run. 24 conformance vectors and 4 study
   proposals, all written by the authors. No external implementation has run
   the suite and no external replication exists.

## Terminology

The same principle appears under earlier names. They all refer to NTA-1.

| Where | Earlier wording | Form |
|---|---|---|
| `docs/design/capability-minimized-execution-v1.md`, Q8.5 | "A tool cannot hand its caller more authority than it had." | delegation, reachability |
| `remora/capabilities/delegation.py` | "Delegation never widens authority" | delegation |
| `remora/capabilities/delegation.py` | "non-transitive by default" | delegation |
| `tests/capabilities/test_capability_delegation.py`, `experiments/capability_minimization_study.py` | "confused deputy" | reachability |
| Q8.4 in the same design document | argument constraints at dispatch | argument |

Capability register: CAP-023 (capability minimization). Research control
matrix: RES-020.
