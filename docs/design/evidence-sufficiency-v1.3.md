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

Since 2026-09-30 the protocol has a committed harness, so a run needs only a fault file and its public commitment:

```bash
python scripts/score_heldout_faults.py FAULTS.json --expect-sha256 <committed digest> --labels labels.json --json record.json --require-pass
```

It refuses a file whose digest differs from the commitment, and it refuses an edit that does not match the frozen checker.
It scores v1.2, v1.3 and v1.4 in the three rows and applies item 6 to the newest suite. A survivor without an `equivalent` label counts as an open gap.
On the 43 faults of the independent analysis it reproduces that analysis's own raw rows for v1.2 and v1.3, case by case, with no disagreement.
The run still needs a selector who has not read the corpus and a public commitment; the harness removes only the need to write one.

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
| T-14 | Ask for a blind external run under section 8 | T-13 | open; an independent analysis on 2026-09-30 selected its faults blind but hashed them locally, not publicly (`docs/assurance/external_adequacy_evidence_sufficiency_v1.md`); `scripts/score_heldout_faults.py` now scores such a run |
| T-15 | Label the survivors of that run before any corpus change; open v1.4 only for open gaps | T-14 | open |
| T-16 | The reference model, its lattice and the coherence checks (D-14) | T-10 | done |
| T-17 | The second operator set with second-order sampling, the redundancy reading and its baseline (D-15) | T-11 | done |
| T-18 | The K1 cases derived from the lattice, and R18 to R20 (D-16) | T-17 | done |
| T-19 | Pre-register and run specification mutation of `model.json` (section 13) | T-16 | done; S-2 not met, twelve row-1 survivors (NEGATIVE_RESULTS.md §68) |
| T-20 | Close the §68 gap in a new corpus version, labelled as fitted | T-19 | done: v1.4 (section 14.6) |
| T-21 | Rule coverage (RC-1 to RC-3), the derivation rule and the held-out catalogue (section 14) | T-19 | done; H-1 to H-3 as in section 14.6, with the power caveat of NEGATIVE_RESULTS.md §69 |

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
- Budd and Gopal (1985), *Program testing by specification mutation*, Computer Languages 10(1). Mutate the specification, not the program, and ask whether the tests tell the mutant specification apart. Taken: section 13. Left: specification languages; the specification here is `model.json`.
- Chilenski and Miller (1994), *Applicability of modified condition/decision coverage to software testing*, Software Engineering Journal 9(5). Each condition must be shown to affect its decision independently. Taken: RC-2 and RC-3 of section 14, applied per decisive outcome. Added: RC-1, the dual, that a condition off an outcome's path does not affect it.
- Offutt, Lee, Rothermel, Untch and Zapf (1996), *An experimental determination of sufficient mutant operators*, ACM TOSEM 5(2). A small operator set can stand in for a large one. Taken: section 13 names its operators before the run and does not add operators after it.

## 13. Specification mutation, pre-registered

### 13.1 Why

All three measures so far seed faults in `checker.py`: mutmut, the second operator set and the independent analysis of 2026-09-30.
Their faults follow the shape of one implementation, and the K1 cases were derived from the second set.
A corpus that is adequate against faults in one program's shape may still miss a wrong reading of the rules that another program would carry.
Specification mutation (Budd and Gopal, 1985) seeds faults in the rules instead.
`scripts/spec_mutation_evidence_sufficiency.py` mutates `model.json`.
It turns each mutant model into a checker: a fresh copy of the frozen checker whose three assessors interpret the mutant model.
Validation, the envelope and the guidance table stay the checker's own.
Each mutant is scored in the three rows of section 8.

### 13.2 Operators

| Operator | Mutants | What it seeds |
|---|---:|---|
| `delete_guard` | 18 | a `require` step removed |
| `swap_guards` | 16 | two adjacent steps exchanged, a terminal excepted |
| `drop_premise` | 2 | one premise removed from a two-premise guard |
| `add_premise` | 124 | a guard also requires another premise of the same claim |
| `premise_reading` | 100 | a premise read by truthiness, `== True`, `is not False`, presence or `is False` |
| `branch_reading` | 18 | a branch arm taken on truthiness, `== True`, `is not False`, falsiness, `== False`, `is not None`, `is not True` or always; the arms swapped |
| `reason_swap` | 142 | an inconclusive reason replaced by every other inconclusive reason of the same claim |
| `verdict_swap` | 18 | a decisive verdict given another status, or another decisive reason of the same claim |
| `state_comparison` | 8 | states compared by raw `==`, case-folded, with list order ignored, by keys only or as strings; a missing state counted as equal or as different; the two verdicts swapped |
| second order | 300 | a fixed-seed (20261001) sample of pairs on one claim whose edits compose on distinct steps |

That is 446 first-order and 300 second-order mutants.
`python scripts/spec_mutation_evidence_sufficiency.py --list` prints the catalogue, each entry with its mutated ladder.
`--catalogue-sha256` prints its digest: `2fbf983a5b29f7f6c2b4bba8319fd8c8d7a59105651f38e11b4e6b3d8c5bd5a8`, over `model.json` at sha256 `861e5dc80ff1983e2b3a640ad0f20b340fb0157c6ecfc6df259d1c2083dba201`.
No operator is added or removed after the first score is read.

### 13.3 Equivalence is computed, not argued

The model reads a premise only through predicates, and each predicate in the catalogue gives one answer on each of eight value classes.
The classes are `true`, `false`, absent, `null`, `1`, `0`, a truthy non-boolean and a falsy non-boolean.
A premise that no edit of a mutant touches is read exactly, by `is True` or `is False`, in both models.
Under an exact reading the last five classes behave as absent.
So two models that agree on every combination of three classes for untouched premises, and eight for touched ones, agree on every premise value JSON can carry.
The script enumerates that domain per mutant.
A mutant that agrees with the model on all of it is equivalent, and leaves the denominator by computation, with no hand label.
The state comparison is decided on the model's twelve declared state values plus absence.
That bound is stated, not proved complete; a comparison mutant equivalent only on it would be reported as such.

### 13.4 Pre-registered criterion

Stated before any mutant was scored, in the commit that adds this section:

1. S-1: every first-order mutant that is not equivalent on the domain of 13.3 is killed on row 3.
2. S-2: every such mutant is killed on row 1, by the authored cases alone.
3. S-3: every second-order mutant that is not equivalent is killed on row 3; its row 1 is reported.
4. Rows 1, 2 and 3 are reported per operator, and each survivor with its witness from the domain.
5. No corpus file changes in the change that reports the result. A survivor is an open gap until a later version closes it, and a case written for it is fitted, as K1 was.

S-2 is the test that matters for generalisation.
Row 3 includes the lattice differential of D-14, which interprets `model.json` itself, so a live specification mutant is expected to die there.
Row 1 has no such help: it asks whether the 79 authored cases, written against checker-shaped faults, also separate wrong readings of the rules.

### 13.5 What this can and cannot show

A pass shows that the corpus separates the specification from every single wrong reading in a named operator space, whatever code carries it.
The operators were written by the corpus's author, after v1.3; they are pre-registered, not blind.
The domain argument covers premise values. State values are bounded to the declared vocabulary.
A misreading the operators cannot express, or one that `model.json` shares with the checker, is not measured.

### 13.6 Result (2026-09-30)

The criterion and the catalogue were pushed in `37b1aac` at 20:08:58 +02:00 before any mutant was scored.
The run followed on the same commit's code; the raw report is `artifacts/evidence-sufficiency-spec-mutation-2026-09-30/spec-mutation.json.gz`.

| Set | Mutants | Equivalent on the domain | Live | Row 1 | Row 2 | Row 3 |
|---|---:|---:|---:|---:|---:|---:|
| first order | 446 | 54 | 392 | 380 | 356 | 392 |
| second order | 300 | 2 | 298 | 298 | 294 | 298 |

| Criterion | Result |
|---|---|
| S-1, every live first-order mutant killed on row 3 | met, 392 of 392 |
| S-2, every live first-order mutant killed on row 1 | **not met**, 380 of 392 |
| S-3, every live second-order mutant killed on row 3 | met, 298 of 298; row 1 also 298 |

Every live mutant of eight operators dies on row 1; the twelve that do not are all `add_premise` on the admission claim.
Each makes one arm of the `admission_present` branch require a premise of the other arm.
Six make a present, accepted and matching admission also depend on `mandatory_admission`, `window_finalized` or `admission_coverage_complete`.
The other six make the absence arm also depend on `admission_source_accepted` or `admission_matches` before it can return VIOLATED.
The only decisive admission cases, A01 and A03, set every premise of both arms to `true`, so the cases cannot see the leak.
Row 3 kills all twelve, and only through the reference model; they are NEGATIVE_RESULTS.md §68, an open gap.

All 54 equivalent mutants are `add_premise` edits that require a premise an earlier guard on the same path already requires.
None of them is killed on row 3, which is the consistency check the computation allows: a mutant the domain calls equivalent must not fail the runner.
Row 2 misses 36 live mutants: the twelve above, and 24 that change only a decisive verdict, which carries no guidance under rule R-6.

As section 13.4 item 5 requires, no corpus file changed in the change that reports this.
`scripts/spec_mutation_evidence_sufficiency.py` now runs in the mutation workflow against `docs/assurance/spec_mutation_baseline_evidence_sufficiency_v1.txt`, which named the twelve as `row1` survivors until v1.4 emptied it (section 14.6).
The v1.3 row reproduces with `--suite evidence-sufficiency-v1.3`.

## 14. Rule coverage and v1.4, pre-registered

### 14.1 Why a criterion and not another case list

Every repair so far has been a list of cases written against a list of faults: G1 to G5, H1, I1, K1.
Section 13 found a family none of those lists contained, and killing its twelve mutants by name would repeat the pattern.
This section defines adequacy from the specification alone, with no fault list, and derives the missing cases from it by a fixed rule.
It then tests the criterion on faults it was not built from.

### 14.2 The criterion

`scripts/rule_coverage_evidence_sufficiency.py` reads the decision ladders of `model.json`.
Every decisive outcome has a path condition: the premises read on the way to it, each with the boolean it must have.
Three obligations follow for the authored cases, in the manner of modified condition/decision coverage (Chilenski and Miller, 1994), per outcome rather than per decision:

| Rule | Obligation |
|---|---|
| RC-1, off-path independence | for every premise the path to an outcome does not read, a case expecting that outcome sets it to `false` |
| RC-2, on-path necessity | for every premise on the path, a case meets the rest of the path condition and has this premise at the opposite boolean or absent |
| RC-3, on-path typing | the same, with the premise at a non-boolean value |

The model has 80 obligations. The 79 cases of v1.3 discharge 58 and leave 22 open.
Five of the open ones are the §68 family (RC-1 on the two admission outcomes).
The other seventeen name faults no catalogue has generated.
For example, no case meets the VIOLATED admission path with the execution observation unaccepted.
So no case was built to tell apart a checker that checks execution and scope acceptance only before ESTABLISHED; whether some case does so by accident is H-3 below.

### 14.3 The derivation rule, fixed now

For each open obligation, `--derive` builds one case from the configuration that meets the path condition with every off-path premise `true`.
It then sets the one premise to `false` (RC-1), to the opposite boolean (RC-2), or to `1` for a `true` requirement and `0` for a `false` one (RC-3).
The expected verdict is the model's; identical observation sets merge; ids continue each claim's numbering; the cases carry gap `L1`.
On the v1.3 corpus the rule yields 22 cases, A26 to A36 and B27 to B37.
Their digest (`python scripts/rule_coverage_evidence_sufficiency.py --suite evidence-sufficiency-v1.3 --derive --sha256`) is `2b1838624cdacdf29a0fff461fcb5913497eebec8c5f5a31bb24e2d4c5b361df`.
`conformance/evidence-sufficiency-v1.4/` will be the v1.3 corpus verbatim plus exactly these cases.
Its runner will add one section that fails on any open obligation, so a later change to `model.json` creates its own obligations without a new fault list.

### 14.4 The held-out catalogue

`python scripts/spec_mutation_evidence_sufficiency.py --catalogue heldout` adds two operators section 13 does not have, and a third-order sample.

| Operator | Mutants | What it seeds |
|---|---:|---|
| `guard_sink` | 12 | a guard that precedes a branch applies to one arm only |
| `guard_hoist` | 7 | a guard inside one arm moves above the branch, so both arms need it |
| third order | 300 | a fixed-seed (20261002) sample of triples on one claim, drawn from both catalogues, whose edits compose on three distinct steps |

Its digest is `8723a9d11601a2c58a2dc105d11d0f38eead9339ab0d1200e6d609a62078d7aa`.
No mutant of it has been scored against any corpus at the commit that adds this section.

### 14.5 Pre-registered predictions

1. H-1, the test of the criterion: v1.4 kills every live mutant of the held-out catalogue on row 1, by the authored cases alone.
2. H-2: v1.4 leaves no rule-coverage obligation open, and meets S-2 of section 13 on the first catalogue. Both hold by construction, and the §68 cases are fitted.
3. H-3, reported and not a criterion: row 1 of the held-out catalogue on v1.3.
4. If H-1 fails, its survivors are published as open gaps, and the derivation rule does not change in the change that reports them.

For the 19 first-order held-out mutants, the criterion predicts H-1 by argument.
A guard that sinks into one arm leaves a premise off that arm's path, and an RC-2 case on that arm's outcome tells it apart.
A guard that is hoisted puts a premise on the other arm's path, and an RC-1 case tells that apart.
So the run tests the argument and its implementation. The 300 third-order mutants have no such argument.
The criterion was written after section 13 had named the §68 family, by the corpus's author; it is pre-registered, not blind.

### 14.6 Result (2026-09-30)

The criterion, the derivation digest and the held-out catalogue were pushed in `f3ba6d0` at 20:31:19 +02:00, before v1.4 existed and before any held-out mutant was scored.
`conformance/evidence-sufficiency-v1.4/` was then built by the derivation, and its cases hash to the pre-registered digest.
The raw reports are in `artifacts/evidence-sufficiency-spec-mutation-2026-09-30/`.

| Prediction | Result |
|---|---|
| H-1, v1.4 kills every live held-out mutant on row 1 | met: 19 of 19 first-order, 300 of 300 third-order |
| H-2, v1.4 discharges every obligation and meets S-2 | met: 80 of 80 obligations; 392 of 392 live first-catalogue mutants on row 1, 298 of 298 second-order |
| H-3, v1.3 on the held-out catalogue, reported | 18 of 19 first-order and 300 of 300 third-order on row 1 |

H-1 is weak evidence, and this section says so rather than letting the table say otherwise.
v1.3 already killed 318 of the 319 held-out mutants on row 1.
The one it missed, `guard_hoist:admission_accounting:0`, makes the absence arm require an accepted admission source, a member of the §68 family.
So the held-out catalogue could separate v1.4 from v1.3 on one mutant, and it was not the family the criterion's other obligations aim at.
The guard-placement mutants that RC-2 was expected to need were already killed by v1.3 cases that happen to cross the same guards.

The derived cases split the same way.
On row 1, only five of the 22 L1 cases kill a mutant of either specification catalogue that no other case kills.
They are A26, A27 and A28 (RC-1 on ESTABLISHED) and A32 and A33 (RC-1 on VIOLATED), the §68 family.
The other seventeen are required by the criterion and are redundant against every fault list measured so far.
The AST operator set of section 6.8, rerun with the v1.4 runner, gives the same 901 of 905, and no kill in it rests on an L1 case alone.
NEGATIVE_RESULTS.md §69 records both points.
The criterion stays, because it needs no fault list and gates the runner, but its measured value is those five cases.

## 15. v1.5: classes instead of fault lists

### 15.1 What the first blind probe showed

The probe of NEGATIVE_RESULTS.md §70 scored faults that nobody chose with the corpus in view.
On decision logic the runner was already close to complete: 80 of 83 decision faults died on row 3.
What survived lay in classes that no fault list had reached: a `null` state, input container types, near misses of `premise_source`, and aliasing of returned values.
Row 1 missed absence as the third arm of a branch premise and the order of two failing guards.
Every earlier repair added cases or rejections for named faults, and v1.4's 22 cases added no kill on blind faults.
v1.5 therefore adds classes.
Each new check is generated from a type or value class, or from the model's structure, and none names a fault.

### 15.2 Mechanisms

| Mechanism | Generated from | Checked by |
|---|---|---|
| Rule-coverage profile v2, RC-V | every premise of every decisive path, on and off it, in each of eight value classes (`true`, `false`, absent, `null`, `1`, `0`, truthy, falsy) | runner section 13; 274 derived cases, gap N1 |
| RC-P | every ordered pair of guards on each decisive path, both failing | section 13 |
| RC-S | a fixed set of 26 state pairs: `null`, zero, `false`, empty containers, key order, case, whitespace, Unicode normal form, `1` against `true` | section 13; also added to the model lattice |
| Input contract | every observations container class (`dict`, `MappingProxyType`, `OrderedDict`, a user `Mapping`); 24 non-JSON value classes at five positions each; 15 near misses of `premise_source`; 11 near misses of each claim | runner section 14 |
| Return isolation | every case: mutate the returned dictionary, the observations and the scope after the call; the verdict must not change | runner section 15 |
| Wider lattice | `model.json` with 11 more state values and 5 more typed premise values; the rules unchanged | runner section 11 (155,319 documents) |

The derivation over the v1.4 corpus hashes to `7c2712a5f8b39c29e4419113b20bce2ca4373e7ed35613ca81d7065b04a51269` (`python scripts/rule_coverage_evidence_sufficiency.py --suite evidence-sufficiency-v1.4 --profile v2 --derive --sha256`).
`tests/test_evidence_sufficiency_v1_5.py` shows each generated section catching a fault of its class.

### 15.3 A defect in the frozen checker

Section 15 found one while it was being written.
`_scope` copies the caller's scope shallowly.
A list nested in the scope is shared with the verdict and with `as_dict()`, so the caller can change a verdict after the call.
The checker stays frozen, so section 15 pins isolation at the top level only, and the record lists the defect under `limits`.
A v2 checker should copy deeply. An unhashable claim raises `TypeError` rather than `ValueError`, also recorded and left outside section 14.

### 15.4 How it is measured

The first probe's faults motivated v1.5, so v1.5's kills of them are fitted.
The test is a second probe, generated by six context-free agents on three model sizes and committed in `a5614b9` before v1.5 was committed.
Its criteria are in `artifacts/evidence-sufficiency-blind-probe-2-2026-09-30/PREREGISTRATION.md`.

### 15.5 Result (2026-09-30)

| Probe 2, 77 decision faults | Row 1 | Row 3 |
|---|---:|---:|
| v1.4 | 73 | 74 |
| v1.5 | 76 | 77 |

v1.5 kills five probe-2 faults that v1.4 misses entirely.
Three treat a `null` state as missing, one refuses a non-dict `Mapping`, and one accepts any `premise_source` beginning with `synthetic_fixture`.
That last form is not among the listed near misses, and the class check catches it anyway.
All five belong to classes the first probe named, so the result shows the class checks generalising within those classes.
It does not show generalisation to classes nobody has named.
One probe-2 fault survives both suites: P2C-20 breaks the value equality of the verdict object, a class no check reads (NEGATIVE_RESULTS.md §71).
The first probe's 96 faults all die on row 3 of v1.5; that is fitted and reported only.
The specification gate now scores v1.5, and both specification catalogues still leave no survivor on either row.
The raw scores are in `artifacts/evidence-sufficiency-v1.5-scores-2026-09-30/` and in the probe's `results/`.

## 16. v1.6: the whole public API against an executable contract

Every earlier check reads a verdict through `as_dict()` or `(status, reason)`.
Held-out probe 2 found a fault outside that view: verdicts that no longer compare equal.
Adding an equality check would repair that fault and no other, so section 16 of the v1.6 runner compares everything a caller can observe against an executable contract.
The contract is `reference_envelope`, written from `model.json` and `guidance.json`.

| Projection | What must hold, on each of 2,000 seeded inputs |
|---|---|
| `as_dict` | equal to the contract, with exact types (`list` not `tuple`, `bool` not `int`) |
| fields | `status` is an `EvidenceStatus`, `claim` is the claim, `missing_evidence` is a tuple |
| equality, repr | two calls on equal inputs give equal verdicts with equal `repr` |
| copy, pickle | a copied, deep-copied or pickled and restored verdict equals the original |
| input_mutated | observations and scope are unchanged after the call, at every depth |
| order | the same inputs in another order give the same verdicts |
| module_state | every module-level container is unchanged by the whole run |
| enum | `EvidenceStatus` has its three members, each equal to its string value |

The inputs mix one-deviation configurations (every guard met but one premise, both arms of each branch) with fully random premises, states and scopes of any JSON value.
Together they reach every reason of every claim.
`tests/test_evidence_sufficiency_v1_6.py` shows the projections catching faults of four classes.
The contract shares its author with the checker, so a shared misreading is not caught.
Held-out probe 3 was locked in `00aa914` before v1.6 was committed; it tests whether the projections reach classes nobody named.

### 16.1 Result (2026-09-30)

Probe 3 has 104 faults, from four new scenarios and two new implementation styles.
v1.6 kills all 61 decision faults on rows 1 and 3, and 97 of 104 faults in all (v1.5: 94).
It adds three kills. One is in the class probe 2 named (verdict equality); two are in classes nobody named: a plain `Enum` in place of `StrEnum`, and a list in place of a tuple on the verdict.
So the whole-API differential caught faults in classes it was not built from, which no earlier mechanism had done.
Seven faults survive. Two are labelled equivalent under the `assess` contract, and five are open gaps outside the decision logic (NEGATIVE_RESULTS.md §72).
Three of the five concern state that crosses calls: a shared default scope, and scope validation skipped for empty observations.
The other two concern the public types themselves: a keyword-only constructor and an alias enum member.

## 17. v1.7: the API surface, call sequences and the crossed contract

Probe 3's open survivors share one property: each check before v1.7 looks at one call at a time, and at the values a call returns.
None looks at the public names and signatures of the module, or at what one call leaves behind for the next.
v1.7 is v1.6 verbatim plus three runner sections, one per class.

| Section | Generated from | What must hold |
|---|---|---|
| 17, API surface | `inspect` over every public name the module defines | names, function signatures, dataclass options and fields, enum members by name and value, and the claim table equal `api_surface.json` |
| 18, call sequences | 300 seeded sequences of 6 calls from the section-16 generator | between calls, every object the caller holds (returned dictionaries, `verdict.scope`, inputs) is mutated, and every call still meets the contract |
| 19, contract crossing | every non-JSON value class × three positions × every claim × three observation shapes (empty, one premise, full) | every combination is refused with `ValueError` |

`api_surface.json` is a snapshot of the frozen checker, so section 17 pins what is, not what a specification requires.
It is identical on CPython 3.11 and 3.14.
`tests/test_evidence_sufficiency_v1_7.py` shows each section catching a fault of its class.
Held-out probe 4 was locked in `2954a48` before v1.7 was committed.

### 17.1 Result (2026-10-01)

v1.6 and v1.7 both kill all 63 decision faults of probe 4 on row 3. Over all 104 faults, v1.7 kills 93 and v1.6 kills 90.
The three new kills lie in classes probe 3 named, and one is a new member of its class: memoised verdicts shared between callers.
Five survivors are labelled equivalent and one out of scope; five are open (NEGATIVE_RESULTS.md §73).
The open ones are a size boundary (lists longer than 32 items), a container crossed with an invalid value, and three properties of the public types: `slots`, case-insensitive enum lookup, and key order.
Nine of the eleven survivors come from the selector that was told how thorough the suite is.

## Deliverables

- This spec.
- `conformance/evidence-sufficiency-v1.3/`, passing all acceptance criteria.
- `scripts/mutation_evidence_sufficiency.py` and `docs/assurance/mutation_baseline_evidence_sufficiency_v1.txt`.
- `scripts/mutation_evidence_sufficiency_ast.py`, `docs/assurance/mutation_baseline_evidence_sufficiency_ast_v1.txt` and `conformance/evidence-sufficiency-v1.3/model.json`.
- `tests/test_evidence_sufficiency_v1_3.py`.
- The `evidence-sufficiency` job in `.github/workflows/mutation.yml`.
- `scripts/spec_mutation_evidence_sufficiency.py` and section 13.
- `scripts/rule_coverage_evidence_sufficiency.py`, section 14 and `conformance/evidence-sufficiency-v1.4/`.
- Section 15 and `conformance/evidence-sufficiency-v1.5/`.
- Section 16 and `conformance/evidence-sufficiency-v1.6/`.
- Section 17 and `conformance/evidence-sufficiency-v1.7/`.
