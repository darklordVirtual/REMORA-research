# REMORA effect-evidence fixture contract v2

Lifecycle: recorded in the contract entry in
[`artifacts/interop/index.json`](../index.json) and repeated in
`manifest.json`. The package files, this README included, carry no state
label, so freezing the package does not change its bytes. This package is
REMORA's side of edge E-EE-V2 in the Federation manifest
(`artifacts/interop/FEDERATION.yaml`). It is not an external verification
record and raises no REMORA capability.

## Why there is a v2

Probity's `invocation_axes` corpus (`probityai/agent-evidence-vectors` at
`d2bdacc7`, issue #918) handed 22 execution bundles to the frozen
[`effect-evidence-v1`](../effect-evidence-v1/README.md) reference verifier.
On three it returned `EFFECT_VERIFIED` where Probity's reader did not:
`bundle_for_other_call`, `dispatched_after_deny` and
`observation_from_the_tool`. Each turns on a fact the v1 input has no field
for. [`effect-evidence-v1.1`](../effect-evidence-v1.1/README.md) repaired
other comparison faults and not these. Both keep their bytes and their
records; the split is a preserved negative result.

v2 adds the three facts as inputs and makes `EFFECT_VERIFIED` depend on them:

| Fact | Field | What it must show |
|---|---|---|
| the call the bundle is bound to | `invocation`, `bundle_call` | the bundle names the invocation, compared as exact strings |
| the decision captured for the invocation | `decision` | a dispatchable verdict, approved where it must be, bound to the invocation |
| who observed | `observer`, `executor` | a read-only reader in another control domain that neither proposed nor executed the call |

The comparison of the declared delta is v1.1's, unchanged, hash preimage
included. Every v1.1 case is carried with a bound lineage and an independent
observer and keeps its expected effect status and state. Twenty-two cases are
new and marked `"added_in": "v2"`. They were written with the gap known, so
they are repair cases, not independent evidence.

## Claims and result vocabulary

- `effect_state_distinction`: as in v1.1.
- `effect_call_binding`: a bundle bound to another call is not evidence about the invocation, and the state for the invocation is `NOT_DISPATCHED`.
- `effect_decision_correspondence`: a dispatch that no captured decision allowed attests to no effect. A deny or abstain, a verdict outside `accept`, `verify` and `escalate`, a missing decision, a `verify` or `escalate` without a boolean approval, and a decision bound to another call are each refused by name.
- `effect_observer_independence`: only an observer derived independent raises the state to `EFFECT_VERIFIED`. A source label is never read.

Results use `ESTABLISHED`, `CONTRADICTED` and `NOT_ESTABLISHED` only. Each
case expects four values: `lineage_status`, `effect_status`, `vantage` and
`highest_established_state`. `effect_status` reports the comparison itself,
so a matching read by the tool is `EFFECT_VERIFIED` there while the state
stays at `EXECUTION_REPORTED_SUCCESS`. `EFFECT_MISMATCH` falls back to
`DISPATCHED` from any vantage, since a contradicted report is not supported
whoever contradicts it. The exact rules are under `rules` in `fixtures.json`.

## Claim ceiling

This package does **not** establish:

- that the capture is authentic or complete;
- that the declared control domains and credentials are true of a deployment;
- that no effect outside the declared delta occurred;
- causation of an observed effect;
- production deployment safety;
- Federation endorsement;
- a second implementation is by itself an independent verification record;

## What REMORA runs

`remora/interop/boundary_fixtures.py` turns each case into the audit trail a
deployment would hold. The decision becomes the assessment, its approval an
`approved` event, its call the `execution_authorized` record, and the
invocation's dispatch the `execution_result`. It hands that trail and the
bundle's call to `verify_receipt`. The refusal reason that comes back is the
case's `lineage_status`; the names in the fixture are REMORA's own. The
vantage is built as `record_signed_effect_receipt` builds it, as an
`ObservationVantage` whose independence is derived. An observer that is an
executor is refused there (`verifier_is_executor`), which the fixture names
`not_independent`. The comparison is `verify_declared_delta`, as in v1.1.

That run is an L0 self-test under `interop-result-v1`. Its record lives under
`artifacts/interop/runs/` and advances nothing.

## Files

- `fixtures.json`: 54 machine-readable cases with expected outcomes and claim results, the lineage, vantage and state rules, and v1.1's `hash_preimage` definition.
- `reference_verifier.py`: author implementation of the contract. It imports no REMORA code.
- `manifest.json`: source revision, SHA-256 of every package file, `package_digest` and the independence boundary.
- `claim-packet.json`, `verifier-request.json`: the producer claims and the request to external verifiers; both are package files and are pinned by the manifest.

Run the author reference implementation with:

```bash
python artifacts/interop/effect-evidence-v2/reference_verifier.py
```

A successful run must report an empty `failures` list.

## Mapping a Probity invocation_axes bundle

The reproduction job (`.github/workflows/probity-invocation-axes-reproduction.yml`)
also pairs Probity's bundles with this verifier. The mapping is the job's
assumption, not a fact either project established:

- `invocation` is Probity's `invocation_binding`, `bundle_call` the bundle's
  `call_binding`, and `observed` the observation's `fields`;
- the decision is the capture's `decision.json`, with `allow` read as
  `accept`, and its `request_binding` as the call;
- `observation.source` `independent_reader` becomes a read-only observer in a
  control domain other than the executor's, and any other source becomes the
  executor reading its own result.

The last point takes Probity's label as the configuration a deployment would
hold. It does not show that any reader was independent.

## Assumptions

- `observed: null` means the reader returned nothing, not that the object is absent.
- an absent field and a field whose value is `null` are different observations.
- a comparison rule outside the vocabulary, or for an undeclared field, rejects the contract instead of being evaluated.
- a success report for a refused dispatch is not attributed to the action.
- the lineage is checked before the comparison, decision first, then the bundle's call.
- independence is derived from `observer` and `executor`; nothing a reader says about itself is read.

## Independence

Running `reference_verifier.py` is a reproduction, not independent
verification, and a second implementation on its own is implementation
diversity. A run record states the independence level separately
(`interop-result-v1`, `L0_SELF_TEST` to `L4_INDEPENDENT_HOST_RUN`). Only
`L3_INDEPENDENT_RECOMPUTATION` or higher, covering every claim, moves the
contract to `EXTERNALLY_VERIFIED`; the conditions are in
[`docs/interop/FEDERATION.md`](../../../docs/interop/FEDERATION.md).
