# Evidence Sufficiency Conformance Review v1.5

**Status:** research/conformance artifact. Synthetic author-run only. Not a standard, certification, production control, APS result or CoSAI deliverable.

v1.5 is an additive corpus for the unchanged v1 checker. [v1.6](../evidence-sufficiency-v1.6/README.md) carries it verbatim and is now the current corpus; v1.5 is frozen.
It exists because a blind probe found faults that survive every row of v1.4 ([NEGATIVE_RESULTS.md §70](../../NEGATIVE_RESULTS.md)), and they lay in classes no fault list had reached.
The design is section 15 of [`docs/design/evidence-sufficiency-v1.3.md`](../../docs/design/evidence-sufficiency-v1.3.md).

## What is frozen

`conformance/evidence-sufficiency-v1/` to `-v1.4/` are not modified.
The first 101 cases are the v1.4 cases, in order; `guidance.json`, `ladders.json` and `invariants.json` are byte-for-byte copies.
`model.json` keeps the v1.4 rules and widens only its lattice.

## What is added

- 274 cases, gap N1, derived by rule-coverage profile v2: every premise in every value class on and off each decisive path, every ordered pair of failing guards, and 26 state pairs.
- Section 13 of the runner fails on any profile-v2 obligation left open.
- Section 14 generates the input contract: container types, 24 non-JSON value classes at five positions, near misses of `premise_source` and of each claim.
- Section 15 checks that no returned value aliases the verdict and no later change to the caller's input reaches it.

## Run

```bash
python conformance/evidence-sufficiency-v1.5/run_evidence_sufficiency.py --check
python scripts/rule_coverage_evidence_sufficiency.py --suite evidence-sufficiency-v1.5 --profile v2
```

## Non-claims

The N1 cases and the generated sections were written after the first blind probe named their classes; their kills of that probe's faults are not independent evidence.
The frozen checker copies a scope shallowly, so a nested scope value is shared with the verdict; section 15 checks the top level only.
Everything under "Non-claims" in the v1.4 README applies here unchanged.
