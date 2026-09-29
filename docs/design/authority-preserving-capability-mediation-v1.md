# Authority-Preserving Capability Mediation v1

**Status:** proposed design. Phases 1 to 3 are implemented; the
pre-registered experiment of section 25 has not run yet. See
[Delivery status](#delivery-status).
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
concrete call. The binding covers principal, tenant, target environment, exact
tool name and full argument hash. It also covers policy, ToolSpec and task
identity, the capability set digest, the resolved effect, runtime identity,
plan binding, expiry and single use. Q8.5 delegation covers nested calls that are themselves REMORA
capabilities: "a tool cannot hand its caller more authority than it had".

A governed tool's implementation can still reach a privileged resource through
its own code without any nested REMORA invocation. Examples are filesystem
access, database and HTTP clients, cloud SDKs, authenticated connection pools,
message queues, secret stores, subprocesses and operating-system services. REMORA may
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

Take a privileged operation B that originates during execution of an
authorized tool A. The authority for B is either established independently or
derived by explicit attenuation from authority A already holds. A derived child
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

Some values change what an effect is allowed to be: provider, adapter,
database, HTTP verb, target environment, credential identity, resource
namespace, region, account and tenant. Such a value is materialized before
authorization, or it triggers a new authority check after resolution and before
execution. An
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

As implemented (phase 3), the three domains are separate processes, each
declared with `REMORA_EXECUTION_DOMAIN_ROLE`:

| Role | Holds | Serves |
|---|---|---|
| `authority` | lease signing material; no effect credential | assess, approve, execute; mints leases |
| `executor` | lease verification key; with `REMORA_EFFECT_ENDPOINT` set, no declared effect credential | `/v1/execution/dispatch-leased`; runs tool code; sends mediated effects to the effect domain |
| `effect` | lease verification key and the declared effect credentials | `/v1/execution/effects` and `/effects/close` only; runs the primitives, never tool code |

Under a strict profile the custody guard refuses any other combination (K12 to
K19). The effect domain trusts nothing the worker sends beyond the lease. It
verifies the lease with verification material only
(`ExecutionLease.verify_authenticity`). It refuses a lease the shared durable
nonce store says was never dispatched. It requires the lease-bound capability
set, and derives the effect authority from its own copy of the tool's signed
ceiling. The per-execution budget and closure are claimed in the same durable
store, so a restart neither reopens a closed execution nor resets its budget.
This answers open question 1: the execution-scoped credential is the lease
itself, bound to the dispatch the nonce store records, and the worker's
transport bearer (`REMORA_EFFECT_TOKEN`) authenticates the hop, not the
authority.

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
| more requests than the execution's budget | `capability_effect_budget_exhausted` |
| mediated tool with no lease-bound capability set (dispatcher) | `capability_set_required` |
| the tool's ceiling cannot be read (dispatcher) | `downstream_ceiling_unavailable` |
| strict profile, mediated tool, no declared ceiling (dispatcher) | `downstream_declaration_required` |
| the lease was never dispatched (effect domain) | `execution_not_started` |
| the dispatch or closure state cannot be read (effect domain) | `execution_state_unverifiable` |
| an effect request that cannot be parsed (effect domain) | `request_malformed` |

Proposed and not needed so far: `capability_resolution_unknown`,
`capability_provider_not_authorized` (a provider switch is a resource refusal
here), `capability_cycle_detected` (the graph is a flat, ordered list under one
parent, so it cannot cycle).

## 20. Conformance invariants

| Invariant | Statement | Phase 1 vector |
|---|---|---|
| NTA-2.1 wrapper | tool A authorized, capability B not: when A requests B, B does not execute | NTA2-01 |
| NTA-2.2 argument | B permitted, B(resource=X) not: A requesting B(X) is refused | NTA2-02, NTA2-03 |
| NTA-2.3 provider | a dynamically selected provider is checked as resolved | NTA2-04 |
| NTA-2.4 default | an omitted value never materializes into authority that would be refused if explicit | NTA2-05 |
| NTA-2.5 chain | A may delegate to B; B may not delegate to C unless a link permits it | NTA2-06 |
| NTA-2.6 ambient credential | in strict mode, execution inside A does not by itself yield credentials for B outside the mediator | custody K15 and K16 (`tests/conformance/test_custody_effect_domain.py`); measured by arm C of the experiment |

## 21. Regression cases

| Case | Setup | Expected | Phase 1 test |
|---|---|---|---|
| 1 confused deputy | `report.generate` authorized, `network.http.post` not; the implementation attempts a POST | refused, no request emitted | `test_case_1_...` |
| 2 resource widening | `filesystem.read workspace://reports/*`; request for `secrets://production/*` | `capability_resource_not_authorized` | `test_case_2_...` |
| 3 late-bound provider | `database.read` for one provider; input selects another | resolved provider checked and refused | `test_case_3_...` |
| 4 implicit target | no resource; runtime would pick a privileged default | `capability_default_unresolved` | `test_case_4_...` |
| 5 direct SDK bypass | tool uses a credential-bearing client directly | research: recorded, no containment claim; strict: no credential or network path | custody K15; the direct-access gate (section 16); experiment arm C |
| 6 valid attenuation | `filesystem.read workspace://reports/*`; request for `.../september.pdf` | executes and is recorded | `test_case_6_...` |
| 7 transitive widening | A delegates B; B attempts C without transitive authority | `capability_delegation_denied` | `test_effect_authority_cannot_be_delegated_on` |

Tests: `tests/capabilities/test_capability_mediation.py`.

## 22. Implementation layout

| Module | Phase |
|---|---|
| `remora/capabilities/resource.py` (canonical resources, patterns, `within`) | 1 |
| `remora/enforcement/effect_capability.py` (`derive_effect_authority`) | 1 |
| `remora/enforcement/execution_context.py` | 1 |
| `remora/enforcement/capability_mediator.py` | 1 (budget in 2) |
| `remora/capabilities/ceiling.py` (`EffectCapability`, `DownstreamCeiling`, shared by ToolSpec and enforcement) | 2 |
| `remora/toolcall/toolspec.py` downstream declaration, bundle schema version; `schemas/tool_spec_v2.yaml` | 2 |
| `remora/enforcement/lease.py` mediated registration, ceiling and executor binding, mediator per dispatch, `ExecutionLease.digest()` | 2 |
| `remora/enforcement/lease.py` `verify_authenticity`, `bind_effect_domain`, strict declaration rule | 3 |
| `remora/enforcement/effect_domain.py`, `remora/enforcement/effect_client.py` | 3 |
| `remora/enforcement/custody.py` effect role and three-domain rules; `remora/enforcement/nonce_store.py` `consumed()` | 3 |
| `servers/execution_api.py` effect role routing and `/effects` routes | 3 |
| `scripts/check_credential_topology.py` direct-access gate | 3 |
| `remora/enforcement/effect_graph.py` (`ResolvedEffectGraph`) | 2 |
| `remora/execution/dispatch.py`, `remora/execution/service.py` nested effects in `execution_result` and the outbox projection | 2 |
| `remora/governance/evidence_coverage.py` `success_established_v2` | 2 |
| `servers/execution_api.py` ceiling from the signed bundle, executors from the registry module | 2 |

## 23. Tool API

A tool opts in by registering as mediated, `register("report.generate",
generate_report, mediated=True)`, and is then called with the mediator as its
second argument:

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
profile. Under a strict profile a tool registered as mediated needs an
explicit declaration and is refused without one
(`downstream_declaration_required`); unmediated tools are unchanged. A migration period may record
`unmediated_effect_observed` without blocking. `ExecutionLease` keeps its
format.

## 25. Research experiment

A pre-registered deterministic experiment compares three arms. Arm A is the
current execution with Q8 capability minimization. Arm B adds downstream
declarations and the mediator. Arm C adds split effect custody, with raw effect
credentials absent from tool workers. Classes: `confused_deputy`, `direct_sdk_access`,
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

This design does not establish any of the following:

- that every privileged effect has been identified;
- that static analysis proves the absence of bypasses;
- that a compromised operating system respects process boundaries;
- that a malicious capability executor constrains itself;
- that a deployment's network segmentation is correct;
- that a provider performs only the effect REMORA observes;
- that a signed ToolSpec is semantically correct;
- that successful mediation proves the business action was right.

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

1. Resolved in phase 3 (section 11): the lease is the execution-scoped
   credential, checked against the durable nonce store, with budget and
   closure held there too.
2. Research-profile honesty. `ExecutionContext` is immutable, but code in the
   same process can build another one, and `contextvars` can be set by any
   code in the process. Phase 1 makes no bypass claim and says so in the
   module docstrings.
3. Resolved in phase 2 for the schema: `downstream_capabilities` is only
   accepted in a schema-version-2 bundle, the signed `schema_version` is now
   checked, and an absent declaration changes no existing spec hash. The
   strict-profile rule of section 24 followed in phase 3.
4. Arm C of the experiment demonstrates containment only if the tool worker
   runs as a separate process without effect credentials in its environment.
   An in-process simulation of arm C is a simulation and is reported as one.
5. Resolved in phase 2 as `success_established_v2`: v1's requirements, with
   the execution result also required to report its nested effects settled.
   A new version rather than a changed v1, so verdicts already given under v1
   do not change after the fact. The only state recorded so far is
   `REFUSED`, `EXECUTED` or `UNKNOWN`; `VERIFIED`, `MISMATCH` and
   `UNVERIFIABLE` need per-effect verification, which is not built.
6. Resolved in phase 3: the direct-access gate is part of
   `scripts/check_credential_topology.py`. It scans every module the
   discovery globs match and requires each privileged interface a governed
   tool reaches directly to be declared with a reason.

## Delivery status

| Phase | Content | Status |
|---|---|---|
| 1 | resource identities and `within`; `DownstreamCeiling`; `derive_effect_authority`; `ExecutionContext`; `CapabilityMediator` (research profile, fails closed); NTA2-01 to NTA2-11 in `conformance/non-transitivity-of-authority-v1` | implemented, library only; not wired into dispatch |
| 2 | ToolSpec v2 downstream declaration and schema-version check; `GovernedToolDispatcher` builds the context and mediator for tools registered as mediated, before the nonce is spent; per-execution effect budget; `ResolvedEffectGraph` in the dispatch result, the `execution_result` chain record and the outbox projection; `success_established_v2`; the execution API reads ceilings from the signed bundle and executors from the registry module | implemented, opt-in, research profile |
| 3 | three-domain custody split with an effect domain holding the credentials; `EffectDomain` and `RemoteEffectClient`; durable closure and budget; strict declaration rule; direct-access gate; experiment pre-registered in `experiments/authority_preserving_capability_mediation/PREREGISTERED.md` | implemented; the experiment has not run |
