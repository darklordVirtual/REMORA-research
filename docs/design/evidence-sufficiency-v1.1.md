# Spec: evidence-sufficiency-v1.1, closing the discrimination gaps found by external seeded-fault testing

## Status

ACCEPTED 2026-09-29. The maintainer decided D-2 (option A) and D-3 (in scope) on that date.
The implementation merged through #637 after the v1.0 external report became public (D-5).
Rul1an ran an external measurement of v1.1 at `57ee035`, published at `9f38519` after the survivors were classified (T-7). Three withheld faults in `canonical()` survived (NEGATIVE_RESULTS.md §64); v1.2 adds cases for them (section 12).
One change landed after that measurement, before merge.
A CodeQL finding flagged an implicit string concatenation in the runner's `limits` list.
The fix made the concatenation explicit and corrected "G1-G4" to "G1-G5" in the same sentence.
Cases, guidance, ladders, the checker and every check are identical to `57ee035`.
The only difference in `run-record.json` is that one `limits` sentence.

## 1. Context

`conformance/evidence-sufficiency-v1/` holds 26 authored cases, a runner and the checker
`checker.py` (sha256 `c4ca50ae…c8e20be0`).
The runner checks authored expectations, two indistinguishable-world witnesses, single-field evidence
erasure, five wrong shortcuts and empty input.

On 2026-09-29 Rul1an ran a seeded-fault adequacy measurement against that suite at `31c4060`, using
`corpus-adequacy` 0.7.0 (`5fa2ff58`), following the scope agreed in issue #629.
The offer came from aeoess/agent-governance-vocabulary#177.
The package is `remora-es-v1-adequacy` (REPORT.md, REPRODUCE.md, three manifests, `mutants.json`).

The run seeded 103 faults in nine classes plus two controls into the checker.
It then asked whether the corpus tells each faulty checker apart from the pinned one.
Both controls behaved: the positive control was killed and the inert control changed nothing.

| Row | What is scored | Killed | Survived |
|---|---|---|---|
| 1 | `status` + `reason` per case | 53 | 27 (guidance class not scored) |
| 2 | `missing_evidence` + `decisive_if` per case | 59 | 44 |
| 3 | full runner, `failures` list | 55 | 48 |

These counts describe the corpus against an agreed fault list.
They are not a score of the checker and not a defect report against it.

### 1.1 Reproduction by the maintainer

The counts above were reproduced exactly with an independent harness.
It applied the same `mutants.json` anchors and scored the same three rows (`preflight.py`, see Deliverables).
The harness differs from `corpus-adequacy`, so this confirms the arithmetic and the fault list.
It does not confirm the tool.

### 1.2 One observation the report did not make

The v1 `--check` mode compares the committed `run-record.json` byte for byte.
That record contains `missing_evidence` and `decisive_if` for every case.
A guidance edit therefore fails `--check` and the pytest wrapper, even though `failures` stays empty.
This was verified by editing one `decisive_if` string.
A snapshot pins bytes and carries no meaning.
Anyone who regenerates `run-record.json` after an edit passes it again.
The report's row 3 result for guidance (0 of 23 killed) is the correct reading for semantic checks.
v1.1 must pin guidance with a semantic check and must not rely on the snapshot.

## 2. Findings this spec must close

| ID | Finding | Evidence in the report | Surviving faults |
|---|---|---|---|
| F-1 | Four reasons are never an expected reason: `scope_unaccepted_or_missing`, `admission_presence_unknown`, `route_observation_unaccepted_or_missing`, `protected_effect_observation_unaccepted` | "What the survivors say" item 1 | class 1: 4 in row 1 and 3 in row 3, class 8: 4, class G: 4 |
| F-2 | Two compound-guard halves are unpinned: `effect_seen` and `"expected_state" not in o` | item 2 | class 1: 2 |
| F-3 | Guard precedence is pinned at two points only | item 3 | class 6: 14 of 16 |
| F-4 | No case gives a premise a truthy non-boolean value | item 4 | class 4: 3 of 3 |
| F-5 | The runner does not check guidance, so the README property "every inconclusive verdict carries `missing_evidence` and `decisive_if`" is unenforced | item 5 | class G: 23 of 23 in row 3 |
| F-6 | One inconclusive reason has no single-failure case (found by the maintainer, see 2.1) | none | probe, see 2.1 |

### 2.1 F-6: a fault class outside the agreed list

After the report the maintainer probed one more fault class.
The probe replaced `o.get(x) is not True` with `o.get(x) is False` in each guard.
The effect is that a missing premise reads as satisfied, which makes the guard fail open.
Against the first v1.1 draft, 18 of 19 such faults were killed through the erasure loop.
The survivor was `valid_control_same_context`.
Its only case, B03, also fails attribution, so erasing the control field never makes the claim decisive.

This class was found and fixed by the author of the corpus.
Its kill count is therefore not independent evidence, and it is not part of any held-out set.

## 3. Goals and non-goals

### Goals

1. Close F-1 to F-6 with cases and runner checks that assert meaning and do not compare bytes.
2. Keep v1 tested bytes frozen so the external v1.0 result stays resolvable to what it measured.
3. Make the v1.0 to v1.1 comparison attributable to the corpus and runner alone.
4. Add structural rules that fail when a future change reopens the same kind of gap.
5. Prepare an external rerun with a held-out fault set.

### Non-goals

1. No change to inference semantics. `checker.py` stays byte-identical.
2. No production, conformance or independent-validation claim.
3. No new score. The target is a named survivor list, as in `docs/assurance/mutation_testing_v1.md`.
4. No reclassification of v1.0 survivors after the fact to improve the v1.0 numbers.

## 4. Decisions

### D-1. The checker is frozen. v1.1 changes the corpus and the runner only. (Decided in this spec.)

The v1.1 runner imports `../evidence-sufficiency-v1/checker.py`.
It records the checker's sha256 and reports `checker_is_frozen_v1`.
It never adds a hash mismatch to `failures`.
A hash check in `failures` would kill every seeded fault by construction and make any adequacy run vacuous.
The frozen-bytes guarantee lives in a pytest test instead, which a mutation harness does not execute.

### D-2. Is guard precedence part of the semantics? (Decided 2026-09-29: option A.)

Every one of the 14 surviving order swaps exchanges two guards that both return `not_established`.
No swap can change a `status`. Only the reported `reason` changes, and only when both premises fail.
The question is therefore whether `reason` is a deterministic contract when several premises fail.

Option A (chosen): yes.
The reported reason is the first failing premise in a declared ladder.
Each ladder follows evidence dependency: existence, then provenance, then binding, then time, then value.
`reason` is a scored field and it selects the guidance, so an unspecified choice would make both non-deterministic contracts.

Option B: no. The suite states that `reason` is order-independent only when exactly one premise fails.
The 14 survivors become expected, the G3 cases and precedence witnesses are dropped, and runner check R-7 is removed.

Pinning each adjacent pair pins the whole order within a segment.
Any reordering other than the identity inverts at least one adjacent pair of the original order.

### D-3. Is premise typing in scope? (Decided 2026-09-29: in scope.)

Decision: in scope.
The README calls these fields trusted synthetic fixture premises, and that sentence is about provenance.
It says nothing about type.
`validate_json` admits strings, integers, lists and objects, so a non-boolean premise is valid input to `assess()`.
The checker's `is True` comparisons already fail closed on such input, so three cases pin behaviour that exists.

This reverses the scope statement posted on #629 at 16:55 UTC the same day, which called class 4 out of scope.
The reversal came after reading the checker source, and it widens the scope.
It moves no survivor out of the count.
The correction is posted on #629 together with the rerun request.

A second point of order belongs on the record as well.
The #629 reply said the precedence decision would be documented before any new case was written.
The G3 cases were drafted in the same session as this spec, before D-2 was recorded here.
They were committed only after the decision, and under option B they would have been removed.

### D-4. Guidance has an oracle independent of the checker. (Decided in this spec.)

`guidance.json` holds the expected `missing_evidence` and `decisive_if` for all 22 inconclusive reasons.
Its content was copied from the pinned checker's `_REASON_GUIDANCE`, and after that it is authored data.
The runner compares every inconclusive verdict against it.
Comparing against the checker's own table would be a tautology, because a seeded fault edits both sides.

### D-5. The v1.0 external result is published before v1.1 merges. (Decided.)

A before and after comparison is only credible if the "before" was public, with a timestamp, before the "after" existed.
The v1.1 pull request is therefore held open until Rul1an's v1.0 report is public.
The rerun is pinned to the pull request's head commit, which stays valid whether or not the branch has merged.

## 5. Requirements

Each requirement names the check that enforces it.

| ID | Requirement | Enforced by |
|---|---|---|
| R-1 | v1 `checker.py` and `cases.json` keep their pinned sha256 values | `test_v1_tested_bytes_are_frozen` |
| R-2 | v1.1 `cases.json` begins with the 26 v1 cases, unchanged and in order | `test_v1_cases_are_carried_verbatim` |
| R-3 | Every new case carries `gap`, `derived_from` and `rationale` | `test_new_cases_declare_origin_and_rationale` |
| R-4 | Every reason literal the checker can return, read from its source by AST, is the expected reason of at least one case | runner `unreached_reason:*` |
| R-5 | Every inconclusive reason in the source has a `guidance.json` entry and every entry has a reason | runner `undeclared_guidance:*`, `orphan_guidance:*` |
| R-6 | Every `not_established` verdict the runner produces (cases, erasures, empty input) carries exactly the declared guidance. Every decisive verdict carries none. | runner `guidance_contract_failures` |
| R-7 | Every adjacent pair in each declared ladder has a witness in which both guards fail. The witness reports the earlier reason, and repairing the earlier premise surfaces the later reason. (Only under D-2 option A.) | runner `precedence:*`, `unwitnessed_precedence:*` |
| R-8 | Every inconclusive reason has an isolation witness: it is the only failing premise, and repairing it makes the verdict decisive | runner `isolation:*`, `unisolated_reason:*` |
| R-9 | For each claim, a truthy non-boolean premise on the last step before a decisive return leaves the verdict inconclusive (only under D-3 in scope) | cases A16, B16, E17 and shortcut `truthy_premise_means_true` |
| R-10 | An effect that is observed but whose observation is not accepted never yields `violated` | case B10 and shortcut `unaccepted_effect_means_violation` |
| R-11 | All v1 runner checks carry over unchanged: expectations, indistinguishable worlds, erasure without strengthening or polarity flip, wrong shortcuts, empty input | runner, `test_erasure_and_shortcut_properties_carry_over` |
| R-12 | The committed `run-record.json` reproduces byte for byte | `--check`, `test_committed_artifact_reproduces_exactly` |
| R-13 | The run record states that G1 to G5 cases were written after the external run named the gaps | `limits` in the record |

The runner check for R-8 is what closes F-6.
With an isolation witness present, the erasure loop turns any fail-open reading of a missing premise into an `inconclusive_strengthening_failure`.

## 6. Design

### 6.1 Layout

```
conformance/evidence-sufficiency-v1/      unchanged (tested bytes frozen)
conformance/evidence-sufficiency-v1.1/
  README.md                   scope, what changed, non-claims
  cases.json                  26 v1 cases verbatim + 24 new cases
  guidance.json               expected guidance per inconclusive reason (D-4)
  ladders.json                declared ladders, precedence and isolation witnesses
  run_evidence_sufficiency.py runner; imports the frozen v1 checker
  run-record.json             deterministic record
tests/test_evidence_sufficiency_v1_1.py
docs/assurance/external_adequacy_evidence_sufficiency_v1.md   v1.0 and v1.1 external result record
```

### 6.2 New cases

Each new case is derived from one v1 case by setting or removing named fields.

| Gap | Cases | Construction |
|---|---|---|
| G1 (F-1) | A09, A10, B09, B10 | One premise fails on a base that would otherwise be decisive. A10 sets `admission_present: null` on the closed-world base A03. B10 sets `effect_observation_accepted: false` on B01, where the effect is observed. |
| G2 (F-2) | A11, E11 | A11: `effect_source_accepted: true`, `effect_seen: false`. E11: `expected_state` removed, `observed_state` kept. |
| G3 (F-3) | A12 to A15, B11 to B15, E12 to E16 | Two adjacent guards fail. The expected reason is the earlier one. B03 already witnesses the control and attribution pair. |
| G4 (F-4) | A16, B16, E17 | The last premise before a decisive return is `1`, `"true"` and `{"at": "declared"}` respectively. |
| G5 (F-6) | B17 | `valid_control_same_context: false` is the only failing premise. |

Every inconclusive reason now has at least one case.
The distribution becomes 4 established, 42 not_established and 4 violated.

### 6.3 Declared ladders (D-2 option A)

| Claim | Segment | Order |
|---|---|---|
| admission_accounting | before the admission block | execution observation, scope |
| admission_accounting | after presence | presence unknown, mandatory rule, window, coverage |
| tested_route_enforcement | before the effect verdict | route observation, operation binding, outside PEP, effect observation accepted |
| tested_route_enforcement | after no effect | effect unknown, effect window, valid control, boundary attribution |
| postcondition_observed | whole ladder | read-back available, source accepted, target bound, fresh, settled, both state values present |

Guards separated by a decisive return are not ordered against each other.
Their order already changes `status`, and existing cases pin it (B01 precedence, A03, E02).

### 6.4 Crash exposure

Dropping either half of `"expected_state" not in o or "observed_state" not in o` makes the checker raise `KeyError`.
E09 and E11 then crash.
A harness counts that as a kill, and it should be reported as "fault exposed by crash".
No case can turn these two faults into a changed verdict, because the faulty checker has no verdict to give.

## 7. Pre-flight against the known fault list

The maintainer ran the reference implementation against Rul1an's 103 faults with the harness from 1.1.

| Row | v1.0 killed / survived | v1.1 killed / survived |
|---|---|---|
| 1, status + reason (classes 1 to 8) | 53 / 27 | 80 / 0 |
| 2, guidance per case | 59 / 44 | 90 / 13 |
| 3, full runner | 55 / 48 | 103 / 0 |

The 13 row 2 survivors are terminal-verdict faults (classes 5 and 7, six of class 8).
They are invisible to that row by construction, as the report explains.
Two of the kills are crashes (6.4).

This table is a pre-flight and does not count as a result.
Cases G1 to G5 were written with the fault list in view, so killing those faults is expected by construction.
The independent evidence is the held-out part of the rerun in section 8.

## 8. External rerun protocol

1. Publish the v1.0 result (D-5) and merge v1.1 as its own commit. Pin that commit.
2. Ask Rul1an to rerun the same three rows, adapted to the v1.1 layout.
   The subject tree must contain both suite directories, because the v1.1 runner imports the v1 checker.
3. Ask for a held-out fault set: classes or instances chosen by Rul1an and not disclosed before the run.
   Classes 1 to 9 of the v1.0 run and the F-6 probe class are known and cannot serve as held-out.
4. Report known and held-out faults in separate tables. Crash kills stay labelled.
5. Record survivors by name in `docs/assurance/external_adequacy_evidence_sufficiency_v1.md`.
   Each survivor gets one of three labels: equivalent, out of scope by a stated contract, or open gap.
   A label is decided before the next corpus change and never moved to improve a count.

## 9. Acceptance criteria

1. `python conformance/evidence-sufficiency-v1.1/run_evidence_sufficiency.py --check` exits 0.
2. `python conformance/evidence-sufficiency-v1/run_evidence_sufficiency.py --check` exits 0, and v1 files are byte-identical to `31c4060`.
3. `pytest tests/test_evidence_sufficiency.py tests/test_evidence_sufficiency_v1_1.py` passes.
4. `scripts/check_prose_style.py` passes for the new Markdown files.
5. The record has `failures: []`, 50 of 50 expectations matched, 28 checker reasons, 15 precedence witnesses and 22 isolation witnesses.
6. D-2 and D-3 are recorded in this document before merge. If either changes, the cases and checks it governs are removed in the same change.

## 10. Tasks

| ID | Task | Depends on | State |
|---|---|---|---|
| T-1 | Reply on #629: accept the run, ask Rul1an to publish it unchanged, state D-2 and D-3 | D-2, D-3 | done (#629, 2026-09-29) |
| T-2 | Add `docs/assurance/external_adequacy_evidence_sufficiency_v1.md` with the v1.0 counts, the named survivors and a link to the published report | T-1 | done |
| T-3 | Commit the v1.1 directory, `guidance.json`, `ladders.json`, runner and tests | D-2, D-3 | done |
| T-4 | Regenerate and commit `run-record.json`; run the prose and artifact gates | T-3 | done |
| T-5 | Register the new documents in `docs/assurance/document_register_v1.yaml`. No claim register row cites evidence-sufficiency, so no claim row changes. | T-3 | done |
| T-6 | Ask Rul1an for the v1.1 rerun with a held-out set (section 8) | T-3, T-2 | done at `57ee035`; the additional faults were not selected blind (see the external record) |
| T-7 | Record the rerun result and label every survivor | T-6 | done: labels on corpus-adequacy/remora-es-v11-adequacy#1, accepted on #629; result and labels in the external record; the open gap is NEGATIVE_RESULTS.md §64, for v1.2 |

## 11. Risks

| Risk | Mitigation |
|---|---|
| v1.1 overfits the known fault list | Held-out faults (8.3); R-13 disclosure; no claim from the known-fault table |
| Reclassifying survivors to improve counts | Labels fixed before the next corpus change (8.5); v1.0 counts never restated |
| Precedence pinned without a real semantic reason | D-2 is an explicit decision with the dependency rationale written down; option B remains available |
| Snapshot checks mistaken for semantic checks | 1.2 is documented; R-6 is semantic |
| The runner's own hash pin makes adequacy vacuous | D-1: the pin is recorded, never a failure |

## 12. v1.2 addendum

v1.2 closes the one gap from the external v1.1 run that was not fitted: three withheld changes to `canonical()` that no v1.1 case could tell apart.
The record is `docs/assurance/external_adequacy_evidence_sufficiency_v1.md`, and the finding is NEGATIVE_RESULTS.md §64.

### 12.1 Scope

`conformance/evidence-sufficiency-v1.2/` holds the 50 v1.1 cases verbatim and three new cases, gap H1.
v1 and v1.1 stay frozen, and their tests pin the bytes the external runs measured.
`guidance.json` and `ladders.json` are copied byte for byte, and the runner differs from v1.1 only in its suite name and one added `limits` entry.
No checker, guidance or ladder change is in scope, so each new case is a plain authored expectation.

### 12.2 Cases

Every postcondition case in v1.1 compares plain strings, apart from E08 (`1` against `true`).
Each H1 case derives from E02 and changes only `expected_state` and `observed_state`, so every other premise holds and the comparison alone decides the verdict.

| Case | Expected state | Observed state | Expected verdict |
|---|---|---|---|
| E18 | `"Closed"` | `"closed"` | VIOLATED, `declared_postcondition_disagreed_at_named_point` |
| E19 | `["closed", "locked"]` | `["locked", "closed"]` | VIOLATED, same reason |
| E20 | `{"state": "closed"}` | `{"state": "open"}` | VIOLATED, same reason |

### 12.3 Pre-flight, not evidence

The maintainer applied the six withheld definitions and the 103 known faults from Rul1an's published manifests to copies of the tree.
On v1.1 the runner reproduced the published split: 103 of 103 known faults killed, two by crash, and 3 of 6 withheld.
On v1.2 it killed 103 of 103 and 6 of 6, with the positive control killed and the inert control unchanged.
`tests/test_evidence_sufficiency_v1_2.py` pins the three `canonical()` faults against the H1 cases.
The H1 cases were written with these faults in view, so these kills show the repair and are not independent evidence.
v1.2 has had no external run.

### 12.4 Not in scope

No case pins that key order in a mapping is ignored (`sort_keys`).
The external runs named no such fault, and adding one here would widen the corpus beyond the finding.

## Deliverables

- This spec.
- `conformance/evidence-sufficiency-v1.1/` reference implementation, passing all acceptance criteria.
- `tests/test_evidence_sufficiency_v1_1.py`.
- `preflight.py`, the harness used for 1.1 and section 7. It is kept outside the repository because it reads Rul1an's `mutants.json`, which quotes BUSL-1.1 source under his package NOTICE.
- `conformance/evidence-sufficiency-v1.2/` and `tests/test_evidence_sufficiency_v1_2.py` (section 12).
