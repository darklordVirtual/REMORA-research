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

A rejection contract, gap `J1`: ten inputs in `cases.json` and ten that JSON cannot express in the runner.
Each must be refused with `ValueError`, never assessed and never refused with another exception class.
They cover an unknown or null claim, non-mapping observations, floats at any depth, a float in the scope and a foreign premise source.
The runner's own table covers tuples, sets, bytes, non-string keys, NaN and subclasses of `str`, `list` and `dict`.
The scope is outside this contract: the frozen checker converts it with `dict()`.
A sequence of pairs is therefore accepted as a scope, and a value `dict()` cannot convert raises `TypeError`, not `ValueError`.
The run record lists this under `limits`; it is recorded and not repaired, because the checker stays frozen.

A reference model, `model.json`: a table-driven restatement of the rules, interpreted by the runner over every combination of premise values, a typed sweep and every state pair (61,544 documents).
The checker must agree with it at every point, so a fault that changes any verdict on that lattice is caught whether or not a case reaches it.

Twenty-three lattice-derived cases, gap `K1` (A17 to A25, B18 to B26, E24 to E28).
Each types one premise (`1`, or `0` for an `is not False` guard) on an otherwise decisive configuration.
They were computed as the smallest cover of the 42 faults that only the reference model caught in the second operator set, and each names the faults it separates.

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
`scripts/mutation_evidence_sufficiency_ast.py` applies a second operator set that mutmut does not have, 705 first-order and 200 second-order mutants, scores them in process, and reports which checks each kill rests on.
It leaves 4 survivors, named in `docs/assurance/mutation_baseline_evidence_sufficiency_ast_v1.txt`.
Both gates fail on a survivor that is in neither place.

## Run

```bash
python conformance/evidence-sufficiency-v1.3/run_evidence_sufficiency.py --out /tmp/es-v1.3.json
python conformance/evidence-sufficiency-v1.3/run_evidence_sufficiency.py --check
python scripts/mutation_evidence_sufficiency.py
python scripts/mutation_evidence_sufficiency_ast.py
```

The earlier rows of the spec's section 7 have their own commands, and their raw outputs are in `artifacts/evidence-sufficiency-mutation-2026-09-30/`.

```bash
python scripts/mutation_evidence_sufficiency.py --scoring-suite evidence-sufficiency-v1.2
python scripts/mutation_evidence_sufficiency_ast.py --corpus first-run
python scripts/mutation_evidence_sufficiency_ast.py --corpus without-k1
python scripts/mutation_evidence_sufficiency_ast.py --workers 1   # where a process pool is refused
```

mutmut refuses native Windows; run the first command in WSL or a Linux container.

## Non-claims

The I1 cases, the rejection set, the envelope checks and the relations were written after the sweep named the gaps, and the K1 cases were derived from the second operator set.
Their kills of those mutants are expected by construction and are not independent evidence.
Two operator sets are two samples of the fault space; a mutant neither generates is not measured.
The reference model shares its author and its specification with the checker, so their agreement cannot catch a misreading both share.
A killed mutant says nothing about the correctness of the checker, and a relation that holds on this corpus is known to hold only on this corpus.
No run under section 8 of the design has happened.
An independent analysis chose 43 faults without reading v1.3 but hashed them locally, not publicly, so it does not meet that protocol (`docs/assurance/external_adequacy_evidence_sufficiency_v1.md`).
Everything under "Non-claims" in the v1.1 and v1.2 READMEs applies here unchanged.
