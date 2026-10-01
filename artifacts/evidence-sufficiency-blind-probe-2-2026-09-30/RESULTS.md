# Held-out probe 2: result

The faults here were committed in `a5614b9` (22:50:40 +02:00) and v1.5 in `6dbd4a5` (22:52:22 +02:00), both before any file here was scored.
Raw results are in `results/`.

## Controls

`p2d/correct.py` and `p2f/correct.py` pass every row on v1.4 and v1.5.
`p2e/correct.py`, meant to be correct, compares states with Python `==`, so `1` equals `true`; both suites kill it (case E08), and it is counted as a fault.
C-0 is met for the two correct controls; the third was not correct.

## Decision faults

A decision fault changes a verdict on the probe domain: 40 of the 60 code faults and all 37 implementations.

| Corpus | Row 1, authored cases alone | Row 3, runner |
|---|---|---|
| v1.4 | 73 of 77 | 74 of 77 |
| v1.5 | 76 of 77 | 77 of 77 |

Over all 97 faults, row 3 kills 91 on v1.4 and 96 on v1.5.

## Criteria

| Criterion | Result |
|---|---|
| C-1, v1.5 kills at least as many decision faults as v1.4 on rows 1 and 3 | met: +3 on each row |
| C-2, every fault killed on row 3 of v1.5 | **not met**: P2C-20 survives |

## What v1.5 added

| Fault | What it does | v1.4 | v1.5 | Caught by |
|---|---|---|---|---|
| P2C-16, p2d/variant_07, p2f/variant_10 | a present `null` state is treated as missing | survives | killed on rows 1 to 3 | RC-S cases and the wider lattice |
| P2C-09 | observations that are a `Mapping` but not a `dict` are refused | survives | killed on row 3 | section 14, containers |
| P2C-10 | any `premise_source` that starts with `synthetic_fixture` is accepted | survives | killed on row 3 | section 14, near misses; its exact form was not among the listed variants |

All three classes are ones the first probe named.
They recur here in faults written independently, on three model sizes, before v1.5 existed.
So the probe shows the class checks catching new members of the classes, not a new class.

## Survivor

P2C-20 makes two identical calls return verdicts that compare unequal: the verdict loses value equality.
Every check compares `as_dict()` output, never the verdict objects, so nothing sees it.
Label: open gap, a class none of the probes had named (NEGATIVE_RESULTS.md §71).

The remaining row-1 miss among decision faults is P2B-01. It crashes only when no scope is given, which authored scoring never does; row 3 kills it as a crash.
