# REMORA interoperability surface

This directory is the stable machine-readable entry point for cross-project
assurance work.

Start with `index.json`. Each contract exposes a producer claim packet, a
manifest that pins every package file, a content-addressed `package_digest`,
and (where applicable) a verifier request. The index also carries the
contract's lifecycle state and the records that justify it.

## Identity

Source provenance (`source_revision`) and package identity (`package_digest`)
are separate facts. The package never names the Git revision that published
it. That revision is recorded outside the package: in `freeze_record` once
the bytes are frozen on master, and in each verifier's own run record as the
revision it consumed. A manifest is never hashed into itself.

## Lifecycle

`DRAFT` → `FROZEN` → `EXTERNAL_RUN_PENDING` → `REPRODUCED` → `EXTERNALLY_VERIFIED`.
The state is written once, in `index.json`, and repeated in the contract's
manifest. Package files carry no state label, so a freeze changes no bytes. A state is only as strong as the records under it.
`REPRODUCED` needs a run record with implementation diversity;
`EXTERNALLY_VERIFIED` needs one that meets the independence contract. An
author run advances nothing. `tests/test_federation_interop_contract.py`
refuses an index whose state exceeds its records.

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
  execution, receipt, effect and verification without transitive credit;
- external run record: what a verifier publishes after evaluating a package,
  with implementation diversity and independence as two separate fields.

None of these carries an authority field. `authority_integrations.json` lists
the reviewed integrations through which they may reach the policy, enforcement
or execution code; it is empty, and a test fails if the formats appear there
without an entry.

The Federation shared vocabulary/status repository remains the appropriate place
for shared edge state. REMORA's local index describes only artifacts REMORA
itself publishes.
