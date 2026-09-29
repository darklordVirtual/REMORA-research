# Evidence Sufficiency Conformance Review v1.1

**Status:** research/conformance artifact. Synthetic author-run only. Not a standard, certification, production control, APS result or CoSAI deliverable.

v1.1 is an additive corpus and runner for the unchanged v1 checker.
It exists because an external seeded-fault run found faults in `checker.py` that the v1 cases could not tell apart.
The design, decisions and requirements are in [`docs/design/evidence-sufficiency-v1.1.md`](../../docs/design/evidence-sufficiency-v1.1.md).

## What is frozen

`conformance/evidence-sufficiency-v1/` is not modified.
The runner here imports `../evidence-sufficiency-v1/checker.py` and records its sha256.
The first 26 cases in `cases.json` are the v1 cases, byte-for-byte equal as JSON values and in the same order.

## What is added

- 24 cases. Each names the gap it closes (`gap`), the v1 case it derives from (`derived_from`) and why (`rationale`).
- `guidance.json`, the expected `missing_evidence` and `decisive_if` for every inconclusive reason.
  The runner compares every inconclusive verdict against it.
  The checker's own table is not the oracle.
- `ladders.json`, the declared order in which inconclusive guards report their reason.
  Each adjacent pair has a witness case, and each inconclusive reason has a case where it is the only failing premise.
- Runner checks for reason coverage, the guidance contract, precedence and isolation, on top of all v1 checks.

## Run

```bash
python conformance/evidence-sufficiency-v1.1/run_evidence_sufficiency.py --out /tmp/es-v1.1.json
python conformance/evidence-sufficiency-v1.1/run_evidence_sufficiency.py --check
```

## Non-claims

The new cases were written after an external run named the gaps they close.
Their kills of those known faults are expected by construction and are not independent evidence.
Everything under "Non-claims" in the v1 README applies here unchanged.
