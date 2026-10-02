# REMORA interoperability surface

This directory is the stable machine-readable entry point for cross-project
assurance work.

Start with `index.json`. Each published contract exposes a producer claim
packet, pinned artifacts and (where applicable) a verifier request.

## Boundary

Interop artifacts do not create REMORA authority. A foreign result is preserved
as a foreign native claim and may be referenced as context only after an
explicit admission step. It never maps automatically to
`ACCEPT`, `VERIFY`, `ABSTAIN` or `ESCALATE`.

The schemas in `schemas/` are intentionally small:

- claim packet: what REMORA claims and what it does not claim;
- external evidence ref: opaque reference to another project's native claim;
- consumed artifact: attribution/provenance only;
- action lineage: join references across proposal, authority, decision,
  execution, receipt, effect and verification without transitive credit.

The Federation shared vocabulary/status repository remains the appropriate place
for shared edge state. REMORA's local index describes only artifacts REMORA
itself publishes.
