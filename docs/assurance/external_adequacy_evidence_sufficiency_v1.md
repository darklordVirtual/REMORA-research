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
| Report | [public package at `011481d`](https://github.com/corpus-adequacy/remora-es-v12-adequacy/blob/011481d51f6d51d519d6671a49f535f0f130d56c/REPORT.md), published after maintainer factual review and publication agreement |
| Factual review | [#629 comment](https://github.com/darklordVirtual/REMORA-research/issues/629#issuecomment-5909549290): no corrections |

The recorded run stays on `c1345b1`.
After the run, the H1 sentence in the v1.2 runner's `limits` list was reworded to name cases E18-E20, and `run-record.json` carries the same sentence.
Cases, `guidance.json`, `ladders.json` and every check are identical to `c1345b1`, and `tests/test_evidence_sufficiency_v1_2.py` checks that the reworded sentence is the only difference in the runner and the record.

### Result

The v1.2 package is public at `011481d`. It reports the same three projections used in v1.1:

| Projection | Known killed / survived | Previously additional killed / survived |
|---|---:|---:|
| Status and reason | 80 / 0 | 6 / 0 |
| Guidance | 90 / 13 | 3 / 3 |
| Runner failures | 103 / 0 | 6 / 0 |

All six measurements completed. Positive controls were killed and inert controls changed nothing. The three canonicalisation faults that survived v1.1 are distinguished by the status/reason and runner-failures projections in v1.2; they remain survivors in the guidance projection because decisive verdicts carry no guidance under rule R-6.

Every fault in the run was known before E18-E20 were written, so this is repair evidence against known faults, not evidence that the corpus generalises, and it does not test checker correctness. The maintainer reproduced every mutant verdict with a separate harness at `c1345b1`; that reproduction is not committed and is not evidence on its own.

## Independent analysis of v1.3 (2026-09-30)

### Record

| Field | Value |
|---|---|
| Measured by | OpenAI Daybreak, an AI analysis the maintainer commissioned; its output is not evidence on its own (`docs/AI_USE.md`), and the committed package lets anyone rerun it |
| Date | 2026-09-30 |
| Subject | `conformance/evidence-sufficiency-v1/` to `-v1.3/` at `c9113a05ad2a8f1dfa35de799d173e0a08cb12f9` |
| Checker sha256 | `c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0`, unchanged from v1 |
| Tool | the package's own scripts (`prepare_faults.py`, `run_faults.py`) on CPython 3.14.0 |
| Fault definitions | `fault-definitions.json`, sha256 `241fe7d878df28021b3ee3294ea780a13a1b12c27fcba6c495fd14fe0c6d1733`: 24 hand-picked single edits and one complete systematic class, the 19 occurrences of `is not True` each turned into `is not False` |
| Package | `artifacts/independent-analysis-2026-09-30/`, committed unchanged; `python artifacts/independent-analysis-2026-09-30/verify_analysis.py` checks the hash, the row totals and the AST sweep counts |

The faults were chosen from the v1 checker and the v1 cases before any v1.3 file was opened, and the definitions were hashed first.
The hash was written to a local report, not committed publicly before the run, so this run does not meet item 2 of section 8 of `docs/design/evidence-sufficiency-v1.3.md`.
It is a locally pre-registered analysis, not the external confirmation that section asks for.

### Result

Rows as in the earlier runs: 1 scores `status` and `reason` against the authored expectations, 2 scores guidance against the unmutated checker, 3 scores the runner's `failures` list or a crash.

| Faults | v1.2 rows 1 / 2 / 3 | v1.3 rows 1 / 2 / 3 |
|---|---|---|
| 24 hand-picked | 23 / 22 / 23 | 24 / 23 / 24 |
| 19 systematic (`is not True` to `is not False`) | 19 / 19 / 19 | 19 / 19 / 19 |

H15 turns `protected_effect_observed is not False` into `is None`, so the integer `0` passes as an observation.
It survives all three v1.2 rows and is killed by K1 cases B21 and B25 in v1.3.
H24 (raw `==` for `canonical()`) survives row 2 in both versions, because a decisive verdict carries no guidance (rule R-6); rows 1 and 3 kill it.
Every one of the 43 faults is killed on the v1.3 runner row, so there is no survivor to label.
The systematic class adds a denominator and no difference between the versions.

### What it does not show

H15 belongs to the typed-premise family from which the K1 cases were derived, so its kill shows the repair and not transfer to a new family.
The analysis matched every fault to a family already named in the v1.3 spec and NEGATIVE_RESULTS.md §65 to §66 and found no new one.
It did not test the four equivalence arguments for the second operator set.
It does not test the checker's correctness or any deployment path.

### Claim audit

The analysis also audited the numbers in the record. What it found is NEGATIVE_RESULTS.md §67, corrected in the same change:

- RES-021 said 300 generated examples per property; the tests run 150.
- RES-021 said the rejection contract has 17 inputs; it has twenty since R18 to R20.
- RES-021 said one tool with its default operators, while reporting a second operator set.
- The historical sweep totals had no raw output in the repository, and the named commands reproduced only the final rows.
- The CHANGELOG headed fitted internal measures "Generalisation measures".

The maintainer reran each historical row with a command added for it and found one more error: the first run of the second operator set had 57 kills resting on one check, not 60.
The raw outputs are in `artifacts/evidence-sufficiency-mutation-2026-09-30/`.
The mutmut rows of section 7 reproduce exactly (377/112 and 469/20), and so does the AST sweep: the analysis's `ast-sweep.json` equals the maintainer's.

### Maintainer reproduction, committed

Earlier reproductions by the maintainer were not committed and were not evidence on their own.
This one is: `scripts/score_heldout_faults.py` scored the 43 definitions after checking their digest.
For v1.2 and v1.3 it agrees with the analysis's raw rows for every fault, on the set of cases that kill on rows 1 and 2 and on row 3.
`tests/test_score_heldout_faults.py` checks that agreement.
It also scores v1.4, which did not exist when the faults were chosen: 43 of 43 on row 3, 24 of 24 hand-picked and 19 of 19 systematic on row 1.
The record is `artifacts/evidence-sufficiency-mutation-2026-09-30/heldout-independent-analysis.json.gz`.

The analysis proposes a stricter acceptance criterion for a future blind run: at least 30 held-out faults across two operators and one complete operator class, and every non-equivalent fault killed on the v1.3 runner row.
