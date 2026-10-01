# Held-out probe 4 for evidence-sufficiency: pre-registration

Committed before evidence-sufficiency v1.7 was committed, and before any file here was scored or read by the maintainer beyond counting it.
v1.7 is designed from probe 3's survivors, generalised to three mechanisms: the public API surface, sequences of calls with every held object mutated between them, and the input contract crossed with every claim and observation shape.

## What was generated

| Source | Model | Allowed input | Output |
|---|---|---|---|
| `p4a.json` | Opus | `checker.py`, v1 README | 20 bugs from extending the module (a new claim, parameter, field or helper) |
| `p4b.json` | Sonnet | same | 20 bugs from first contributions by junior developers |
| `p4c.json` | Opus | same | 20 bugs aimed at a very thorough suite, described in general terms |
| `p4d.json` | Haiku | same | 20 bugs from refactoring |
| `p4e/` | Opus | `SPEC.md` only | a rule-DSL correct implementation and 12 one-mistake variants |
| `p4f/` | Sonnet | `SPEC.md` only | a validation-first implementation and 12 variants |

The `p4c` prompt described the suite's kinds of checks in general terms, without its contents, to make the probe as hard as possible.
No prompt named any earlier fault or survivor.
`probe4-faults.json` is `p4a` to `p4d` in the harness format. `SHA256SUMS` pins every file listed in it.

## Criteria, fixed now

Scored on v1.6 and v1.7.

1. E-0: the correct implementations pass every row on both suites, or the failure is analysed first.
2. E-1: the faults killed on row 3 of v1.7 but not of v1.6 are reported with their classes, and whether probe 3 named each class.
3. E-2: every fault not labelled equivalent with a written argument is killed on row 3 of v1.7; survivors are published as open gaps.
4. No corpus file changes in the change that reports the result.
