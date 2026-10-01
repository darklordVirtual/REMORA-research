# Blind generalisation probe of evidence-sufficiency v1.4: result

The criteria in `PREREGISTRATION.md` were pushed in `a0c3d32` (2026-09-30T22:34:09+02:00) before any file here was scored.
Raw results are in `results/`.

## Decision faults

A decision fault changes `status` or `reason` for some valid input.
All 36 variants are decision faults: each disagrees with `model.json` on the probe domain.
So are 47 of the 60 code faults; the other 13 change validation, the envelope or guidance only.

| Corpus | Row 1, authored cases alone | Row 3, runner |
|---|---|---|
| v1.2 | 57 of 83 | 66 of 83 |
| v1.3 | 76 of 83 | 80 of 83 |
| v1.4 | 76 of 83 | 80 of 83 |

## Criteria

| Criterion | Result |
|---|---|
| B-0, the three correct implementations pass every row on every suite | met |
| B-1, every code fault killed on row 3 of v1.4 | **not met**: 56 of 60; FW3-09, FW3-17, FW3-19 and FW3-20 survive |
| B-2, every variant killed on row 3 of v1.4 | **not met**: 34 of 36; mr2/variant_11 and mr3/variant_10 survive |
| B-3, row 1 of v1.4 on decision faults | 76 of 83 (v1.3 the same, v1.2 57) |

## Survivors and labels

Labels were set after the result was read and before any corpus change. None is labelled equivalent.

| Fault | What it does | Label |
|---|---|---|
| FW3-09, mr2/variant_11, mr3/variant_10 | a state that is present with value `null` is treated as missing | open gap: `null` is a JSON value the checker accepts, and neither the cases nor the model's state lattice contain it. Three selectors found it independently |
| FW3-17 | observations that are a `Mapping` but not a `dict` are refused | open gap, low: the signature accepts any `Mapping`; no check passes one |
| FW3-19 | `premise_source` is case- and space-normalised before the guard | open gap: the rejection contract tries only `production` and the empty string |
| FW3-20 | `as_dict()` returns the verdict's own scope mapping | open gap: MR-7 checks aliasing of the caller's scope, not of the returned dictionary |

Row 1 of v1.4 misses seven decision faults, and row 3 kills four of them.
Three code faults (FW2-04, FW2-09, FW3-08) read an absent branch premise (`admission_present`, `protected_effect_observed`) as `false`; the runner kills them.
Rule coverage did not ask for that witness: RC-2 accepts the opposite boolean, and for a branch premise absence is a third arm.
mr2/variant_04 checks the admission source only when the candidate matches, so two inconclusive reasons trade places; only the reference model sees it, because no case has both premises false.
FW3-09 and the two `null`-state variants are the other three, and no row kills them.

## Reading

On blind faults, v1.3 and v1.4 are the same corpus: the 22 rule-coverage cases of v1.4 added no kill.
The corpus generalises well on its own decision logic: row 3 kills 80 of 83 decision faults, and every miss is the `null` state.
Its weak side is the part no fault list had reached: `null` as a value, input types and normalisation, and aliasing of returned values.
The probe is not a run under section 8: the agents share a model family with the maintainer's assistant, and the maintainer wrote their prompts and `SPEC.md`.
