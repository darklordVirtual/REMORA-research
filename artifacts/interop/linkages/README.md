# Linkage records

One `bcr-linkage-v1` record per run record that has been given an Agent
Authority Conformance Profiles profile revision and a Bounded Claim
Reproduction level. The schema is
`artifacts/interop/schemas/bcr-linkage-v1.schema.json`; the rules are in
[docs/interop/FEDERATION.md](../../../docs/interop/FEDERATION.md#linkage-records).

No record exists yet. The author runs under `artifacts/interop/runs/` are
`L0_SELF_TEST`, and no profile revision has been published for them, so no
run has a documented level. A contract's lifecycle state (`FROZEN`,
`EXTERNAL_RUN_PENDING`) is not a level and is never written here.

`scripts/interop_package.py --check` validates every record in this
directory, resolves its source record by path and digest, and refuses a
record whose level, status or claim differs from the source.
