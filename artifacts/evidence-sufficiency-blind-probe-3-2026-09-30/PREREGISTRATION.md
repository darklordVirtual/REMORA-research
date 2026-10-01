# Held-out probe 3 for evidence-sufficiency: pre-registration

Committed before evidence-sufficiency v1.6 was committed, and before any file here was scored or read by the maintainer beyond counting it.
v1.6 is designed from probe 2's one survivor (verdict value equality), generalised to a differential test of the whole public API.
Probe 3 asks whether that mechanism catches faults in classes nobody has named.

## What was generated

| Source | Model | Allowed input | Output |
|---|---|---|---|
| `p3a.json` | Sonnet | `checker.py`, v1 README | 20 bugs from imagined performance changes |
| `p3b.json` | Opus | same | 20 bugs from imagined modernisation changes |
| `p3c.json` | Opus | same | 20 bugs aimed at a thorough suite that checks rules, rejection, key order, typing and returned dictionaries |
| `p3d.json` | Haiku | same | 20 bugs introduced while fixing something else |
| `p3e/` | Opus | `SPEC.md` only | state-machine correct implementation and 12 one-mistake variants |
| `p3f/` | Sonnet | `SPEC.md` only | data-driven engine, the same |

No prompt mentioned equality, copying, pickling or any finding of the earlier probes.
`probe3-faults.json` is `p3a` to `p3d` in the harness format. `SHA256SUMS` pins every file listed in it.
The first `p3d` run reported success without writing its file; the same agent was asked to write it, and did.

## Criteria, fixed now

Scored on v1.5 and v1.6.

1. D-0: the correct implementations pass every row on both suites, or the failure is analysed first.
2. D-1, the test of the mechanism: the faults killed on row 3 of v1.6 but not of v1.5 are reported with their classes; the mechanism generalises to the extent that they fall outside the class probe 2 named.
3. D-2: every fault not labelled equivalent with a written argument is killed on row 3 of v1.6; survivors are published as open gaps.
4. No corpus file changes in the change that reports the result.
