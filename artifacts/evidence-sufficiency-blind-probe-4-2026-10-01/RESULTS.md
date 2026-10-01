# Held-out probe 4: result

The faults were committed in `2954a48` (09:50:42 +02:00) and v1.7 in `e464829` (09:51:36 +02:00), both before any file here was scored.
Raw results are in `results/`; the survivor labels, set before any corpus change, are in `labels.json`.

## Controls

On the first scoring, both correct implementations failed row 3 of v1.7 on `api_surface:ASSESSORS`.
The cause was the implementation harness, not the implementations: it replaced the claim table with wrappers named `assess`, which section 17 reads as a changed table.
The wrappers now carry the claim's name, and both controls pass every row on v1.6 and v1.7 (E-0 met after the analysis the criterion asks for).
Earlier probes were scored on suites without section 17 and are not affected.

## Decision faults

39 code faults and all 24 implementations change a verdict on the probe domain.
v1.6 and v1.7 both kill all 63 on row 3, and 62 on row 1; the row-1 miss is p4e/variant_12, which only the runner's relations and reference model see.

## All faults

| Corpus | Row 3, of 104 |
|---|---:|
| v1.6 | 90 |
| v1.7 | 93 |

## What v1.7 added (E-1)

| Fault | What it does | Section | Class named by probe 3? |
|---|---|---|---|
| P4C-01 | the default scope is one shared dictionary | 18, call sequences | yes |
| P4C-02 | verdicts are memoised, so equal inputs return the same object and one caller's change to its scope reaches another | 18, call sequences | the class (state across calls) yes; memoisation was not among probe 3's faults |
| P4C-17 | an alias member is added to `EvidenceStatus` | 17, API surface | yes |

## Survivors (E-2 not met)

| Fault | What it does | Label |
|---|---|---|
| P4A-06, P4C-03, P4C-04 | `canonical()` escapes non-ASCII text or uses spaced separators | equivalent under the `assess` contract: `canonical()` is used for equality only (mutation family F) |
| P4C-15 | an empty-string `decisive_if` is dropped from `as_dict()` | equivalent under the `assess` contract: no guidance entry is empty |
| P4D-17 | guidance is looked up for decisive verdicts too | equivalent under the `assess` contract: no decisive reason is in the guidance table, which section 6 of the runner enforces (mutation family G) |
| P4C-20 | a scope that is not a `dict` is stored as given | out of scope: the scope's coercion is a recorded limit of the frozen checker |
| P4C-07 | list validation stops after 32 elements | open gap: no check uses a list longer than a few items |
| P4C-09 | observations that are a non-dict `Mapping` skip validation | open gap: section 14 tries those containers with valid values only, and section 19 crosses invalid values with `dict` only |
| P4C-16 | the verdict dataclass gains `slots=True` | open gap, low: section 17 omits version-dependent dataclass options |
| P4C-18 | `EvidenceStatus` looks values up case-insensitively | open gap, low: section 17 records members, not lookup behaviour |
| P4C-19 | `as_dict()` changes its key order | open gap, low: every comparison sorts keys |

Nine of the eleven survivors come from `p4c`, the selector told in general terms how thorough the suite is.
