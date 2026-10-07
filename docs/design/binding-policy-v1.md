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
| `UNVERIFIABLE` | The deployment cannot verify it. Recorded at startup as a declared gap. | Non-core bindings only: `task_identity`, `capability_set` |

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

`exact_call`, `tenant` and `audience` were already always compared on the API
path and stay so.

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
