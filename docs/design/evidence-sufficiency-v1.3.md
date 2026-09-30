# Spec: evidence-sufficiency-v1.3, test adequacy by mutation analysis, metamorphic relations and generated inputs

## Status

ACCEPTED 2026-09-30. The maintainer took decisions D-6 to D-13 on that date, before the new cases were written, and D-14 to D-16 later the same day, after the first sweep was closed.
The implementation lands in the same change as this spec, together with the finding that motivated it (NEGATIVE_RESULTS.md §65).
`conformance/evidence-sufficiency-v1/`, `-v1.1/` and `-v1.2/` stay frozen; `tests/test_evidence_sufficiency_v1_3.py` pins their bytes.
v1.3 has had no external run. Section 8 records the protocol for one, and it must be blind.

## 1. Context

The checker `conformance/evidence-sufficiency-v1/checker.py` (sha256 `c4ca50ae…c8e20be0`) has been measured three times by an external party with hand-picked faults.
The v1.0 run found 103 faults in nine classes; v1.1 closed those gaps and was measured against six further faults, of which three survived; v1.2 closed those three.
Each round found what its fault list was built to find. None of them measured the checker against a systematic operator set, so nothing said what the lists had left out.

On 2026-09-30 the maintainer ran mutmut 3.8.0 with its default operators over the checker.
It generated 489 mutants. The v1.2 corpus, scored in the three projections of the external runs (status and reason per case, guidance per case, the runner's failure list), killed 377 and missed 112.
Every mutant in the decision paths of the three assessors was killed. The survivors sat beside those paths.

| Family | Survivors | What the v1.2 corpus never checked | Real gap |
|---|---:|---|---|
| A | 41 | the `claim` field of a verdict: every assessor's claim constant, every `_unknown(claim, …)` argument, `_result`, the `as_dict` key | yes |
| B | 40 | the `scope` field: the `_scope` default, every `scope` argument, the `as_dict` key | yes |
| C | 12 | the text of a `ValueError` message | no: the contract pins the exception class, not its wording |
| D | 8 | input rejection: `validate_json` branches and recursion, `canonical`'s own validation, the claim and observations guard in `assess` | yes |
| E | 3 | `canonical()` without `sort_keys`: the key order of a mapping would count | yes, and section 12.4 of the v1.1 spec had called it hypothetical |
| F | 7 | `canonical()` separators and `ensure_ascii` | no: only the string form changes; equality on JSON values is preserved |
| G | 1 | `_result`: `and` replaced by `or` between the inconclusive status and the guidance table | no: unreachable while every inconclusive reason is in the table and no decisive reason is, which R-5 already pins |

### 1.1 Reading a sweep

A survivor is a mutant no check tells apart from the original. It is a statement about the corpus, never about the checker.
Some survivors are equivalent to the original program, and deciding that is undecidable in general (Budd and Angluin, 1982).
A kill rate is therefore never a target. The measure this spec adopts is a named set of survivors, each with a stated reason, that may only shrink (D-10).
A killed mutant is not evidence that the checker is correct: mutants stand in for real faults only to the degree measured by Just et al. (2014), and much of that correlation is explained by suite size (Papadakis et al., 2018).
One tool with one operator set was used. A fault mutmut never generates was not measured.

## 2. Findings this spec must close

| ID | Finding | Family |
|---|---|---|
| F-7 | No check reads `verdict.claim`. A checker that names the wrong claim, or none, passes every v1.2 check. A consumer of `run-record.json` reads that field | A |
| F-8 | No check reads `verdict.scope`. The scope a caller binds a verdict to could be dropped or replaced | B |
| F-9 | The README's premise boundary says non-JSON values are refused. Nothing exercised the refusal, so a checker that assessed a float or a tuple passed | D |
| F-10 | Removing `sort_keys` from `canonical()` survives. Section 12.4 of the v1.1 spec declined to pin key order because no external run had named the fault; a systematic sweep has now named it | E |
| F-11 | The runner ended on the first exception a faulty checker raised. The external harness counts that as a kill, but the runner reported nothing about which check crashed | runner |
| F-12 | The only adequacy measure was a hand-picked fault list. Nothing ratcheted: a corpus change that lost discrimination would not have failed anything | method |

## 3. Goals and non-goals

### Goals

- Close F-7 to F-12 with additive cases, runner checks and a gate, leaving the checker and the earlier corpora untouched.
- Declare the invariants of a verdict as data, and make the runner fail when the declaration and the implementation disagree.
- Keep every survivor of the sweep named, classified and ratcheted.
- State the blind protocol under which v1.3 could earn independent evidence.

### Non-goals

- No change to `checker.py`. Its looseness around `scope` (section 6.3) is recorded, not repaired.
- No claim that the corpus generalises. Every new check was written after the sweep named the gap.
- No claim about production, cryptographic, APS or CoSAI conformance.
- No second tool in this change; section 8 asks the external party for one.

## 4. Decisions

### D-6. Mapping key order is in scope. (Reverses v1.1 spec section 12.4.)

Section 12.4 declined to pin `sort_keys` because adding a case for a fault nobody had named would widen the corpus beyond the finding.
The sweep has named it, three times. RFC 8259 section 4 defines an object as an unordered collection of members, so two mappings with the same members in another order are the same state.
E21 pins that at the top level and E23 at depth. E22 pins the boundary: a list inside a mapping keeps its order.

### D-7. The rejection contract is part of the checker's contract.

Malformed input is refused with `ValueError`. The class is pinned; the message text is not (family C stays equivalent).
The refusal must come from `assess` and from `canonical` alike, because the runner calls `canonical` directly.
Inputs JSON cannot express (tuples, sets, bytes, non-string keys, a `str` subclass, NaN) live in the runner as a named table, so the corpus file stays JSON.

### D-8. `claim` and `scope` are contract fields. Scope is echoed, never consulted.

A verdict names the claim it answers and carries the scope it was given, with `{"kind": "synthetic_fixture", "bounded": true}` when none or an empty one is given.
Status, reason and guidance are identical under every scope. The runner checks all of this on every case under four declared scopes.

### D-9. Metamorphic relations are declared data.

`invariants.json` names eleven relations (Chen, Cheung and Yiu, 1998). The runner implements each by id and fails with `unimplemented_relation` or `undeclared_relation` when the two sets differ.
A relation records how many times it was checked, and a relation checked zero times is a failure.
The relations answer the oracle problem (Barr et al., 2015) for inputs no authored case covers: they say what must not change, without saying what the right verdict is.

### D-10. The internal adequacy measure is a named-survivor ratchet, not a score.

`scripts/mutation_evidence_sufficiency.py` sweeps the checker with mutmut and compares the survivors with `docs/assurance/mutation_baseline_evidence_sufficiency_v1.txt`.
A survivor absent from the baseline fails the gate. A baseline entry that dies is reported as a hint to remove it. The baseline may only shrink through a reviewed diff.
Each survivor is classified in `docs/assurance/mutation_testing_v1.md` by family with the reason it is equivalent under the pinned contract.
This is the same discipline the enforcement sweep adopted (issue #280), for the same reason: a score would force equivalent mutants to be argued away.

### D-11. Independent evidence for v1.3 must come from a blind run. (Section 8.)

The sweep, the family test and the generated-input tests were all written by the maintainer with the survivors in view.
They show the repair. Only faults chosen without sight of v1.3, and committed before the run, can show generalisation.

### D-12. The runner reports a crash, it does not die of one.

Each of the ten runner sections runs under crash capture. A checker that raises on valid input yields `crash:<section>:<Exception>` in `failures`.
The external harness still counts an adapter crash as a kill on its per-case rows; the runner row now names the section.

### D-13. Generated-input tests are derandomised.

The Hypothesis tests run with `derandomize=True`, a fixed example budget and no deadline, so a CI run is reproducible and a failure is a counterexample, not a flake.
A relation that holds on 150 generated inputs is known to hold on those inputs.

### D-14. The corpus is scored against the input lattice, not only against authored cases.

`model.json` is a table-driven reference model of the checker, written from the v1 README and the declared ladders.
The runner interprets it over every combination of premise values (`true`, `false`, absent) for every claim.
It also interprets it over a typed sweep around each decisive configuration, and over twelve state values in every pair for the postcondition claim.
The checker must agree on status and reason at every point (McKeeman, 1998).
A fault that changes any verdict on that lattice is therefore caught whether or not somebody authored a case for it.
The model compares states structurally and never through `canonical()`, so the two implementations disagree on any fault in either comparison.
The model shares its author and its specification with the checker; agreement catches an implementation slip in either and cannot catch a misreading both share.

### D-15. A second operator set measures the corpus against faults it was not tuned to.

`scripts/mutation_evidence_sufficiency_ast.py` applies nine operators mutmut does not have, listed in 6.8, plus a fixed-seed sample of second-order mutants (Jia and Harman, 2009).
Every mutant is scored in process by the runner, and its kill signature is the set of check labels that failed.
A mutant killed by one label only is fragile, and that label is load-bearing; the report states both.
The survivors are ratcheted against `docs/assurance/mutation_baseline_evidence_sufficiency_ast_v1.txt` under the same discipline as D-10.

### D-16. Faults only the lattice sees become authored cases, derived and not written.

The first run of the second operator set found 42 mutants that only the reference model killed.
`--derive-cases` computes, for those mutants, a greedy cover of lattice points on which they and the model disagree, and writes each point as a case with the model's verdict.
Those cases carry gap `K1`, name the mutants they separate, and exist so that the external rows that score authored cases alone (rows 1 and 2) see what the lattice sees.
They are derived from the sweep and are not independent evidence.

## 5. Requirements

Each requirement names the check that enforces it. R-1 to R-13 of the v1.1 spec carry over unchanged.

| ID | Requirement | Enforced by |
|---|---|---|
| R-14 | v1.2 `cases.json`, `guidance.json` and `ladders.json` keep their pinned sha256 values; v1.3 carries the 53 v1.2 cases verbatim and in order, and copies guidance and ladders byte for byte | `test_earlier_tested_bytes_are_frozen`, `test_v12_cases_are_carried_verbatim_and_in_order`, `test_v12_guidance_and_ladders_are_carried_byte_for_byte` |
| R-15 | Every new case carries `gap`, `derived_from` and `rationale`; E21 and E23 differ from their observed state only in key order as loaded from the file | `test_new_cases_declare_origin_and_rationale`, `test_key_order_cases_differ_only_in_key_order_as_loaded` |
| R-16 | Every rejection in the corpus and in the runner's table is refused with `ValueError`, by `assess` and by `canonical` | runner `rejection:*`, `test_every_rejection_is_refused_with_valueerror` |
| R-17 | Every declared relation is implemented, executed at least once, and holds on every case; every implemented relation is declared | runner `unimplemented_relation:*`, `undeclared_relation:*`, `<id>:never_checked`, `<id>:*`; `test_every_declared_relation_is_executed_and_holds` |
| R-18 | The verdict echoes its claim and its scope under every declared scope, and its envelope has the declared shape | MR-1, MR-2, MR-3 |
| R-19 | A checker exception inside any runner section is a named failure, not the end of the run | `crashes` and `crash:*` in the record |
| R-20 | One representative fault per family A, B, D and E is told apart by v1.3 and survives v1.2 | `test_each_survivor_family_is_told_apart_by_v1_3`, `test_each_survivor_family_survives_v1_2` |
| R-21 | The relations hold on generated inputs, derandomised | the Hypothesis tests in `tests/test_evidence_sufficiency_v1_3.py` |
| R-22 | Every survivor of the sweep is named in the baseline and classified; a new survivor fails the gate; an empty sweep fails the gate | `scripts/mutation_evidence_sufficiency.py`, `test_mutation_baseline_is_well_formed_and_classified` |
| R-23 | The committed `run-record.json` reproduces byte for byte and lists no failures | `--check`, `test_committed_artifact_reproduces_exactly`, `test_record_has_no_failures` |
| R-24 | The record states that the new checks were written after the sweep, and states the checker's `scope` looseness | `limits` in the record, `test_record_discloses_that_the_new_checks_were_written_after_the_sweep` |
| R-25 | The checker agrees with `model.json` on every lattice point, on the typed sweep and on every authored case; the model's reason order contains every declared ladder and its reason set equals the checker's vocabulary | runner `reference_model:*`, `model_ladder_mismatch:*`, `model_reason_mismatch:*`; `test_reference_model_agrees_on_the_whole_lattice`, `test_lattice_cases_agree_with_the_reference_model` |
| R-26 | A typed premise on a field no earlier case types is told apart by the reference model and by a K1 case | `test_reference_model_tells_apart_a_fault_no_authored_case_reaches` |
| R-27 | Every survivor of the second operator set is named in its baseline and classified; the operator catalogue covers every operator and every assessor; second-order pairs never overlap | `scripts/mutation_evidence_sufficiency_ast.py`, `test_second_operator_set_*`, `test_second_order_pairs_do_not_overlap_and_are_seeded` |
| R-28 | Every K1 case types exactly one premise, names the mutants it separates, and carries the model's verdict | `test_new_cases_declare_origin_and_rationale` |

## 6. Design

### 6.1 Layout

```
conformance/evidence-sufficiency-v1/        unchanged (tested bytes frozen)
conformance/evidence-sufficiency-v1.1/      unchanged
conformance/evidence-sufficiency-v1.2/      unchanged
conformance/evidence-sufficiency-v1.3/
  README.md                   scope, what changed, non-claims
  cases.json                  53 v1.2 cases verbatim + E21-E23 + 10 rejections
  guidance.json               byte copy of v1.2
  ladders.json                byte copy of v1.2
  invariants.json             declared scopes, premise classes, distinct pairs, relations
  model.json                  table-driven reference model and the lattice it is checked on
  run_evidence_sufficiency.py runner; imports the frozen v1 checker; crash capture
  run-record.json             deterministic record
scripts/mutation_evidence_sufficiency.py                          the mutmut sweep and its gate
scripts/mutation_evidence_sufficiency_ast.py                      the second operator set, its gate and --derive-cases
docs/assurance/mutation_baseline_evidence_sufficiency_v1.txt      named mutmut survivors
docs/assurance/mutation_baseline_evidence_sufficiency_ast_v1.txt  named survivors of the second set
tests/test_evidence_sufficiency_v1_3.py
```

### 6.2 New cases (gap I1)

| Case | Derived from | Expected state | Observed state | Verdict |
|---|---|---|---|---|
| E21 | E01 | `{"state":"closed","lock":"held"}` | `{"lock":"held","state":"closed"}` | ESTABLISHED |
| E22 | E19 | `{"members":["closed","locked"]}` | `{"members":["locked","closed"]}` | VIOLATED |
| E23 | E21 | `{"outer":{"x":1,"y":2}}` | `{"outer":{"y":2,"x":1}}` | ESTABLISHED |

`cases.json` is written without sorting keys, because a sorted rewrite would make E21 and E23 compare equal under the faulty checker too.
The wrong shortcut `same_members_in_another_key_order_means_disagreement` witnesses E21.
With the 23 K1 cases of 6.9 the distribution becomes 6 established, 65 not_established and 8 violated over 79 cases.

### 6.3 Rejections (gap J1)

| ID | Input | Why it must be refused |
|---|---|---|
| R01, R02 | an unknown claim; a null claim | no assessor |
| R03, R04 | a list; null | observations must be a mapping |
| R05 | a float state | outside the fixture vocabulary |
| R06, R07 | a float inside a list; a float inside a nested mapping | validation recurses |
| R08 | a float in the scope | the scope is validated like the observations |
| R09, R10 | premise source `production`; an empty premise source | the production guard |
| R11 to R20 (runner) | tuple, set, bytes, an int key at depth, a `str` subclass, NaN, an int key at the top, a `list` subclass, a `dict` subclass, a `str`-subclass key | not expressible in JSON; R18 to R20 were added when the second operator set relaxed the exact type checks to `isinstance` and survived |

The frozen checker coerces a scope through `dict()`. A sequence of pairs is accepted as a scope, and a non-mapping the coercion cannot convert raises `TypeError`.
That is outside the contract this corpus pins. It is recorded in the record's `limits` and not repaired, because the checker stays frozen; a v2 checker should validate the scope as a mapping before coercion.

### 6.4 Metamorphic relations

| ID | Transformation | What must not change |
|---|---|---|
| MR-1 | any declared scope | `claim` |
| MR-2 | any declared scope | `scope` is the given one or the default; status, reason, guidance |
| MR-3 | any declared scope | the envelope keys; `decisive_if` present exactly when not_established |
| MR-4 | observations in reversed key order | status, reason, guidance |
| MR-5 | one added field the checker never reads | status, reason, guidance |
| MR-6 | the same call twice | the whole verdict |
| MR-7 | mutate the caller's scope after the call | the inputs; the verdict's scope |
| MR-8 | assign to a verdict field | raises `FrozenInstanceError` |
| MR-9 | swap expected and observed state | status, reason |
| MR-10 | set one acceptance premise of a decisive case to false | never the opposite decisive status |
| MR-11 | every declared distinct pair; every state value under any key order | `canonical` separates the pair; `canonical` is unchanged by key order |

The premise classes for MR-10 are declared in `invariants.json`: acceptance premises may be flipped, observation values (`admission_present`, `protected_effect_observed`, the two states) may not, because flipping an observation value legitimately changes the world.
MR-11's declared pairs include `1` against `true`, `"1"` against `1`, `[]` against `{}`, `{"a": null}` against `{}` and a decomposed against a precomposed `é`.
The comparison is exact on code points. A producer that needs Unicode normalisation must apply it before the checker.

### 6.5 The gate

The sandbox copies the checker into an importable package, copies the four suite directories and points the v1.3 runner at the package.
It reads the reason vocabulary from the unmutated source, so mutmut's own rewriting of the served copy is not mistaken for a fault.
The scoring tests are the three external projections. mutmut's mutant ids are stable only within one version; the baseline header records the version.
The gate runs in `.github/workflows/mutation.yml`: on the weekly schedule with the enforcement sweep, on dispatch, and on every pull request that touches the corpus, the script or the baseline.

### 6.6 Tests

`tests/test_evidence_sufficiency_v1_3.py` has three groups.
The first pins bytes and carry-over. The second scores one representative fault per family against both runners: v1.3 must fail and v1.2 must not.
A control fault from the H1 family must fail both, so the differential cannot pass by a runner that fails on everything.
The third checks the relations with Hypothesis on generated observation sets and generated JSON states, including that `canonical` is injective exactly on structural equality with `1` and `true` kept apart.

### 6.7 The reference model and its lattice

`model.json` declares, per claim, an ordered list of steps of four kinds.
A `require` step names premises and the reason it fails with.
A `branch` step selects a sub-ladder on an exact boolean and names the reason for any other value.
A `compare` step names the two state fields and the verdicts for equal, different and missing.
A `terminal` step names a decisive verdict.
The interpreter in the runner is twenty lines and has no knowledge of `checker.py`.
The lattice is 61,236 documents: 3^9 premise combinations for the admission claim, 3^8 for the route claim, and 3^5 times 12 times 12 state pairs for the postcondition claim.
The typed sweep adds 308 documents: each premise of each decisive configuration set to each of seven non-boolean values.
Two coherence checks keep the model honest against the rest of the corpus.
Every ladder segment in `ladders.json` must be a subsequence of the model's reason order, and the model's reason set must equal the vocabulary read from the checker's source.

### 6.8 The second operator set

| Operator | Mutants | What it seeds |
|---|---:|---|
| `delete_statement` | 86 | a guard, a return or an assignment removed |
| `swap_adjacent_guards` | 24 | two neighbouring guards exchanged |
| `comparison_variant` | 96 | `is True` and its kin flipped, negated, made truthiness or made equality |
| `reason_confusion` | 236 | a reason literal replaced by every other reason of the same assessor |
| `status_polarity` | 16 | a terminal status replaced by each other status |
| `field_confusion` | 197 | a premise name replaced by every other premise the assessor reads |
| `state_comparison` | 10 | the postcondition comparison replaced by raw, `str`, `repr`, unsorted, case-folded, stripped, anagram, inverted, constant or length comparison |
| `negate_condition` | 33 | an `if` test negated |
| `type_vocabulary` | 7 | a scalar type dropped or added; an exact type check relaxed to `isinstance` |
| second order | 200 | a fixed-seed sample of non-overlapping pairs |

Every mutant is a text edit on the checker's source, applied in memory, so a second-order mutant is two edits and a catalogue entry is reproducible from the source alone.

### 6.9 Lattice-derived cases (gap K1)

The 23 cases A17 to A25, B18 to B26 and E24 to E28 each set one premise to `1`, or `0` for an `is not False` guard, on a configuration that is otherwise decisive.
They were computed by `--derive-cases` as the smallest greedy cover of the 42 mutants that only the reference model killed.
All 42 are `comparison_variant` mutants that read a premise by truthiness or by `== True`.
The v1.1 typing pin (D-3) covered one premise per claim, the last before a decisive return; these pin the other nineteen.
Each case names the mutants it separates in a `separates` field, and its expectation is the model's verdict.

## 7. Pre-flight, not evidence

| Sweep | Mutants | Killed | Survived | Survivors by family | Reproduce with |
|---|---:|---:|---:|---|---|
| mutmut, v1.2 corpus, three projections | 489 | 377 | 112 | A 41, B 40, C 12, D 8, E 3, F 7, G 1 | `scripts/mutation_evidence_sufficiency.py --scoring-suite evidence-sufficiency-v1.2` |
| mutmut, v1.3 corpus, three projections | 489 | 469 | 20 | C 12, F 7, G 1 | `scripts/mutation_evidence_sufficiency.py` |
| second operator set, v1.3 before R18-R20 and K1 | 905 | 898 | 7 | 3 `isinstance` relaxations (real), 4 equivalent | `scripts/mutation_evidence_sufficiency_ast.py --corpus first-run` |
| second operator set, v1.3 with R18-R20, before K1 | 905 | 901 | 4 | 4 equivalent, as below | `scripts/mutation_evidence_sufficiency_ast.py --corpus without-k1` |
| second operator set, v1.3 as merged | 905 | 901 | 4 | 4 equivalent: a stripped canonical string, and three swaps of mutually exclusive guards | `scripts/mutation_evidence_sufficiency_ast.py` |

The two middle states of the second set were never committed on their own; `--corpus` rebuilds each by removing what the sweep led to.
The raw output of every row is in `artifacts/evidence-sufficiency-mutation-2026-09-30/`.
mutmut refuses native Windows; the mutmut rows were reproduced in a `python:3.12-slim` container.

The 20 mutmut survivors and the 4 survivors of the second set are named in their baselines. Each is argued equivalent under the pinned contract in `docs/assurance/mutation_testing_v1.md`; none is proven equivalent, because that is undecidable.
The family test passes: each of seven representative faults fails v1.3 and survives v1.2, and the H1 control fails both.
The Hypothesis tests pass at 150 examples per property, derandomised.
The reference model agrees with the checker on all 61,544 lattice and typed documents and on all 79 authored cases.

The redundancy reading of the second set is the part worth keeping.
In the first run, 57 of 898 kills rested on one label: 42 on the reference model alone, 14 on the rejection contract alone, 1 on a crash.
With R18 to R20 and before the K1 cases, 60 of 901 did: 42, 17 and 1, because R18 to R20 alone kill the three `isinstance` relaxations.
This section first gave 60 for the first run, which mixed the two states; NEGATIVE_RESULTS.md §67 records the correction.
The 42 were typed-premise faults on premises no authored case had typed; without the lattice they would have survived, which is what D-16 answers.
After the K1 cases, 18 kills rest on one label, none of them on the model alone, because every lattice-only kill now has an authored witness as well.

None of this is independent evidence. The cases, the relations and the tests were written with the survivor list in view, and the tool that produced the list is the tool that scores the result.

## 8. External protocol for v1.3

The earlier protocol (v1.1 spec, section 8) withheld faults from the maintainer, but the selector had seen the corpus design and the pre-flight totals.
For v1.3 the run must be blind, and the record says beforehand what would count.

1. The selector chooses faults from `checker.py` at the pinned commit without reading `conformance/evidence-sufficiency-v1.3/` or this spec's sections 6 and 7, and states that in the commitment.
2. The selector commits the sha256 of the fault definitions publicly before the run, as before.
3. At least one systematic class is run in full (every mutant of one operator), so the result has a denominator, and at least one tool other than corpus-adequacy 0.7.0 or mutmut 3.8.0 is used.
4. Rows and crash kills are reported as in the earlier runs. Hand-picked and systematic faults are reported in separate tables.
5. The maintainer labels every survivor (equivalent, out of scope by a stated contract, open gap) before any corpus change, and never moves a label to improve a count.
6. Pre-registered criterion: v1.3 is confirmed only if every held-out fault that is not labelled equivalent is killed on the runner row. Any open gap goes to v1.4 with the same discipline as sections 12 of the v1.1 spec and this one.
7. Rows 1 and 2 score the authored cases alone; row 3 scores the runner, and only row 3 sees the lattice of D-14. A fault killed on row 3 and not on row 1 is reported as such, and it is the signal that another K1-style derivation is due.

## 9. Acceptance criteria

1. `python conformance/evidence-sufficiency-v1.3/run_evidence_sufficiency.py --check` exits 0 with an empty `failures` list and an empty `crashes` list.
2. `python scripts/mutation_evidence_sufficiency.py` exits 0 with no survivor outside the baseline.
3. `pytest tests/test_evidence_sufficiency_v1_3.py tests/test_evidence_sufficiency_v1_2.py tests/test_evidence_sufficiency_v1_1.py tests/test_evidence_sufficiency.py` passes.
4. The v1, v1.1 and v1.2 directories are byte-identical to their pinned values.
5. NEGATIVE_RESULTS.md §65, the research control matrix (RES-021), the document register and CHANGELOG record the finding, the method and the result.

## 10. Tasks

| ID | Task | Depends on | Status |
|---|---|---|---|
| T-8 | Sweep the checker with mutmut and classify every survivor | none | done (§65) |
| T-9 | Write this spec and take D-6 to D-13 | T-8 | done |
| T-10 | Cases E21-E23, the rejection set, `invariants.json`, the runner with crash capture, the record | T-9 | done |
| T-11 | The gate script, the baseline, the workflow job | T-10 | done |
| T-12 | The test module: pins, family differential, generated inputs | T-10 | done |
| T-13 | Register the method: RES-021, related-work section 14, `mutation_testing_v1.md`, CHANGELOG, index | T-10 | done |
| T-14 | Ask for a blind external run under section 8 | T-13 | open; an independent analysis on 2026-09-30 selected its faults blind but hashed them locally, not publicly (`docs/assurance/external_adequacy_evidence_sufficiency_v1.md`) |
| T-15 | Label the survivors of that run before any corpus change; open v1.4 only for open gaps | T-14 | open |
| T-16 | The reference model, its lattice and the coherence checks (D-14) | T-10 | done |
| T-17 | The second operator set with second-order sampling, the redundancy reading and its baseline (D-15) | T-11 | done |
| T-18 | The K1 cases derived from the lattice, and R18 to R20 (D-16) | T-17 | done |

## 11. Risks

| Risk | Mitigation |
|---|---|
| The survivor classification is wrong and an equivalent-labelled mutant is a real gap | each family states the contract clause that makes it equivalent; a reviewer can test the clause; section 8 asks a second tool to disagree |
| Relations pinned as invariants are accidental properties of this checker | each relation names the contract it encodes (D-8, D-7, D-6); a relation with no contract behind it is not added |
| The gate depends on one mutmut version | the version is in the baseline header; a version change regenerates the baseline in a reviewed diff |
| Writing tests against a survivor list fits the corpus to the tool | D-11: only a blind run counts as evidence; section 8 asks for a second tool |
| Long runner, larger record, harder review | sections are small functions with one failure vocabulary each; the record keeps counts per relation |
| The reference model repeats the checker's mistakes | it is table driven, compares states structurally, and is checked against the declared ladders and the reason vocabulary; a shared misreading of the specification is the residual risk, and section 8 names it |
| Derived cases fit the corpus to the second operator set | they are labelled K1 with the mutants they separate; the operator set is committed and its survivors ratcheted, so the fit is visible and bounded |

## 12. Research grounding

Each source is listed with what this spec takes from it and what it leaves.

- DeMillo, Lipton and Sayward (1978), *Hints on Test Data Selection*, IEEE Computer 11(4). Mutation analysis: seed small faults, ask whether the tests notice. Taken: the method and the two hypotheses that carry it (competent programmer, coupling). Left: any use of the kill rate as a quality score.
- Budd and Angluin (1982), *Two notions of correctness and their relation to testing*, Acta Informatica 18(1). Equivalent mutants are undecidable. Taken: the named-survivor ratchet instead of a score (D-10).
- Offutt (1992), *Investigations of the software testing coupling effect*, ACM TOSEM 1(1). Tests that kill simple mutants tend to kill complex ones. Taken as the reason a first-order sweep is worth running. Left: any claim that higher-order faults are covered.
- Jia and Harman (2011), *An Analysis and Survey of the Development of Mutation Testing*, IEEE TSE 37(5), and Papadakis et al. (2019), *Mutation Testing Advances*, Advances in Computers 112. The cost controls and the equivalent-mutant problem. Taken: a scoped subject and a scoring runner that finishes in a minute.
- Just et al. (2014), *Are mutants a valid substitute for real faults in software testing?*, FSE, and Papadakis et al. (2018), *Are mutation scores correlated with real fault detection?*, ICSE. The correlation exists and much of it is suite size. Taken: section 1.1's reading of what a kill means.
- Andrews, Briand and Labiche (2005), *Is mutation an appropriate tool for testing experiments?*, ICSE. Generated mutants behave like real faults for comparing test techniques. Taken: mutation as the internal comparator between v1.2 and v1.3.
- Kurtz et al. (2016), *Analyzing the validity of selective mutation with dominator mutants*, FSE. Many mutants are subsumed by others. Left for now: the families in section 1 are a hand classification, not a subsumption graph; section 8 item 3 asks for a full operator class so subsumption can be studied.
- Kintis et al. (2018), *Detecting Trivial Mutant Equivalences via Compiler Optimisations*, IEEE TSE 44(4). Taken: the idea that equivalence is argued from the program, not from the tests; here from the contract clauses.
- Chen, Cheung and Yiu (1998), *Metamorphic testing: a new approach for generating next test cases*, HKUST-CS98-01; Segura et al. (2016), *A Survey on Metamorphic Testing*, IEEE TSE 42(9); Chen et al. (2018), *Metamorphic Testing: A Review of Challenges and Opportunities*, ACM Computing Surveys 51(1). Relations between inputs and outputs replace an oracle. Taken: MR-1 to MR-11 (D-9). Left: automated relation inference.
- Barr et al. (2015), *The Oracle Problem in Software Testing*, IEEE TSE 41(5). Why authored expectations cannot cover generated inputs. Taken: the split between authored cases (an oracle per case) and relations (no oracle).
- Claessen and Hughes (2000), *QuickCheck*, ICFP, and MacIver et al. (2019), *Hypothesis: A new approach to property-based testing*, JOSS 4(43). Generated inputs under stated properties, with shrinking. Taken: the third test group (D-13). Left: stateful testing; the checker is a pure function.
- Zhu, Hall and May (1997), *Software unit test coverage and adequacy*, ACM Computing Surveys 29(4), and Inozemtseva and Holmes (2014), *Coverage is not strongly correlated with test suite effectiveness*, ICSE. Why coverage was not used as the adequacy measure.
- Nosek et al. (2018), *The preregistration revolution*, PNAS 115(11). Taken: section 8 item 6, the criterion stated before the run.
- McKeeman (1998), *Differential Testing for Software*, Digital Technical Journal 10(1). Two implementations of one specification disagree where one is wrong. Taken: D-14, the reference model over the lattice. Left: random differential inputs; the lattice is enumerated.
- Jia and Harman (2009), *Higher Order Mutation Testing*, Information and Software Technology 51(10). Pairs of faults can mask each other. Taken: the fixed-seed second-order sample of D-15. Left: the search for subsuming higher-order mutants.

## Deliverables

- This spec.
- `conformance/evidence-sufficiency-v1.3/`, passing all acceptance criteria.
- `scripts/mutation_evidence_sufficiency.py` and `docs/assurance/mutation_baseline_evidence_sufficiency_v1.txt`.
- `scripts/mutation_evidence_sufficiency_ast.py`, `docs/assurance/mutation_baseline_evidence_sufficiency_ast_v1.txt` and `conformance/evidence-sufficiency-v1.3/model.json`.
- `tests/test_evidence_sufficiency_v1_3.py`.
- The `evidence-sufficiency` job in `.github/workflows/mutation.yml`.
