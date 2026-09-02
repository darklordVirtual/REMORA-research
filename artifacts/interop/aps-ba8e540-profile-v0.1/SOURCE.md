# REMORA x APS profile v0.1 interop run

Status: author-produced Mode B observation. This is not an APS compliance claim.

| field | value |
|---|---|
| who ran it | Stian Skogbrott, `@darklordVirtual` |
| date | 2026-09-02 |
| profile | `remora-aps-profile-v0.1` |
| implementation | `darklordVirtual/REMORA-research` at baseline `ba8e5402681479a0ae20d8abfcb90a78fc06973b`, plus the uncommitted adapter recorded beside this evidence |
| corpus | `Agent-Authority-Conformance/aps-conformance-suite` at `cd5cce183fa3a5c58c00723f61383b1e1ea6ac40` |
| mode | B; REMORA implementations compute canonical bytes, hashes and signature verdicts |
| environment | CPython 3.12.13, Node v24.19.0, Linux |
| adapter SHA-256 | `5ff5ff396288b62421974009d4515ab789aa62e6ebd24ae5317efc9fec5018f9` |
| mappings SHA-256 | `aa35958af09ae1ca9f88faabff01ace1a88358c1380d59fd8f2a173c22b971bf` |
| results SHA-256 | `dddef1103db39bb30c26c60918f344ee54ef834c5b79b11930b163547baa7d27` |

## Result

| family | disposition | result | evidence boundary |
|---|---:|---:|---|
| `actionref-canonical` | run | 6/6 | REMORA JCS over adapter-constructed APS projection |
| `accountability-record` | run | 12/12 | REMORA Ed25519/digest evidence; schema-only negatives labelled adapter evidence |
| `receipt-decision-relation` | run | 7/7 | frozen profile projection; binding checked before time |
| `instruction-provenance` | `NOT_RUN` | 0 | mapped subset is inseparable from declined filesystem path rules in this fixture |
| REMORA→APS accountability mapping | checked separately | 5/5 | pure mapping assertions, not counted as APS vectors |

Aggregate: 25 APS vectors passed, zero divergences; five mapping assertions
passed, zero mapping divergences. Three of four declared families were run. The
fourth is not included in the numerator and is not silently treated as a pass.

## Claim boundary

The run supports author-produced interoperability evidence for the three named
families at the named revisions. It does not support the statement “REMORA is
APS compliant”. APS `action_ref` remains a correlation key and never replaces
REMORA exact-call identity. Schema-only checks in `accountability-record` test
adapter behaviour and are identified as such per profile rule 4.

## Reproduction

```sh
test "$(git -C REMORA-research rev-parse HEAD)" = ba8e5402681479a0ae20d8abfcb90a78fc06973b
test "$(git -C aps-conformance-suite rev-parse HEAD)" = cd5cce183fa3a5c58c00723f61383b1e1ea6ac40
RERUN="$(mktemp -t remora-aps-profile-XXXXXX.json)"
PYTHONPATH=REMORA-research python -m remora.interop.aps.adapter \
  --aps-suite aps-conformance-suite --output "$RERUN"
diff -u REMORA-research/artifacts/interop/aps-ba8e540-profile-v0.1/results.json "$RERUN"
```

Expected stdout:

```text
{"families_declared":4,"families_run":3,"families_not_run":1,"vectors_run":25,"passed":25,"divergences":0,"mapping_checks":5,"mapping_divergences":0}
```

The APS repository-wide `npm test` passed TypeScript typecheck and digest
integrity, then this container denied the `tsx` IPC socket with
`listen EPERM /tmp/tsx-0/131.pipe`. No full APS-native suite result is claimed
for this environment.

The historical `interop/remora-edd8a4e` record remains unchanged.
