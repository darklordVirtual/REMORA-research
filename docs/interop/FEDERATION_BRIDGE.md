# REMORA Federation Bridge and loss-aware interoperability

Status: implemented 2026-10-07 for `federation-port/v0` (Mode A, portable
verifier). Context: [aeoess/agent-governance-vocabulary#177](https://github.com/aeoess/agent-governance-vocabulary/issues/177).
There, [federation-port](https://github.com/aeoess/federation-port) was
published as a V0 prototype. The next test it named was an adapter written by
another project, for a check it already performs, without changing the core.

## The problem

REMORA's native claims bind more than some federation transports carry. Its
exact-call binding covers the tool, the full argument content with scalar
types and array order, the tenant, the target and the principal.
The V0 transport carries the action as JavaScript values, a caller-supplied
tenant label, an approval id and per-component evidence bytes. A REMORA check
reported through V0 as "exact-call binding" would claim more than V0 can
carry.

The bridge does not weaken REMORA to fit a transport, and it never reports a
transport-level result as the native one.

## Two planes

```text
REMORA native assurance plane         authorization, exact-call binding, fresh authority,
        |                             lease, lifecycle, effect verification
        v
REMORA Federation Bridge              native envelope, capability declaration,
        |                             claim projection, projection records
        v
transport adapter (federation-port/v0, or a later transport)
        v
admission -> executor -> dispatch outcome -> (optional) REMORA effect verifier
```

The transport consumes a projection of the native model. It does not define it.

## Projection: a claim only gets weaker

| Result | Meaning |
|---|---|
| `PRESERVED` | the transport carries every dimension the native claim needs |
| `NARROWED` | a useful subset survives, exported as a separate, narrower claim |
| `NOT_ESTABLISHED` | the transport carries too little to establish it |
| `UNSUPPORTED` | the transport lacks the lifecycle or interface |

These describe projection strength, not the result of a check. The mapping is
data: [`projection-map.yaml`](../../artifacts/interop/federation-port-v0/projection-map.yaml)
names each native claim's dimensions and the capabilities each needs, and
[`capabilities.yaml`](../../artifacts/interop/federation-port-v0/capabilities.yaml)
states what V0 carries. `remora/federation/projection.py` derives the result
from both and from the action's own losses. `ProjectionMap.assert_export`
refuses an adapter claim the projection does not permit.

### federation-port/v0

| Native claim | Projection | Exported claim |
|---|---|---|
| authorization integrity | PRESERVED | `remora.authorization_integrity` |
| `exact_call_binding-v1.1` | NARROWED | `remora.port_v0.bound_action` |
| `fresh_authority_at_dispatch` | NARROWED | `remora.authorization_unexpired` |
| principal binding | NOT_ESTABLISHED | none |
| authority/executor custody isolation | NOT_ESTABLISHED | none |
| effect verification | UNSUPPORTED | none |

`remora.port_v0.bound_action` covers the tool, the argument values,
structure and array order as JavaScript values, the tenant label, the approval
id and the submitted evidence. Under V0 it does not cover the scalar type (`1`
and `1.0`), an authenticated tenant, the principal or an independently
authenticated target.

## The native envelope and its evidence

`remora/federation/models.py` describes one authorization once, before any
transport sees it (`remora-federation-action-v1`). It keeps REMORA's canonical
argument bytes, their canonicalization (`remora-canonical-json-v1`), their
digest and a typed scalar listing, so int and float stay distinct natively. A
field the workflow does not have is `null` and listed in `unavailable`.

The adapter receives the canonical envelope bytes, with the transport's
projection inside, signed with Ed25519 in `REMORA/FEDERATION-ACTION/v1`
(`remora-federation-evidence-v1`). The bytes travel base64-encoded and are
verified as sent, so no language's JSON encoding decides what was signed.

An action V0 would change is refused, not narrowed: an integer beyond 2^53 - 1
loses digits in JavaScript, so its argument values do not survive.

## The adapter (Mode A)

[`integrations/federation-port/remora-adapter`](../../integrations/federation-port/remora-adapter/README.md)
is a federation-port/v0 `authority_evidence` component. It verifies the
signature against a public key the customer pins, compares the signed V0
projection with the action the runtime will dispatch, and reports the three
exported claims. It holds no secret, reaches no network and does not run
REMORA.

Its tests run it inside an unmodified federation-port runtime, checked out at
the revision pinned in [`fixtures.json`](../../artifacts/interop/federation-port-v0/fixtures.json)
with a check that nothing under its `src/` changed. CI runs them on every
change.

## Projection records

Every bridge result carries one `remora-federation-projection-v1` record per
native claim. It states the projection, what was preserved, what was not
established and the action's losses. It also carries the digests of the native
evidence, the transport evidence, the adapter, the map and the capability
declaration, with the REMORA and transport revisions.

## Lifecycle: an execution report is not an effect

`remora/federation/lifecycle.py` reads a transport outcome as an execution
report. `provider_confirmed` becomes `EXECUTION_REPORTED_SUCCESS` with the
effect `NOT_ESTABLISHED`. Only REMORA's effect verifier
(`remora.governance.effect_verification`), observing a system of record, can
establish `EFFECT_VERIFIED`; that stays a separate edge any transport can
compose with.

## Acceptance criteria

| | Criterion | Where |
|---|---|---|
| AC-01 | adapter runs against unmodified federation-port/v0 | adapter tests (revision and clean `src/` asserted) |
| AC-02 | valid supported actions are admitted | fixture `valid`, `provider_confirmed` |
| AC-03 | mutated tool, arguments, target, tenant, approval, operation or evidence refused | adapter tests, eight mutations |
| AC-04 | never full `exact_call_binding-v1.1` | manifest claims are a subset of the map's exports |
| AC-05 | `1` versus `1.0` is a stated loss, not a false pass | fixture `lossy_float`; Python projection tests |
| AC-06 | principal binding NOT_ESTABLISHED under V0 | fixture `other_principal`; projection records |
| AC-07 | expiry at admission is not full fresh authority | `remora.authorization_unexpired`; revocation not established |
| AC-08 | `provider_confirmed` never becomes `EFFECT_VERIFIED` | `tests/test_federation_bridge.py` |
| AC-09 | every result has projection records with digests | fixtures; adapter test AC-09 |
| AC-10 | the transport is replaceable without changing native primitives | `remora/federation/transports/`; nothing in `remora/enforcement` or `remora/execution` imports the bridge |
| AC-11 | a stronger transport preserves without changing the native claim | a capability declaration alone moves exact-call to PRESERVED |
| AC-12 | native, projected, runtime and effect layers stay distinct | projection records, lifecycle reading |

## What this does not establish

- Anything about a deployment: the fixtures use published test keys.
- Independence: REMORA wrote the adapter, the fixtures and the tests. The
  interoperability question on #177 is answered only by a run someone else
  reproduces.
- Isolation: federation-port/v0 runs adapters in its own process (its
  section 10), so custody isolation over V0 stays NOT_ESTABLISHED.
- Revocation, trusted time, ToolSpec freshness or signing-key status over V0.
