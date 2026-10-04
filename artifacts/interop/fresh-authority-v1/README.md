# REMORA fresh-authority fixture contract v1

Lifecycle: recorded in the contract entry in
[`artifacts/interop/index.json`](../index.json) and repeated in
`manifest.json`. The package files, this README included, carry no state
label, so freezing the package does not change its bytes. This package is
REMORA's side of edge E-FA in the Federation manifest
(`artifacts/interop/FEDERATION.yaml`). It is not an external verification
record and raises no REMORA capability.

## Purpose

Let a verifier maintained by another project reproduce fourteen bounded outcomes about whether an authorization is re-evaluated at the moment it is used, from pinned bytes, without importing REMORA code.

## Claims and result vocabulary

- `fresh_authority_at_dispatch`: ESTABLISHED means only that, under this fixture contract, an authorization is re-evaluated when presented and does not survive expiry, revocation of its signing key, redemption, or a change of the observation, policy bundle or tool definition it was issued under.

Results use `ESTABLISHED`, `CONTRADICTED` and `NOT_ESTABLISHED` only. A case
whose expected claim result is `NOT_ESTABLISHED` still has an expected
outcome: the evidence in that case cannot support the claim, and a verifier
that reaches a different outcome reports `CONTRADICTED` for it.

## Claim ceiling

This package does **not** establish:

- that the clock at the enforcement point is trustworthy;
- that revocation propagates to every enforcement point in bounded time;
- that every execution path passes through the enforcement point;
- production deployment safety;
- Federation endorsement;
- a second implementation is by itself an independent verification record;

## What REMORA runs

A grant case goes through `PolicyDecisionToken` and `EnforcementGate.check(consume=True)`: validity window, revoked signing key, observation binding, one-time redemption. A dispatch case goes through `ExecutionLease` and `GovernedToolDispatcher` with the policy bundle and tool-definition identity in force at dispatch. `remora/interop/boundary_fixtures.py` runs every case.

That run is an L0 self-test under `interop-result-v1`. Its record lives under
`artifacts/interop/runs/` and advances nothing. the single-use and expiry paths are also within the mutation-testing baseline (`docs/assurance/mutation_testing_v1.md`); author evidence only.

## Files

- `fixtures.json`: 14 machine-readable cases with expected outcomes and claim results.
- `reference_verifier.py`: author implementation of the contract. It imports no REMORA code.
- `manifest.json`: source revision, SHA-256 of every package file, `package_digest` and the independence boundary.
- `claim-packet.json`, `verifier-request.json`: the producer claims and the request to external verifiers; both are package files and are pinned by the manifest.

Run the author reference implementation with:

```bash
python artifacts/interop/fresh-authority-v1/reference_verifier.py
```

A successful run must report an empty `failures` list.

## Assumptions

- timestamps are UTC ISO-8601 and the window is [issued_at, expires_at).
- `revoked_kids` at a presentation is the revocation state the enforcement point can see at that moment.
- a grant decision other than `accept` is never an execution authorization.

## Independence

Running `reference_verifier.py` is a reproduction, not independent
verification, and a second implementation on its own is implementation
diversity. A run record states the independence level separately
(`interop-result-v1`, `L0_SELF_TEST` to `L4_INDEPENDENT_HOST_RUN`). Only
`L3_INDEPENDENT_RECOMPUTATION` or higher, covering every claim, moves the
contract to `EXTERNALLY_VERIFIED`; the conditions are in
[`docs/interop/FEDERATION.md`](../../../docs/interop/FEDERATION.md).
