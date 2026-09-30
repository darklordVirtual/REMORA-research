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
| Report | [REPORT.md at `05f7a08`](https://github.com/Rul1an/remora-es-v1-adequacy/blob/05f7a087b6462400f4eb9ea9e4fb7d4aa023ccd3/REPORT.md), delivered privately on 2026-09-29 and published unchanged the same day |

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

## v1.1 rerun

### Record

| Field | Value |
|---|---|
| Measured by | Rul1an |
| Date | 2026-09-29 |
| Agreement | darklordVirtual/REMORA-research#629 |
| Subject | `conformance/evidence-sufficiency-v1/` and `conformance/evidence-sufficiency-v1.1/` at `57ee0351a6acd6c1dd865ca933603469ab519cd4`, the #637 head before the squash |
| Checker sha256 | `c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0`, unchanged from v1 |
| Tool | corpus-adequacy 0.7.0 at `5fa2ff587497b00ac684a767335b9068f7e520a6` |
| Report | [REPORT.md at `9f38519`](https://github.com/corpus-adequacy/remora-es-v11-adequacy/blob/9f3851995bbe395e510dde9ce9a03ebb6f1f965a/REPORT.md), delivered privately on 2026-09-29 and published unchanged the same day, after the survivors were classified |
| Classification | [corpus-adequacy/remora-es-v11-adequacy#1](https://github.com/corpus-adequacy/remora-es-v11-adequacy/issues/1), public with the package |

The recorded run stays on `57ee0351`.
#637 merged as `8772d85`, and within the two conformance directories the only difference is the "G1-G4" to "G1-G5" limits string in the v1.1 runner and run record.
The checker, cases, `guidance.json` and `ladders.json` are byte-identical.
Both the maintainer and Rul1an compared the trees; the result therefore applies to `8772d85` by source comparison, not by a second run.

### Known faults

The same 103 fault definitions and projections as v1.0.

| Row | Scored fields | v1.0 killed / survived | v1.1 killed / survived | Crash kills in v1.1 |
|---|---|---|---|---|
| 1 | `status`, `reason` per case (80 faults, guidance class not scored) | 53 / 27 | 80 / 0 | 2 |
| 2 | `missing_evidence`, `decisive_if` per case | 59 / 44 | 90 / 13 | 2 |
| 3 | runner `failures` | 55 / 48 | 103 / 0 | 2 |

The v1.1 cases were written with this fault list in view, and the maintainer's pre-flight gave the same counts before the run.
This table shows the repair against known faults. It is not evidence that the corpus generalises.

### Additional faults

Rul1an committed six further definitions by hash before execution, in `f2dac55` of Rul1an/remora-es-v1-adequacy.
They were chosen after the public v1.1 design and the pre-flight totals were known, so they are withheld from the maintainer but not blind.

| Fault | Rows 1, 2 and 3 |
|---|---|
| Admission match reads `admission_source_accepted` | killed |
| Route binding reads `outside_required_pep` | killed |
| Postcondition binding reads `source_accepted` | killed |
| `canonical()` case-folds string values | survived |
| `canonical()` sorts list values | survived |
| `canonical()` compares mapping keys only | survived |

No crash kills in this set.
The maintainer applied the six definitions to a copy of `8772d85` and got the same split; that reproduction is not committed and is not evidence on its own.

### Survivors and their labels

Labels were set after the result was known, on corpus-adequacy/remora-es-v11-adequacy#1, and Rul1an accepted them on #629.

| Finding | Label | Next |
|---|---|---|
| Row 2: 13 known faults that change a terminal outcome (six polarity flips, six terminal reasons, raw equality) | out of scope by a stated contract: rule R-6 gives a decisive verdict no guidance, so row 2 cannot see them. All 13 are killed on row 3 | none |
| Admission and postcondition aliases | killed, but each matches a known mutation on the declared adapter path; no independent evidence | none |
| Route alias | killed; partly overlaps guard removal, no independence claimed | none |
| The three `canonical()` faults | open gap, in scope: each merges distinct states, so a disagreeing postcondition would be ESTABLISHED. Every postcondition case compares scalar strings except E08 (`1` against `true`) | cases E18-E20 in v1.2 (NEGATIVE_RESULTS.md §64); written after the faults were known |

v1.2 cases for the open gap are written after these faults were known.
They will demonstrate the repair against them and will not count as independent evidence; v1 and v1.1 stay frozen.

### History of this section

Before publication this section read: "The package is private until the survivors are classified and publication is agreed, so no v1.1 counts are stated here."
It also recorded two properties from Rul1an's statement on #629.
The additional definitions were not held out in the sense of section 8 of `docs/design/evidence-sufficiency-v1.1.md`.
The denominator was not reduced after the results were seen.
Both properties hold in the published report.

## v1.2 rerun

### Record

| Field | Value |
|---|---|
| Measured by | Rul1an |
| Date | 2026-09-30 |
| Agreement | darklordVirtual/REMORA-research#629 |
| Subject | `conformance/evidence-sufficiency-v1/`, `-v1.1/` and `-v1.2/` at `c1345b1f9e0f877454bf996b2160d533c5a9b16a`, the #641 squash commit |
| Checker sha256 | `c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0`, unchanged from v1 |
| Tool | corpus-adequacy 0.7.0 at `5fa2ff587497b00ac684a767335b9068f7e520a6` |
| Fault definitions | the 103 known and six additional definitions of the v1.1 rerun, with the same controls and the same three rows |
| Report | [private package at `011481d`](https://github.com/corpus-adequacy/remora-es-v12-adequacy/blob/011481d51f6d51d519d6671a49f535f0f130d56c/REPORT.md), delivered on 2026-09-30 |
| Factual review | [#629 comment](https://github.com/darklordVirtual/REMORA-research/issues/629#issuecomment-5909549290): no corrections |

The recorded run stays on `c1345b1`.
After the run, the H1 sentence in the v1.2 runner's `limits` list was reworded to name cases E18-E20, and `run-record.json` carries the same sentence.
Cases, `guidance.json`, `ladders.json` and every check are identical to `c1345b1`, and `tests/test_evidence_sufficiency_v1_2.py` checks that the reworded sentence is the only difference in the runner and the record.

### Result

The package is private until Rul1an publishes it, so no v1.2 counts or survivor labels are stated here.
The maintainer found no factual corrections and agreed on #629 to publication of the package unchanged.
Once the package is public, this section gets the counts and labels, as the v1.1 section did.

Every fault in the run was known before E18-E20 were written, so the run can show the repair against those faults.
It is not evidence that the corpus generalises, and it does not test checker correctness.
The maintainer reproduced every mutant verdict with a separate harness at `c1345b1`; that reproduction is not committed and is not evidence on its own.
