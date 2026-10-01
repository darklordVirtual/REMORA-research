# Held-out probe 3: result

The faults were committed in `00aa914` (23:14:10 +02:00) and v1.6 in `f9a8a27` (23:14:38 +02:00), both before any file here was scored.
Raw results are in `results/`. Both correct implementations pass every row on v1.5 and v1.6 (D-0 met).

## Decision faults

37 of the 80 code faults and all 24 implementations change a verdict on the probe domain.
v1.5 kills all 61 on row 3 and 60 on row 1; v1.6 kills all 61 on both rows.
The one row-1 difference is P3C-20, which caches verdicts by `id()`, so whether a case hits a stale entry depends on memory reuse; both suites kill it on row 3.

## All faults

| Corpus | Row 3, of 104 |
|---|---:|
| v1.5 | 94 |
| v1.6 | 97 |

## What v1.6 added (D-1)

| Fault | What it does | Projection | Class named before? |
|---|---|---|---|
| P3C-07 | verdicts no longer compare equal | equality, copy | yes: probe 2 (P2C-20) |
| P3C-08 | `EvidenceStatus` becomes a plain `str` `Enum`, so `str(status)` changes | enum | no |
| P3C-10 | `missing_evidence` on the verdict becomes a list, while `as_dict()` is unchanged | fields | no |

Two of the three lie in classes no probe had named. The projections of section 16 caught them because they compare everything a caller observes, not a listed fault.

## Survivors (D-2 not met)

Labels were set after the result was read and before any corpus change.

| Fault | What it does | Label |
|---|---|---|
| P3C-05 | an empty-string `decisive_if` is dropped from `as_dict()` | equivalent under the `assess` contract: every `decisive_if` in the guidance table is non-empty, so no call to `assess` can build one |
| P3C-15 | `canonical()` escapes non-ASCII text | equivalent: `canonical()` is used for equality only, the argument for mutation family F in `docs/assurance/mutation_testing_v1.md` |
| P3A-18, P3C-02 | the default scope is one shared dictionary, so changing `verdict.scope` on one verdict changes later verdicts | open gap: section 15 mutates `as_dict()` copies, never the verdict's own fields |
| P3C-19 | the scope is not validated when the observations are empty | open gap: section 14 crosses value classes with positions but always with full observations |
| P3B-19 | `EvidenceVerdict` becomes keyword-only, so positional construction raises | open gap, low: the public constructor is not in any contract |
| P3C-09 | an alias member `UNKNOWN` is added to `EvidenceStatus` | open gap, low: section 16 checks member values, not names |

Every survivor is outside the decision logic. Three open gaps are about returned objects and module state across calls, and two about the public types' own API.
