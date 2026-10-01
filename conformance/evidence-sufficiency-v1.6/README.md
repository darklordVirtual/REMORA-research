# Evidence Sufficiency Conformance Review v1.6

**Status:** research/conformance artifact. Synthetic author-run only. Not a standard, certification, production control, APS result or CoSAI deliverable.

v1.6 is the current corpus for the unchanged v1 checker. It is v1.5 verbatim plus one runner section.
Section 16 compares the checker's whole public API with an executable contract on 2,000 seeded inputs.
It covers the returned dictionary with exact types, the verdict's value semantics under repetition, copying and pickling, the enum contract, deep non-mutation of the inputs, order independence and the module's own state.
The design is section 16 of [`docs/design/evidence-sufficiency-v1.3.md`](../../docs/design/evidence-sufficiency-v1.3.md).

## Run

```bash
python conformance/evidence-sufficiency-v1.6/run_evidence_sufficiency.py --check
```

## Non-claims

Section 16 was written after held-out probe 2 named one fault outside the `as_dict()` view; its kill of that fault is not independent evidence.
The contract shares its author with the checker, and the inputs are a seeded sample, not an enumeration.
Everything under "Non-claims" in the v1.5 README applies here unchanged.
