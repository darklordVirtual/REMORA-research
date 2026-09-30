# Evidence Sufficiency Conformance Review v1.2

**Status:** research/conformance artifact. Synthetic author-run only. Not a standard, certification, production control, APS result or CoSAI deliverable.

v1.2 is an additive corpus for the unchanged v1 checker.
It exists because an external run with withheld faults found three changes to `canonical()` that the v1.1 cases could not tell apart ([NEGATIVE_RESULTS.md §64](../../NEGATIVE_RESULTS.md)).
The record of that run is [`docs/assurance/external_adequacy_evidence_sufficiency_v1.md`](../../docs/assurance/external_adequacy_evidence_sufficiency_v1.md); the design is section 12 of [`docs/design/evidence-sufficiency-v1.1.md`](../../docs/design/evidence-sufficiency-v1.1.md).

## What is frozen

`conformance/evidence-sufficiency-v1/` and `conformance/evidence-sufficiency-v1.1/` are not modified.
The runner here imports `../evidence-sufficiency-v1/checker.py` and records its sha256.
The first 50 cases in `cases.json` are the v1.1 cases, equal as JSON values and in the same order.
`guidance.json` and `ladders.json` are byte-for-byte copies of the v1.1 files, and the runner checks are those of v1.1.

## What is added

Three postcondition cases, gap `H1`, each derived from E02 and expected VIOLATED:

| Case | Expected state | Observed state | Fault it tells apart |
|---|---|---|---|
| E18 | `"Closed"` | `"closed"` | string values case-folded |
| E19 | `["closed", "locked"]` | `["locked", "closed"]` | list order erased |
| E20 | `{"state": "closed"}` | `{"state": "open"}` | only mapping keys compared |

## Run

```bash
python conformance/evidence-sufficiency-v1.2/run_evidence_sufficiency.py --out /tmp/es-v1.2.json
python conformance/evidence-sufficiency-v1.2/run_evidence_sufficiency.py --check
```

## Non-claims

The H1 cases were written after the external run named the three faults.
Their kills of those faults are expected by construction and are not independent evidence.
v1.2 has had no external run.
Everything under "Non-claims" in the v1.1 README applies here unchanged.
