# BindingPolicy and the v2 strict contract (CR-006)

Status: implemented 2026-10-07. Finding: RMR-CR-006
([security review](../assurance/reviews/2026-10-07-272b6c56/README.md)).
Matrix: [`binding_policy_matrix_v1.yaml`](../assurance/binding_policy_matrix_v1.yaml).

## Problem

Most lease bindings were configuration-conditional. The lease signed a task
identity, a capability digest, a resolved effect or a surface, but whether
anything compared them depended on separate flags, resolvers and observers.
Their absence was logged, not refused. Under a strict profile a lease carrying
a resolved-effect hash executed with no resolver bound, and the surface
binding was inert on the API path. A deployment could believe it had a binding
it did not have.

## Decision

A strict deployment states what must be bound, in one file, and starts only
when it can compare it.

### Three states, nothing implicit

Every binding in the matrix is stated as one of:

| State | Meaning | Where allowed |
|---|---|---|
| `REQUIRED` | Compared at dispatch, before the nonce is spent. Its comparator must exist at startup. | Every binding |
| `NOT_APPLICABLE` | The binding has no meaning for this tool. | Per tool, for `resolved_effect` only, and only when the signed ToolSpec declares a read-only action |
| `UNVERIFIABLE` | The deployment cannot verify it. Recorded at startup as a declared gap. | Non-core bindings only: `task_identity`, `capability_set` (not with MEDIATED tools, see below) |

A missing binding, or any other value, refuses startup. A missing resolver is
never `NOT_APPLICABLE`: a consequential tool must have a real resolver, and
the read-only test is the decision engine's fail-closed one (unknown or
unrecognised action types never qualify).

### Versioned strict contracts

The strict profiles are semantically versioned, because a contract version can
make a configuration that started before refuse to start:

- `review/v1`, `controlled_pilot/v1`: the strict profile as of v0.12.0.
  Selectable only explicitly, and recorded as `runtime_profile.legacy_contract`.
- `review/v2`, `controlled_pilot/v2`: v1 plus a mandatory BindingPolicy
  (`REMORA_BINDING_POLICY`). A bare `review` or `controlled_pilot` means v2.

The accepted contract, the policy digest and the declared `UNVERIFIABLE`
bindings are recorded as `binding_policy.accepted`.

### Startup, not first request

A strict profile now refuses at API import (`servers/api.py`), not on the first
metadata lookup. Startup checks each REQUIRED binding's comparator:
`REMORA_CAPABILITY_POLICY_FILE` for `capability_set`,
`REMORA_EFFECT_REGISTRY_MODULE` for `resolved_effect`, and the signed bundle
for `runtime_surface`.

### Dispatch

`GovernedToolDispatcher.bind_binding_policy` turns each REQUIRED binding into
a comparison in the existing pre-consumption refusal chain:

| Binding | Refusal |
|---|---|
| `actor` | `actor_unbound` |
| `task_identity` | `task_identity_required` |
| `capability_set` | `capability_set_required` |
| `resolved_effect` | `resolved_effect_unverifiable` (no resolver), `resolved_effect_unbound` (no resolved effect in the lease) |
| `runtime_surface` | `surface_unobservable`, `surface_unbound`, `surface_changed` |
| `effect_mediation` | see [Effect mediation](#effect-mediation-cr-005) |

`exact_call`, `tenant` and `audience` were already always compared on the API
path and stay so.

## Effect mediation (CR-005)

`effect_mediation` is a core binding, so under v2 it is always REQUIRED.
It means a privileged tool reaches effects only through the mediator, and
its signed spec says so. ToolSpec schema version 3
([`tool_spec_v3.yaml`](../../schemas/tool_spec_v3.yaml)) adds two signed
fields: `effect_mode` (`MEDIATED` or `NONE`) and
`credential_policy.direct_effect_credentials` (`FORBIDDEN` or `PERMITTED`).
The rules are in `remora/execution/effect_policy.py`:

| Condition | Refusal |
|---|---|
| `effect_mode` absent | `effect_mode_missing` |
| `MEDIATED` without downstream capabilities | `effect_capabilities_missing` |
| `MEDIATED` registered with `mediated=False` | `effect_mediation_not_registered` |
| `NONE` with downstream capabilities | `effect_none_declares_capabilities` |
| `NONE` for a tool that is not signed read-only | `effect_none_for_consequential_tool` |
| `NONE` registered mediated | `effect_none_registered_mediated` |
| `direct_effect_credentials` other than `FORBIDDEN` | `direct_effect_credentials_not_forbidden` |
| no effect-policy check bound to the dispatcher | `effect_policy_unverifiable` |

An absent mode is unknown, never `NONE`, and an empty ceiling is not read as
`NONE` either. `NONE` is a signed claim, not proof that the code has no hidden
effect, which is why it is accepted only for read-only tools.

The rules run three times. Startup checks every signed spec, refuses an
executor that has no separate effect domain (`REMORA_EFFECT_ENDPOINT`), and
refuses `capability_set: UNVERIFIABLE` when any tool is MEDIATED, because a
mediated effect's authority derives from the capability set. Registration
checks each registered tool against its spec, and the executor builds its
dispatcher at API import so a bad registry refuses to start. Dispatch checks
again, before the nonce is spent.

`remora init-review` writes three domains: the authority, an executor that
runs tool code and holds no effect credential, and an effect domain that holds
the credential and runs the primitives (`register_effect_executors`).

What this establishes: the declared mediation is enforced at the dispatcher.
What it does not: that the deployment's effect credentials are unreachable
from tool code by some other route (a mounted secret, a metadata endpoint, a
shared host). That stays NOT_ESTABLISHED; the custody split only checks the
environment variables the deployment names.

## Not changed

- research, development and the v1 contract keep the configuration-conditional
  behaviour;
- the lease format, every dispatcher property and the reference runtime;
- `EnforcementGate.enforce()` is deprecated, not removed: it checks a token
  without its authorization context, has no production caller, and a test
  refuses new ones.

## Not established

A BindingPolicy declares and enforces what this deployment compares. It does
not establish that the comparators are correct (that is their own tests), and
it does not reach tools outside the governed dispatcher:
`runtime_capability_surface_completeness` stays NOT_ESTABLISHED.
