# Evidence Sufficiency Conformance Review v1.7

**Status:** research/conformance artifact. Synthetic author-run only. Not a standard, certification, production control, APS result or CoSAI deliverable.

v1.7 is the current corpus for the unchanged v1 checker. It is v1.6 verbatim plus three runner sections.

- Section 17 compares the module's public API surface (names, signatures, dataclass options, enum members by name) with `api_surface.json`.
- Section 18 runs 300 seeded sequences of calls and mutates every object the caller holds between calls; every call must still meet the contract.
- Section 19 crosses every invalid value class with every position, claim and observation shape, empty included.

The design is section 17 of [`docs/design/evidence-sufficiency-v1.3.md`](../../docs/design/evidence-sufficiency-v1.3.md).

## Run

```bash
python conformance/evidence-sufficiency-v1.7/run_evidence_sufficiency.py --check
```

## Non-claims

Sections 17 to 19 were written after held-out probe 3 named their classes; their kills of those faults are not independent evidence.
`api_surface.json` pins the frozen checker as it is, not as a specification would require it.
Everything under "Non-claims" in the v1.6 README applies here unchanged.
