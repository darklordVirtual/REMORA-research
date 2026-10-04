# AgentAvow signed tool manifest to REMORA authorization, E8 fixture contract v0.1

Lifecycle: recorded in the contract entry in
[`artifacts/interop/index.json`](../index.json) and repeated in
`manifest.json`. The package files, this README included, carry no state
label, so freezing the package does not change its bytes. This package is
REMORA's side of edge E8 in the Federation manifest
(`artifacts/interop/FEDERATION.yaml`). It is not an external verification
record and raises no REMORA capability.

## Purpose

Let a verifier maintained by another project reproduce eight bounded outcomes about whether an attested tool definition is the one bound into an authorization, from pinned bytes, without importing REMORA code. The reference verifier needs `cryptography` for Ed25519 and nothing else.

## Claims and result vocabulary

- `attested_definition_binding`: ESTABLISHED means only that, under profile v0, the edge reports digest_bound exactly when the tool definition a named signer attested is byte-identical, by digest, to the tool definition bound into the authentic authorization, reports digest_mismatch otherwise, and refuses to evaluate an unverifiable manifest or authorization.

Results use `ESTABLISHED`, `CONTRADICTED` and `NOT_ESTABLISHED` only. A case
whose expected claim result is `NOT_ESTABLISHED` still has an expected
outcome: the evidence in that case cannot support the claim, and a verifier
that reaches a different outcome reports `CONTRADICTED` for it.

## Claim ceiling

This package does **not** establish:

- that the signer or its project is trustworthy;
- that the tool definition is semantically correct or safe;
- that the runtime exposed exactly that definition (E7);
- that the authorized call executed or had an effect;
- that AgentAvow's actual wire format is the one profile v0 assumes;
- production deployment safety;
- Federation endorsement;
- a second implementation is by itself an independent verification record;

## What REMORA runs

`remora/interop/agentavow/adapter.py` verifies the manifest under a caller-supplied key, normalizes it to an observed tool definition with an `UNADMITTED` evidence reference, and compares the digest with `toolspec_hash` inside an authentic `ExecutionLease`. The adapter never admits, decides or mints.

That run is an L0 self-test under `interop-result-v1`. Its record lives under
`artifacts/interop/runs/` and advances nothing. this is the first foreign edge REMORA consumes. Its matrix status stays EXPERIMENTAL until AgentAvow confirms or corrects the profile.

## Files

- `fixtures.json`: 8 machine-readable cases with expected outcomes and claim results.
- `reference_verifier.py`: author implementation of the contract. It imports no REMORA code.
- `manifest.json`: source revision, SHA-256 of every package file, `package_digest` and the independence boundary.
- `claim-packet.json`, `verifier-request.json`: the producer claims and the request to external verifiers; both are package files and are pinned by the manifest.

Run the author reference implementation with:

```bash
python artifacts/interop/agentavow-tool-manifest-e8-v0.1/reference_verifier.py
```

A successful run must report an empty `failures` list.

## Assumptions

- the manifest wire format, signature preimage and digest rule are REMORA's profile v0 assumptions, recorded in `fixtures.json` under `profile`, and are not confirmed by AgentAvow.
- trusted signer keys are supplied by the consuming deployment; no registry is consulted.
- the fixtures use the JCS-trivial subset, so `json.dumps` with sorted keys and no whitespace reproduces RFC 8785.

## Independence

Running `reference_verifier.py` is a reproduction, not independent
verification, and a second implementation on its own is implementation
diversity. A run record states the independence level separately
(`interop-result-v1`, `L0_SELF_TEST` to `L4_INDEPENDENT_HOST_RUN`). Only
`L3_INDEPENDENT_RECOMPUTATION` or higher, covering every claim, moves the
contract to `EXTERNALLY_VERIFIED`; the conditions are in
[`docs/interop/FEDERATION.md`](../../../docs/interop/FEDERATION.md).
