# REMORA exact-call-binding fixture contract v1.1

Lifecycle: recorded in the contract entry in
[`artifacts/interop/index.json`](../index.json) and repeated in
`manifest.json`. The package files, this README included, carry no state
label, so freezing the package does not change its bytes. This package is
REMORA's side of edge E-ECB-V1-1 in the Federation manifest
(`artifacts/interop/FEDERATION.yaml`). It is not an external verification
record and raises no REMORA capability.

## Why there is a v1.1

[`exact-call-binding-v1`](../exact-call-binding-v1/README.md) is frozen and
has an external second-implementation run recorded against its digest, so its
bytes do not change. The pre-Federation probes of 2026-10-06
(`tests/test_pre_federation_fixture_adequacy_adversarial.py`) found two
things v1 does not cover:

- v1 says scalar types are significant but tests that only with the string
  `"0"` against the integer `0`. A verifier whose JSON parser maps every
  number to one double passes v1 while being unable to tell `1` from `1.0`.
- v1 does not name the temporal boundary. Its cases are static values, so a
  verifier can be green on every case while a live dispatcher executes a call
  that was changed after its binding was checked.

v1.1 carries every v1 case unchanged and seven new ones marked
`"added_in": "v1.1"`. Three set an integer against an integral float, in
both directions and one level down. One is a positive control: an unchanged
float still dispatches. The rest set `true` against `1`, add an argument
whose value is `null`, and change an integer beyond 2^53 that a binary double
cannot tell apart from its neighbour. They were
written with the gap known, so they are repair cases, not independent
evidence. v1 stays published with its records; its blind spots are a
preserved negative result.

## Purpose

Let a verifier maintained by another project reproduce twenty-two bounded outcomes about an authorization and the calls presented against it, from pinned bytes, without importing REMORA code.

## Claims and result vocabulary

- `exact_call_binding`: ESTABLISHED means only that, under this fixture contract, an authorization dispatches exactly the call it was issued for: a change in tool, argument content, argument type (including integer to float, bool to integer and absent to null), array order, tenant, target or principal is refused, and object member order is not a change.
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
- that a call object mutated after the binding check is refused (see the temporal boundary below);
- a prescribed hash algorithm or wire format for the binding;
- production deployment safety;
- Federation endorsement;
- a second implementation is by itself an independent verification record;

## Temporal boundary

Every case is a static value: the call presented is fixed when the case is
written. Verify-then-mutate (TOCTOU) is outside what this corpus can test. In
that attack the caller keeps a reference to a mutable argument object, lets
the binding check pass, and changes the object before the tool reads it. A
post-verification mutation of a mutable argument has no representation in a
JSON fixture, so a green run here says nothing about it.

REMORA tests that boundary separately, against its own dispatcher, in
`tests/test_pre_federation_toctou_adversarial.py`:
`GovernedToolDispatcher.dispatch` executes a private copy of the arguments
and re-checks the argument hash before it spends the nonce. That test is
author evidence about REMORA, not part of this contract. A verifier that wants
to attack the temporal boundary needs a harness that drives a live
dispatcher, not this fixture file.

## What REMORA runs

`ExecutionLease` binds (tool, canonical arguments, tenant, target, principal) into a signed, single-use lease; `GovernedToolDispatcher` recomputes the binding immediately before execution and burns the nonce on dispatch. `remora/interop/boundary_fixtures.py` runs every case through those two classes.

That run is an L0 self-test under `interop-result-v1`. Its record lives under
`artifacts/interop/runs/` and advances nothing.

## Files

- `fixtures.json`: 22 machine-readable cases with expected outcomes and claim results.
- `reference_verifier.py`: author implementation of the contract. It imports no REMORA code.
- `manifest.json`: source revision, SHA-256 of every package file, `package_digest` and the independence boundary.
- `claim-packet.json`, `verifier-request.json`: the producer claims and the request to external verifiers; both are package files and are pinned by the manifest.

Run the author reference implementation with:

```bash
python artifacts/interop/exact-call-binding-v1.1/reference_verifier.py
```

A successful run must report an empty `failures` list.

## Assumptions

- an authorization with integrity `intact` is authentic under the implementation's own signing scheme.
- `unsigned` and `tampered` describe an authorization the implementation cannot verify; the expected outcome is a refusal and the claim result is NOT_ESTABLISHED.
- canonical content follows the fixture's `canonical_form` note; the algorithm that compares it is the implementation's.
- JSON numbers are compared as written: an integer and a float with the same value are different scalars, and integers are exact.

## Independence

Running `reference_verifier.py` is a reproduction, not independent
verification, and a second implementation on its own is implementation
diversity. A run record states the independence level separately
(`interop-result-v1`, `L0_SELF_TEST` to `L4_INDEPENDENT_HOST_RUN`). Only
`L3_INDEPENDENT_RECOMPUTATION` or higher, covering every claim, moves the
contract to `EXTERNALLY_VERIFIED`; the conditions are in
[`docs/interop/FEDERATION.md`](../../../docs/interop/FEDERATION.md).
