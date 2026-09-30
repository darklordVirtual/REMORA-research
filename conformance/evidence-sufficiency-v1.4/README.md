# Evidence Sufficiency Conformance Review v1.4

**Status:** research/conformance artifact. Synthetic author-run only. Not a standard, certification, production control, APS result or CoSAI deliverable.

v1.4 is an additive corpus for the unchanged v1 checker.
It exists because pre-registered specification mutation of `model.json` found twelve cross-branch premise faults that no v1.3 case could tell apart ([NEGATIVE_RESULTS.md §68](../../NEGATIVE_RESULTS.md)).
The design, the pre-registration and the result are sections 13 and 14 of [`docs/design/evidence-sufficiency-v1.3.md`](../../docs/design/evidence-sufficiency-v1.3.md).

## What is frozen

`conformance/evidence-sufficiency-v1/` to `-v1.3/` are not modified.
The first 79 cases in `cases.json` are the v1.3 cases, equal as JSON values and in the same order, and the rejection set is the same.
`guidance.json`, `ladders.json`, `invariants.json` and `model.json` are byte-for-byte copies of the v1.3 files.
The runner is the v1.3 runner with one section added; every earlier check carries over.

## What is added

A criterion instead of a fault list.
Every decisive outcome of `model.json` has a path condition: the premises read on the way to it, each with the boolean it must have.
Three rule-coverage obligations follow, per outcome:

| Rule | Obligation |
|---|---|
| RC-1 | every premise off the path is set to `false` in some case that still expects the outcome |
| RC-2 | every premise on the path is at the opposite boolean or absent in some case that meets the rest of the path |
| RC-3 | the same, with the premise at a non-boolean value |

The model has 80 obligations. v1.3 discharged 58.

Twenty-two cases, gap `L1` (A26 to A36, B27 to B37), one per open obligation.
They were produced by the derivation rule of section 14.3, whose output digest was pushed before the cases were scored against anything.
Each case names the obligations it discharges.

A twelfth runner section, `rule_coverage`, fails on any obligation no authored case discharges.
The obligations come from the model, so a later change to its rules creates its own obligations without a new fault list.

## Result

The predictions of section 14.5 were met.

| Measure | v1.3 | v1.4 |
|---|---|---|
| rule-coverage obligations discharged | 58 of 80 | 80 of 80 |
| specification mutants, first catalogue, live, killed on row 1 | 380 of 392 | 392 of 392 |
| held-out catalogue, first order, killed on row 1 | 18 of 19 | 19 of 19 |
| held-out catalogue, third order, killed on row 1 | 300 of 300 | 300 of 300 |

## Run

```bash
python conformance/evidence-sufficiency-v1.4/run_evidence_sufficiency.py --check
python scripts/rule_coverage_evidence_sufficiency.py --suite evidence-sufficiency-v1.4
python scripts/spec_mutation_evidence_sufficiency.py
python scripts/spec_mutation_evidence_sufficiency.py --catalogue heldout --json heldout.json
```

The two code-level mutation gates (`scripts/mutation_evidence_sufficiency.py` and `scripts/mutation_evidence_sufficiency_ast.py`) still score v1.3.
v1.4 runs every v1.3 check on a superset of its cases, so a mutant v1.3 kills, v1.4 kills too.

## Non-claims

The five RC-1 cases that kill the §68 mutants are fitted: section 13 named that family before the criterion was written.
The held-out test had little power. v1.3 already killed 318 of the 319 held-out mutants, and the one it missed is of the §68 family (NEGATIVE_RESULTS.md §69).
Seventeen of the 22 L1 cases kill no mutant that another case does not also kill, in either specification catalogue or the AST operator set; mutmut was not rerun on v1.4.
They are there because the criterion requires them.
Rule coverage is complete relative to the decision ladders of `model.json` only; a rule the model does not express, or a misreading the model shares with the checker, is not covered.
Everything under "Non-claims" in the v1.3 README applies here unchanged.
