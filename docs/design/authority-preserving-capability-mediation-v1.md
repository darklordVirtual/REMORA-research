# Authority-Preserving Capability Mediation v1

**Status:** proposed design. Phase 1 (library, research profile) is
implemented; phases 2 and 3 are not. See [Delivery status](#delivery-status).
**Scope:** governed execution, nested capabilities, privileged resources,
internal dispatch and effect authority.
**Principle:** NTA-2 in
[Non-Transitivity of Authority](../security/non-transitivity-of-authority.md).

> Authorization does not propagate implicitly through implementation reachability.

A tool may be authorized to execute without being authorized to exercise every
capability its implementation can technically reach. This document defines how
REMORA preserves that property at runtime.

## 1. The gap

`ExecutionLease` and `GovernedToolDispatcher` bind an accepted action to a
concrete call: principal, tenant, target environment, exact tool name, full
argument hash, policy identity, ToolSpec identity, task identity, capability
set digest, resolved effect, runtime identity, plan binding, expiry and single
use. Q8.5 delegation covers nested calls that are themselves REMORA
capabilities: "a tool cannot hand its caller more authority than it had".

A governed tool's implementation can still reach a privileged resource through
its own code without any nested REMORA invocation: filesystem access, database
clients, HTTP clients, cloud SDKs, authenticated connection pools, message
queues, secret stores, subprocesses and operating-system services. REMORA may
authorize `report.generate` while the implementation performs
`filesystem.read` and `network.http.post`, and neither crosses an authority
boundary.

`docs/assurance/credential_topology.yaml` already records the limit. L3:
reachability through an already authenticated client object, connection pool
or subprocess is invisible to a static import scan, and delegation within the
execution domain "remains possible and is not claimed against". L5: tool
callables close over the credentials they use. `ResolvedEffect` (Q7.4) binds a
tool to the effect it is declared to resolve to; it does not establish that the
implementation performs no other privileged effect.

## 2. Security property

NTA-1 (implemented): authorization of capability A does not authorize a
capability B that A can invoke.

NTA-2 (this design): authorization of tool A does not authorize privileged
effect B merely because A's implementation can technically perform B. A
privileged effect needs its own authority basis.

## 3. Load-bearing invariant

For every privileged operation B that originates during execution of an
authorized tool A, the authority for B is either established independently or
derived by explicit attenuation from authority A already holds, and the child
authority is a subset of the parent's. It is never created from caller
assertions, implementation assumptions, ambient credentials, implicit defaults,
provider or adapter selection, connection state, or hidden runtime
configuration. No implementation detail may widen authority.

## 4. Effect capabilities

An `EffectCapability` is a primitive ability to act on an effect-bearing
resource, distinct from an agent-facing tool. Initial classes:
`filesystem.read`, `filesystem.write`, `network.http.get`, `network.http.post`,
`network.http.put`, `network.http.patch`, `network.http.delete`,
`database.read`, `database.write`, `database.delete`, `secret.read`,
`process.execute`, `queue.publish`, `cloud.invoke`. The list is extensible.

A capability names its resource precisely enough for policy to mean something,
for example `filesystem.read` on `workspace://reports/september.pdf`, or
`network.http.post` on `https://billing.example/api/invoice`.

## 5. Authority source

A tool never creates authority for its own downstream effects. The effective
downstream authority for one execution of tool A is:

```text
A authorized by the caller's capability set          (parent authority)
  ∩ A's declared downstream ceiling (signed ToolSpec)
  ∩ task, tenant and environment policy
  ∩ the deployment capability registry
```

Anything outside the intersection is denied. A library, SDK or credential that
makes an effect technically possible creates no authority for it.

Decision (2026-09-29): the ToolSpec declaration is the ceiling for effect
capabilities. The caller's set grants the tool, not its effects, so the effect
authority is the ceiling issued under the parent set's identity, and policy can
remove capabilities from it but never add one. See
[Decisions](#decisions-2026-09-29).

## 6. ToolSpec extension

ToolSpec gains an optional downstream declaration:

```yaml
tool: report.generate
downstream_capabilities:
  - capability: database.read
    resources: ["database://reporting-eu/*"]
    purpose: generate_report
  - capability: filesystem.read
    resources: ["workspace://templates/*"]
    purpose: render_report
```

The declaration is a ceiling, not a grant. It cannot raise what deployment
policy allows: a declared `filesystem.read` that task policy removes stays
unavailable.

## 7. Mediation boundary

Privileged effects during a governed execution go through one surface,
`CapabilityMediator`, which receives the requested primitive and resource and
takes everything else from the active execution context:

```python
mediator.invoke("filesystem.read", "workspace://reports/september.pdf", {...})
```

The tool supplies no principal, tenant, task identity, policy identity, parent
capability set or authority provenance. Code the caller controls must not be
able to manufacture or replace the authority context.

## 8. Reuse of existing authority

No parallel authorization system. The design reuses `EffectiveCapabilitySet`,
Q8.4 argument constraints, Q8.5 delegation, capability epochs, task identity,
ToolSpec, policy and runtime identity, effect resolution and execution
evidence. A child effect authority cannot contain a capability outside its
ceiling, cannot widen resource or argument constraints, cannot outlive its
parent, keeps tenant, environment, task and policy version, keeps its ancestry,
and is non-transitive.

## 9. No security-relevant defaults after authorization

A value that changes what an effect is allowed to be (provider, adapter,
database, HTTP verb, target environment, credential identity, resource
namespace, region, account, tenant) is materialized before authorization, or
triggers a new authority check after resolution and before execution. An
omitted resource that the runtime would fill in later is refused
(`capability_default_unresolved`).

## 10. Caller-controlled dispatch

A caller-controlled value that selects which privileged implementation runs
(database type, provider, protocol, HTTP method, backend, adapter, region,
account, resource type) is part of the authority decision. If `A(input=x)`
resolves to privileged operation B, B is checked after resolution; A being
authorized is not enough. In this design the provider, account or region is the
authority part of the resource identity, so a switched provider is a different
resource and is checked as one.

## 11. Ambient authority and profiles

Research profile: the mediator runs in the tool's own process. It demonstrates
the authority semantics and records what was requested; direct library access
remains possible, and no bypass-resistance claim is made.

Strict profile: privileged effects run in a credential-holding component
separate from the tool worker. The worker holds no downstream effect credential
and cannot mint authority; it receives a narrow capability client. The
credential-holding component verifies the parent execution identity, derives or
verifies the downstream authority, checks resource and argument constraints,
executes the primitive, records the result and returns only what the caller
needs. This extends the existing authority/executor custody split
(`remora/enforcement/custody.py`) to internal effects.

## 12. Execution context

The enforcement layer creates an immutable context before invoking the
deployment-owned callable: `execution_id`, `proposal_id`, `tenant_id`,
`principal_id`, `target_environment`, `context_id`, `task_id`, `tool_name`,
`toolspec_hash`, `policy_bundle_hash`, `capability_digest`,
`runtime_identity_hash`, `parent_lease_digest`. It never comes from agent input.
Under a strict profile, a privileged request with no valid active context is
refused.

## 13. Nested effect resolution

Each mediated effect resolves on its own. `report.generate` producing
`database.read` on `reporting://monthly/2026-09` and `filesystem.read` on
`workspace://templates/report.html` is recorded as those two effects under the
parent execution, not collapsed into one generic `report.generate` effect.

## 14. ResolvedEffectGraph

`ResolvedEffect` stays the record of one effect. A bounded aggregate records an
execution with nested effects:

```python
@dataclass(frozen=True)
class ResolvedEffectGraph:
    root: ResolvedEffect
    children: tuple[ResolvedEffectNode, ...]
```

Each node records capability, operation, canonical resource, implementation,
parent effect, authority digest, arguments hash and result state. An unbounded
or cyclic graph is refused, or truncated with an explicit evidence state.

## 15. Effect evidence

A parent is not reported as fully established while a required privileged
child has unknown state. Nested outcomes: `REFUSED`, `EXECUTED`, `FAILED`,
`UNKNOWN`, `VERIFIED`, `MISMATCH`, `UNVERIFIABLE`. A parent postcondition may
still establish success independently; missing evidence never silently becomes
successful evidence.

## 16. Direct-access detection

A repository gate reports governed tool implementations that import or call
known privileged interfaces directly (`socket`, `subprocess`, `os.system`,
`urllib`, `requests`, `httpx`, database drivers, cloud SDKs, secret stores,
filesystem primitives) outside approved mediator implementations. It is
evidence of conformance, not proof of absence: dynamic loading, native
extensions and opaque clients remain limits.

## 17. Deployment enforcement

Strict deployments add controls outside Python where practical: effect
credentials absent from tool workers and present only in the capability
executor, filesystem mount restrictions, process isolation, network egress
restrictions, service identity and namespace separation. Library enforcement
does not establish deployment containment.

## 18. No generic bypass

There is no public equivalent of `skip_governance=True` for privileged
operations carrying caller-controlled data. An unavoidable internal bypass is
named, statically enumerable, unavailable to agent-controlled code, unable to
widen effect authority, covered by regression tests and listed in the trust-base
documentation.

## 19. Failure semantics

Failure is closed, and a mediator failure never falls back to direct resource
access. Refusal codes, reusing the existing `CapabilityRefusal` vocabulary
where it already has the meaning:

| Situation | Code |
|---|---|
| no active execution, or it has ended | `capability_context_missing` |
| capability outside the effect authority | `capability_not_allowed` |
| resource outside the capability's patterns, or ambiguous | `capability_resource_not_authorized` |
| arguments outside their constraints | `capability_argument_mismatch` |
| parent set stale or revoked | `capability_stale`, `capability_revoked` |
| delegation refused, including depth | `capability_delegation_denied` |
| no resolved resource | `capability_default_unresolved` |
| no executor for the capability | `capability_executor_unavailable` |
| effect authority from another execution | `capability_digest_mismatch` |

Proposed and not yet needed in phase 1: `capability_resolution_unknown`,
`capability_provider_not_authorized` (a provider switch is a resource refusal
here), `capability_cycle_detected`.

## 20. Conformance invariants

| Invariant | Statement | Phase 1 vector |
|---|---|---|
| NTA-2.1 wrapper | tool A authorized, capability B not: when A requests B, B does not execute | NTA2-01 |
| NTA-2.2 argument | B permitted, B(resource=X) not: A requesting B(X) is refused | NTA2-02, NTA2-03 |
| NTA-2.3 provider | a dynamically selected provider is checked as resolved | NTA2-04 |
| NTA-2.4 default | an omitted value never materializes into authority that would be refused if explicit | NTA2-05 |
| NTA-2.5 chain | A may delegate to B; B may not delegate to C unless a link permits it | NTA2-06 |
| NTA-2.6 ambient credential | in strict mode, execution inside A does not by itself yield credentials for B outside the mediator | phase 3 |

## 21. Regression cases

| Case | Setup | Expected | Phase 1 test |
|---|---|---|---|
| 1 confused deputy | `report.generate` authorized, `network.http.post` not; the implementation attempts a POST | refused, no request emitted | `test_case_1_...` |
| 2 resource widening | `filesystem.read workspace://reports/*`; request for `secrets://production/*` | `capability_resource_not_authorized` | `test_case_2_...` |
| 3 late-bound provider | `database.read` for one provider; input selects another | resolved provider checked and refused | `test_case_3_...` |
| 4 implicit target | no resource; runtime would pick a privileged default | `capability_default_unresolved` | `test_case_4_...` |
| 5 direct SDK bypass | tool uses a credential-bearing client directly | research: recorded, no containment claim; strict: no credential or network path | phase 3 |
| 6 valid attenuation | `filesystem.read workspace://reports/*`; request for `.../september.pdf` | executes and is recorded | `test_case_6_...` |
| 7 transitive widening | A delegates B; B attempts C without transitive authority | `capability_delegation_denied` | `test_effect_authority_cannot_be_delegated_on` |

Tests: `tests/capabilities/test_capability_mediation.py`.

## 22. Implementation layout

| Module | Phase |
|---|---|
| `remora/capabilities/resource.py` (canonical resources, patterns, `within`) | 1 |
| `remora/enforcement/effect_capability.py` (`EffectCapability`, `DownstreamCeiling`, `derive_effect_authority`) | 1 |
| `remora/enforcement/execution_context.py` | 1 |
| `remora/enforcement/capability_mediator.py` | 1 |
| `remora/enforcement/effect_graph.py`, `resolved_effect.py` extension | 2 |
| `remora/toolcall/toolspec.py` downstream declaration | 2 |
| `remora/enforcement/lease.py` context creation at dispatch | 2 |
| strict-profile capability executor and custody rule | 3 |

## 23. Tool API

```python
def generate_report(args, capabilities):
    rows = capabilities.invoke("database.read", "database://reporting-eu/monthly",
                               {"query": args["query"]})
    template = capabilities.invoke("filesystem.read", "workspace://templates/report.html")
    return render(rows.result, template.result)
```

Under strict mediation a tool receives no generic credential-bearing client.
The interface can be ergonomic; the authority model must not depend on
developer discipline.

## 24. Compatibility

Tools without a downstream declaration keep running under the research
profile. A strict profile requires an explicit declaration, and a v1 ToolSpec
without one is refused there. A migration period may record
`unmediated_effect_observed` without blocking. `ExecutionLease` keeps its
format.

## 25. Research experiment

A pre-registered deterministic experiment compares arm A (current execution
with Q8 capability minimization), arm B (A plus downstream declarations and the
mediator) and arm C (B plus split effect custody, with raw effect credentials
absent from tool workers). Classes: `confused_deputy`, `direct_sdk_access`,
`resource_widening`, `argument_widening`, `provider_switch`,
`implicit_default`, `transitive_delegation`, `stale_parent_authority`,
`legitimate_nested_effect`. Metrics: unauthorized effect rate, unauthorized
nested invocation block rate, legitimate nested false-block rate, mediated
effect coverage, ambient effect authority surface, unknown effect rate. The
experiment separates mechanism efficacy from real-world security rate, and a
zero failure count is not a universal safety claim.

## 26. Evidence artifact

`results/authority_preserving_capability_mediation_v1.json`: corpus, arms,
results by class, first layer stopping each class, false blocks, known limits,
generator and revision, reproduced by
`python experiments/authority_preserving_capability_mediation.py --check`.

## 27. Capability register

A register entry is not marked implemented because a library exists. It uses
the register's existing ladder (`IMPLEMENTED_LIBRARY`, `WIRED_REFERENCE_PATH`,
`WIRED_API_PATH`, `PERSISTED_ATOMIC`, `ENFORCED_PRODUCTION`,
`EXTERNALLY_VERIFIED`). Phase 1 is CAP-024 at `IMPLEMENTED_LIBRARY`. The runtime
property NTA-2 is a separate register entry under `unestablished_properties`
(`implementation_effect_non_transitivity`, `NOT_ESTABLISHED`), because a library
test does not establish a deployed property; it stays there until a strict
deployment provides evidence. A strict-profile rung, if one is wanted between
`WIRED_API_PATH` and `ENFORCED_PRODUCTION`, is added to the ladder together with
the evidence rule `scripts/check_capability_semantics.py` applies to it.

## 28. Relationship to existing mechanisms

Q7.4 `ResolvedEffect` answers what effect an authorized tool resolves to; this
design adds which privileged effects happen inside that execution. Q8.4
argument constraints apply to every mediated effect. Q8.5 delegation is the
authority foundation for nested effects. The outer `ExecutionLease` stays the
root of execution authority; nested authority is derived from it and never
invented. Credential topology L3 and L5 become explicit validation targets,
narrowed where a strict deployment provides evidence and never declared closed
because an in-process mediator exists.

## 29. Interpretation

Pure computation needs no mediation. Effects with independent security
consequences need independent authority. The boundary follows authority and
effect, not source-code structure.

## 30. Non-claims

This design does not establish that every privileged effect has been
identified; that static analysis proves the absence of bypasses; that a
compromised operating system respects process boundaries; that a malicious
capability executor constrains itself; that a deployment's network
segmentation is correct; that a provider performs only the effect REMORA
observes; that a signed ToolSpec is semantically correct; or that successful
mediation proves the business action was right.

## 31. Definition of done

1. `CapabilityMediator` exists and fails closed.
2. The authority context comes from enforcement, never caller input.
3. Filesystem, network and database primitives are represented.
4. ToolSpec can declare maximum downstream capabilities.
5. Child authority is derived through attenuation.
6. Resource and argument constraints apply to nested effects.
7. Security-relevant defaults are resolved before authority is exercised.
8. Dynamic provider or adapter selection is evaluated on the resolved capability.
9. Nested effects are part of execution evidence.
10. Strict mode separates effect credentials from tool workers.
11. Direct-access regression cases exist.
12. NTA-2 conformance tests pass.
13. The experiment is pre-registered before results are generated.
14. A committed reproducible artifact exists.
15. Credential topology limits are re-audited, not silently removed.
16. Capability and claim registers reflect the evidence actually held.

## 32. Core principle

> Technical reachability is not authority.

Every privileged effect inherits a valid, narrowed authority path that can be
inspected and verified independently.

## Decisions (2026-09-29)

1. The signed ToolSpec declaration is the ceiling for a tool's effect
   capabilities. The caller's capability set authorizes the tool; the effect
   authority is the ceiling issued under the parent set's identity (tenant,
   environment, task, policy version, epochs, ancestry), and deployment policy
   can only remove capabilities from it. A capability policy that grants effect
   capabilities per task was the alternative; it can be added later as a
   further intersection.
2. Resource identities are `<scheme>://<authority>/<path>`, and the authority
   part names the provider, account or region. A provider switch is therefore
   a resource refusal, not a separate mechanism.
3. Ambiguous resources are refused, not normalised: `.` and `..` segments,
   empty segments, percent-encoding, backslashes, whitespace, control
   characters, user information, queries and fragments. A normalising
   comparison would authorise `workspace://reports/../secrets/key` as
   `workspace://reports/secrets/key`; the conformance test for NTA2-03 shows
   exactly that.
4. Resource patterns are Q8.4 constraints (the `within` operator), so they are
   part of the effect authority's digest and cannot be changed after issue.
5. Existing refusal codes are reused where they already carry the meaning
   (section 19).

## Open questions

1. Who authenticates the tool worker to the capability executor in the strict
   profile. The executor holds no lease signing material (custody rule 3), so
   the channel needs an execution-scoped credential bound to the lease that
   expires with the execution and carries a per-execution budget. Otherwise a
   worker could keep requesting effects after its tool returned.
2. Research-profile honesty. `ExecutionContext` is immutable, but code in the
   same process can build another one, and `contextvars` can be set by any
   code in the process. Phase 1 makes no bypass claim and says so in the
   module docstrings.
3. The ToolSpec change alters the signed bundle hash. It needs a schema
   version, and section 24's rule (a v1 spec without a declaration is refused
   under a strict profile) has to be implemented with it.
4. Arm C of the experiment demonstrates containment only if the tool worker
   runs as a separate process without effect credentials in its environment.
   An in-process simulation of arm C is a simulation and is reported as one.
5. The nested-effect evidence (section 15) should extend the
   `success_established_v1` coverage contract (Q8.7) rather than define a
   second notion of success.
6. The direct-access gate (section 16) should extend
   `scripts/check_credential_topology.py` rather than add a second scanner.

## Delivery status

| Phase | Content | Status |
|---|---|---|
| 1 | resource identities and `within`; `DownstreamCeiling`; `derive_effect_authority`; `ExecutionContext`; `CapabilityMediator` (research profile, fails closed); NTA2-01 to NTA2-11 in `conformance/non-transitivity-of-authority-v1` | implemented, library only; not wired into dispatch |
| 2 | ToolSpec downstream declaration with schema version; context and mediator created by `GovernedToolDispatcher`; `ResolvedEffectGraph`; evidence contract | not started |
| 3 | strict profile: capability executor holding effect credentials, worker without them, custody rule and deployment checks; direct-access gate; pre-registered experiment and artifact | not started |
