# REMORA effect-evidence fixture contract v1.1

Lifecycle: recorded in the contract entry in
[`artifacts/interop/index.json`](../index.json) and repeated in
`manifest.json`. The package files, this README included, carry no state
label, so freezing the package does not change its bytes. This package is
REMORA's side of edge E-EE-V1-1 in the Federation manifest
(`artifacts/interop/FEDERATION.yaml`). It is not an external verification
record and raises no REMORA capability.

## Why there is a v1.1

[`effect-evidence-v1`](../effect-evidence-v1/README.md) is frozen and has an
external second-implementation run recorded against its digest, so its bytes
do not change. The pre-Federation probes of 2026-10-06
(`tests/test_pre_federation_fixture_adequacy_adversarial.py`) found that v1
could be passed by a verifier that shares REMORA's own former blind spots:

- its reference verifier read a missing field and an explicit `null` the
  same way, so `{"deleted_at": null}` verified against an object without
  `deleted_at`, and its corpus had no case that tells the two apart;
- a comparison rule outside the vocabulary (`excat`) fell back to `exact`,
  and a rule for a field the contract does not declare was ignored;
- `exact` compared containers with native equality, so `1` matched `1.0`
  and `{"archived": true}` matched `{"archived": 1}`.

REMORA's `verify_declared_delta` had the first two faults as well and was
fixed in the same change. v1.1 carries every v1 case unchanged and ten new
ones marked `"added_in": "v1.1"`. They were written with the faults known, so
they are repair cases, not independent evidence. v1 stays published with its
records; its blind spots are a preserved negative result.

## Purpose

Let a verifier maintained by another project reproduce twenty-two bounded outcomes about what an execution's evidence establishes, from pinned bytes, without importing REMORA code.

## Claims and result vocabulary

- `effect_state_distinction`: ESTABLISHED means only that, under this fixture contract, NOT_DISPATCHED, DISPATCHED, EXECUTION_REPORTED_SUCCESS and EFFECT_VERIFIED are kept apart, a reported success is never promoted to a verified effect without an observation of the declared delta, an absent field is not an explicit null, a postcondition whose rule map is outside the vocabulary or names an undeclared field is rejected rather than evaluated, and an unobservable or vacuous postcondition leaves the state where it was.

Results use `ESTABLISHED`, `CONTRADICTED` and `NOT_ESTABLISHED` only. A case
whose expected claim result is `NOT_ESTABLISHED` still has an expected
outcome: the evidence in that case cannot support the claim, and a verifier
that reaches a different outcome reports `CONTRADICTED` for it.

`effect_status` adds one value to v1's five: `CONTRACT_REJECTED`. It is the
fixture's name for REMORA refusing the rule map with `ValueError` before any
comparison; it is not a sixth `EffectStatus`.

## Claim ceiling

This package does **not** establish:

- that the reader is independent of the tool that acted;
- that the observed object is the one the call targeted;
- that no effect outside the declared delta occurred;
- causation of an observed effect;
- production deployment safety;
- Federation endorsement;
- a second implementation is by itself an independent verification record;

## What REMORA runs

`verify_declared_delta` checks the rule map, then compares the observed object against the declared delta only and returns one of five statuses; the fixture's state ladder is applied over that status and the dispatcher's `DispatchResult`. `remora/interop/boundary_fixtures.py` runs every case, mapping the rule-map `ValueError` to `CONTRACT_REJECTED`.

That run is an L0 self-test under `interop-result-v1`. Its record lives under
`artifacts/interop/runs/` and advances nothing.

## Files

- `fixtures.json`: 22 machine-readable cases with expected outcomes and claim results.
- `reference_verifier.py`: author implementation of the contract. It imports no REMORA code.
- `manifest.json`: source revision, SHA-256 of every package file, `package_digest` and the independence boundary.
- `claim-packet.json`, `verifier-request.json`: the producer claims and the request to external verifiers; both are package files and are pinned by the manifest.

Run the author reference implementation with:

```bash
python artifacts/interop/effect-evidence-v1.1/reference_verifier.py
```

A successful run must report an empty `failures` list.

## Assumptions

- `observed: null` means the reader returned nothing, not that the object is absent.
- an absent field and a field whose value is `null` are different observations.
- only declared fields are compared, under the rules in the fixture's `rules.comparison` note.
- a comparison rule outside the vocabulary, or for an undeclared field, rejects the contract instead of being evaluated.
- a success report for a refused dispatch is not attributed to the action.

## Independence

Running `reference_verifier.py` is a reproduction, not independent
verification, and a second implementation on its own is implementation
diversity. A run record states the independence level separately
(`interop-result-v1`, `L0_SELF_TEST` to `L4_INDEPENDENT_HOST_RUN`). Only
`L3_INDEPENDENT_RECOMPUTATION` or higher, covering every claim, moves the
contract to `EXTERNALLY_VERIFIED`; the conditions are in
[`docs/interop/FEDERATION.md`](../../../docs/interop/FEDERATION.md).
