# External seeded-fault adequacy run: evidence-sufficiency-v1

## Record

| Field | Value |
|---|---|
| Measured by | Rul1an |
| Date | 2026-09-29 |
| Agreement | darklordVirtual/REMORA-research#629, offer in aeoess/agent-governance-vocabulary#177 |
| Subject | `conformance/evidence-sufficiency-v1/` at `31c4060630923344d43d9fac26821150262c3687` |
| Checker sha256 | `c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0` |
| Corpus sha256 | `a0048cc021ab7cd7f7d1b09a93e13c7dbdee9f7a685ea617a112da8af3c88d7e` |
| Tool | corpus-adequacy 0.7.0 at `5fa2ff587497b00ac684a767335b9068f7e520a6` |
| Report | delivered privately on 2026-09-29 (Rul1an/remora-es-v1-adequacy); public link added when published |

## Result

Controls behaved in all rows: the positive control was killed and the inert control changed nothing.

| Row | Scored fields | Killed | Survived |
|---|---|---|---|
| 1 | `status`, `reason` per case | 53 | 27 |
| 2 | `missing_evidence`, `decisive_if` per case | 59 | 44 |
| 3 | runner `failures` | 55 | 48 |

Four kills are crashes (`KeyError`) and are read as "fault exposed by crash".
The counts describe the corpus against an agreed fault list.
They do not score the checker, and they do not report a defect in it.

The maintainer reproduced all three rows exactly with a separate harness over the same fault list.

## Survivors and their labels

Labels were set after the result was known. This is stated here and not hidden.

| Finding | Label | Closed in |
|---|---|---|
| Four reasons never expected | open gap | v1.1 (G1) |
| `effect_seen` and `expected_state` compound halves | open gap | v1.1 (G2) |
| 14 of 16 guard-order swaps | open gap: precedence is semantic (D-2, option A) | v1.1 (G3) |
| 3 truthiness faults | open gap: typing in scope (D-3). An earlier #629 comment said out of scope; D-3 reverses it | v1.1 (G4) |
| Guidance unchecked by the runner | open gap | v1.1 (runner R-5, R-6) |

## Status of v1.1

Not yet measured externally. A rerun with a held-out fault set was requested on #629.
See section 8 of `docs/design/evidence-sufficiency-v1.1.md`.
