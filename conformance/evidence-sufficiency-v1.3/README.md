# Evidence Sufficiency Conformance Review v1.3

**Status:** research/conformance artifact. Synthetic author-run only. Not a standard, certification, production control, APS result or CoSAI deliverable.

v1.3 is an additive corpus for the unchanged v1 checker.
It exists because a systematic mutation sweep over `checker.py` found 112 mutants that no v1.2 check could tell apart ([NEGATIVE_RESULTS.md §65](../../NEGATIVE_RESULTS.md)).
The design, the decisions and the research grounding are in [`docs/design/evidence-sufficiency-v1.3.md`](../../docs/design/evidence-sufficiency-v1.3.md).
The three external runs with hand-picked faults are recorded in [`docs/assurance/external_adequacy_evidence_sufficiency_v1.md`](../../docs/assurance/external_adequacy_evidence_sufficiency_v1.md).

## What is frozen

`conformance/evidence-sufficiency-v1/`, `-v1.1/` and `-v1.2/` are not modified.
The runner here imports `../evidence-sufficiency-v1/checker.py` and records its sha256.
The first 53 cases in `cases.json` are the v1.2 cases, equal as JSON values and in the same order.
`guidance.json` and `ladders.json` are byte-for-byte copies of the v1.2 files, and every v1.1 and v1.2 runner check carries over.

## What is added

Three postcondition cases, gap `I1`, for the key order of a mapping:

| Case | Expected state | Observed state | Expected verdict | Fault it tells apart |
|---|---|---|---|---|
| E21 | `{"state":"closed","lock":"held"}` | `{"lock":"held","state":"closed"}` | ESTABLISHED | key order compared |
| E22 | `{"members":["closed","locked"]}` | `{"members":["locked","closed"]}` | VIOLATED | nested list order erased |
| E23 | `{"outer":{"x":1,"y":2}}` | `{"outer":{"y":2,"x":1}}` | ESTABLISHED | only top-level keys sorted |

The key order in `cases.json` is the fault E21 and E23 expose, so the file is written without sorting keys and a test pins that.

A rejection contract, gap `J1`: ten inputs in `cases.json` and seven that JSON cannot express in the runner.
Each must be refused with `ValueError`, never assessed and never refused with another exception class.
They cover an unknown or null claim, non-mapping observations, floats at any depth, a float in the scope, a foreign premise source, and tuples, sets, bytes, non-string keys, a `str` subclass and NaN.

Eleven metamorphic relations, declared in `invariants.json` and executed over every case.
The runner fails on a relation it does not implement or implements without declaring.
They pin that the verdict echoes its claim and scope and that the envelope has a fixed shape.
Key order, unrelated fields and the scope never change a verdict; inputs are neither mutated nor aliased; a verdict is immutable.
The state comparison is symmetric, flipping an acceptance premise never inverts polarity, and `canonical()` separates every declared distinct pair while ignoring key order at any depth.

Every section of the runner runs under crash capture.
A checker that raises on valid input is reported as `crash:<section>:<Exception>` in `failures` instead of ending the run.

## Mutation gate

`scripts/mutation_evidence_sufficiency.py` builds a sandbox, runs mutmut over the checker with this corpus as the test, and compares the survivors with `docs/assurance/mutation_baseline_evidence_sufficiency_v1.txt`.
On this corpus 489 mutants leave 20 survivors, each named in the baseline and classified in `docs/assurance/mutation_testing_v1.md`.
The gate fails on a survivor that is in neither place.

## Run

```bash
python conformance/evidence-sufficiency-v1.3/run_evidence_sufficiency.py --out /tmp/es-v1.3.json
python conformance/evidence-sufficiency-v1.3/run_evidence_sufficiency.py --check
python scripts/mutation_evidence_sufficiency.py
```

## Non-claims

The I1 cases, the rejection set, the envelope checks and the relations were written after the sweep named the gaps.
Their kills of those mutants are expected by construction and are not independent evidence.
The sweep uses one tool and its default operators; a mutant it never generates is not measured.
A killed mutant says nothing about the correctness of the checker, and a relation that holds on this corpus is known to hold only on this corpus.
v1.3 has had no external run; section 8 of the design records the blind protocol for one.
Everything under "Non-claims" in the v1.1 and v1.2 READMEs applies here unchanged.
