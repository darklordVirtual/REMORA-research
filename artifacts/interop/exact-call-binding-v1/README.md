# REMORA exact-call-binding fixture contract v1

Lifecycle: recorded in the contract entry in
[`artifacts/interop/index.json`](../index.json) and repeated in
`manifest.json`. The package files, this README included, carry no state
label, so freezing the package does not change its bytes. This package is
REMORA's side of edge E-ECB in the Federation manifest
(`artifacts/interop/FEDERATION.yaml`). It is not an external verification
record and raises no REMORA capability.

## Purpose

Let a verifier maintained by another project reproduce fifteen bounded outcomes about an authorization and the calls presented against it, from pinned bytes, without importing REMORA code.

## Claims and result vocabulary

- `exact_call_binding`: ESTABLISHED means only that, under this fixture contract, an authorization dispatches exactly the call it was issued for: a change in tool, argument content, argument type, array order, tenant, target or principal is refused, and object member order is not a change.
- `single_use_authorization`: ESTABLISHED means only that, under this fixture contract, one authorization dispatches at most once and a refused mismatch does not spend it.

Results use `ESTABLISHED`, `CONTRADICTED` and `NOT_ESTABLISHED` only. A case
whose expected claim result is `NOT_ESTABLISHED` still has an expected
outcome: the evidence in that case cannot support the claim, and a verifier
that reaches a different outcome reports `CONTRADICTED` for it.

## Claim ceiling

This package does **not** establish:

- correct semantic intent of the authorized call;
- that an external effect occurred;
- that every path to the tool passes through the enforcement point;
- a prescribed hash algorithm or wire format for the binding;
- production deployment safety;
- Federation endorsement;
- a second implementation is by itself an independent verification record;

## What REMORA runs

`ExecutionLease` binds (tool, canonical arguments, tenant, target, principal) into a signed, single-use lease; `GovernedToolDispatcher` recomputes the binding immediately before execution and burns the nonce on dispatch. `remora/interop/boundary_fixtures.py` runs every case through those two classes.

That run is an L0 self-test under `interop-result-v1`. Its record lives under
`artifacts/interop/runs/` and advances nothing. exact-call binding and single-use consumption are also the scope of the mutation-testing baseline over the grant and lease code (`docs/assurance/mutation_testing_v1.md`); that baseline is author evidence and does not advance this contract.

## Files

- `fixtures.json`: 15 machine-readable cases with expected outcomes and claim results.
- `reference_verifier.py`: author implementation of the contract. It imports no REMORA code.
- `manifest.json`: source revision, SHA-256 of every package file, `package_digest` and the independence boundary.
- `claim-packet.json`, `verifier-request.json`: the producer claims and the request to external verifiers; both are package files and are pinned by the manifest.

Run the author reference implementation with:

```bash
python artifacts/interop/exact-call-binding-v1/reference_verifier.py
```

A successful run must report an empty `failures` list.

## Assumptions

- an authorization with integrity `intact` is authentic under the implementation's own signing scheme.
- `unsigned` and `tampered` describe an authorization the implementation cannot verify; the expected outcome is a refusal and the claim result is NOT_ESTABLISHED.
- canonical content follows the fixture's `canonical_form` note; the algorithm that compares it is the implementation's.

## Independence

Running `reference_verifier.py` is a reproduction, not independent
verification, and a second implementation on its own is implementation
diversity. A run record states the independence level separately
(`interop-result-v1`, `L0_SELF_TEST` to `L4_INDEPENDENT_HOST_RUN`). Only
`L3_INDEPENDENT_RECOMPUTATION` or higher, covering every claim, moves the
contract to `EXTERNALLY_VERIFIED`; the conditions are in
[`docs/interop/FEDERATION.md`](../../../docs/interop/FEDERATION.md).
