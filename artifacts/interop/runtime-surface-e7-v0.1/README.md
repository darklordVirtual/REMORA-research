# REMORA runtime-surface E7 fixture contract v0.1

Lifecycle: **`DRAFT`**. The single source for the state is the contract entry
in [`artifacts/interop/index.json`](../index.json); `manifest.json` repeats it
and this line must agree with both. This package prepares the REMORA side of
E7 in `aeoess/agent-governance-vocabulary#179`. It is not an external
verification record and does not raise any REMORA capability to
`EXTERNALLY_VERIFIED`.

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

## Identity and provenance

Three things are kept apart, because one Git revision cannot pin the bytes
that describe it.

| Fact | Where it lives |
|---|---|
| Source provenance: the REMORA revision the fixtures were derived from | `source_revision` = `35db242ffd212320576a0636e125cf8dbf12a25c`, in `manifest.json`, `claim-packet.json`, `verifier-request.json` and `fixtures.json` |
| Package identity: the exact bytes a verifier evaluates | `manifest.json` lists every package file with its SHA-256; `package_digest` is the SHA-256 of those lines, so the manifest is never hashed into itself |
| The Git revision a verifier actually consumed | the verifier's own run record (`external-run-record-v1`), written after the fact; it is never embedded in this package |

A verifier therefore says "these exact bytes were evaluated" by quoting
`package_digest` and the input digests, not a Git revision. When the package
is frozen on master, the index records the reachable revision that carries
these bytes in `freeze_record`. That record sits outside the package.

Exact source-artifact SHA-256 values are in `manifest.json`. The contract does
not replace those source records.

## Files

- `fixtures.json`: five machine-readable inputs and expected per-claim results.
- `reference_verifier.py`: zero-dependency author implementation of the
  contract. It imports no REMORA code.
- `manifest.json`: source revision, SHA-256 of every package file,
  `package_digest` and the independence boundary.
- `claim-packet.json`, `verifier-request.json`: the producer claims and the
  request to external verifiers; both are package files and are pinned by the
  manifest.

Run the author reference implementation with:

```bash
python artifacts/interop/runtime-surface-e7-v0.1/reference_verifier.py
```

A successful run must report an empty `failures` list.

## Diversity and independence are two facts

Running `reference_verifier.py` is **not** independent verification, and
neither is a second implementation by itself. A run record states both facts
separately (`external-run-record-v1`):

| Fact | Values |
|---|---|
| Implementation diversity | `AUTHOR_IMPLEMENTATION`, `REPRODUCTION` (this verifier, run by someone else), `SECOND_IMPLEMENTATION` |
| Operator | `AUTHOR`, `EXTERNAL` |
| Independence | `INDEPENDENT`, `NOT_INDEPENDENT` |

`INDEPENDENT` is allowed only when all of these hold: a second
implementation, maintained outside REMORA, run by an external operator, and
importing neither REMORA runtime code nor this verifier. The record must also
repeat the claim ceiling and the non-claims. The schema enforces the
combination. A
second implementation that fails any of those conditions is recorded as
`SECOND_IMPLEMENTATION` + `NOT_INDEPENDENT`; it moves the contract to
`REPRODUCED`, never to `EXTERNALLY_VERIFIED`.

That external record should publish:

1. its own implementation revision;
2. the REMORA fixture revision and package digests;
3. the exact command used;
4. one result per claim;
5. implementation diversity and independence, as two separate fields, plus
   the Git revision actually consumed;
6. the same claim ceiling stated above.

## Relation to E8

This package does not implement the proposed AgentAvow ↔ REMORA E8 edge.
Static tool-definition identity, runtime tool-set identity and temporal binding
remain unevaluated until both projects agree on those semantics.
