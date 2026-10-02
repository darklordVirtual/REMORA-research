# REMORA runtime-surface E7 fixture contract v0.1

Status: **proposal**. This package prepares the REMORA side of E7 in
`aeoess/agent-governance-vocabulary#179`. It is not an external verification
record and does not raise any REMORA capability to `EXTERNALLY_VERIFIED`.

## Purpose

Let a verifier maintained by another project reproduce five bounded outcomes
from pinned bytes without importing REMORA runtime or decision code.

The primary claim is:

`bounded_observed_surface_matches_governed_set`

Result vocabulary:

- `ESTABLISHED`: the supplied complete `agent-runtime` observation matches
  the supplied governed tool set under this contract.
- `CONTRADICTED`: the supplied evidence directly disagrees with the bounded
  claim, for example an undeclared callable tool.
- `NOT_ESTABLISHED`: the evidence cannot support the claim, for example the
  runtime identity changed or observation coverage is incomplete.

The fifth vector evaluates a separate claim, `exclusive_effect_path`. An
observed alternative path contradicts exclusivity. Absence of a path would not
establish exclusivity unless path-inventory completeness were independently
established.

## Claim ceiling

This package does **not** establish:

- `runtime_capability_surface_completeness` for an external agent host;
- absence of host credentials or capabilities outside the observed process;
- absence of unobserved alternative execution paths;
- execution occurrence;
- production enforcement;
- causation of an observed effect.

The repository-wide global property therefore remains
`runtime_capability_surface_completeness = NOT_ESTABLISHED`.

## Pinned provenance

The fixture contract is derived from REMORA revision
`35db242ffd212320576a0636e125cf8dbf12a25c`.

Exact source-artifact SHA-256 values are in `manifest.json`. The contract does
not replace those source records.

## Files

- `fixtures.json`: five machine-readable inputs and expected per-claim results.
- `reference_verifier.py`: zero-dependency author implementation of the
  contract. It imports no REMORA code.
- `manifest.json`: source revision, SHA-256 pins and independence boundary.

Run the author reference implementation with:

```bash
python artifacts/interop/runtime-surface-e7-v0.1/reference_verifier.py
```

A successful run must report an empty `failures` list.

## Independence rule

Running `reference_verifier.py` is **not** independent verification. A
cross-project E7 record requires a separately maintained implementation that
consumes the pinned fixture bytes and reproduces the expected per-claim
outcomes without importing REMORA code or using this verifier as a dependency.

That external record should publish:

1. its own implementation revision;
2. the REMORA fixture revision and package digests;
3. the exact command used;
4. one result per claim;
5. whether the run was independent, second implementation, or author-produced;
6. the same claim ceiling stated above.

## Relation to E8

This package does not implement the proposed AgentAvow ↔ REMORA E8 edge.
Static tool-definition identity, runtime tool-set identity and temporal binding
remain unevaluated until both projects agree on those semantics.
