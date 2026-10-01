# Held-out probe 2 for evidence-sufficiency: pre-registration

Committed before evidence-sufficiency v1.5 was committed, and before any file here was scored or read by the maintainer beyond counting it.
v1.5 is being designed from the findings of the first probe (`artifacts/evidence-sufficiency-blind-probe-2026-09-30/`); these faults exist before it, so they cannot have been fitted to it.

## What was generated

Six context-free agents on 2026-09-30, on three model sizes, none shown the corpus, the tests, the designs or earlier fault lists:

| Source | Model | Allowed input | Output |
|---|---|---|---|
| `p2a.json` | Sonnet | `checker.py`, v1 README | 20 bugs introduced by imagined feature pull requests |
| `p2b.json` | Haiku | same | 20 bugs of ordinary maintenance |
| `p2c.json` | Opus | same | 20 bugs chosen to evade a good but ordinary test suite |
| `p2d/` | Sonnet | `SPEC.md` only | object-oriented correct implementation and 12 one-mistake variants |
| `p2e/` | Haiku | same | functional style, the same |
| `p2f/` | Opus | same | defensive production style, the same |

The prompts named no fault category for `p2b` and `p2c` and did not mention any finding of the first probe.
`probe2-faults.json` is `p2a` to `p2c` in the harness format. `SHA256SUMS` pins every file.

## Criteria, fixed now

Scored on v1.4 and v1.5 with `scripts/score_heldout_faults.py` and `scripts/probe_reimplementations_evidence_sufficiency.py`.

1. C-0: the three correct implementations pass every row on both suites.
2. C-1, the generalisation test: of the decision faults (those that change a verdict on the probe domain), v1.5 kills at least as many as v1.4 on row 1 and on row 3, and the difference is reported with the faults behind it.
3. C-2: every fault not labelled equivalent (with a written argument) is killed on row 3 of v1.5; survivors are published as open gaps.
4. No corpus file changes in the change that reports the result.
