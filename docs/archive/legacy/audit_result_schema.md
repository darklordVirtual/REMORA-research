> **NOTICE:** This document is **HISTORICAL** and has been explicitly archived. Referencing this document as truth in any runtime processes, algorithms, papers or claims is strictly prohibited in the active repository.

---


# Reproducibility and Audit Schema

This document defines the JSON schema and workflow for audit-ready DecisionEnvelope
rows produced by external validation runs.

Result JSONL schema (one object per line):

Required fields:
- `dataset`: string
- `item_id`: string
- `question`: string
- `expected_answer`: nullable
- `oracle_raw_outputs`: list of raw strings from oracles
- `oracle_normalized_outputs`: list of normalized answers
- `majority_answer`: nullable
- `remora_answer`: nullable
- `action`: one of `accept`/`verify`/`abstain`/`escalate`
- `phase`: string
- `trust`: number
- `H`: number
- `D`: number
- `V_trajectory`: list of numbers (optional)
- `policy_reason`: string
- `correct`: boolean or null
- `unsafe_execution`: boolean
- `decision_hash`: string
- `timestamp`: ISO8601 string
- `model_providers`: list of {provider, model}
- `prompt_template_version`: string

Storage and signing
-------------------
- Results should be stored as `results/external_validation_raw.jsonl` and
  checksummed with SHA-256; the hash should be added to the summary artifact.

Repro Command Example
---------------------
See `docs/validation/EXTERNAL_VALIDATION_PLAN.md` (Section 4, Validation Procedure) for example commands. Always include
the exact `git rev-parse HEAD` and `python --version` in the summary.
