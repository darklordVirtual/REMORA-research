# Blind generalisation probe of evidence-sufficiency v1.4: pre-registration

Written and pushed before any file in this directory was scored against any corpus.

## What was generated, and by whom

Six fresh AI agents (Claude, with no conversation context) produced the faults on 2026-09-30.
None was given the corpus, the tests, the design documents or any earlier fault list.

| Source | Allowed input | Output |
|---|---|---|
| `fw1.json` | `checker.py` and the v1 README only | 20 refactor and copy-paste slips |
| `fw2.json` | same | 20 semantic misreadings of the evidence rules |
| `fw3.json` | same | 20 Python and JSON pitfalls |
| `mr1/` | `SPEC.md` only | one correct early-return implementation and 12 variants, each with one misreading |
| `mr2/` | `SPEC.md` only | the same in a table-driven style |
| `mr3/` | `SPEC.md` only | the same in a nested-conditional style |

`SPEC.md` is a prose restatement of `model.json` written by the maintainer for this probe.
`blind-faults.json` is `fw1` to `fw3` converted to the format of `scripts/score_heldout_faults.py` (offsets computed; text unchanged).
`SHA256SUMS` pins every file.

## Limits known before the run

The agents were not blind in the sense of section 8 of the v1.3 spec: they are the same model family as the maintainer's assistant, and the maintainer wrote their prompts and `SPEC.md`.
They did not see the corpus. Their instructions forbade reading anything else, and each reported its file reads.

## Criteria, fixed now

Scored with `scripts/score_heldout_faults.py` (code faults) and `scripts/probe_reimplementations_evidence_sufficiency.py` (implementations), on v1.2, v1.3 and v1.4.

1. B-0, control: the three `correct.py` implementations pass all three rows on every suite. If one fails, the failure is analysed before anything else is read as a result.
2. B-1: every code fault is killed on row 3 of v1.4, unless it is labelled equivalent with a written argument before any corpus change.
3. B-2: every variant that disagrees with `model.json` on the probe domain is killed on row 3 of v1.4.
4. B-3, the generalisation indicator: the share of B-1 and B-2 faults killed on row 1 of v1.4, by the authored cases alone, reported beside v1.2 and v1.3.
5. No corpus file changes in the change that reports the result. Survivors are published with their labels.
